"use client";
import {useEffect,useRef,useState,type PointerEvent,type KeyboardEvent} from 'react';
import type {ObjectOperation} from '@/lib/api';
import {Piece,ItemPicture} from './PlayPieces';
import {workshopTrace,type TraceEvent} from '@/lib/workshop-trace';

type Dot={x:number;y:number};
type Material=Dot&{kind:string};
type Design={pieces:Material[];moves:Dot[];polished:number[]};
const blank=():Design=>({pieces:[],moves:[],polished:[]});
const btn='focus-ring min-h-11 rounded-xl border border-stone-300 bg-white px-4 py-2 text-sm font-semibold disabled:opacity-40';
const wood:Record<string,Record<string,Dot>>={boat:{hull:{x:50,y:68},mast:{x:50,y:40},sail:{x:66,y:42}},coaster:{slat1:{x:50,y:38},slat2:{x:50,y:50},slat3:{x:50,y:62}}};
const labels:Record<string,string>={sunflower:'向日葵',rose:'粉玫瑰',tulip:'郁金香',hydrangea:'蓝绣球',lily:'百合',dandelion:'蒲公英',jasmine:'茉莉',mint:'薄荷叶',lavender:'薰衣草',cosmos:'波斯菊',rosemary:'迷迭香',daisy:'小雏菊',warm:'暖色小花',leaf:'尤加利叶',hull:'船身',mast:'桅杆',sail:'帆片',slat1:'第一块木条',slat2:'第二块木条',slat3:'第三块木条'};
const rope=[{x:70,y:38},{x:30,y:55},{x:85,y:72}];
const walk=[{x:20,y:70},{x:42,y:50},{x:65,y:40},{x:84,y:66}];
const near=(a:Dot,b:Dot)=>Math.hypot(a.x-b.x,a.y-b.y)<8;

export function Workshop({objectId,action,progress,sessionId,disabled,onSubmit,runtimeId=null,recordTrace=false}:{objectId:string;action:ObjectOperation;progress:Record<string,unknown>;sessionId:number;disabled:boolean;onSubmit:(p:Record<string,unknown>)=>Promise<boolean>;runtimeId?:number|null;recordTrace?:boolean}){
  const [design,setDesign]=useState<Design>(()=>({...blank(),...(progress.design as Partial<Design>??{})}));
  const [style,setStyle]=useState(String(progress.item??action.items[0]?.id??''));
  const [selected,setSelected]=useState(0);
  const [done,setDone]=useState(Boolean(progress.done&&progress.design));
  const [ready,setReady]=useState(false);
  const [error,setError]=useState('');
  const [saving,setSaving]=useState(false);
  const inFlight=useRef(false);
  const trace=useRef<ReturnType<typeof workshopTrace>|null>(null);
  const traceTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>{
    if(recordTrace){trace.current=workshopTrace(sessionId,objectId,`v4_${objectId}__${action.id}`,runtimeId);void trace.current.flush();}
    return()=>{if(traceTimer.current)clearTimeout(traceTimer.current);trace.current=null;};
  },[sessionId,objectId,action.id,runtimeId,recordTrace]);
  function record(event:Omit<TraceEvent,'seq'>){
    trace.current?.record(event);
    if(traceTimer.current)clearTimeout(traceTimer.current);
    traceTimer.current=setTimeout(()=>{void trace.current?.flush();},600);
  }
  const drag=useRef<{index:number;offset:Dot}|null>(null);
  const key=runtimeId?`workshop:${sessionId}:${runtimeId}:${objectId}:${action.id}`:`workshop:${sessionId}:${objectId}:${action.id}`;
  const initial=useRef(JSON.stringify(progress));
  useEffect(()=>{const t=setTimeout(()=>{
    try{const draft=JSON.parse(sessionStorage.getItem(key)??'null');if(draft?.base===initial.current){setDesign(draft.design);setStyle(draft.style);setDone(draft.done);}}catch{}
    setReady(true);
  },0);return()=>clearTimeout(t);},[key]);
  useEffect(()=>{if(ready)try{sessionStorage.setItem(key,JSON.stringify({design,style,done,base:JSON.stringify(progress)}));}catch{}},[design,style,done,key,progress,ready]);
  const flower=objectId==='flowers', timber=objectId==='wood_work', knot=objectId==='rope';
  const targets=timber?(action.geometry_version==='tight-v6'?{hull:{x:50,y:68},mast:{x:50,y:54},sail:{x:54.8,y:51.5}}:wood[style]??wood.boat):{};
  const sequence=knot?rope:walk;
  const stage=design.moves.length;
  const locked=disabled||saving||done;
  const assembled=timber&&Object.entries(targets).every(([kind,p])=>design.pieces.some(m=>m.kind===kind&&near(m,p)));
  const complete=flower?design.pieces.length>=3&&design.pieces.some(p=>p.kind!=='leaf'):timber?assembled&&(action.geometry_version==='tight-v6'||design.polished.length===3):stage===sequence.length;
  const hint=flower?'点击桌上的花材放入花器，再拖动花头调整高度与位置。':timber?(action.geometry_version==='tight-v6'?'取用木片并拖入对应轮廓，拼好后即可保存。':'点击取用木片，拖入虚线轮廓；拼好后擦拭三个金色边缘。'):knot?['把右侧绳头拖入金色圆圈，跨过左绳。','把左侧绳头拖入金色圆圈，反向交叉。','向右下方拉动绳端，让平结收紧。','两端已拉紧，可以收好这枚绳结。'][stage]:'点击沙滩上下一处脚印，沿潮线走到终点。';
  const cursor=design.moves.at(-1)??{x:10,y:85};
  function position(e:PointerEvent<SVGGElement>):Dot{
    const r=e.currentTarget.ownerSVGElement!.getBoundingClientRect();
    return {x:Math.round((e.clientX-r.left)/r.width*100),y:Math.round((e.clientY-r.top)/r.height*100)};
  }
  function update(index:number,p:Dot){
    const next={x:Math.min(flower?85:93,Math.max(flower?15:7,p.x)),y:Math.min(flower?66:90,Math.max(flower?12:10,p.y))};
    setDesign(d=>({...d,pieces:d.pieces.map((m,i)=>i===index?{...m,...next}:m),polished:timber?[]:d.polished}));
  }
  function down(e:PointerEvent<SVGGElement>,index:number){if(locked)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);setSelected(index);const p=position(e),m=design.pieces[index];drag.current={index,offset:{x:p.x-m.x,y:p.y-m.y}};}
  function move(e:PointerEvent<SVGGElement>){if(locked||!drag.current)return;const p=position(e);update(drag.current.index,{x:p.x-drag.current.offset.x,y:p.y-drag.current.offset.y});}
  function up(e:PointerEvent<SVGGElement>){if(!drag.current)return;const {index,offset}=drag.current;drag.current=null;if(locked)return;const raw=position(e);let p={x:raw.x-offset.x,y:raw.y-offset.y};if(timber){const target=targets[design.pieces[index].kind];if(target&&near(p,target))p=target;}p={x:Math.min(flower?85:93,Math.max(flower?15:7,p.x)),y:Math.min(flower?66:90,Math.max(flower?12:10,p.y))};update(index,p);record({operation:'move',method:'pointer',piece_index:index,...p});}
  function nudge(e:KeyboardEvent<SVGGElement>,index:number){if(locked)return;const delta:Record<string,Dot>={ArrowUp:{x:0,y:-3},ArrowDown:{x:0,y:3},ArrowLeft:{x:-3,y:0},ArrowRight:{x:3,y:0}};const d=delta[e.key];if(d){e.preventDefault();setSelected(index);const p={x:Math.min(flower?85:93,Math.max(flower?15:7,design.pieces[index].x+d.x)),y:Math.min(flower?66:90,Math.max(flower?12:10,design.pieces[index].y+d.y))};update(index,p);record({operation:'move',method:'keyboard',piece_index:index,...p});}}
  function add(kind:string){if(locked)return;setError('');record({operation:'add',method:'button',material:kind,piece_index:design.pieces.length});setDesign(d=>({...d,pieces:[...d.pieces,{kind,x:flower?25+d.pieces.length*8:15,y:flower?25+d.pieces.length%3*15:28+d.pieces.length*20}]}));setSelected(design.pieces.length);}
  function visit(i:number,method:TraceEvent['method']='button'){if(locked||i!==stage)return;record({operation:'visit',method,piece_index:i,...sequence[i]});setDesign(d=>({...d,moves:[...d.moves,sequence[i]]}));}
  function polish(i:number,method:TraceEvent['method']){if(locked)return;record({operation:'polish',method,piece_index:i});setDesign(d=>({...d,polished:Array.from(new Set([...d.polished,i]))}));}
  async function finish(){if(!complete||locked||inFlight.current)return;inFlight.current=true;setSaving(true);setError('');record({operation:'submit',method:'button'});void trace.current?.flush();try{const ok=await onSubmit({command:'finish_graphical',item:style,...(trace.current?{trace_draft_id:trace.current.draftId()}:{}),...(flower||timber?{pieces:design.pieces,...(timber?{polished:design.polished}:{})}:{moves:design.moves})});if(ok){setDone(true);sessionStorage.removeItem(key);}else setError('作品还在桌上，请根据提示重试保存。');}finally{inFlight.current=false;setSaving(false);}}
  if(!ready)return <p role="status">正在铺开操作台…</p>;
  return <section data-testid={`workshop-${objectId}`} className="space-y-4">
    {!!action.items.length&&<fieldset className="flex flex-wrap gap-2"><legend className="mb-2 text-xs tracking-widest text-stone-500">{flower?'选择花器':'作品样式'}</legend>{action.items.map(i=><button key={i.id} type="button" aria-pressed={style===i.id} disabled={locked} className={`${btn} ${style===i.id?'border-teal-700 bg-teal-50':''}`} onClick={()=>{record({operation:'style',method:'button',choice:i.id});setStyle(i.id);if(timber)setDesign(blank());}}>{flower?(i.id==='white'?'浅口花器':'小陶瓶'):i.name}</button>)}</fieldset>}
    {action.daily_hint&&<p className="rounded-xl bg-amber-50 p-3 text-sm">{action.daily_hint}</p>}
    <p id={`workshop-help-${objectId}`} className="text-sm leading-6 text-stone-600">{done?'作品已保存。可以查看完成的样子，或再做一份。':hint}</p>
    <div className={(flower||timber)&&!done?"grid items-start gap-3 sm:grid-cols-[110px_minmax(0,1fr)]":""}>
    {(flower||timber)&&!done&&<div aria-label="桌上的材料" className="flex flex-wrap justify-center gap-2 rounded-xl bg-[#f5f0e5] p-2">{(flower?(action.daily_materials??['daisy','warm','leaf']):Object.keys(targets)).map(kind=><button key={kind} aria-label={`取用${labels[kind]}`} className="focus-ring w-24 rounded-xl border border-white bg-white/70 p-2 text-xs text-stone-700 shadow-sm disabled:opacity-40" disabled={locked||(flower?design.pieces.length>=8:design.pieces.some(p=>p.kind===kind))} onClick={()=>add(kind)}><ItemPicture kind={kind}/>{labels[kind]}</button>)}</div>}
    <svg viewBox="0 0 400 300" aria-label={flower?'插花操作台':timber?'木作操作台':knot?'绳结练习台':'沙滩步行路线'} aria-describedby={`workshop-help-${objectId}`} className="mx-auto aspect-[4/3] w-full max-w-[520px] touch-none overflow-hidden rounded-2xl border border-[#d9ccb3] bg-[#eee3cb] shadow-inner" data-testid="workshop-canvas">
      <rect width="400" height="215" fill={flower?'#f5f1e7':knot?'#e7d4b5':timber?'#e5cfab':'#98c4c9'}/>
      {flower?<><path d="M0 213 H400 M0 256 H400" stroke="#d4c09c"/><ellipse cx="200" cy="275" rx="75" ry="12" fill="#c7b58e" opacity=".35"/><path d="M145 233 Q150 279 200 278 Q250 279 255 233Z" fill={style==='white'?'#ede4ca':'#bf9873'} stroke="#a78a65" strokeWidth="2"/><ellipse cx="200" cy="233" rx="55" ry="12" fill="#c5b78f"/>{design.pieces.map((m,i)=><path key={i} d={`M${200+(i%3-1)*8} 239 Q${m.x*4+8} 208 ${m.x*4} ${m.y*3}`} stroke="#748363" strokeWidth="2.5" fill="none"/>)}</>:timber?<><path d="M0 48 H400 M0 125 H400 M0 222 H400" stroke="#cbb18a" strokeWidth="2"/>{Object.entries(targets).map(([kind,p])=><g key={kind} transform={`translate(${p.x*4} ${p.y*3}) scale(1.7)`} opacity=".28"><Piece kind={kind}/><rect x="-26" y="-25" width="52" height="50" rx="6" fill="none" stroke="#77592e" strokeDasharray="3 3"/></g>)}</>:knot?<><path d={`M35 250 Q110 80 240 115 Q170 200 100 165 Q180 90 ${stage>=2?340:290} ${stage>=2?216:70}`} fill="none" stroke="#a97851" strokeWidth="11" strokeLinecap="round"/><path d={`M365 250 Q310 80 160 115 Q230 200 300 165 Q230 90 ${stage>=1?120:90} ${stage>=1?165:70}`} fill="none" stroke="#e8b869" strokeWidth="10" strokeLinecap="round"/></>:<><path d="M0 140 Q70 80 150 130 Q210 180 290 110 Q340 80 400 130 V300 H0Z" fill="#f0e0bd"/><path d="M0 122 Q70 62 150 112 Q210 162 290 92 Q340 62 400 112" fill="none" stroke="#edf4e4" strokeWidth="8"/><path d="M40 255 L80 210 L168 150 L260 120 L336 198" stroke="#bb9e6e" strokeDasharray="3 8" strokeWidth="3" fill="none"/>{walk.map((p,i)=><g key={i} role="button" aria-label={`走到第${i+1}处脚印`} tabIndex={locked||i!==stage?-1:0} aria-disabled={locked||i!==stage} className="cursor-pointer focus:outline-none" onClick={()=>visit(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();visit(i,'keyboard');}}}><circle cx={p.x*4} cy={p.y*3} r="23" fill={i===stage?'#e5b760':'#dccbab'} stroke={i===stage?'#927345':'#c5af88'}/><text x={p.x*4} y={p.y*3+5} fontSize="14" textAnchor="middle" fill="#5b4b37">{i<stage?'✓':i+1}</text></g>)}<g transform={`translate(${cursor.x*4-14} ${cursor.y*3-18})`}><ellipse rx="5" ry="9" fill="#967d54"/><ellipse cx="10" cy="9" rx="5" ry="9" fill="#967d54"/></g></>}
      {design.pieces.map((m,i)=><g key={i} role="button" aria-label={`${labels[m.kind]} ${i+1}，左右${m.x}，高低${m.y}`} aria-disabled={locked} tabIndex={locked?-1:0} className="cursor-grab outline-none active:cursor-grabbing focus:drop-shadow-lg" transform={`translate(${m.x*4} ${m.y*3}) scale(${flower?1.3:1.7})`} onPointerDown={e=>down(e,i)} onPointerMove={move} onPointerUp={up} onPointerCancel={()=>{drag.current=null;}} onKeyDown={e=>nudge(e,i)} onFocus={()=>setSelected(i)}>
        <circle r={flower?20:27} fill={selected===i&&!done?'#fff9df':'transparent'} fillOpacity=".45" stroke={selected===i&&!done?'#b49c62':'transparent'} strokeDasharray="2 3"/>
        <g pointerEvents="none"><Piece kind={m.kind}/></g>
      </g>)}
      {assembled&&!done&&action.geometry_version!=='tight-v6'&&<PolishTargets locked={locked} polished={design.polished} onPolish={polish}/>}
      {knot&&stage<3&&!done&&<><circle cx={rope[stage].x*4} cy={rope[stage].y*3} r="22" fill="#efd18d" stroke="#9e804f" strokeDasharray="4 3"/><text x={rope[stage].x*4} y={rope[stage].y*3+5} fontSize="12" textAnchor="middle">拖到这里</text><g role="button" aria-label={`移动绳头：${action.steps?.[stage]}`} tabIndex={locked?-1:0} className="cursor-grab outline-none focus:opacity-60" onPointerDown={e=>{if(locked)return;e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{if(e.buttons===1&&!locked){const p=position(e);e.currentTarget.setAttribute('transform',`translate(${p.x*4} ${p.y*3})`);}}} onPointerUp={e=>{const p=position(e);e.currentTarget.setAttribute('transform',`translate(${stage%2?90:290} 70)`);if(!locked&&near(p,rope[stage]))visit(stage,'pointer');}} onPointerCancel={e=>e.currentTarget.setAttribute('transform',`translate(${stage%2?90:290} 70)`)} onKeyDown={e=>{if(!locked&&(e.key==='Enter'||e.key===' ')){e.preventDefault();visit(stage,'keyboard');}}} transform={`translate(${stage%2?90:290} 70)`}><circle r="20" fill={stage%2?'#a97851':'#e8b869'} stroke="#fff8e8" strokeWidth="3"/><text y="5" textAnchor="middle" fontSize="12">绳头</text></g></>}
    </svg></div>
    {!done&&(flower||timber)&&!!design.pieces.length&&<div className="flex flex-wrap items-center gap-2"><span className="text-xs text-stone-500">选中后可用方向键微调</span>{flower&&<button className={btn} disabled={locked} onClick={()=>{record({operation:'remove',method:'button',piece_index:selected});setDesign(d=>({...d,pieces:d.pieces.filter((_,i)=>i!==selected)}));}}>移走选中花材</button>}<button className={btn} disabled={locked} onClick={()=>{record({operation:'clear',method:'button'});setDesign(blank());}}>清空操作台</button></div>}
    <div className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-sm text-stone-600">{done?'已完成，作品和操作已记录。':flower?`${design.pieces.length} / 8 枝 · 至少放入 3 枝`:timber?`${design.pieces.length} / 3 木片${action.geometry_version==='tight-v6'?' · 对齐后即可完成':` · ${design.polished.length} / 3 边缘已打磨`}`:`${stage} / ${sequence.length} 处已完成`}</p>{done?<button className={btn} disabled={disabled} onClick={()=>{record({operation:'restart',method:'button'});setDone(false);setDesign(blank());setError('');}}>再做一次</button>:<button className="focus-ring min-h-12 rounded-xl bg-teal-900 px-5 py-3 font-semibold text-white disabled:opacity-40" disabled={locked||!complete} onClick={()=>void finish()}>{saving?'正在保存…':flower||timber?'完成并保存作品':knot?'收好绳结':'结束这段散步'}</button>}</div>
    {error&&<p role="alert" className="text-sm text-amber-900">{error}</p>}
  </section>;
}

function PolishTargets({locked,polished,onPolish}:{locked:boolean;polished:number[];onPolish:(i:number,method:TraceEvent['method'])=>void}){
  return <>{[0,1,2].map(i=><g key={i} role="button" aria-label={`打磨第${i+1}处边缘`} tabIndex={locked?-1:0} className="cursor-pointer outline-none focus:opacity-60" onClick={()=>onPolish(i,'button')} onKeyDown={e=>{if(!locked&&(e.key==='Enter'||e.key===' ')){e.preventDefault();onPolish(i,'keyboard');}}}><circle cx={140+i*60} cy="253" r="17" fill={polished.includes(i)?'#809773':'#e0ae60'}/><text x={140+i*60} y="259" textAnchor="middle" fontSize="16" fill="white">{polished.includes(i)?'✓':'✧'}</text></g>)}</>;
}
