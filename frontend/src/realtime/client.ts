import type { QueryClient } from '@tanstack/react-query';
import { applyLiveMessage } from './events';
import type { LiveMessage } from './events';
export type LiveStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline';
type Options = { cache: QueryClient; token: () => string | null; renew: () => Promise<string | null>; disabled: () => void; status: (status:LiveStatus) => void; role: (role:string) => void; socket?: (url:string) => WebSocket };
export class RealtimeClient {
  private socket:WebSocket|null=null; private timer:ReturnType<typeof setTimeout>|null=null; private stopped=true; private authenticated=false; private attempt=0; private thread:string|undefined;
  constructor(private options:Options){}
  start(){this.stopped=false;this.connect();}
  stop(){this.stopped=true;if(this.timer)clearTimeout(this.timer);this.timer=null;this.socket?.close();this.socket=null;this.authenticated=false;}
  setThread(thread:string|undefined){if(thread===this.thread)return;const previous=this.thread;this.thread=thread;if(this.authenticated){if(previous)this.send({type:'unsubscribe',thread_id:previous});if(thread)this.send({type:'subscribe',thread_id:thread});}}
  private send(message:object){if(this.socket?.readyState===1)this.socket.send(JSON.stringify(message));}
  private reconnect(){if(this.stopped)return;this.options.status('reconnecting');this.timer=setTimeout(()=>this.connect(),Math.min(1000*2**this.attempt++,30000));}
  private connect(){
    if(this.stopped||!this.options.token())return;
    this.authenticated=false;this.options.status(this.attempt?'reconnecting':'connecting');
    const url=`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`;
    const socket=(this.options.socket || (url=>new WebSocket(url)))(url);this.socket=socket;
    socket.onopen=()=>{if(!this.stopped&&this.socket===socket)this.send({type:'auth',token:this.options.token()});};
    socket.onmessage=event=>{if(this.stopped||this.socket!==socket)return;let message:LiveMessage;try{message=JSON.parse(String(event.data));}catch{return;}if(!message||typeof message!=='object')return;
      if(message.type==='ping'){this.send({type:'pong'});return;}
      if(message.type==='auth.ok'){this.authenticated=true;this.attempt=0;this.options.status('connected');if(message.role)this.options.role(message.role);if(this.thread)this.send({type:'subscribe',thread_id:this.thread});void this.options.cache.refetchQueries({type:'active'});return;}
      if(this.authenticated)void applyLiveMessage(this.options.cache,message).catch(()=>{});
    };
    socket.onerror=()=>{};
    socket.onclose=event=>{if(this.stopped||this.socket!==socket)return;this.authenticated=false;
      if(event.code===4403){this.options.disabled();this.stop();return;}
      if(event.code===4401){void this.options.renew().then(token=>{if(token)this.reconnect();else this.options.status('offline');},()=>this.reconnect());return;}
      this.reconnect();
    };
  }
}
