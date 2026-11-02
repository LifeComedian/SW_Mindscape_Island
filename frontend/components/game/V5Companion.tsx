"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
import {getV5,postV5,seenV5,type Proposal,type V5Snapshot} from '@/lib/holiday-v5';
import {getIslandGuides,type IslandGuide} from '@/lib/api';
import {PlayerAppearance} from './PlayerAppearance';
import {SceneDialog} from './SceneDialog';
import {ObjectExplorer} from './ObjectExplorer';
import {InvitationTimePicker} from '@/components/social/InvitationTimePicker';
import {PhoneActivityComposer} from '@/components/social/PhoneActivityComposer';
const btn='focus-ring rounded-xl border bg-white px-4 py-3 font-semibold disabled:opacity-50';
export function V5Companion({sid,revision,minute,day,totalDays=7,location,blocked,onChanged,onPortrait,onExecute}:{sid:number;revision:number;minute:number;day:number;totalDays?:number;location:string;blocked:boolean;onChanged:()=>void;onPortrait:(url:string)=>void;onExecute:(id:string,inputs:Record<string,string>)=>Promise<boolean>}){
  const [data,setData]=useState<V5Snapshot|null>(null),[goals,setGoals]=useState<IslandGuide[]>([]),[book,setBook]=useState(false),[invite,setInvite]=useState(''),[gender,setGender]=useState<'male'|'female'|''>(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[hidden,setHidden]=useState(false),[notices,setNotices]=useState<{id:string;text:string}[]>([]);
  const callbacks=useRef({onChanged,onPortrait});useEffect(()=>{callbacks.current={onChanged,onPortrait};},[onChanged,onPortrait]);
  const load=useCallback(async()=>{const [d,g]=await Promise.all([getV5(sid),getIslandGuides(sid)]);if(d.closed)return;setData(d);setGoals(g.guides);const read=JSON.parse(localStorage.getItem(`v5-notices:${sid}`)??'[]') as string[];setNotices(d.notifications.filter(n=>!read.includes(n.id)));if(d.profile)callbacks.current.onPortrait(d.profile.portrait_url);},[sid]);
  useEffect(()=>{const t=setTimeout(()=>void load().catch(()=>setError('新版状态暂未同步，请重试。')),0);return()=>clearTimeout(t);},[load,revision]);
  useEffect(()=>{const fn=()=>void load().catch(()=>{});window.addEventListener('v5-guides-changed',fn);const poll=setInterval(fn,5000);return()=>{window.removeEventListener('v5-guides-changed',fn);clearInterval(poll);};},[load]);
  useEffect(()=>{const fn=(event:Event)=>setInvite((event as CustomEvent<string>).detail);window.addEventListener('v5-invite-object',fn);return()=>window.removeEventListener('v5-invite-object',fn);},[]);
  async function save(){if(!gender||busy)return;setBusy(true);try{await postV5(sid,'profile',{gender,idempotency_key:`v5-appearance-${sid}-${gender}`});await load();callbacks.current.onChanged();}catch(e){setError(e instanceof Error?e.message:'形象未保存，请重试。');}finally{setBusy(false);}}
  useEffect(()=>{const t=setTimeout(()=>setHidden(localStorage.getItem(`v5-guide-hidden:${sid}`)==='1'),0);return()=>clearTimeout(t);},[sid]);
  function toggleGuide(value:boolean){void seenV5(sid,'guide_preferences',value?'skip':'resume').then(()=>load()).catch(()=>{});setHidden(value);localStorage.setItem(`v5-guide-hidden:${sid}`,value?'1':'0');}
  useEffect(()=>{if(data?.next_local)void seenV5(sid,'guide_step',hidden?'none':goals[0]?.id??'none',true).catch(()=>{});},[sid,data?.next_local,hidden,goals[0]?.id]);
  const proposal=data?.proposals[0];
  useEffect(()=>{
    if(!data?.next_local)return;
    const sample=()=>{void postV5(sid,'foreground',{idempotency_key:crypto.randomUUID(),visible:document.visibilityState==='visible',waiting:busy,paused:blocked,view:book?'guidebook':invite?'invitation':'island'}).catch(()=>{});};
    sample();const t=setInterval(sample,15000);document.addEventListener('visibilitychange',sample);
    return()=>{clearInterval(t);document.removeEventListener('visibilitychange',sample);};
  },[sid,data?.next_local,busy,blocked,book,invite]);
  return <><section className="mx-3 my-2 rounded-xl border border-teal-200 bg-white/95 p-3" data-testid="v5-orientation">{error&&<p role="alert">{error}<button className={btn} onClick={()=>void load()}>重新同步</button></p>}{!hidden? <><p className="font-bold">{goals[0]?.title??'按自己的兴趣探索小岛'}</p><p className="my-1 text-sm">{goals[0]?.detail??'可以独处、交流或相约，任务里的探索清单始终可查看。'}</p>{goals[0]?.id.startsWith('book')&&<button className={btn} disabled={blocked||location!=='guest_room'} onClick={()=>setBook(true)}>打开岛屿介绍册{location!=='guest_room'?'（先回客房）':''}</button>}<button className="ml-3 text-xs underline" onClick={()=>toggleGuide(true)}>收起引导</button></>:<button className="text-sm underline" onClick={()=>toggleGuide(false)}>展开探索引导</button>}</section>
    {!!notices.length&&!blocked&&!proposal&&!book&&!invite&&data?.profile&&<aside role="status" className="fixed bottom-5 right-4 z-[120] max-w-sm rounded-2xl border bg-white p-4 shadow-xl"><p className="font-bold">邀约有了回复</p>{notices.slice(-3).map(n=><p key={n.id} className="my-2 text-sm">{n.text}</p>)}<button className={btn} onClick={()=>{const read=JSON.parse(localStorage.getItem(`v5-notices:${sid}`)??'[]') as string[];localStorage.setItem(`v5-notices:${sid}`,JSON.stringify(Array.from(new Set([...read,...notices.map(n=>n.id)]))));setNotices([]);}}>知道了</button></aside>}
    {data&&!data.profile&&<SceneDialog title="选择本次假期的角色"><PlayerAppearance value={gender} onChange={setGender}/><button className={btn} disabled={!gender||busy} onClick={()=>void save()}>确认形象</button></SceneDialog>}
    {book&&<SceneDialog title="岛屿介绍册" onClose={()=>setBook(false)}><ObjectExplorer sessionId={sid} objectId="guidebook" revision={revision} onExecute={onExecute}/></SceneDialog>}
    {invite&&<SceneDialog title="邀请别人一起" onClose={()=>setInvite('')}><PhoneActivityComposer sessionId={sid} language="zh-CN" disabled={busy||blocked} initialRecipe={invite} expanded onChanged={()=>{callbacks.current.onChanged();setInvite('');}}/></SceneDialog>}
    {proposal&&<ProposalDialog key={proposal.source_action_id} sid={sid} proposal={proposal} name={data?.residents.find(r=>r.id===proposal.agent_id)?.name??'居民'} day={day} totalDays={totalDays} minute={minute} onChanged={()=>{void load();callbacks.current.onChanged();}}/>}
  </>;
}
function ProposalDialog({sid,proposal,name,day,totalDays,minute,onChanged}:{sid:number;proposal:Proposal;name:string;day:number;totalDays:number;minute:number;onChanged:()=>void}){
  const recommendedDay=Math.min(totalDays,Math.max(proposal.start_day,minute+30>1200 && day<totalDays?day+1:day));
  const recommendedMinute=recommendedDay>day?Math.max(540,Math.min(1200,proposal.start_minute)):Math.min(1200,Math.max(minute+30,proposal.start_minute));
  const [startDay,setStartDay]=useState(recommendedDay),[startMinute,setStartMinute]=useState(recommendedMinute),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [timeValid,setTimeValid]=useState(false);
  const pending=useRef<Record<string,unknown>|null>(null);
  async function act(operation:string){if(busy)return;setBusy(true);setError('');pending.current??={operation,source_action_id:proposal.source_action_id,start_day:startDay,start_minute:startMinute,idempotency_key:crypto.randomUUID()};try{await postV5(sid,'confirm',pending.current);pending.current=null;onChanged();}catch(e){setError(e instanceof Error?e.message:'安排未确认，请调整时间。');pending.current=null;}finally{setBusy(false);}}
  return <SceneDialog title={`${name}提出了一份安排`} onClose={()=>void act('dismiss')}><p className="leading-7">{proposal.reply}</p><p className="mt-3 text-sm">确认后会同步到手机邀约和任务安排。可以调整时间或继续商量。</p><div className="my-4"><InvitationTimePicker sid={sid} recipe={proposal.recipe_id} agents={[proposal.agent_id]} minDay={day} totalDays={totalDays} day={startDay} minute={startMinute} disabled={busy} onChange={(d,m)=>{setStartDay(d);setStartMinute(m);}} onValid={setTimeValid}/></div>{error&&<p role="alert" className="my-3 text-rose-700">{error}</p>}<div className="flex gap-3"><button className={btn} disabled={busy||!timeValid||startMinute<0} onClick={()=>void act('confirm')}>确认安排</button><button className={btn} disabled={busy} onClick={()=>void act('dismiss')}>继续商量</button></div></SceneDialog>;
}
