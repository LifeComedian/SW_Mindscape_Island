"use client";

import type { WorldInteractionPrompt, WorldResident } from "@/lib/api";
import type { Language } from "@/lib/i18n";
import { Portrait } from "./DialogueOverlay";
import { GameOverlayFrame } from "./GameOverlayFrame";

export function InteractionPromptOverlay({ prompt, resident, portraitUrl, language, busy, onRespond }: { prompt: WorldInteractionPrompt; resident: WorldResident | null; portraitUrl?: string; language: Language; busy: boolean; onRespond: (response: "accept" | "later" | "decline") => void }) {
  const isChinese = language === "zh-CN";
  const allowed = new Set(prompt.allowed_responses);
  const name = resident?.name ?? `${isChinese ? "居民" : "Resident"} ${prompt.initiator_agent_id}`;
  return (
    <GameOverlayFrame label={isChinese ? `${name}发起交流` : `${name} started a conversation`} escapeHint={isChinese ? "请选择交谈、稍后或拒绝；Escape 不会代替你的选择。" : "Choose Talk, Later, or Decline; Escape does not choose for you."}>
      <section data-testid="interaction-prompt" className="p-5 sm:p-7">
        <div className="flex items-start gap-4">
          <Portrait name={name} url={portraitUrl} testId="prompt-portrait" />
          <div className="min-w-0">
            <p className="text-xs font-black uppercase tracking-[0.16em] text-amber-800">{isChinese ? "居民想和你聊聊" : "A resident wants to talk"}</p>
            <h2 className="mt-1 text-xl font-black text-stone-950">{name}</h2>
            <p className="mt-3 text-base leading-7 text-stone-700">{prompt.display_opening_text}</p>
            <p className="mt-2 text-xs text-stone-500">{isChinese ? `第 ${prompt.expiry_day} 天 ${formatMinutes(prompt.expiry_time_minutes)} 前有效` : `Available until day ${prompt.expiry_day} at ${formatMinutes(prompt.expiry_time_minutes)}`}</p>
          </div>
        </div>
        <div className="mt-6 grid gap-2 sm:grid-cols-3">
          {allowed.has("accept") ? <button data-overlay-primary data-testid="interaction-prompt-accept" type="button" onClick={() => onRespond("accept")} disabled={busy} className="focus-ring min-h-12 rounded-xl bg-teal-800 px-4 text-sm font-black text-white hover:bg-teal-900 disabled:opacity-50">{isChinese ? "交谈" : "Talk"}</button> : null}
          {allowed.has("later") ? <button data-testid="interaction-prompt-later" type="button" onClick={() => onRespond("later")} disabled={busy} className="focus-ring min-h-12 rounded-xl border border-amber-300 bg-amber-50 px-4 text-sm font-black text-amber-950 hover:bg-amber-100 disabled:opacity-50">{isChinese ? "稍后" : "Later"}</button> : null}
          {allowed.has("decline") ? <button data-testid="interaction-prompt-decline" type="button" onClick={() => onRespond("decline")} disabled={busy} className="focus-ring min-h-12 rounded-xl border border-stone-300 bg-white px-4 text-sm font-black text-stone-700 hover:bg-stone-100 disabled:opacity-50">{isChinese ? "拒绝" : "Decline"}</button> : null}
        </div>
      </section>
    </GameOverlayFrame>
  );
}

function formatMinutes(value: number) {
  const hours = Math.floor(value / 60).toString().padStart(2, "0");
  const minutes = (value % 60).toString().padStart(2, "0");
  return `${hours}:${minutes}`;
}
