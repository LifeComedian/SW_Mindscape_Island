"use client";
import {useCallback,useEffect,useRef,useState} from "react";
import {Piece} from "./PlayPieces";
type Attempt={round:number;position:number;contact_ms:number|null};
const btn="focus-ring min-h-11 rounded-xl border bg-white px-4 py-3 disabled:opacity-40";
export function TimedVolley({sid,runtimeId,progress,disabled,onHit,partners=[]}:{sid:number;runtimeId?:number|null;progress:Record<string,unknown>;disabled:boolean;onHit:(p:Record<string,unknown>)=>Promise<boolean>;partners?:string[]}){
 const [difficulty,setDifficulty]=useState("easy"),[attempts,setAttempts]=useState<Attempt[]>([]),[frame,setFrame]=useState(0),[position,setPosition]=useState(50),[feedback,setFeedback]=useState(""),[sending,setSending]=useState(false);
 const targets=progress.targets as number[]|undefined,version=progress.game_version,modern=version==='volley-position-v1',started=modern&&!!targets,done=Boolean(progress.done),duration=Number(progress.duration_ms??1800),tolerance=Number(progress.tolerance??12);
 const returnDuration=Number(progress.return_ms??380),between=Number(progress.between_ms??120);
 const [impact,setImpact]=useState({x:50,y:300,rotation:180});
 const id=String(progress.practice_id??''),key=`volley-position:${sid}:${runtimeId??'solo'}:${id}`;
 const data=useRef<Attempt[]>([]),start=useRef(0),x=useRef(50),hit=useRef<Attempt|null>(null),phase=useRef<'flight'|'return'>('flight'),saveRef=useRef(onHit),lock=useRef(disabled),round=attempts.length;
 const court=useRef<SVGSVGElement>(null);
 const [ready,setReady]=useState(false),[saveError,setSaveError]=useState('');
 const [visualPhase,setVisualPhase]=useState<'flight'|'return'>('flight'),[contact,setContact]=useState(false);
 useEffect(()=>{saveRef.current=onHit;lock.current=disabled;},[onHit,disabled]);
 useEffect(()=>{let restored:Attempt[]=[];try{const value=JSON.parse(sessionStorage.getItem(key)??'null');if(Array.isArray(value?.attempts))restored=value.attempts;}catch{}
  const timer=setTimeout(()=>{data.current=restored;setAttempts(restored);hit.current=null;phase.current='flight';setVisualPhase('flight');setContact(false);setFrame(0);start.current=0;setReady(false);setFeedback(restored.length?'进度已恢复，准备好再继续':'准备好后再发球');},0);return()=>clearTimeout(timer);},[key]);
 const successful=useCallback((a:Attempt)=>!!targets&&a.contact_ms!==null&&Math.abs(a.position-targets[a.round])<=tolerance&&a.contact_ms/duration>=.72&&a.contact_ms/duration<=.98,[targets,tolerance,duration]);
 const save=useCallback(async(values:Attempt[])=>{setSending(true);setSaveError('');try{const ok=await saveRef.current({command:'finish',practice_id:id,attempts:values});if(ok)sessionStorage.removeItem(key);else setSaveError('本轮记录还在，请重试保存。');}catch{setSaveError('连接中断，记录已保留，请重试保存。');}finally{setSending(false);}},[id,key]);
 useEffect(()=>{
  if(!ready||!started||done||data.current.length>=12)return;
  let token=0,live=true;
  function tick(){if(!live)return;const elapsed=performance.now()-start.current;setFrame(elapsed);
   if(phase.current==='flight'&&(hit.current||elapsed>=duration)){
    hit.current=hit.current??{round:data.current.length,position:x.current,contact_ms:null};
    const fraction=Math.min(1,(hit.current.contact_ms??duration)/duration);
    setImpact({x:50+(targets![data.current.length]-50)*fraction,y:45+255*fraction,rotation:fraction*180});
    phase.current='return';setVisualPhase('return');setContact(successful(hit.current));start.current=performance.now();setFrame(0);setFeedback(successful(hit.current)?'接稳了！':hit.current.contact_ms===null?'球落下了，再来一球':Math.abs(hit.current.position-targets![data.current.length])>tolerance?'偏了一点，靠近落点再试':'时机差一点，再来');
   }else if(phase.current==='return'&&elapsed>=returnDuration){
    data.current=[...data.current,hit.current!];try{sessionStorage.setItem(key,JSON.stringify({attempts:data.current}));}catch{}setAttempts(data.current);hit.current=null;phase.current='flight';setVisualPhase('flight');start.current=performance.now()+between;setFrame(0);
    if(data.current.length>=12){void save(data.current);return;}
   }
   token=requestAnimationFrame(tick);
  }token=requestAnimationFrame(tick);return()=>{live=false;cancelAnimationFrame(token);};
 },[ready,started,done,id,duration,key,save,successful,targets,tolerance,round,returnDuration,between]);
 function strike(){if(!ready||!started||done||phase.current!=='flight'||hit.current||data.current.length>=12||lock.current)return;const ms=performance.now()-start.current;if(ms<0)return;hit.current={round:data.current.length,position:x.current,contact_ms:Math.min(duration,Math.round(ms))};}
 function move(value:number){x.current=Math.max(5,Math.min(95,value));setPosition(x.current);}
 const flight=Math.max(0,Math.min(1,frame/duration)),target=targets?.[Math.min(round,11)]??50;
 const rebound=Math.max(0,Math.min(frame/returnDuration,1));
 const ballX=visualPhase==='return'?impact.x+(contact?(50-impact.x)*rebound:0):50+(target-50)*flight,ballY=visualPhase==='return'?(contact?impact.y-(impact.y-45)*rebound:impact.y+65*rebound):45+255*flight;
 const rotation=visualPhase==='return'?impact.rotation+rebound*160:flight*180;
 return <section className="space-y-4" aria-label="限时垫球练习">
 <p>移动到球的落点附近，球靠近手臂时点击或按空格垫起。鼠标/触摸移动，方向键也能调整。每轮12球，失误后直接继续。</p>
 {(!started||done)&&<><select aria-label="垫球难度" className="rounded-xl border p-3" value={difficulty} onChange={e=>setDifficulty(e.target.value)}><option value="easy">轻松 · 每球1.8秒</option><option value="challenge">标准 · 每球1.1秒</option><option value="fast">挑战 · 每球0.8秒</option></select><button disabled={disabled} className={btn+" ml-3"} onClick={()=>void onHit({command:'start',difficulty})}>{done?'再练一轮':version&&!modern?'保留旧记录，开始新版练习':'开始练习'}</button></>}
 {started&&!done&&<><p className="min-h-7 text-lg font-bold">第 {Math.min(round+1,12)}/12 球 · {ready&&frame<0?`准备 ${Math.ceil(-frame/1000)}`:feedback}</p>{partners.length>0&&<p>{partners[round%partners.length]}向你传球 · 把球垫回伙伴身边</p>}
 {!ready&&<button className={btn+" w-full bg-teal-50"} disabled={disabled} onClick={()=>{court.current?.scrollIntoView({block:'center',behavior:'instant'});court.current?.focus({preventScroll:true});start.current=performance.now()+3000;setFrame(-3000);setReady(true);}}>准备好了，开始接球</button>}
 <svg ref={court} viewBox="0 0 600 400" tabIndex={0} role="application" aria-label="移动接球场地" className="mx-auto block max-h-[45dvh] w-full touch-none rounded-2xl bg-[#dbe8df] outline-none focus:ring-2 focus:ring-teal-600"
 onPointerMove={e=>{if(!started||done)return;const r=e.currentTarget.getBoundingClientRect();move((e.clientX-r.left)/r.width*100);}}
 onPointerDown={e=>{e.preventDefault();e.currentTarget.focus({preventScroll:true});e.currentTarget.setPointerCapture(e.pointerId);const r=e.currentTarget.getBoundingClientRect();move((e.clientX-r.left)/r.width*100);if(e.pointerType!=='touch')strike();}}
 onKeyDown={e=>{if(['ArrowLeft','ArrowRight',' '].includes(e.key)){e.preventDefault();if(e.key===' ')strike();else move(x.current+(e.key==='ArrowLeft'?-4:4));}}}>
 <path d="M40 40H560L590 360H10Z" fill="#bfcbaa" stroke="white" strokeWidth="4"/><path d="M25 200H575M300 40V360" stroke="white" strokeWidth="3"/><path d="M30 95H570" stroke="#647b70" strokeWidth="4"/>
 <ellipse cx={target*6} cy="335" rx={tolerance*6} ry="15" fill="#f9e49a" opacity=".7" stroke="#9c8c4f" strokeDasharray="6 5"/>
 <g transform={`translate(${position*6} 335)`}><ellipse cy="16" rx="29" ry="9" fill="#647b70" opacity=".25"/><path d="M-13 -15L-24 12M13 -15L24 12" stroke="#344e61" strokeWidth="9" strokeLinecap="round"/><path d="M-14 -47H14L20 -12H-20Z" fill="#db9367"/><circle cy="-65" r="13" fill="#d7ac83"/><path d="M-14 -40L0 -27L14 -40" fill="none" stroke="#d7ac83" strokeWidth="8" strokeLinecap="round"/></g>
 {round<12&&<g data-testid="volley-ball" data-phase={visualPhase} transform={`translate(${ballX*6} ${ballY}) rotate(${rotation})`}><Piece kind="court"/></g>}
 <text x="300" y="389" textAnchor="middle" fill="#355c4f" fontSize="17">靠近落点 · 球到手臂附近时垫起</text></svg>
 <button className={btn+" w-full"} disabled={disabled||!ready||frame<0||round>=12} onClick={strike}>垫球（空格）</button></>}
 {(done||round>=12)&&<p role="status" className="rounded-xl bg-teal-50 p-4">本轮完成 · 接稳 {done?Number(progress.score):attempts.filter(successful).length}/12 球{sending?' · 正在保存…':''}</p>}
 {!done&&round>=12&&!sending&&<div role="status">{saveError||'本轮在浏览器中保留，可以保存后继续。'}<button className={btn} disabled={disabled} onClick={()=>void save(data.current)}>保存本轮记录</button></div>}
 </section>;
}
