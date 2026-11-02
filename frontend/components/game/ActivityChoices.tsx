"use client";

import { useEffect, useState } from "react";
import { getPlayerActivities, invitePlayerActivity, type PlayerActivity, type WorldResident } from "@/lib/api";
import type { Language } from "@/lib/i18n";

export function ActivityChoices({sessionId, objectId, locationId, day, minute, residents, language, disabled, onChanged}: {
  sessionId: number; objectId: string; locationId: string; day: number; minute: number; residents: WorldResident[];
  language: Language; disabled: boolean; onChanged: () => void;
}) {
  const [activities, setActivities] = useState<PlayerActivity[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [partner, setPartner] = useState<number | undefined>();
  useEffect(() => {
    let live = true;
    void getPlayerActivities(sessionId).then(result => {if (live) setActivities(result.activities);}).catch(() => {if (live) setActivities([]);});
    return () => {live = false;};
  }, [sessionId, locationId]);
  const options = activities.filter(a => a.object_ids.includes(objectId));
  if (!options.length) return null;
  const nearby = residents.filter(r => r.current_location_id === locationId);
  async function invite(activity: PlayerActivity) {
    if (disabled || busy) return;
    setBusy(true);
    try {
      await invitePlayerActivity(sessionId, activity, day, minute + (activity.needs_partner ? 15 : 0), language, partner);
      setMessage(language === "zh-CN" ? (activity.needs_partner ? "邀请已发出。对方同意并实际到场后，在“当前活动”中开始。" : "已准备好，可以在“当前活动”中开始。") : "Activity proposed. Start from Current activities when accepted and everyone is present.");
      onChanged();
    } catch {
      setMessage(language === "zh-CN" ? "当前时间、伙伴或物品不可用，邀请未确认。请查看已有安排或稍后重试。" : "The time, partner or object is unavailable. Check existing plans and retry later.");
    } finally {setBusy(false);}
  }
  return <section className="space-y-2" aria-label={language === "zh-CN" ? "这里的活动" : "Activities here"}>
    {options.some(a => a.needs_partner && !a.required_resident_ids.length) ? <label className="block text-sm">{language === "zh-CN" ? "选择要邀请的在场居民" : "Choose someone nearby"}<select className="focus-ring mt-1 w-full rounded border p-2" value={partner ?? ""} onChange={e => setPartner(e.target.value ? Number(e.target.value) : undefined)}><option value="">{language === "zh-CN" ? "请选择" : "Select"}</option>{nearby.map(r => <option key={r.agent_id} value={r.agent_id}>{r.name}</option>)}</select></label> : null}
    {options.map(a => <button key={a.recipe_id} data-testid={`activity-invite-${a.recipe_id}`} className="focus-ring w-full rounded-lg border border-amber-300 bg-amber-50 p-3 text-left text-xs font-bold disabled:opacity-50" disabled={disabled || busy || (a.needs_partner && !a.required_resident_ids.length && !partner)} onClick={() => void invite(a)}>{a.label[language] ?? a.label.en} · {a.duration_minutes}{language === "zh-CN" ? ` 分钟${a.needs_partner ? "（邀请，15 分钟后开始）" : ""}` : " min"}</button>)}
    {message ? <p role="status" className="text-xs leading-5">{message}</p> : null}
  </section>;
}
