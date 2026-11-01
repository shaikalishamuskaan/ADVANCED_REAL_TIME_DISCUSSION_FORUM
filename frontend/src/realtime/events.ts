import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import { request } from '../lib/api';
import type { Comment, Page, Thread } from '../lib/types';
export interface LiveMessage { type: string; event?: string; thread_id?: string; data?: Record<string, unknown>; role?: string }
const receivedComments = new WeakMap<QueryClient, Set<string>>();
function walk(value: unknown, change: (item: Record<string, unknown>) => Record<string, unknown>): unknown {
  if (Array.isArray(value)) return value.map(item => walk(item, change));
  if (!value || typeof value !== 'object') return value;
  const object = { ...(value as Record<string, unknown>) };
  for (const key of ['pages','items','replies']) if (object[key]) object[key] = walk(object[key], change);
  return change(object);
}
export async function applyLiveMessage(cache: QueryClient, message: LiveMessage, fetchThread = (id: string) => request<Thread>(`/api/forum/threads/${id}`)) {
  if (message.type === 'notification') { await Promise.all([cache.invalidateQueries({queryKey:['notifications']}),cache.invalidateQueries({queryKey:['unread']})]); return; }
  if (message.type !== 'event') return;
  const data = message.data || {}; const threadId = message.thread_id || (typeof data.thread_id === 'string' ? data.thread_id : undefined);
  if (message.event === 'like.changed' && typeof data.target_id === 'string' && typeof data.like_count === 'number') {
    cache.setQueriesData({predicate:query=>['threads','thread','comments','replies'].includes(String(query.queryKey[0]))}, old => walk(old, item => item.id === data.target_id ? {...item, like_count:data.like_count} : item));
    return;
  }
  if (message.event === 'thread.created' && (threadId || typeof data.id === 'string')) {
    try {
      const thread = typeof data.title==='string' && typeof data.description==='string' && Array.isArray(data.tags) && data.author ? data as unknown as Thread : await fetchThread(threadId || String(data.id));
      if (!thread.id) thread.id = threadId!;
      for (const query of cache.getQueryCache().findAll({queryKey:['threads']})) {
        const tag = query.queryKey[1]; if (tag && !thread.tags.includes(String(tag))) continue;
        cache.setQueryData<InfiniteData<Page<Thread>>>(query.queryKey, old => old ? {...old,pages:old.pages.map((page,index)=>({...page,items:[...(index===0?[thread]:[]),...page.items.filter(item=>item.id!==thread.id)]}))}:old);
      }
    } catch { await cache.invalidateQueries({queryKey:['threads']}); }
  }
  if (message.event === 'thread.deleted' && threadId) cache.setQueriesData<InfiniteData<Page<Thread>>>({queryKey:['threads']},old=>old?{...old,pages:old.pages.map(page=>({...page,items:page.items.filter(item=>item.id!==threadId)}))}:old);
  if (message.event === 'comment.created' && threadId) {
    const id = String(data.id || data.comment_id || ''); const parentId = data.parent_id;
    if (id && typeof data.body==='string' && typeof data.depth==='number') {
      let received = receivedComments.get(cache);
      if (!received) { received = new Set(); receivedComments.set(cache, received); }
      if (received.has(id)) return;
      received.add(id);
      if (received.size > 2000) received.delete(received.values().next().value!);
      const comment = {...data,id,author:data.author || (data.author_id?{id:data.author_id,username:data.author_username}:null),replies:[],replies_next_cursor:null,reply_count:0,like_count:0,liked_by_me:false} as unknown as Comment;
      if (!parentId) cache.setQueryData<InfiniteData<Page<Comment>>>(['comments',threadId], old => old ? {...old,pages:old.pages.map((page,index)=>({...page,items:index===0&&!old.pages.some(page=>page.items.some(item=>item.id===id))?[comment,...page.items]:page.items}))}:old);
      else {
        cache.setQueriesData({predicate:query=>['comments','replies'].includes(String(query.queryKey[0]))},old=>walk(old,item=>{
          if(item.id!==parentId)return item;
          const replies=Array.isArray(item.replies)?item.replies as Comment[]:[];
          if(replies.some(reply=>reply.id===id))return item;
          return {...item,reply_count:Number(item.reply_count || 0)+1,...(Array.isArray(item.replies)?{replies:[comment,...replies].slice(0,3)}:{})};
        }));
        cache.setQueryData<InfiniteData<Page<Comment>>>(['replies',parentId],old=>old?{...old,pages:old.pages.map((page,index)=>({...page,items:index===0&&!old.pages.some(page=>page.items.some(item=>item.id===id))?[comment,...page.items]:page.items}))}:old);
      }
    } else await cache.invalidateQueries({queryKey:['comments',threadId]});
  }
  if (message.event?.startsWith('thread.') || message.event?.startsWith('comment.')) {
    const keys:unknown[][] = [['search']];
    if (threadId) keys.push(['thread',threadId]);
    // Reconcile server counts after inserting live data: the HTTP response to
    // our own write may already include this event, and previews are bounded.
    if (message.event==='comment.created' && threadId) {
      keys.push(['comments',threadId]);
      if (typeof data.parent_id==='string') keys.push(['replies',data.parent_id]);
    }
    if (message.event!=='thread.created')keys.push(['threads']);
    if (message.event!=='comment.created' && message.event?.startsWith('comment.')) keys.push(['comments',threadId],['replies']);
    await Promise.all(keys.map(queryKey=>cache.invalidateQueries({queryKey})));
  }
}
