"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
import {getV5,postV5,type V5Snapshot} from '@/lib/holiday-v5';
import {HolidayIllustration} from '../game/HolidayIllustration';
import {SocialAvatar,useSocialIdentity} from './SocialIdentity';
import {PhoneActivityComposer} from './PhoneActivityComposer';
const button='focus-ring rounded-xl border px-4 py-3 disabled:opacity-50';
export function PrivateMessages({sessionId,disabled,onChanged}:{sessionId:number;disabled:boolean;onChanged:()=>void}){
  const [data,setData]=useState<V5Snapshot|null>(null),[agent,setAgent]=useState(1),[text,setText]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const identity=useSocialIdentity();
  const sending=useRef(false);
  const pending=useRef<{agent_id:number;message:string;idempotency_key:string}|null>(null);
  const log=useRef<HTMLDivElement>(null);
  const load=useCallback(()=>getV5(sessionId).then(setData),[sessionId]);
  useEffect(()=>{const initial=setTimeout(()=>void load().catch(()=>setError('私信暂未同步，请重试。')),0);const timer=setInterval(()=>void load().catch(()=>{}),5000);return()=>{clearTimeout(initial);clearInterval(timer);};},[load]);
  useEffect(()=>{log.current?.scrollTo({top:log.current.scrollHeight});},[data?.messages.length,agent]);
  async function send(){if(!text.trim()||sending.current||disabled||!data||data.closed)return;sending.current=true;setBusy(true);setError('');pending.current??={agent_id:agent,message:text.trim(),idempotency_key:crypto.randomUUID()};try{await postV5(sessionId,'messages',pending.current);pending.current=null;setText('');await load();window.dispatchEvent(new Event('v5-guides-changed'));onChanged();}catch(e){setError(e instanceof Error?e.message:'未取得回复，保留消息后可以重试。');}finally{sending.current=false;setBusy(false);}}
  const name=data?.residents.find(r=>r.id===agent)?.name??'居民';
  return <section className="space-y-4 py-4" data-testid="private-messages">
    <label className="block font-bold">和谁聊聊<select aria-label="私信居民" className="ml-3 rounded border p-2" disabled={busy||!data} value={agent} onChange={e=>{pending.current=null;setAgent(Number(e.target.value));setText('');setError('');}}>{data?.residents.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
    <p className="text-sm text-stone-500">可以异地聊聊。对方忙碌时也能收到私信，一起活动的时间可以再商量。</p>
    <div className="grid items-start gap-4 md:grid-cols-[180px_minmax(0,1fr)]">
      <aside data-testid="private-resident-illustration" className="flex items-center gap-3 md:block"><div className="w-20 shrink-0 md:w-full"><HolidayIllustration id={`resident.${agent}.closeup`}/></div><p className="font-bold md:mt-2 md:text-center">{name}</p></aside>
      <div className="min-w-0 space-y-3">
        <div ref={log} role="log" aria-label={`和${name}的私信`} className="max-h-80 min-h-24 space-y-5 overflow-y-auto rounded-xl bg-stone-100 p-3">
          {!data&&<p role="status">正在打开私信…</p>}
          {data&&!data.messages.some(m=>m.agent_id===agent)&&<p className="text-sm text-stone-500">还没有聊过天，打个招呼吧。</p>}
          {data?.messages.filter(m=>m.agent_id===agent).map(m=><article key={m.id} className="space-y-3"><div className="flex items-start justify-end gap-2"><div className="rounded-xl bg-teal-100 p-3"><strong className="text-xs">{identity.name(0,'你')}</strong><p className="mt-1 whitespace-pre-wrap leading-7">{m.message}</p></div><SocialAvatar agentId={0} name={identity.name(0,'你')} size={32}/></div><div className="flex items-start gap-2"><SocialAvatar agentId={agent} name={name} size={32}/><div className="rounded-xl bg-white p-3"><strong className="text-xs">{name}</strong><p className="mt-1 whitespace-pre-wrap leading-7">{m.reply}</p></div></div></article>)}
          {busy&&<p role="status">{name}正在回复…</p>}
        </div>
        <textarea aria-label="私信内容" className="min-h-24 w-full rounded-xl border bg-white p-3" value={text} maxLength={1000} disabled={busy||disabled||!data||data.closed} onChange={e=>{setText(e.target.value);pending.current=null;}} placeholder="聊聊见闻，或问问愿不愿意一起做什么……"/>
        <button className={button} disabled={busy||disabled||!text.trim()||!data||data.closed} onClick={()=>void send()}>{busy?'正在回应…':'发送私信'}</button>
        {error&&<p role="alert" className="rounded-xl bg-amber-50 p-3">{error}<button className="ml-3 underline" onClick={()=>void load().then(()=>setError('')).catch(()=>setError('暂未同步，请稍后重试。'))}>重新同步</button></p>}
        {data?.closed&&<p>本次假期已经结束。</p>}
      </div>
    </div>
    <PhoneActivityComposer key={agent} sessionId={sessionId} language="zh-CN" disabled={disabled||busy||!data||!!data.closed} onChanged={onChanged} initialPartner={agent}/>
  </section>;
}
