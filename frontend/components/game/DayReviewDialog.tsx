"use client";
import {useEffect, useRef} from "react";
import type {DayReview} from "@/lib/api";
import type {Language} from "@/lib/i18n";

export function DayReviewDialog({review, language, busy, onConfirm, onClose}: {review: DayReview; language: Language; busy: boolean; onConfirm: () => void; onClose: () => void}) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {close.current?.focus();}, []);
  const zh = language === "zh-CN";
  return <div className="fixed inset-0 z-[80] grid place-items-center bg-stone-950/45 p-4" onKeyDown={e => {if (e.key === "Escape" && !busy) onClose();}}>
    <section role="dialog" aria-modal="true" aria-labelledby="day-review-title" data-testid="day-review-dialog" className="max-h-[85vh] w-full max-w-xl overflow-auto rounded-2xl bg-white p-6 text-stone-900 shadow-xl">
      <h2 id="day-review-title" className="text-xl font-bold">{zh ? `第 ${review.day} 天 · 今日回顾` : `Day ${review.day} · Review`}</h2>
      <p className="my-3 text-sm">{zh ? "这里可以回看今天做过的事。你的私人感想留在度假册里。" : "These are recorded actions. Your personal reflections stay in your journal."}</p>
      {review.events.length ? <ol className="space-y-2 text-sm">{review.events.map(e => <li key={e.event_id}>{String(Math.floor(e.minute / 60)).padStart(2, "0")}:{String(e.minute % 60).padStart(2, "0")} · {e.label}</li>)}</ol> : <p>{review.empty_message}</p>}
      {review.pending_arrangements.length ? <div className="my-4 rounded border border-amber-400 bg-amber-50 p-3"><p className="font-bold">{zh ? "休息会退出以下今天的安排：" : "Resting leaves these arrangements:"}</p><ul>{review.pending_arrangements.map(p => <li key={p.plan_id}>{p.label}</li>)}</ul><p className="mt-2 text-sm">{zh ? "已经完成的部分会保留，其余安排到此结束。" : "Completed parts remain recorded; unfinished parts stay unfinished."}</p></div> : null}
      <div className="mt-5 flex gap-3"><button ref={close} type="button" disabled={busy} onClick={onClose} className="focus-ring rounded border p-3">{zh ? "再逛一会儿" : "Keep exploring"}</button><button type="button" data-testid="day-review-confirm" disabled={busy} onClick={onConfirm} className="focus-ring rounded bg-teal-700 p-3 text-white disabled:opacity-50">{zh ? (review.pending_arrangements.length ? "确认退出安排并休息" : "回客房休息") : "Confirm and rest"}</button></div>
    </section>
  </div>;
}
