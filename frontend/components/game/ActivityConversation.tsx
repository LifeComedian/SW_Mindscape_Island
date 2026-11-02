"use client";
import {useEffect,useRef,useState} from "react";
import type {ActivityExperience} from "@/lib/api";
import {GalleryWork} from "./GalleryWork";

const buttonBase="focus-ring min-h-11 rounded-xl border border-teal-200 px-4 py-3 font-semibold disabled:opacity-40";
const btn=buttonBase+" bg-white hover:bg-teal-50";
export function ActivityConversation({sessionId,activity,busy,speaker,onSpeaker,message,onMessage,onSend,onSuggest}:{
  sessionId:number;activity:ActivityExperience;busy:boolean;speaker:number;onSpeaker:(id:number)=>void;
  message:string;onMessage:(text:string)=>void;onSend:()=>void;onSuggest:()=>void;
}){
  const panel=useRef<HTMLDivElement>(null),atBottom=useRef(true),last=useRef(0);
  const [unread,setUnread]=useState(false),[highlight,setHighlight]=useState(0);
  const who=activity.people.find(p=>p.id===(speaker||activity.people[0]?.id))?.name??"对方";
  const demonstrator=activity.people.find(p=>activity.demonstration_work?.author===`resident:${p.id}`)?.name??"伙伴";
  const key=`activity-reading:${sessionId}:${activity.runtime_id}`;
  useEffect(()=>{
    const timer=setTimeout(()=>{
      const node=panel.current;if(!node)return;
      const id=activity.history.at(-1)?.id??0;
      if(last.current===0){
        let saved:string|null=null;try{saved=sessionStorage.getItem(key);}catch{}
        node.scrollTop=saved===null?node.scrollHeight:Number(saved);
        atBottom.current=node.scrollHeight-node.scrollTop-node.clientHeight<70;
      }else if(id>last.current){
        setHighlight(id);
        if(atBottom.current)node.scrollTo({top:node.scrollHeight,behavior:"smooth"});else setUnread(true);
      }
      last.current=id;
    },0);
    return()=>clearTimeout(timer);
  },[activity.history,key]);
  useEffect(()=>{
    if(!highlight)return;
    const timer=setTimeout(()=>setHighlight(0),4500);
    return()=>clearTimeout(timer);
  },[highlight]);
  return <section aria-label="活动对话" className="min-w-0 overflow-hidden rounded-2xl border border-teal-200 bg-white shadow-sm lg:sticky lg:top-16 lg:flex lg:max-h-[calc(100dvh-9rem)] lg:flex-col">
    <header className="shrink-0 border-b bg-teal-50 px-4 py-3"><h2 className="text-lg font-bold text-teal-950">现场对话</h2><p className="text-sm text-teal-800">和伙伴聊作品，也可以只聊聊近况</p></header>
    <div ref={panel} role="log" aria-label="活动中的对话与反馈" aria-live="polite" aria-relevant="additions" className="max-h-[46dvh] min-h-48 space-y-4 overflow-y-auto overscroll-contain p-4 lg:min-h-32 lg:flex-1"
      onScroll={()=>{const node=panel.current;if(!node)return;atBottom.current=node.scrollHeight-node.scrollTop-node.clientHeight<70;try{sessionStorage.setItem(key,String(node.scrollTop));}catch{}if(atBottom.current)setUnread(false);}}>
      {activity.history.map(h=><article key={h.id} className={`rounded-xl p-3 transition-colors duration-700 ${h.speaker==="你"?"ml-5 bg-teal-50":h.kind==="action"?"border-l-4 border-amber-300 bg-amber-50":"mr-3 bg-stone-50"} ${h.id===highlight?"ring-2 ring-teal-400":""}`}>
        <strong className="text-base text-teal-950">{h.speaker}</strong>
        <p className="mt-2 whitespace-pre-wrap text-base leading-8 sm:text-[17px]">{h.text}</p>
      </article>)}
      {busy&&<p role="status" className="rounded-xl border border-dashed border-teal-300 p-4 text-base text-teal-800">{who}正在回应或完成操作<span className="motion-safe:animate-pulse">……</span></p>}
      {activity.demonstration_work&&<details className="rounded-xl border p-3"><summary className="cursor-pointer text-base font-semibold">查看{demonstrator}示范后留下的作品</summary><GalleryWork item={{...activity.demonstration_work,id:activity.demonstration_work.work_id,name:activity.demonstration_work.title}}/></details>}
    </div>
    {unread&&<button className={`${btn} mx-4 my-2 bg-teal-50`} onClick={()=>{panel.current?.scrollTo({top:panel.current.scrollHeight,behavior:"smooth"});setUnread(false);}}>有新回复 ↓</button>}
    <div className="shrink-0 space-y-2 border-t bg-white p-3">
      <div className="flex flex-wrap gap-2">{activity.people.map(p=><button className={`${btn} ${(speaker||activity.people[0]?.id)===p.id?"ring-2 ring-teal-700":""}`} key={p.id} aria-pressed={(speaker||activity.people[0]?.id)===p.id} onClick={()=>onSpeaker(p.id)}>{p.name}</button>)}</div>
      <textarea aria-label="活动中想说的话" placeholder={`和${who}聊聊近况，或者说说眼前的作品……`} value={message} onChange={e=>onMessage(e.target.value)} maxLength={600} className="min-h-20 w-full rounded-xl border p-3 text-base leading-7"/>
      <div className="flex flex-wrap gap-2"><button className={`${buttonBase} bg-teal-900 text-white hover:bg-teal-800`} disabled={busy||!message.trim()} onClick={onSend}>对{who}说</button>
        <button className={btn} disabled={busy} onClick={onSuggest}>听听{who}接下来想做什么</button></div>
    </div>
  </section>;
}
