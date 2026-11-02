"use client";
import Image from 'next/image';
import {createContext,useContext,useEffect,useState,type ReactNode} from 'react';
import {getV5,type V5Snapshot} from '@/lib/holiday-v5';
import {holidayArt} from '@/lib/holiday-art';
import {resolveApiAssetUrl} from '@/lib/api';
const Identity=createContext<{data:V5Snapshot|null;nickname:string}|null>(null);
export function SocialIdentityProvider({sessionId,nickname,enabled,children}:{sessionId?:number;nickname:string;enabled:boolean;children:ReactNode}){
  const [data,setData]=useState<V5Snapshot|null>(null);
  useEffect(()=>{let active=true;if(enabled&&sessionId)void getV5(sessionId).then(d=>{if(active)setData(d);}).catch(()=>{});return()=>{active=false;};},[sessionId,enabled]);
  return <Identity.Provider value={enabled?{data,nickname}:null}>{children}</Identity.Provider>;
}
export function useSocialIdentity(){
  const value=useContext(Identity);
  return {enabled:!!value,name:(id:number,fallback:string)=>value?(id?value.data?.residents.find(r=>r.id===id)?.name??fallback:value.nickname):fallback,
    portrait:(id:number)=>value?(id?holidayArt(`resident.${id}.closeup`)?.url:value.data?.profile?resolveApiAssetUrl(value.data.profile.portrait_url):undefined):undefined};
}
export function SocialAvatar({agentId,name,size=40}:{agentId:number;name:string;size?:number}){
  const identity=useSocialIdentity();const src=identity.portrait(agentId);
  return <span className="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-white ring-1 ring-stone-200 text-sm font-bold text-stone-700" style={{width:size,height:size}}>{src?<Image src={src} alt={`${identity.name(agentId,name)}的头像`} unoptimized width={size} height={size} className="h-full w-full object-cover object-top origin-top scale-[2.2]"/>:name.slice(0,1)}</span>;
}
