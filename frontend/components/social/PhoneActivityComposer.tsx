"use client";
import {InvitationTimePicker} from "./InvitationTimePicker";
import {SocialAvatar} from "./SocialIdentity";
import {useEffect, useState} from "react";
import {getPlayerActivities, getSessionWorld, invitePlayerActivity, type PlayerActivity, type WorldSnapshot} from "@/lib/api";
import type {Language} from "@/lib/i18n";

export function PhoneActivityComposer({sessionId, language, disabled, onChanged, initialRecipe="", initialPartner, expanded=false}: {sessionId: number; language: Language; disabled: boolean; onChanged: () => void; initialRecipe?:string; initialPartner?:number; expanded?:boolean}) {
  const [activities, setActivities] = useState<PlayerActivity[]>([]);
  const [world, setWorld] = useState<WorldSnapshot | null>(null);
  const [selected, setSelected] = useState(initialRecipe);
  const [partner, setPartner] = useState(initialRecipe);
  const [partners,setPartners] = useState<number[]>(initialPartner?[initialPartner]:[]);
  const [invitationMessage,setInvitationMessage] = useState("");
  const [startDay,setStartDay]=useState(0),[startMinute,setStartMinute]=useState(-1),[timeValid,setTimeValid]=useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([getPlayerActivities(sessionId), getSessionWorld(sessionId, language)]).then(([catalog, snapshot]) => {
      if (active) {setActivities(catalog.activities.filter(a => a.needs_partner && (!initialPartner || (a.min_participants??2)<=2))); setWorld(snapshot);}
    }).catch(() => {if (active) setMessage("活动暂未加载，请重新打开手机重试。");});
    return () => {active = false;};
  }, [sessionId, language, initialPartner]);
  const groupEnabled = ["chaoxi-holiday-v3","chaoxi-holiday-v4","chaoxi-holiday-v5","chaoxi-holiday-v6"].includes(world?.world.world_version ?? "");
  const activity = activities.find(a => a.recipe_id === selected);
  const minimumPartners=Math.max(1,(activity?.min_participants??2)-1);
  const maximumPartners=Math.max(1,(activity?.max_participants??4)-1);
  async function invite() {
    if (!activity || busy || disabled) return;
    setBusy(true); setMessage("");
    try {

      await invitePlayerActivity(sessionId, activity, startDay||world!.world.current_day, startMinute, language, groupEnabled ? partners : partner ? Number(partner) : undefined, invitationMessage);
      setMessage("邀请已发送。对方回应后，可在这里查看状态；双方同意后会出现在任务中。"); onChanged();
    } catch {setMessage("邀请尚未发出：时间、伙伴或场地与已有安排冲突，或已临近休息时间。请调整后再试。");}
    finally {setBusy(false);}
  }
  return <details open={expanded || undefined} className="rounded-xl border border-teal-200 bg-white p-4"><summary className="focus-ring cursor-pointer font-bold">发起邀约</summary>
    <div className="mt-3 space-y-3">
      <label className="block text-sm">想一起做什么<select aria-label="邀约活动" value={selected} onChange={e => {setSelected(e.target.value);setPartners(initialPartner?[initialPartner]:[]);}} className="mt-1 w-full rounded border p-2"><option value="">选择活动</option>{activities.map(a => <option key={a.recipe_id} value={a.recipe_id}>{a.label[language] ?? a.label.en}</option>)}</select></label>
      {activity ? <p className="text-sm">地点：{world?.locations.find(l => l.location_id === activity.location_id)?.name ?? activity.location_id} · 约 {activity.duration_minutes} 分钟</p> : null}
      {activity?.required_resident_ids.length ? <p className="text-sm">邀请：{activity.required_resident_ids.map(id => world?.residents.find(r => r.agent_id === id)?.name ?? "岛上居民").join("、")}</p> : null}
      {activity && !activity.required_resident_ids.length && !groupEnabled ? <label className="block text-sm">邀请谁<select aria-label="邀约居民" value={partner} onChange={e => setPartner(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="">选择居民</option>{world?.residents.map(r => <option key={r.agent_id} value={r.agent_id}>{r.name}</option>)}</select></label> : null}
      {activity && groupEnabled ? <fieldset className="rounded-xl border p-3"><legend className="px-1 text-sm">邀请谁（{minimumPartners}—{maximumPartners} 位）</legend><div className="grid grid-cols-2 gap-3">{world?.residents.filter(r=>!initialPartner || r.agent_id===initialPartner).map(r=><label key={r.agent_id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={partners.includes(r.agent_id)} disabled={!partners.includes(r.agent_id) && partners.length>=maximumPartners} onChange={e=>setPartners(ids=>e.target.checked ? [...ids,r.agent_id] : ids.filter(id=>id!==r.agent_id))}/><SocialAvatar agentId={r.agent_id} name={r.name} size={28}/>{r.name}</label>)}</div></fieldset> : null}
      <label className="block text-sm">想怎么邀请大家<textarea value={invitationMessage} onChange={e=>setInvitationMessage(e.target.value)} maxLength={500} placeholder="想一起做什么？写一句自己的邀请……" className="mt-1 w-full rounded border p-2" /></label>
      {activity&&world&&<InvitationTimePicker sid={sessionId} recipe={activity.recipe_id} agents={groupEnabled?partners:partner?[Number(partner)]:activity.required_resident_ids} minDay={world.world.current_day} totalDays={world.world.total_days} day={startDay||world.world.current_day} minute={startMinute} disabled={busy||disabled} onChange={(d,m)=>{setStartDay(d);setStartMinute(m);}} onValid={setTimeValid}/>}
      <button type="button" onClick={() => void invite()} disabled={busy || disabled || !timeValid || !activity || (!activity.required_resident_ids.length && (groupEnabled ? partners.length<minimumPartners || partners.length>maximumPartners : !partner))} className="rounded-lg bg-teal-800 px-4 py-2 font-bold text-white disabled:opacity-50">{busy ? "正在发送…" : "发送邀请"}</button>
      {message ? <p role="status" className="text-sm leading-6">{message}</p> : null}
    </div>
  </details>;
}
