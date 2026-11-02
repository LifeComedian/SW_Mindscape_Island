"use client";

import { X } from "lucide-react";

import type { WorldActor, WorldConversation } from "@/lib/api";
import type { Language } from "@/lib/i18n";

export function AccessibleWorldLog({
  open,
  language,
  conversations,
  actors,
  onClose,
}: {
  open: boolean;
  language: Language;
  conversations: WorldConversation[];
  actors: WorldActor[];
  onClose: () => void;
}) {
  if (!open) return null;
  const isChinese = language === "zh-CN";
  return (
    <aside
      data-testid="accessible-world-log"
      role="region"
      aria-label={isChinese ? "可访问世界记录" : "Accessible world log"}
      className="absolute inset-x-3 bottom-3 z-40 max-h-[72%] overflow-y-auto rounded-2xl border border-stone-300 bg-white/95 p-4 text-stone-900 shadow-2xl backdrop-blur sm:inset-x-auto sm:right-3 sm:w-[min(460px,calc(100%-1.5rem))]"
    >
      <div className="sticky top-0 flex items-center justify-between gap-3 bg-white/95 pb-3">
        <div>
          <h3 className="font-black">{isChinese ? "附近公开交谈记录" : "Nearby public conversation log"}</h3>
          <p className="mt-1 text-xs text-stone-500">{isChinese ? "只包含当前地点允许观察的公开记录。" : "Only public records observable at your current location."}</p>
        </div>
        <button type="button" onClick={onClose} className="focus-ring inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-stone-300 bg-white hover:bg-stone-50" aria-label={isChinese ? "关闭世界记录" : "Close world log"}>
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div data-testid="ambient-conversations" className="space-y-3">
        {conversations.length ? conversations.map((conversation) => (
          <article key={conversation.conversation_id} data-testid={`ambient-conversation-${conversation.conversation_id}`} data-conversation-status={conversation.status} className="rounded-xl border border-stone-200 bg-stone-50 p-3">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-teal-800">
              {conversation.status === "active" ? isChinese ? "交谈正在进行" : "Conversation in progress" : isChinese ? "交谈已自然结束" : "Conversation ended naturally"}
            </p>
            <div className="space-y-2">
              {(conversation.turns ?? []).map((turn, index) => {
                const speaker = actors.find((actor) => actor.agent_id === Number(turn.speaker_id));
                return (
                  <p key={`${turn.turn_id ?? index}`} data-testid="ambient-conversation-turn" className="rounded-lg bg-white px-3 py-2 text-sm leading-6 text-stone-700">
                    <span className="mr-2 font-bold text-stone-950">{turn.speaker_name ?? speaker?.name ?? (isChinese ? "岛民" : "Resident")}:</span>
                    {turn.content}
                  </p>
                );
              })}
            </div>
          </article>
        )) : <p className="rounded-lg bg-stone-50 px-3 py-4 text-sm text-stone-500">{isChinese ? "当前没有可观察的公开交谈。" : "No public conversation is observable here."}</p>}
      </div>
    </aside>
  );
}
