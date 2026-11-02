"use client";
import {useEffect,useRef,useState,type PointerEvent} from "react";
import {workshopTrace,type TraceEvent} from '@/lib/workshop-trace';
import {Piece,ItemPicture} from "./PlayPieces";
type Part={kind:string;x:number;y:number;angle:number};
type Draft={title:string;pieces:Part[]};
const materials:Record<string,string>={plank:"长木条",square:"方块",circle:"圆片",triangle:"三角片",hull:"船身",mast:"桅杆",sail:"帆片"};
const button="focus-ring min-h-11 rounded-xl border bg-white px-3 py-2 text-sm disabled:opacity-40";
export function FreeWoodwork({sid,disabled,progress,onSave,runtimeId=null}:{sid:number;runtimeId?:number|null;disabled:boolean;progress:Record<string,unknown>;onSave:(value:Record<string,unknown>)=>Promise<boolean>}){
  const key=`v6-freewood:${sid}:${runtimeId??'solo'}`;
  const [draft,setDraft]=useState<Draft>({title:"我的自由木作",pieces:[]}),[selected,setSelected]=useState(-1);
  const [undo,setUndo]=useState<Draft[]>([]),[ready,setReady]=useState(false),[saving,setSaving]=useState(false),[saved,setSaved]=useState(false);
  const trace=useRef<ReturnType<typeof workshopTrace>|null>(null);
  useEffect(()=>{trace.current=workshopTrace(sid,'wood_work','v4_wood_work__free',runtimeId);void trace.current.flush();return()=>{void trace.current?.flush();};},[sid,runtimeId]);
  function record(operation:TraceEvent['operation'],method:TraceEvent['method']='button'){trace.current?.record({operation,method,...(selected>=0?{piece_index:selected}:{})});void trace.current?.flush();}
  const canvas=useRef<SVGSVGElement>(null);
  const tray=useRef<{kind:string;x:number;y:number}|null>(null);
  const [ghost,setGhost]=useState<{kind:string;x:number;y:number}|null>(null);
  function location(x:number,y:number){const svg=canvas.current!,p=svg.createSVGPoint();p.x=x;p.y=y;const q=p.matrixTransform(svg.getScreenCTM()!.inverse());return{x:q.x/6,y:q.y/4};}
  function addPart(kind:string,x=50,y=45){change({...draft,pieces:[...draft.pieces,{kind,x,y,angle:0}]});setSelected(draft.pieces.length);}
  const rotate=useRef<{start:Draft}|null>(null);
  const drag=useRef<{index:number;start:Draft;dx:number;dy:number}|null>(null);
  useEffect(()=>{const t=setTimeout(()=>{try{
    const stored=JSON.parse(sessionStorage.getItem(key)??"null");
    if(stored?.pieces)setDraft(stored);
    else if(progress.design)setDraft({title:String(progress.title??"我的自由木作"),pieces:(progress.design as {pieces:Part[]}).pieces});
  }catch{}setReady(true);},0);return()=>clearTimeout(t);},[key,progress]);
  useEffect(()=>{if(ready)try{sessionStorage.setItem(key,JSON.stringify(draft));}catch{}},[draft,key,ready]);
  const locked=disabled||saving;
  function change(next:Draft,operation?:TraceEvent["operation"]){record(operation??(next.pieces.length>draft.pieces.length?'add':next.pieces.length<draft.pieces.length?'remove':'move'));setUndo(h=>[...h.slice(-39),draft]);setDraft(next);setSaved(false);}
  function edit(p:Partial<Part>){if(selected<0||locked)return;change({...draft,pieces:draft.pieces.map((x,i)=>i===selected?{...x,...p}:x)},p.angle!==undefined?'rotate':'move');}
  function point(e:PointerEvent<SVGGElement>){return location(e.clientX,e.clientY);}
  function place(e:PointerEvent<SVGGElement>){const d=drag.current;if(!d||locked)return;const p=point(e);
    setDraft(v=>({...v,pieces:v.pieces.map((m,i)=>i===d.index?{...m,x:Math.round(Math.min(94,Math.max(6,p.x-d.dx))*10)/10,y:Math.round(Math.min(92,Math.max(8,p.y-d.dy))*10)/10}:m)}));}
  async function save(){if(locked||!draft.pieces.length)return;setSaving(true);record('submit');try{
    if(await onSave({command:"finish_graphical",...draft,trace_draft_id:trace.current?.draftId()})){setSaved(true);sessionStorage.removeItem(key);}
  }finally{setSaving(false);}}
  if(!ready)return <p>正在铺开木作台…</p>;
  return <section className="space-y-4" data-testid="free-woodwork">
    <p className="text-sm leading-7">自由拼成你想要的形状。拖动木片，或选中后用方向键微调；可以旋转、叠放与复制。最多24块，不按“像不像”打分。</p>
    <div aria-label="木片材料盘" className="grid grid-cols-4 gap-2 sm:grid-cols-7">{Object.entries(materials).map(([kind,label])=><button key={kind} aria-label={`取用${label}`} className={button+" touch-none cursor-grab"} disabled={locked||draft.pieces.length>=24}
      onPointerDown={e=>{if(locked)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);tray.current={kind,x:e.clientX,y:e.clientY};setGhost({kind,x:e.clientX,y:e.clientY});}}
      onPointerMove={e=>{if(tray.current)setGhost({kind,x:e.clientX,y:e.clientY});}}
      onPointerUp={e=>{const t=tray.current;tray.current=null;setGhost(null);if(!t)return;if(Math.hypot(t.x-e.clientX,t.y-e.clientY)<5){addPart(kind);return;}const p=location(e.clientX,e.clientY);if(p.x>=6&&p.x<=94&&p.y>=8&&p.y<=92)addPart(kind,p.x,p.y);}}
      onPointerCancel={()=>{tray.current=null;setGhost(null);}}
      onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();addPart(kind);}}}><ItemPicture kind={kind}/>{label}</button>)}</div>
    {ghost&&<div className="pointer-events-none fixed z-[100] w-20 -translate-x-1/2 -translate-y-1/2" style={{left:ghost.x,top:ghost.y}}><ItemPicture kind={ghost.kind}/></div>}
    <svg ref={canvas} viewBox="0 0 600 400" className="w-full touch-none rounded-2xl border border-amber-300 bg-[#e2c599] shadow-inner" aria-label="自由木作操作台">
      <defs><pattern id="wood-grain-v6" width="120" height="48" patternUnits="userSpaceOnUse"><path d="M0 8Q60 0 120 8M0 20Q50 35 120 20M0 44H120" stroke="#c59e6d" strokeWidth="1" fill="none"/></pattern></defs>
      <rect width="600" height="400" fill="url(#wood-grain-v6)"/>
      {draft.pieces.map((p,i)=><g key={i} role="button" tabIndex={locked?-1:0} aria-label={`${materials[p.kind]} ${i+1}`} aria-pressed={selected===i}
        transform={`translate(${p.x*6} ${p.y*4}) rotate(${p.angle}) scale(1.8)`} className="cursor-grab outline-none focus:drop-shadow-lg"
        onFocus={()=>setSelected(i)} onPointerDown={e=>{if(locked)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);const t=point(e);drag.current={index:i,start:draft,dx:t.x-p.x,dy:t.y-p.y};setSelected(i);}}
        onPointerMove={place} onPointerUp={e=>{place(e);if(drag.current){record('move','pointer');const before=drag.current.start;setUndo(h=>[...h.slice(-39),before]);drag.current=null;setSaved(false);}}}
        onPointerCancel={()=>{if(drag.current)setDraft(drag.current.start);drag.current=null;}}
        onKeyDown={e=>{const d={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(d&&!locked){e.preventDefault();edit({x:Math.max(6,Math.min(94,p.x+d[0])),y:Math.max(8,Math.min(92,p.y+d[1]))});}}}>
        <rect x="-31" y="-27" width="62" height="54" rx="5" fill="transparent" stroke={i===selected?"#115e59":"none"} strokeDasharray="3 3" strokeWidth="2"/>
        <g pointerEvents="none"><Piece kind={p.kind}/></g>
        {selected===i&&!locked&&<g role="slider" aria-label="旋转选中木片" aria-valuenow={p.angle} tabIndex={0} onPointerDown={e=>{e.stopPropagation();e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);rotate.current={start:draft};}}
          onPointerMove={e=>{e.stopPropagation();if(!rotate.current)return;const q=location(e.clientX,e.clientY),angle=Math.round((Math.atan2((q.y-p.y)*4,(q.x-p.x)*6)*180/Math.PI+90)/15)*15;setDraft(v=>({...v,pieces:v.pieces.map((part,j)=>j===i?{...part,angle:(angle+360)%360}:part)}));}}
          onPointerUp={e=>{e.stopPropagation();if(rotate.current){const before=rotate.current.start;setUndo(h=>[...h.slice(-39),before]);record('rotate','pointer');rotate.current=null;setSaved(false);}}}
          onPointerCancel={()=>{if(rotate.current)setDraft(rotate.current.start);rotate.current=null;}}
          onKeyDown={e=>{e.stopPropagation();if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();edit({angle:(p.angle+(e.key==='ArrowRight'?15:345))%360});}}}>
          <path d="M0 -25V-39" stroke="#115e59"/><circle cy="-40" r="7" fill="white" stroke="#115e59" strokeWidth="2"/></g>}
      </g>)}
    </svg>
    <div className="flex flex-wrap items-center gap-2">
      <button className={button} disabled={locked||selected<0} onClick={()=>edit({angle:(draft.pieces[selected].angle+15)%360})}>旋转15°</button>
      <button className={button} disabled={locked||selected<0||draft.pieces.length>=24} onClick={()=>{const p=draft.pieces[selected];change({...draft,pieces:[...draft.pieces,{...p,x:Math.min(94,p.x+4),y:Math.min(92,p.y+4)}]},'copy');setSelected(draft.pieces.length);}}>复制</button>
      <button className={button} disabled={locked||selected<0} onClick={()=>{const p=draft.pieces[selected];change({...draft,pieces:[...draft.pieces.filter((_,i)=>i!==selected),p]},'layer');setSelected(draft.pieces.length-1);}}>移到最上层</button>
      <button className={button} disabled={locked||selected<0} onClick={()=>{change({...draft,pieces:draft.pieces.filter((_,i)=>i!==selected)});setSelected(-1);}}>删除</button>
      <button className={button} disabled={locked||!undo.length} onClick={()=>{record('undo');setDraft(undo.at(-1)!);setUndo(h=>h.slice(0,-1));setSelected(-1);setSaved(false);}}>撤销</button>
    </div>
    <label className="block">作品名字<input maxLength={30} aria-label="木作作品名字" disabled={locked} className="ml-3 rounded-lg border p-2" value={draft.title} onChange={e=>setDraft(d=>({...d,title:e.target.value}))}/></label>
    <div className="flex items-center justify-between"><p role="status">{draft.pieces.length}/24 块{saved?" · 作品已保存，可在展示架浏览":""}</p><button className={"focus-ring min-h-11 rounded-xl bg-teal-900 px-4 py-3 text-white disabled:opacity-40"} disabled={locked||!draft.pieces.length||!draft.title.trim()} onClick={()=>void save()}>{saving?"正在保存…":"保存作品"}</button></div>
  </section>;
}
