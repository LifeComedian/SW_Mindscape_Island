"use client";
import {useEffect,useRef,useState,type PointerEvent} from "react";
import {HolidayIllustration} from "./HolidayIllustration";
import {SceneDialog} from "./SceneDialog";
type Style={color:string;width:number;erase:boolean};
type Drawing={strokes:number[][][];stroke_styles:Style[]};
const baseStyle:Style={color:"#355f59",width:.65,erase:false};
const button="focus-ring min-h-11 rounded-xl border bg-white px-3 py-2 disabled:opacity-40";
export function paint(canvas:HTMLCanvasElement,drawing:Drawing){
 const ctx=canvas.getContext("2d")!,w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);
 drawing.strokes.forEach((line,i)=>{
  const style=drawing.stroke_styles[i]??baseStyle;ctx.globalCompositeOperation=style.erase?"destination-out":"source-over";
  ctx.strokeStyle=style.color;ctx.fillStyle=style.color;ctx.lineWidth=style.width*w/100;ctx.lineCap="round";ctx.lineJoin="round";
  if(line.length===1){ctx.beginPath();ctx.arc(line[0][0]*w/100,line[0][1]*h/100,ctx.lineWidth/2,0,Math.PI*2);ctx.fill();return;}
  ctx.beginPath();ctx.moveTo(line[0][0]*w/100,line[0][1]*h/100);
  for(let j=1;j<line.length-1;j++)ctx.quadraticCurveTo(line[j][0]*w/100,line[j][1]*h/100,(line[j][0]+line[j+1][0])*w/200,(line[j][1]+line[j+1][1])*h/200);
  const last=line.at(-1)!;ctx.lineTo(last[0]*w/100,last[1]*h/100);ctx.stroke();
 });ctx.globalCompositeOperation="source-over";
}
export function SketchPreview({strokes,styles,label}:{strokes:number[][][];styles?:Style[];label:string}){
 const canvas=useRef<HTMLCanvasElement>(null);
 useEffect(()=>{if(canvas.current)paint(canvas.current,{strokes,stroke_styles:styles??strokes.map(()=>baseStyle)});},[strokes,styles]);
 return <canvas ref={canvas} width={1200} height={900} aria-label={label} className="aspect-[4/3] w-full rounded-xl bg-[#fffdf6]"/>;
}
export function SketchCanvas({sid,runtimeId,item,disabled,progress,onSave}:{sid:number;runtimeId?:number|null;item:string;disabled:boolean;progress:Record<string,unknown>;onSave:(p:Record<string,unknown>)=>Promise<boolean>}){
 const canvas=useRef<HTMLCanvasElement>(null),draft=useRef<Drawing>({strokes:[],stroke_styles:[]}),drawing=useRef(false);
 const [style,setStyle]=useState<Style>(baseStyle),[count,setCount]=useState(0),[ready,setReady]=useState(false),[message,setMessage]=useState(""),[saving,setSaving]=useState(false),[reference,setReference]=useState(false);
 const redo=useRef<{line:number[][];style:Style}[]>([]),[canRedo,setCanRedo]=useState(false);
 const key=`sketch-canvas:${sid}:${runtimeId??"solo"}:${item}`;
 const locked=disabled||saving;
 function redraw(){if(canvas.current)paint(canvas.current,draft.current);}
 function persist(){setCount(draft.current.strokes.length);try{sessionStorage.setItem(key,JSON.stringify(draft.current));}catch{setMessage("草稿暂时无法保存在浏览器，请及时保存作品。");}}
 useEffect(()=>{const timer=setTimeout(()=>{try{
  const saved=JSON.parse(sessionStorage.getItem(key)??"null");
  draft.current=saved?.strokes?saved:progress.item===item&&progress.strokes?{strokes:progress.strokes as number[][][],stroke_styles:(progress.stroke_styles as Style[])??(progress.strokes as number[][][]).map(()=>baseStyle)}:{strokes:[],stroke_styles:[]};
 }catch{draft.current={strokes:[],stroke_styles:[]};}
 redo.current=[];setCanRedo(false);setCount(draft.current.strokes.length);redraw();setReady(true);},0);return()=>clearTimeout(timer);},[key]); // progress is only an initial fallback; never replace an unsaved stroke on refresh.
 function point(e:{clientX:number;clientY:number}){const r=canvas.current!.getBoundingClientRect();return [Math.round(Math.max(0,Math.min(100,(e.clientX-r.left)/r.width*100))*10)/10,Math.round(Math.max(0,Math.min(100,(e.clientY-r.top)/r.height*100))*10)/10];}
 function start(e:PointerEvent<HTMLCanvasElement>){
  if(locked||!ready)return;e.preventDefault();
  if(draft.current.strokes.length>=256){setMessage("已达到256笔，可撤销部分内容后继续。");return;}
  e.currentTarget.setPointerCapture(e.pointerId);drawing.current=true;redo.current=[];setCanRedo(false);
  draft.current.strokes.push([point(e)]);draft.current.stroke_styles.push({...style});setMessage("");redraw();
 }
 function move(e:PointerEvent<HTMLCanvasElement>){
  if(!drawing.current)return;
  const coalesced=e.nativeEvent.getCoalescedEvents?.(),events=coalesced?.length?coalesced:[e.nativeEvent],line=draft.current.strokes.at(-1)!;
  for(const event of events){const p=point(event),last=line.at(-1)!;if(Math.hypot(p[0]-last[0],p[1]-last[1])<.15)continue;
   if(line.length>=2048){line.splice(1,line.length-2,...line.slice(1,-1).filter((_,i)=>i%2===0));}
   line.push(p);
  }redraw();
 }
 function end(e:PointerEvent<HTMLCanvasElement>){if(!drawing.current)return;move(e);drawing.current=false;persist();}
 function undo(){if(locked||!draft.current.strokes.length)return;redo.current.push({line:draft.current.strokes.pop()!,style:draft.current.stroke_styles.pop()!});setCanRedo(true);redraw();persist();}
 async function save(){if(locked||!draft.current.strokes.length)return;setSaving(true);setMessage("");
  // Downsample points while preserving strokes, endpoints, styles, and order.
  let strokes=draft.current.strokes.map(line=>line.slice());
  while(strokes.reduce((n,line)=>n+line.length,0)>11000){
   strokes=strokes.map(line=>line.length<=2?line:line.filter((_,i)=>i===0||i===line.length-1||i%2===0));
  }
  try{if(await onSave({command:"save",item,strokes,stroke_styles:draft.current.stroke_styles,drawing_version:"canvas-v1",source_quality:"client_reported_drawing"})){setMessage("速写已保存，可以在速写册里找到。");sessionStorage.removeItem(key);}}finally{setSaving(false);}
 }
 const art=item==="boat"?"exhibit.photos.harbor":item==="house"?"exhibit.photos.street":"location.loc_01";
 return <section className="space-y-4" aria-label="速写工作台">
 <p>按住画笔连续画线，也可以擦除、撤销。参照图可展开查看；画一笔也能保存。</p>
 <div className="grid gap-4 xl:grid-cols-[.75fr_1.25fr]">
 <aside><button className={button+" w-full"} onClick={()=>setReference(true)}>放大参照图</button><HolidayIllustration id={art} staticDay/></aside>
 <div className="min-w-0"><div className="mb-3 flex flex-wrap gap-2">
 <button className={button} aria-pressed={!style.erase} onClick={()=>setStyle(s=>({...s,erase:false}))}>画笔</button><button className={button} aria-pressed={style.erase} onClick={()=>setStyle(s=>({...s,erase:true}))}>橡皮</button>
 <label>粗细<select aria-label="画笔粗细" className="ml-2 rounded border p-2" value={style.width} onChange={e=>setStyle(s=>({...s,width:Number(e.target.value)}))}>{[.35,.65,1.3,2.4,5].map(w=><option key={w} value={w}>{w}</option>)}</select></label>
 {["#355f59","#333333","#a55d4c","#c69b48","#5488a0","#7a9364"].map(c=><button key={c} aria-label={`画笔颜色${c}`} aria-pressed={style.color===c&&!style.erase} className={`h-11 w-11 rounded-full border-4 ${style.color===c?"border-amber-300":"border-white"}`} style={{background:c}} onClick={()=>setStyle(s=>({...s,color:c,erase:false}))}/>)}</div>
 <canvas ref={canvas} width={1200} height={900} aria-label="速写画纸" data-stroke-count={count} onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end} className="aspect-[4/3] w-full touch-none rounded-xl border border-stone-300 bg-[#fffdf6] shadow-inner"/>
 <div className="mt-3 flex flex-wrap gap-2"><button className={button} disabled={locked||!count} onClick={undo}>撤销</button><button className={button} disabled={locked||!canRedo} onClick={()=>{const r=redo.current.pop();if(r){draft.current.strokes.push(r.line);draft.current.stroke_styles.push(r.style);setCanRedo(redo.current.length>0);redraw();persist();}}}>重做</button><button className={button} disabled={locked||!count} onClick={()=>{redo.current=draft.current.strokes.map((line,i)=>({line,style:draft.current.stroke_styles[i]})).reverse();draft.current={strokes:[],stroke_styles:[]};setCanRedo(true);redraw();persist();}}>清空画纸</button>
 <button className="focus-ring rounded-xl bg-teal-900 px-4 py-3 text-white disabled:opacity-40" disabled={locked||!count} onClick={()=>void save()}>{saving?"保存中…":"保存速写"}</button></div><p role="status">{message||`${count} 笔 · 草稿自动保留`}</p></div></div>
 {reference&&<SceneDialog title="速写参照图" wide onClose={()=>setReference(false)}><HolidayIllustration id={art} staticDay/></SceneDialog>}
 </section>;
}
