import { afterEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { RealtimeClient } from '../realtime/client';
import { applyLiveMessage } from '../realtime/events';

class Socket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: {data:string}) => void) | null = null;
  onclose: ((event: {code:number}) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: object[] = [];
  send(data:string) { this.sent.push(JSON.parse(data)); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(data:object) { this.onmessage?.({data:JSON.stringify(data)}); }
  close(code=1000) { this.readyState = 3; this.onclose?.({code}); }
}
function connection() {
  const sockets:Socket[] = []; const urls:string[] = []; const cache=new QueryClient();
  const options={cache,token:()=> 'access-token',renew:vi.fn(async()=> 'renewed-token'),disabled:vi.fn(),status:vi.fn(),role:vi.fn(),socket:(url:string)=>{urls.push(url);const socket=new Socket();sockets.push(socket);return socket as unknown as WebSocket;}};
  const client=new RealtimeClient(options);return {client,sockets,urls,options,cache};
}
afterEach(()=>vi.useRealTimers());

it('authenticates in its first frame, subscribes after acknowledgement, and answers heartbeats',()=>{
  const {client,sockets,urls,options}=connection();client.setThread('thread-one');client.start();const socket=sockets[0];socket.open();
  expect(urls[0]).toMatch(/\/ws$/);expect(urls[0]).not.toContain('access-token');expect(socket.sent).toEqual([{type:'auth',token:'access-token'}]);
  socket.receive({type:'auth.ok',role:'member'});expect(socket.sent.at(-1)).toEqual({type:'subscribe',thread_id:'thread-one'});expect(options.role).toHaveBeenCalledWith('member');
  socket.receive({type:'ping'});expect(socket.sent.at(-1)).toEqual({type:'pong'});
  client.setThread('thread-two');expect(socket.sent.slice(-2)).toEqual([{type:'unsubscribe',thread_id:'thread-one'},{type:'subscribe',thread_id:'thread-two'}]);
  client.setThread(undefined);expect(socket.sent.at(-1)).toEqual({type:'unsubscribe',thread_id:'thread-two'});client.stop();
});
it('refetches active data and restores the current subscription after reconnect',async()=>{
  vi.useFakeTimers();const {client,sockets,cache}=connection();const refetch=vi.spyOn(cache,'refetchQueries');client.setThread('thread-one');client.start();sockets[0].open();sockets[0].receive({type:'auth.ok'});sockets[0].close(1006);
  expect(sockets).toHaveLength(1);await vi.advanceTimersByTimeAsync(1000);expect(sockets).toHaveLength(2);sockets[1].open();sockets[1].receive({type:'auth.ok'});
  expect(sockets[1].sent).toContainEqual({type:'subscribe',thread_id:'thread-one'});expect(refetch).toHaveBeenCalledTimes(2);client.stop();await vi.advanceTimersByTimeAsync(60000);expect(sockets).toHaveLength(2);
});
it('renews an expired socket session and stops on a disabled account',async()=>{
  vi.useFakeTimers();const {client,sockets,options}=connection();client.start();sockets[0].close(4401);await vi.advanceTimersByTimeAsync(1000);expect(options.renew).toHaveBeenCalledOnce();expect(sockets).toHaveLength(2);
  sockets[1].close(4403);expect(options.disabled).toHaveBeenCalledOnce();await vi.advanceTimersByTimeAsync(60000);expect(sockets).toHaveLength(2);
});
it('ignores obsolete sockets and events before authentication',async()=>{
  vi.useFakeTimers();const {client,sockets,cache}=connection();const invalidate=vi.spyOn(cache,'invalidateQueries');client.start();sockets[0].receive({type:'notification'});expect(invalidate).not.toHaveBeenCalled();sockets[0].close(1006);await vi.advanceTimersByTimeAsync(1000);sockets[0].receive({type:'auth.ok'});expect(sockets[1].sent).toEqual([]);client.stop();
});
it('updates nested like counts without changing the current users like state',async()=>{
  const cache=new QueryClient();const key=['comments','thread-one'];cache.setQueryData(key,{pages:[{items:[{id:'comment-one',like_count:0,liked_by_me:true,replies:[{id:'reply-one',like_count:0,liked_by_me:false}]}]}],pageParams:[null]});
  await applyLiveMessage(cache,{type:'event',event:'like.changed',data:{target_id:'reply-one',like_count:7}});
  expect(cache.getQueryData(key)).toMatchObject({pages:[{items:[{replies:[{like_count:7,liked_by_me:false}]}]}]});
});
it('prepends a new thread only to matching tag feeds and deduplicates repeated delivery',async()=>{
  const cache=new QueryClient();const empty={pages:[{items:[],next_cursor:null}],pageParams:[null]};cache.setQueryData(['threads',''],empty);cache.setQueryData(['threads','python'],empty);cache.setQueryData(['threads','rust'],empty);
  const fetch=vi.fn(async()=>({id:'new-thread',title:'New',description:'Body',tags:['python'],author:{id:'author'}} as never));const event={type:'event',event:'thread.created',thread_id:'new-thread'};
  await applyLiveMessage(cache,event,fetch);await applyLiveMessage(cache,event,fetch);
  expect(cache.getQueryData(['threads','python'])).toMatchObject({pages:[{items:[{id:'new-thread'}]}]});expect(cache.getQueryData(['threads','rust'])).toEqual(empty);
  expect(cache.getQueryData(['threads',''])).toMatchObject({pages:[{items:[{id:'new-thread'}]}]});
});
it('inserts new comments once and updates parent reply previews and loaded replies once',async()=>{
  const cache=new QueryClient();cache.setQueryData(['comments','thread-one'],{pages:[{items:[{id:'parent',reply_count:0,replies:[]}]}],pageParams:[null]});cache.setQueryData(['replies','parent'],{pages:[{items:[]}],pageParams:[null]});
  const event={type:'event',event:'comment.created',thread_id:'thread-one',data:{comment_id:'new-reply',body:'A reply',depth:2,parent_id:'parent',author_id:'author',author_username:'alice'}};
  await applyLiveMessage(cache,event);await applyLiveMessage(cache,event);
  expect(cache.getQueryData(['comments','thread-one'])).toMatchObject({pages:[{items:[{reply_count:1,replies:[{id:'new-reply',body:'A reply'}]}]}]});expect(cache.getQueryData(['replies','parent'])).toMatchObject({pages:[{items:[{id:'new-reply'}]}]});
});
it('refreshes notifications and badge on private delivery and removes deleted threads',async()=>{
  const cache=new QueryClient();cache.setQueryData(['notifications',false],{items:[]});cache.setQueryData(['unread'],{unread_count:0});await applyLiveMessage(cache,{type:'notification'});expect(cache.getQueryState(['unread'])?.isInvalidated).toBe(true);expect(cache.getQueryState(['notifications',false])?.isInvalidated).toBe(true);
  cache.setQueryData(['threads',''],{pages:[{items:[{id:'deleted'},{id:'keep'}]}],pageParams:[null]});await applyLiveMessage(cache,{type:'event',event:'thread.deleted',thread_id:'deleted'});expect(cache.getQueryData(['threads',''])).toMatchObject({pages:[{items:[{id:'keep'}]}]});
});
