"use client";

import { Clock3, X } from "lucide-react";
import { useEffect, useRef } from "react";

import type { Language } from "@/lib/i18n";

const PRESETS = [5, 15, 30, 60] as const;

export function PassTimeDialog({
  language,
  minutes,
  currentTime,
  busy,
  onMinutesChange,
  onConfirm,
  onClose,
}: {
  language: Language;
  minutes: number;
  currentTime: string;
  busy: boolean;
  onMinutesChange: (minutes: number) => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const isChinese = language === "zh-CN";

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-stone-950/45 p-4 backdrop-blur-sm">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="pass-time-title"
        data-testid="pass-time-dialog"
        className="w-full max-w-md rounded-2xl border border-white/70 bg-white p-5 shadow-2xl"
      >
        <header className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-black uppercase tracking-wide text-teal-700">
              {isChinese ? `当前岛屿时间 ${currentTime}` : `Current island time ${currentTime}`}
            </p>
            <h2 id="pass-time-title" className="mt-1 text-xl font-black text-stone-950">
              {isChinese ? "消磨时间" : "Pass time"}
            </h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label={isChinese ? "关闭消磨时间选择" : "Close pass time selection"}
            onClick={onClose}
            disabled={busy}
            className="focus-ring grid h-11 w-11 place-items-center rounded-full border border-stone-300 text-stone-700 hover:bg-stone-100 disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <div className="mt-5 grid grid-cols-4 gap-2" aria-label={isChinese ? "常用等待时长" : "Common wait durations"}>
          {PRESETS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={minutes === value}
              onClick={() => onMinutesChange(value)}
              disabled={busy}
              className={`focus-ring min-h-11 rounded-lg border px-2 text-sm font-bold disabled:opacity-50 ${minutes === value ? "border-teal-700 bg-teal-50 text-teal-950" : "border-stone-300 text-stone-700 hover:bg-stone-50"}`}
            >
              {value} {isChinese ? "分钟" : "min"}
            </button>
          ))}
        </div>

        <label htmlFor="pass-time-minutes" className="mt-5 block text-sm font-bold text-stone-800">
          {isChinese ? `手动选择：${minutes} 分钟` : `Choose manually: ${minutes} minutes`}
        </label>
        <input
          id="pass-time-minutes"
          data-testid="pass-time-minutes"
          type="range"
          min={5}
          max={120}
          step={5}
          value={minutes}
          disabled={busy}
          onChange={(event) => onMinutesChange(Number(event.target.value))}
          className="focus-ring mt-3 w-full accent-teal-700"
        />
        <div className="mt-1 flex justify-between text-xs text-stone-500" aria-hidden="true">
          <span>5</span><span>120</span>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="focus-ring min-h-11 rounded-lg border border-stone-300 px-4 text-sm font-bold text-stone-700 hover:bg-stone-50 disabled:opacity-50">
            {isChinese ? "取消" : "Cancel"}
          </button>
          <button data-testid="pass-time-confirm" type="button" onClick={onConfirm} disabled={busy} className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-lg bg-teal-800 px-4 text-sm font-bold text-white hover:bg-teal-900 disabled:opacity-50">
            <Clock3 className="h-4 w-4" aria-hidden="true" />
            {isChinese ? `等待 ${minutes} 分钟` : `Wait ${minutes} minutes`}
          </button>
        </div>
      </section>
    </div>
  );
}
