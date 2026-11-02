"use client";
import {useEffect, useState} from "react";
import {getPlayerRecords} from "@/lib/api";
import type {Language} from "@/lib/i18n";

export function PlayerRecords({sessionId, language}: {sessionId: number; language: Language}) {
  const [records, setRecords] = useState<Awaited<ReturnType<typeof getPlayerRecords>>["records"]>([]);
  const [history, setHistory] = useState<Awaited<ReturnType<typeof getPlayerRecords>>["history"]>([]);
  const [failed, setFailed] = useState(false);
  const [works,setWorks]=useState<NonNullable<Awaited<ReturnType<typeof getPlayerRecords>>['works']>>([]);
  useEffect(() => {
    let live = true;
    void getPlayerRecords(sessionId).then(data => {if (live) {setRecords(data.records); setHistory(data.history ?? []);setWorks(data.works??[]);}}).catch(() => {if (live) setFailed(true);});
    return () => {live = false;};
  }, [sessionId]);
  return <section className="mb-6 rounded-xl border bg-white p-4" aria-label={language === "zh-CN" ? "我的度假文字" : "My travel notes"}>
    <h3 className="font-bold">{language === "zh-CN" ? "登岛以来的足迹" : "My island journey"}</h3>
    <ol className="my-4 space-y-3">{history.map(item => <li key={item.id} className="border-l-2 border-teal-300 pl-3"><p className="text-xs text-stone-500">10月{item.world_day}日 {String(Math.floor(item.time_minutes / 60)).padStart(2,"0")}:{String(item.time_minutes % 60).padStart(2,"0")}</p><p className="mt-1 text-sm">{item.text}</p></li>)}</ol>
    {works.map((w,i)=><article key={i} className="my-3 rounded-xl border bg-amber-50 p-4"><h4 className="font-bold">10月{w.day}日 · {w.title}</h4>{w.text&&<p className="whitespace-pre-wrap">{w.text}</p>}{w.strokes&&<svg viewBox="0 0 100 100" aria-label={w.title} className="h-56 w-full">{w.strokes.map((s,j)=><polyline key={j} points={s.map(p=>p.join(',')).join(' ')} stroke="#355f59" strokeWidth="1" fill="none"/>)}</svg>}</article>)}
    {!records.length&&!works.length ? <p className="mt-2 text-sm text-stone-600">{failed ? (language === "zh-CN" ? "暂未加载成功，重新打开菜单可重试。" : "Could not load. Reopen the menu to retry.") : (language === "zh-CN" ? "还没有保存作品或文字。完成制作、速写或写张明信片后，可以在这里回看。" : "No notes saved yet.")}</p> : null}
    {records.map(r => <article key={r.id} className="mt-3 border-t pt-3"><p className="text-xs text-stone-500">{language === "zh-CN" ? `第 ${r.world_day} 天 · ${r.visibility === "private" ? "私人" : "已公开"} · 我的自述` : `Day ${r.world_day} · ${r.visibility}`}</p><p className="mt-1 whitespace-pre-wrap break-words text-sm">{r.body}</p></article>)}
  </section>;
}
