"use client";
import {useEffect,useRef,useState} from "react";
import {workshopTrace,type TraceEvent} from "@/lib/workshop-trace";
const targets=[{x:70,y:38},{x:30,y:55},{x:85,y:72}];
const captions=["两条绳子的尾端朝上：红绳在左，蓝绳在右。","第一半结：蓝绳压过红绳，从下方绕出。","第二半结：现在换红绳压过蓝绳，再从下方穿出。","向两侧均匀拉紧。两个半结方向相反，形成平结。"];
const red=[
  "M70 280Q100 225 155 160L170 70",
  "M70 280Q100 220 180 180Q260 135 240 115Q215 100 190 125L260 65",
  "M70 280Q115 220 180 180Q260 140 238 112Q190 90 170 122Q148 160 220 170L310 65",
  "M50 210L150 176Q210 125 264 158Q285 185 230 190Q190 190 174 160L360 130",
];
const blue=[
  "M350 280Q320 225 265 160L250 70",
  "M350 280Q310 210 240 170Q165 120 185 105Q205 91 225 120L155 65",
  "M350 280Q310 220 240 175Q165 130 185 108Q230 90 250 122Q270 160 200 170L110 65",
  "M370 210L270 176Q210 125 156 158Q135 185 190 190Q230 190 246 160L60 130",
];
export function RopeWorkshop({sid,runtimeId=null,disabled,onSave}:{sid:number;runtimeId?:number|null;disabled:boolean;onSave:(p:Record<string,unknown>)=>Promise<boolean>}){
  const [step,setStep]=useState(0),[saved,setSaved]=useState(false),[ready,setReady]=useState(false);
  const key=`rope-v6:${sid}:${runtimeId??'solo'}`;
  const trace=useRef<ReturnType<typeof workshopTrace>|null>(null);
  useEffect(()=>{trace.current=workshopTrace(sid,'rope','v4_rope__make',runtimeId);void trace.current.flush();return()=>{void trace.current?.flush();};},[sid,runtimeId]);
  function advance(next:number,operation:TraceEvent['operation']='visit',method:TraceEvent['method']='button'){
    trace.current?.record({operation,method,choice:`step_${next}`});void trace.current?.flush();setStep(next);setSaved(false);
  }
  async function save(){trace.current?.record({operation:'submit',method:'button'});await trace.current?.flush();
    const ok=await onSave({command:'finish_graphical',moves:targets,trace_draft_id:trace.current?.draftId()});
    if(ok){setSaved(true);try{sessionStorage.removeItem(key);}catch{}}
  }
  useEffect(()=>{const t=setTimeout(()=>{try{setStep(Math.max(0,Math.min(3,Number(sessionStorage.getItem(key)??0))));}catch{}setReady(true);},0);return()=>clearTimeout(t);},[key]);
  useEffect(()=>{if(ready)try{sessionStorage.setItem(key,String(step));}catch{}},[key,ready,step]);
  if(!ready)return <p>正在摆好练习绳…</p>;
  return <section className="space-y-4" aria-label="平结练习">
    <div className="flex flex-wrap gap-2">{["摆好绳端","右压左，绕出","左压右，穿出","两侧拉紧"].map((s,i)=><span key={s} className={`rounded-full px-3 py-2 text-sm ${i===step?"bg-teal-900 text-white":"bg-stone-100"}`}>{i+1} · {s}</span>)}</div>
    <p className="rounded-xl bg-amber-50 p-4 text-base leading-8">{captions[step]}</p>
    <svg viewBox="0 0 420 330" className="mx-auto max-h-[43dvh] w-auto max-w-full rounded-2xl border bg-[#eee1c7]" aria-label={captions[step]}>
      <defs><pattern id="rope-mat-v6" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M0 0H20M0 0V20" stroke="#d9c7a8" strokeWidth=".7"/></pattern></defs>
      <rect width="420" height="330" fill="url(#rope-mat-v6)"/>
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        <path d={blue[step]} stroke="#194f78" strokeWidth="18" className="transition-[d] duration-700"/>
        <path d={blue[step]} stroke="#5ca0c9" strokeWidth="11" strokeDasharray="2 5" className="transition-[d] duration-700"/>
        <path d={red[step]} stroke="#f8eedb" strokeWidth="24" className="transition-[d] duration-700"/>
        <path d={red[step]} stroke="#9c392e" strokeWidth="18" className="transition-[d] duration-700"/>
        <path d={red[step]} stroke="#d47757" strokeWidth="11" strokeDasharray="2 5" className="transition-[d] duration-700"/>
        {step===1&&<path d="M225 120L155 65" stroke="#357ca7" strokeWidth="16"/>}
        {step>=2&&<path d={step===2?"M250 122Q270 160 220 169":"M246 160L285 152"} stroke="#357ca7" strokeWidth="16"/>}
      </g>
      <text x="25" y="310" fill="#9c392e" fontSize="17">红绳 · 左手端</text><text x="270" y="310" fill="#194f78" fontSize="17">蓝绳 · 右手端</text>
      {step<3&&<g role="button" tabIndex={disabled?-1:0} aria-label="拖动绳端完成当前步骤" className="cursor-grab outline-none focus:drop-shadow-lg"
        onPointerDown={e=>{if(!disabled)e.currentTarget.setPointerCapture(e.pointerId);}}
        onPointerUp={e=>{if(disabled)return;const r=e.currentTarget.ownerSVGElement!.getBoundingClientRect();if(Math.hypot(e.clientX-(r.left+r.width*.5),e.clientY-(r.top+r.height*.5))<r.width*.3)advance(Math.min(3,step+1),"visit","pointer");}}
        onKeyDown={e=>{if(!disabled&&(e.key==="Enter"||e.key===" ")){e.preventDefault();advance(Math.min(3,step+1),"visit","keyboard");}}}>
        <circle cx="210" cy="42" r="25" fill="#fff6d9" stroke="#b08b3d" strokeDasharray="4 3"/><text x="210" y="48" textAnchor="middle" fontSize="13">绳端 ↓</text>
      </g>}
    </svg>
    <p className="text-sm text-stone-600">{step<3?"把上方绳端拖向结的中央，观察下一步；也可点击下方按钮。":"检查两侧绳端：两个半结方向相反，结身平整。"}练习结仅用于理解编结，不用于攀爬或承重。</p>
    <div className="flex flex-wrap gap-3"><button className="focus-ring rounded-xl border p-3" disabled={disabled||step===0} onClick={()=>{advance(step-1,"undo");}}>上一步</button>{step<3?<button disabled={disabled} className="focus-ring rounded-xl bg-teal-900 p-3 text-white" onClick={()=>advance(step+1)}>跟着完成这一步</button>:<button disabled={disabled||saved} className="focus-ring rounded-xl bg-teal-900 p-3 text-white" onClick={()=>void save()}>{saved?"绳结已保存":"收好这枚平结"}</button>}<button disabled={disabled} className="focus-ring rounded-xl border p-3" onClick={()=>{advance(0,"restart");}}>重新练习</button></div>
  </section>;
}
