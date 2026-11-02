"use client";
import {useCallback, useEffect, useRef, useState} from "react";
import {HolidayIllustration} from "./HolidayIllustration";
import {activityArt} from "@/lib/holiday-art";
import {Court,PlayingCard} from "./PlayPieces";
import {ObjectExplorer} from "./ObjectExplorer";
import {UnoTable} from "./UnoTable";
import {TimedVolley} from "./TimedVolley";
import {ActivityConversation} from "./ActivityConversation";
import {SceneDialog} from "./SceneDialog";
import {ApiError, getStageCards, changePlayerPlan, getActivityExperience, changeActivityExperience, getIslandGuides, type StageCard, type ActivityExperience, type IslandGuide} from "@/lib/api";

const button = "focus-ring min-h-11 rounded-xl border border-teal-200 bg-white px-4 py-3 text-left text-sm font-semibold hover:bg-teal-50 disabled:opacity-40";
type ActivityRequest=Parameters<typeof changeActivityExperience>[2];
type PendingActivity={runtimeId:number;request:ActivityRequest};
type Props = {sessionId: number; revision: number; open: boolean; onClose: () => void; onCount: (n: number) => void; onActive: (v: boolean) => void; onChanged: () => void};
export function HolidayActivities({sessionId, revision, open, onClose, onCount, onActive, onChanged}: Props) {
  const [cards, setCards] = useState<StageCard[]>([]);
  const [guides, setGuides] = useState<IslandGuide[]>([]);
  const [activity, setActivity] = useState<ActivityExperience | null>(null);
  const [ready, setReady] = useState<StageCard | null>(null);
  const [busyKind,setBusyKind]=useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retryRequest,setRetryRequest]=useState<PendingActivity|null>(null);
  const [message, setMessage] = useState("");
  const [speaker, setSpeaker] = useState(0);
  const [gamePartners,setGamePartners] = useState<number[]>([]);
  const [seen, setSeen] = useState<string[]>([]);
  const [mobileTab,setMobileTab]=useState<"operation"|"dialogue">("operation");
  const dismissed = useRef(new Set<number>());
  const callbacks = useRef({onChanged,onActive,onClose,onCount});
  useEffect(() => {callbacks.current = {onChanged,onActive,onClose,onCount};}, [onChanged,onActive,onClose,onCount]);
  const executing=useRef(false);
  const generation=useRef(0);
  const pending = useRef<PendingActivity|null>(null);
  const pendingKey=`activity-pending:${sessionId}`;
  useEffect(()=>{const timer=setTimeout(()=>{
    try{const saved=JSON.parse(sessionStorage.getItem(pendingKey)??'null');
      if(saved&&Number.isInteger(saved.runtimeId)&&typeof saved.request?.idempotency_key==='string'&&typeof saved.request?.operation==='string'){
        pending.current=saved;setRetryRequest(saved);setMessage(saved.request.message??'');setError('发现上次尚未确认的操作，请重试以核对保存结果。');
      }
    }catch{setError('无法读取上次操作的恢复记录。');}
  },0);return()=>clearTimeout(timer);},[pendingKey]);
  const load = useCallback(async () => {
    const ticket=++generation.current;
    const [stages, current, goals] = await Promise.all([getStageCards(sessionId),getActivityExperience(sessionId),getIslandGuides(sessionId)]);
    if(ticket!==generation.current)return;
    setCards(stages.cards); setActivity(current.activity); setGuides(goals.exploration ?? goals.guides);
    setReady(current.activity ? null : stages.cards.find(c => (c.ready_to_begin || c.status === "active" && c.is_present) && c.viewer_response === "accepted" && !dismissed.current.has(c.runtime_id)) ?? null);
  }, [sessionId]);
  useEffect(() => {const t = setTimeout(() => {void load().catch(() => setError("活动同步失败，请重试。")); try {setSeen(JSON.parse(sessionStorage.getItem(`v3-tasks:${sessionId}`) ?? "[]"));} catch {}}, 0); return () => clearTimeout(t);}, [load, revision, sessionId]);
  useEffect(() => {callbacks.current.onActive(Boolean(activity || ready || retryRequest));}, [activity,ready,retryRequest]);
  const visible = cards.filter(c => c.viewer_response === "accepted" && ["waiting","active"].includes(c.status));
  const signatures = [...guides.filter(g => g.progress < g.total).map(g => g.id), ...visible.map(c => `plan:${c.commitment_id}`)].join("|");
  useEffect(() => {
    const keys = signatures.split("|").filter(Boolean);
    callbacks.current.onCount(open ? 0 : keys.filter(k => !seen.includes(k)).length);
    if (open) {const next = Array.from(new Set([...seen,...keys])); sessionStorage.setItem(`v3-tasks:${sessionId}`, JSON.stringify(next)); const t=setTimeout(()=>setSeen(next),0); if (keys.every(k=>seen.includes(k))) clearTimeout(t); return ()=>clearTimeout(t);}
  }, [signatures,seen,open,sessionId]);
  async function command(operation: string, extra: Partial<ActivityRequest> = {}, recovering=false) {
    const rid = recovering?pending.current?.runtimeId:activity?.runtime_id ?? ready?.runtime_id;
    if (!rid || executing.current) return false;
    if(pending.current&&!recovering){setError("上一次请求的结果还未确认，请先重试上次操作，再进行其他动作。");return false;}
    const envelope=pending.current??{runtimeId:rid,request:{...extra,operation,idempotency_key:crypto.randomUUID(),expected_revision:activity?.revision}};
    try{sessionStorage.setItem(pendingKey,JSON.stringify(envelope));}catch{setError('浏览器暂时无法保存恢复记录，这次操作尚未发送。请恢复存储空间后重试。');return false;}
    pending.current=envelope;
    executing.current=true; generation.current++;
    setBusy(true); setBusyKind(operation); setError("");
    try {
      const next = await changeActivityExperience(sessionId,envelope.runtimeId,envelope.request);
      const sent=envelope.request; pending.current = null; try{sessionStorage.removeItem(pendingKey);}catch{} setRetryRequest(null); setReady(null); callbacks.current.onClose(); if(operation==="chat")setMessage(current=>current===sent.message?"":current);
      setActivity(next.status === "active" ? next : null); callbacks.current.onChanged(); await load().catch(()=>{}); return true;
    } catch (e) {
      if(e instanceof ApiError&&e.status<500&&e.status!==408&&(e.status!==429||e.code==='activity_limit')&&e.code!=='activity_busy'){pending.current=null;try{sessionStorage.removeItem(pendingKey);}catch{}}
      setRetryRequest(pending.current);
      const reasons:Record<string,string>={stale_revision:'活动进度已更新，已同步最新状态。你的操作还未提交，请再试一次。',activity_busy:'对方正在回复，请稍等片刻再操作。',focus_changed:'这次活动已结束或切换，请回到当前活动。',participants_missing:'参与者尚未到齐，请检查现场人员。',idempotency_conflict:'这次操作的记录已变化，请重新选择。',activity_limit:'这次活动的交谈已告一段落，可以继续操作或结束活动。'};
      setError(e instanceof ApiError?(reasons[e.code??'']??(/[\u4e00-\u9fff]/.test(e.message)?e.message:e.status>=500?'服务器暂时未完成处理，操作内容已保留，请重试。':'暂时无法完成这次操作，已同步活动状态，请重试。')):'连接中断，操作内容已保留，请重试刚才的操作。');
      await load().catch(()=>{});return false;
    } finally {executing.current=false;setBusy(false);}
  }
  async function plan(card: StageCard, operation: "arrive"|"start"|"withdraw"|"cancel") {
    setBusy(true); setError("");
    try {await changePlayerPlan(sessionId,card.commitment_id,card.plan_revision!,operation); await load(); callbacks.current.onChanged();}
    catch {setError("还未满足开始条件，请检查时间、地点和到场人数。"); await load();}
    finally {setBusy(false);}
  }
  const notices = error ? <p role="alert" className="my-3 rounded-xl bg-amber-50 p-3 text-amber-950">{error}{retryRequest&&<button className={`${button} ml-3`} disabled={busy} onClick={()=>void command(retryRequest.request.operation,{},true)}>重试上次操作</button>}</p> : null;
  if (activity) return <SceneDialog title={activity.title} wide status="活动进行中 · 岛屿时间暂停">
    <div data-testid="activity-scene" className="grid items-start gap-5">
<div className="flex gap-2 lg:hidden"><button className={button} aria-pressed={mobileTab==="operation"} onClick={()=>setMobileTab("operation")}>操作场景</button><button className={button} aria-pressed={mobileTab==="dialogue"} onClick={()=>setMobileTab("dialogue")}>对话 · {activity.history.length} 条</button></div><div className="grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">{notices}
      {activity.world_version==='chaoxi-holiday-v6'&&['volley_pass','volley_match'].includes(activity.kind)?<div className={`min-w-0 lg:col-start-1 ${mobileTab==='dialogue'?'hidden lg:block':''}`}><TimedVolley sid={sessionId} runtimeId={activity.runtime_id} progress={{...activity.game}} disabled={busy} partners={activity.people.map(p=>p.name)} onHit={payload=>command('game',{choice_id:'volley-position',inputs:{payload:JSON.stringify(payload)}})}/></div>:activity.world_version==='chaoxi-holiday-v6'&&activity.kind==='table_game'?<div className={`min-w-0 lg:col-start-1 ${mobileTab==='dialogue'?'hidden lg:block':''}`}><UnoTable activity={activity} busy={busy} onCommand={(choice,partners)=>void command('game',{choice_id:choice,...(partners?{participant_ids:partners}:{})})}/></div>:['chaoxi-holiday-v4','chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(activity.world_version ?? "") ? <div className={`min-w-0 lg:col-start-1 lg:row-span-1 ${mobileTab==="dialogue"?"hidden lg:block":""}`}><ObjectExplorer inActivity guidance="activity_default" runtimeId={activity.runtime_id} key={activity.runtime_id} initialActionId={({flower_arranging:'v4_flowers__make',woodcraft:'v4_wood_work__make',rope_practice:'v4_rope__make',beach_walk:'v4_beach__walk',beach_search:'v4_beach__shell'} as Record<string,string>)[activity.kind]} sessionId={sessionId} revision={activity.revision} disabled={busy} onExecute={(choice_id,inputs)=>command('action',{choice_id,inputs})} /></div> : <details><summary className="focus-ring cursor-pointer py-3 font-semibold">看看现场还能做什么</summary><div className="grid gap-2 sm:grid-cols-2">{activity.catalogue.filter(c=>!c.id.startsWith("gathering_")).map(c=><button key={c.id} className={button} disabled={busy} onClick={()=>void command("action",{choice_id:c.id})}>{c.label}</button>)}</div></details>}
      <div className={`min-w-0 lg:col-start-2 lg:row-start-1 lg:row-span-1 ${mobileTab==="operation"?"hidden lg:block":""}`}><aside className="grid min-w-0 items-center gap-4 ">{activityArt(activity)?<><div className="rounded-xl [&_img]:max-h-56"><HolidayIllustration id={activityArt(activity)!} /></div><div className="rounded-xl border border-stone-200 bg-white px-4 py-3"><p className="text-xs text-stone-500">{activity.location} · 现场伙伴</p><p className="mt-1 text-sm font-semibold text-teal-900">{activity.people.map(p=>p.name).join(" · ")}</p></div></>:<div data-art-slot={`activity:${activity.kind}`} className="rounded-2xl bg-gradient-to-br from-teal-950 via-teal-800 to-amber-700 px-6 py-10 text-white"><p className="text-sm opacity-80">{activity.location}</p><p className="mt-2 text-3xl font-bold">{activity.title}</p><p className="mt-3 text-sm">{activity.people.map(p=>p.name).join(" · ")}</p></div>}
      </aside><ActivityConversation sessionId={sessionId} activity={activity} busy={busy&&["chat","suggest","demonstrate","speech"].includes(busyKind)} speaker={speaker} onSpeaker={setSpeaker} message={message} onMessage={setMessage} onSend={()=>void command("chat",{message,speaker_id:speaker||activity.people[0]?.id})} onSuggest={()=>void command("suggest",{speaker_id:speaker||activity.people[0]?.id})}/></div>
      {!activity.speech_done && ["welcome","bonfire"].includes(activity.kind) ? <button className={button} disabled={busy} onClick={()=>void command("speech")}>{activity.kind === "welcome" ? "准备好了，听听欢迎致辞" : "围坐好了，听听今晚的开场"}</button> : null}
      {activity.catalogue.some(c=>c.id.startsWith("gathering_")) && <section><h2 className="mb-2 font-bold">今晚的小安排</h2><div className="grid gap-2 sm:grid-cols-2">{activity.catalogue.filter(c=>c.id.startsWith("gathering_")).map(c=><button key={c.id} className={button} disabled={busy} onClick={()=>void command("action",{choice_id:c.id})}>{c.label}</button>)}</div></section>}

      {activity.world_version!=='chaoxi-holiday-v6'&&['volley_pass','volley_match'].includes(activity.kind)&&<section className="rounded-xl border bg-teal-50 p-4"><h2 className="font-bold">一起打排球</h2>{!activity.game||activity.game.finished?<button className={button} disabled={busy} onClick={()=>void command('game',{choice_id:'start'})}>开始一轮配合</button>:<><p>第{activity.game.turn+1}球 · 目标：{['左','中','右'][activity.game.target??1]}</p><Court target={activity.game.target??1} disabled={busy} onHit={zone=>void command('game',{choice_id:String(zone)})}/></>}{activity.game&&<p>成功配合：{activity.game.score} / {activity.game.turn}</p>}</section>}
      {activity.world_version==='chaoxi-holiday-v6'&&activity.kind==='welcome'&&<UnoTable activity={activity} busy={busy} onCommand={(choice,partners)=>void command('game',{choice_id:choice,...(partners?{participant_ids:partners}:{})})}/>}
      {activity.world_version!=='chaoxi-holiday-v6'&&(activity.catalogue.some(c=>c.id==='table_catalog') || activity.kind==='table_game' || ['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(activity.world_version ?? '') && activity.kind==='welcome') ? <section className="rounded-xl border bg-teal-50 p-4"><h2 className="mb-2 font-bold">一起玩颜色接龙（2–4人）</h2>{['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(activity.world_version ?? '') && activity.kind==='welcome' && (!activity.game || activity.game.finished) && <fieldset className="mb-3 flex flex-wrap gap-3"><legend>选择一至三位到场的伙伴</legend>{activity.people.map(p=><label key={p.id}><input type="checkbox" checked={gamePartners.includes(p.id)} disabled={busy || !gamePartners.includes(p.id) && gamePartners.length>=3} onChange={e=>setGamePartners(ids=>e.target.checked?[...ids,p.id]:ids.filter(i=>i!==p.id))}/>{p.name}</label>)}</fieldset>}{!activity.game || activity.game.finished ? <button className={button} disabled={busy} onClick={()=>void command("game",{choice_id:"start",...(activity.kind==="welcome"?{participant_ids:gamePartners.length?gamePartners:activity.people.slice(0,3).map(p=>p.id)}:{})})}>开一局</button> : <><div className="mb-4 flex items-center justify-center gap-4 rounded-2xl border-8 border-[#ae8a59] bg-[#788c76] p-5 text-white"><span>桌面 · 第 {activity.game.turn+1} 轮</span><PlayingCard card={activity.game.top} disabled={true} onPlay={()=>{}}/></div><div aria-label="你的手牌" className="flex flex-wrap gap-2 p-3">{activity.game.hand.map((c,i)=><PlayingCard key={`${i}-${c}`} card={c} disabled={busy || (c[0]!==activity.game!.top[0] && c[1]!==activity.game!.top[1])} onPlay={()=>void command("game",{choice_id:c})}/>)}<button className={button} disabled={busy} onClick={()=>void command("game",{choice_id:"draw"})}>摸一张</button></div></>}</section> : null}

      <button className="focus-ring w-full rounded-xl bg-teal-900 p-4 font-semibold text-white disabled:opacity-50 lg:col-span-2" disabled={busy} onClick={()=>void command("end")}>结束这次活动，回到小岛</button>
      </div>
    </div>
  </SceneDialog>;
  if (ready) return <SceneDialog title="大家到齐了" onClose={()=>{dismissed.current.add(ready.runtime_id);setReady(null);}}><p className="text-lg font-bold">{ready.activity_label?.["zh-CN"]}</p><p className="my-4 leading-7">现在进入活动吗？活动期间可以交谈、做些事情，结束后再继续逛小岛。</p>{notices}<button className={button} disabled={busy} onClick={()=>void command("begin")}>进入活动</button></SceneDialog>;
  if (!open && retryRequest) return <SceneDialog title="恢复上次操作">{notices}</SceneDialog>;
  if (!open) return null;
  return <SceneDialog title="任务与安排" onClose={onClose}>{notices}<div className="space-y-4">
    {guides.map(g=><article key={g.id} className="rounded-xl border bg-white p-4"><div className="flex justify-between gap-3"><h2 className="font-bold">{g.title}</h2><span className="text-sm text-teal-800">{g.progress}/{g.total}</span></div><p className="mt-2 text-sm leading-6 text-stone-600">{g.detail}</p></article>)}
    <h2 className="pt-2 text-lg font-bold">已经约好的事</h2>{!visible.length && <p className="text-sm text-stone-600">还没有安排。看看手机里的邀约，或约大家做件事。</p>}
    {visible.map(c=><article key={c.runtime_id} className="space-y-3 rounded-xl border bg-white p-4"><h3 className="font-bold">{c.activity_label?.["zh-CN"]}</h3><p className="text-sm">10月{c.scheduled_day}日 · {String(Math.floor((c.scheduled_time_minutes??0)/60)).padStart(2,"0")}:{String((c.scheduled_time_minutes??0)%60).padStart(2,"0")} · {c.location_label?.["zh-CN"]}</p><div className="flex flex-wrap gap-2">{c.plan_controls?.filter(o=>["arrive","start","cancel","withdraw"].includes(o) && !(c.ready_to_begin && ["arrive","start"].includes(o))).map(o=><button key={o} className={button} disabled={busy} onClick={()=>void plan(c,o as "arrive"|"start"|"cancel"|"withdraw")}>{({arrive:"我到了", start:"大家到齐，准备开始",cancel:"取消安排",withdraw:"退出报名"} as Record<string,string>)[o]}</button>)}{(c.ready_to_begin || c.status==='active' && c.is_present) && <button className={button} disabled={busy} onClick={()=>setReady(c)}>进入活动</button>}</div></article>)}
  </div></SceneDialog>;
}
