import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../auth/AuthProvider';
import { getAccessToken, refreshSession, setSession, subscribeSession } from '../lib/api';
import { RealtimeClient } from './client';
import type { LiveStatus } from './client';
export function useRealtime(thread:string|undefined){
  const auth=useAuth();const cache=useQueryClient();const [token,tokenChanged]=useState(getAccessToken());const [status,setStatus]=useState<LiveStatus>('connecting');const client=useRef<RealtimeClient|null>(null);
  useEffect(()=>subscribeSession(tokenChanged),[]);
  useEffect(()=>{if(!auth.user||!token)return;const socket=new RealtimeClient({cache,token:getAccessToken,renew:refreshSession,disabled:()=>setSession(null),status:setStatus,role:role=>{if(role!==auth.user?.role)void auth.reloadProfile().catch(()=>{});}});client.current=socket;socket.setThread(thread);socket.start();return()=>{socket.stop();client.current=null;};},[auth.user?.id,token,cache,auth.reloadProfile]);
  useEffect(()=>{client.current?.setThread(thread);},[thread]);
  return status;
}
