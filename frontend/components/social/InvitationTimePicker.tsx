"use client";
import {useEffect,useRef,useState} from 'react';
import {requestJson} from '@/lib/api';

export function InvitationTimePicker({sid,recipe,agents,day,minute,minDay,totalDays=7,disabled,onChange,onValid}:{sid:number;recipe:string;agents:number[];day:number;minute:number;minDay:number;totalDays?:number;disabled?:boolean;onChange:(day:number,minute:number)=>void;onValid:(valid:boolean)=>void}){
 const [times,setTimes]=useState<number[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 const callbacks=useRef({onChange,onValid,minute});
 useEffect(()=>{callbacks.current={onChange,onValid,minute};},[onChange,onValid,minute]);
 const ids=[...agents].sort((a,b)=>a-b).join(',');
 useEffect(()=>{
  let live=true;const timer=setTimeout(()=>{setLoading(true);setError('');callbacks.current.onValid(false);},0);
  requestJson<{times:number[]}>(`/sessions/${sid}/world/v5/invitation-slots?recipe_id=${encodeURIComponent(recipe)}&day=${day}&agent_ids=${ids}`)
   .then(result=>{if(!live)return;setTimes(result.times);const chosen=result.times.includes(callbacks.current.minute)?callbacks.current.minute:result.times.find(t=>t>=callbacks.current.minute)??result.times[0]??-1;callbacks.current.onChange(day,chosen);callbacks.current.onValid(chosen>=0);})
   .catch(()=>{if(live){setTimes([]);setError('可选时段暂未加载，请重试。');}}).finally(()=>{if(live)setLoading(false);});
  return()=>{live=false;clearTimeout(timer);};
 },[sid,recipe,day,ids,refresh]);
 return <div className="flex flex-wrap items-center gap-3"><label>日期<select aria-label="邀约日期" className="ml-2 rounded border p-2" value={day} disabled={disabled} onChange={e=>{onValid(false);onChange(Number(e.target.value),-1);}}>{Array.from({length:totalDays-minDay+1},(_,i)=>minDay+i).map(d=><option key={d} value={d}>10月{d}日</option>)}</select></label>
 <label>时间<select aria-label="邀约时间" className="ml-2 rounded border p-2" value={minute} disabled={disabled||loading||!times.length} onChange={e=>onChange(day,Number(e.target.value))}>{loading||!times.length?<option value={-1}>{loading?'正在查询…':'当天没有可安排时段'}</option>:times.map(t=><option key={t} value={t}>{String(Math.floor(t/60)).padStart(2,'0')}:{String(t%60).padStart(2,'0')}</option>)}</select></label>
 {!loading&&!times.length&&!error&&<p className="text-sm">请换一天，或调整活动与伙伴。</p>}{error&&<p role="alert">{error}<button onClick={()=>setRefresh(n=>n+1)} className="ml-2 underline">重试</button></p>}
 </div>;
}
