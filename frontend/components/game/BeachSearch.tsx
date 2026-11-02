"use client";
import {useState} from "react";
import Image from "next/image";
import {holidayArt} from "@/lib/holiday-art";
import type {ObjectOperation} from "@/lib/api";
import {useHolidayNight} from "./HolidayNight";
export function BeachSearch({action,progress,disabled,onFind}:{action:ObjectOperation;progress:Record<string,unknown>;disabled:boolean;onFind:(p:Record<string,unknown>)=>Promise<boolean>}){
  const [zoom,setZoom]=useState(1),[cursor,setCursor]=useState({x:50,y:50});
  const night=useHolidayNight();
  const scene=action.scenes?.find(s=>s.id===progress.scene),art=scene?holidayArt(scene.art_id,night):null;
  const found=(progress.found??[]) as string[],marks=(progress.marks??[]) as {id:string;x:number;y:number}[];
  const hint=progress.hint as {x:number;y:number;name:string;radius:number}|undefined,done=Boolean(progress.done);
  return <section className="space-y-4" aria-label="海滩寻物">
    <p className="leading-7">从画面里寻找六样小物。点击找到的位置，可以放大后拖动滚动条查看细节。没有倒计时，找到后把小物留在原处。</p>
    <div className="flex flex-wrap gap-2">{action.scenes?.map(s=><button key={s.id} disabled={disabled} aria-pressed={scene?.id===s.id} className="focus-ring rounded-xl border bg-white p-3" onClick={()=>void onFind({command:"start",scene:s.id})}>{s.name}</button>)}</div>
    {scene&&art&&<>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">{scene.targets.map(t=><li key={t.id} className={`rounded-xl border p-3 ${found.includes(t.id)?"bg-teal-100 text-teal-900":"bg-amber-50"}`}>{found.includes(t.id)?"✓ ":"○ "}{t.name}</li>)}</ul>
      <div className="flex flex-wrap items-center gap-3"><label>放大<select className="ml-2 rounded-lg border p-2" aria-label="寻物画面缩放" value={zoom} onChange={e=>setZoom(Number(e.target.value))}>{[1,1.5,2,3].map(n=><option key={n} value={n}>{n}倍</option>)}</select></label><button disabled={disabled||done} className="focus-ring rounded-xl border p-3" onClick={()=>void onFind({command:"hint"})}>提示一个范围</button></div>
      <div className="max-h-[65dvh] overflow-auto rounded-2xl border border-amber-200 bg-stone-100">
        <div className="relative" style={{width:`${zoom*100}%`}} role="button" tabIndex={disabled||done?-1:0} aria-label="寻物画面，方向键移动光标，回车查找"
          onClick={e=>{if(disabled||done)return;const r=e.currentTarget.getBoundingClientRect();void onFind({command:"find",x:Math.round((e.clientX-r.left)/r.width*1000)/10,y:Math.round((e.clientY-r.top)/r.height*1000)/10});}}
          onKeyDown={e=>{if(disabled||done)return;const delta={ArrowUp:[0,-2],ArrowDown:[0,2],ArrowLeft:[-2,0],ArrowRight:[2,0]}[e.key];if(delta){e.preventDefault();setCursor(p=>({x:Math.max(0,Math.min(100,p.x+delta[0])),y:Math.max(0,Math.min(100,p.y+delta[1]))}));}if(e.key==="Enter"){e.preventDefault();void onFind({command:"find",...cursor});}}}>
          <Image unoptimized src={art.url} width={art.width} height={art.height} alt={scene.name+"寻物画面"} className="block h-auto w-full" draggable={false}/>
          {marks.map(p=><span key={p.id} className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-teal-800 px-2 text-white shadow" style={{left:`${p.x}%`,top:`${p.y}%`}}>✓</span>)}
          {hint&&!done&&<span className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-4 border-dashed border-yellow-200 bg-amber-100/10" style={{left:`${hint.x}%`,top:`${hint.y}%`,width:"24%",aspectRatio:"1"}}/>}
          <span className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 text-2xl text-white [text-shadow:0_0_3px_black]" style={{left:`${cursor.x}%`,top:`${cursor.y}%`}}>＋</span>
        </div>
      </div>
      <p role="status">{done?"这幅画里的六样小物都找到了。":`已找到 ${found.length}/6 样`}{hint&&!done?` · 在圈出的范围找找${hint.name}。`:""} · 使用 {Number(progress.hints??0)} 次提示</p>
    </>}
  </section>;
}
