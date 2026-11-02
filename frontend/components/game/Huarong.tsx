"use client";
import {useEffect,useRef,useState,type PointerEvent} from "react";
const sizes=[[2,2],[2,1],[1,2],[1,2],[1,2],[1,2],[1,1],[1,1],[1,1],[1,1]];
const names=["曹操","关羽","张飞","赵云","马超","黄忠","兵一","兵二","兵三","兵四"];
const directions={up:[0,-1],down:[0,1],left:[-1,0],right:[1,0]};
type Direction=keyof typeof directions;
const labels=["出口在望","让出通道","左右换位","迂回前进","步步为营","横刀立马"];
const button="focus-ring min-h-11 rounded-xl border bg-white px-4 py-2 disabled:opacity-40";
function available(board:number[],piece:number,d:Direction){
 const [w,h]=sizes[piece],pos=board[piece],[dx,dy]=directions[d];let steps=0;
 for(let n=1;n<=4;n++){
  const x=pos%4+dx*n,y=Math.floor(pos/4)+dy*n;
  if(x<0||y<0||x+w>4||y+h>5)break;
  if(board.some((p,i)=>{if(i===piece)return false;const [ow,oh]=sizes[i],ox=p%4,oy=Math.floor(p/4);return x<ox+ow&&x+w>ox&&y<oy+oh&&y+h>oy;}))break;
  steps=n;
 }return steps;
}
export function Huarong({progress,disabled,onMove,storageKey="huarong-draft"}:{progress:Record<string,unknown>;disabled:boolean;onMove:(p:Record<string,unknown>)=>Promise<boolean>;storageKey?:string}){
 const [selected,setSelected]=useState(0),[level,setLevel]=useState(Number(progress.level??1));
 const serverBoard=progress.board as number[]|undefined,hint=progress.hint as {piece:number;direction:Direction}|undefined;
 type Draft={board:number[];base:number[];moves:Record<string,unknown>[];batch:Record<string,unknown>|null};
 const draft=useRef<Draft|null>(null),running=useRef(false),send=useRef(onMove);
 const [local,setLocal]=useState<number[]|null>(null),[pending,setPending]=useState(false),[error,setError]=useState('');
 useEffect(()=>{send.current=onMove;},[onMove]);
 useEffect(()=>{const timer=setTimeout(()=>{try{const value=JSON.parse(sessionStorage.getItem(storageKey)??'null') as Draft|null;if(value?.board&&value.moves){draft.current=value;setLocal(value.board);setPending(true);setError('有待保存的移动，点击继续同步。');}}catch{}},0);return()=>clearTimeout(timer);},[storageKey]);
 function persist(){if(draft.current)sessionStorage.setItem(storageKey,JSON.stringify(draft.current));else sessionStorage.removeItem(storageKey);}
 async function flush(){
  const d=draft.current;if(!d||running.current)return;
  running.current=true;setError('');
  try{
   while(d.moves.length){
    const batch=d.batch??{command:'batch',base_board:[...d.base],moves:d.moves.slice(0,20),batch_id:crypto.randomUUID()};d.batch=batch;persist();
    if(!await send.current(batch)){setError('移动仍保留在此设备，请重试同步。');return;}
    const commands=batch.moves as {piece:number;direction:Direction;steps:number}[];
    for(const m of commands){const [dx,dy]=directions[m.direction];d.base[m.piece]+=m.steps*(dx+dy*4);}
    d.moves.splice(0,commands.length);d.batch=null;persist();
    // Let the outer request state settle before sending the next ordered batch.
    await new Promise(resolve=>setTimeout(resolve,0));
   }
   draft.current=null;persist();setLocal(null);setPending(false);
  }catch{setError('连接或本地存储暂不可用，移动仍保留，请重试。');}
  finally{running.current=false;}
 }
 useEffect(()=>{if(!pending||error)return;const timer=setTimeout(()=>void flush(),180);return()=>clearTimeout(timer);});
 useEffect(()=>{if(!pending)return;const leave=(e:BeforeUnloadEvent)=>{e.preventDefault();};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[pending]);
 const board=local??serverBoard,done=board?.[0]===13;
 const locked=disabled&&!pending;
 const drag=useRef<{piece:number;x:number;y:number;direction:Direction;offset:number}|null>(null);
 const [preview,setPreview]=useState<{piece:number;x:number;y:number}|null>(null);
 function point(e:PointerEvent<SVGGElement>){const svg=e.currentTarget.ownerSVGElement!,p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM()!.inverse());}
 function down(e:PointerEvent<SVGGElement>,piece:number){if(locked||done||!board)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);const p=point(e);drag.current={piece,x:p.x,y:p.y,direction:'right',offset:0};setSelected(piece);}
 function move(e:PointerEvent<SVGGElement>){const d=drag.current;if(!d||!board)return;const p=point(e),dx=p.x-d.x,dy=p.y-d.y;d.direction=Math.abs(dx)>Math.abs(dy)?dx<0?'left':'right':dy<0?'up':'down';d.offset=Math.min(available(board,d.piece,d.direction)*100,Math.abs(Math.abs(dx)>Math.abs(dy)?dx:dy));const [x,y]=directions[d.direction];setPreview({piece:d.piece,x:x*d.offset,y:y*d.offset});}
 function commit(piece:number,direction:Direction,steps=1){
  if(!board||steps>available(board,piece,direction)||locked||done)return;
  const [dx,dy]=directions[direction],next=[...board];next[piece]+=steps*(dx+dy*4);
  draft.current??={board:[...board],base:[...board],moves:[],batch:null};
  draft.current.board=next;draft.current.moves.push({command:'move',piece,direction,steps});
  setLocal(next);setPending(true);setPreview(null);
  try{persist();}catch{setError('本地存储不可用，请保持页面打开并同步移动。');}
 }
 async function up(e:PointerEvent<SVGGElement>){move(e);const d=drag.current;drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);if(!d||!board){setPreview(null);return;}const steps=Math.round(d.offset/100);if(!steps){setPreview(null);return;}await commit(d.piece,d.direction,steps);}
 return <section className="space-y-4" aria-label="华容道棋盘">
 <p role="status" className="min-h-7 text-sm">{pending?(error||"移动正在后台保存，可以继续拖动。"):"移动已同步"}{error&&<button className={button} onClick={()=>void flush()}>继续同步</button>}</p>
 <p className="leading-7">直接拖动滑块，让曹操到达下方出口。遇到障碍会停住，松手自动对齐；也可以选中后用方向键移动。</p>
 <div className="flex flex-wrap gap-2"><select className="rounded-lg border p-3" aria-label="华容道关卡" value={level} onChange={e=>setLevel(Number(e.target.value))}>{labels.map((s,i)=><option value={i+1} key={s}>{i+1} · {s}</option>)}</select><button className={button} disabled={disabled||pending} onClick={()=>void onMove({command:"start",level})}>{board?"切换关卡":"开始"}</button></div>
 {board&&<><svg viewBox="0 0 420 550" className="mx-auto max-h-[62dvh] w-full max-w-[440px] touch-none rounded-2xl bg-[#344c47] shadow-inner" role="group" aria-label="4乘5华容道棋盘">
 <rect x="10" y="10" width="400" height="500" rx="8" fill="#183b35"/>
 {board.map((pos,i)=>{const [w,h]=sizes[i],offset=preview?.piece===i?preview:{x:0,y:0};return <g key={i} role="button" tabIndex={locked||done?-1:0} aria-label={names[i]} aria-pressed={selected===i} transform={`translate(${offset.x} ${offset.y})`}
 className="cursor-grab outline-none active:cursor-grabbing" onPointerDown={e=>down(e,i)} onPointerMove={move} onPointerUp={e=>void up(e)} onPointerCancel={()=>{drag.current=null;setPreview(null);}} onFocus={()=>setSelected(i)}
 onKeyDown={e=>{const d={ArrowUp:"up",ArrowDown:"down",ArrowLeft:"left",ArrowRight:"right"}[e.key] as Direction|undefined;if(d&&!locked&&!done){e.preventDefault();if(available(board,i,d))void commit(i,d);}}}>
 <rect x={14+pos%4*100} y={14+Math.floor(pos/4)*100} width={w*100-8} height={h*100-8} rx="10" fill={i===0?"#bd664b":i===1?"#c6a165":i<6?"#b38a60":"#dbc4a1"} stroke={hint?.piece===i?"#62e0c1":selected===i?"#fff4bd":"#6b5036"} strokeWidth={selected===i||hint?.piece===i?4:2}/>
 <rect x={23+pos%4*100} y={23+Math.floor(pos/4)*100} width={w*100-26} height={h*100-26} rx="5" fill="none" stroke="#f7dfaf" opacity=".5"/>
 <text x={10+pos%4*100+w*50} y={18+Math.floor(pos/4)*100+h*50} textAnchor="middle" fontFamily="serif" fontSize={i===0?34:24} fill={i===0?"#fff4d5":"#513821"}>{names[i]}{hint?.piece===i?({up:'↑',down:'↓',left:'←',right:'→'})[hint.direction]:''}</text>
 </g>;})}<path d="M116 510H304" stroke="#f2ca71" strokeWidth="9"/><text x="210" y="541" textAnchor="middle" fontSize="18" fill="#fff1cd">出口 ↓</text></svg>
 <div className="flex flex-wrap gap-2"><button className={button} disabled={disabled||pending||!(progress.undo as unknown[])?.length} onClick={()=>void onMove({command:"undo"})}>撤销一步</button><button className={button} disabled={disabled||pending} onClick={()=>void onMove({command:"restart"})}>重开本关</button><button className={button} disabled={disabled||pending||done} onClick={()=>void onMove({command:"hint"})}>提示下一步</button></div>
 {hint&&<p role="status">可以把{names[hint.piece]}向{({up:"上",down:"下",left:"左",right:"右"})[hint.direction]}移动一格。</p>}
 <p role="status">{done?"出口打开了，成功过关！":"拖动棋子继续"} · {Number(progress.moves??0)} 次操作 · {Number(progress.hints??0)} 次提示</p></>}
 </section>;
}
