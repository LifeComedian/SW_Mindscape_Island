"use client";

import { History, LoaderCircle, Send, X } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";

import { resolveApiAssetUrl, type WorldConversationTurn, type WorldResident } from "@/lib/api";
import type { Language } from "@/lib/i18n";
import {HolidayIllustration} from "./HolidayIllustration";
import { GameOverlayFrame } from "./GameOverlayFrame";

export function DialogueOverlay({
  language,
  resident,
  turns,
  residentPortraitUrl,
  participantPortraitUrl,
  message,
  busy,
  canEnd,
  onMessageChange,
  onMessageFocus,
  onSubmit,
  onEnd,
}: {
  language: Language;
  resident: WorldResident;
  turns: WorldConversationTurn[];
  residentPortraitUrl?: string;
  participantPortraitUrl?: string;
  message: string;
  busy: boolean;
  canEnd: boolean;
  onMessageChange: (value: string) => void;
  onMessageFocus: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onEnd: () => void;
}) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const latest = turns.at(-1);
  const latestIsParticipant = latest?.speaker_type === "participant" || latest?.speaker_type === "user";
  const speakerName = latestIsParticipant ? (language === "zh-CN" ? "你" : "You") : resident.name;
  const speakerPortrait = latestIsParticipant ? participantPortraitUrl : residentPortraitUrl;
  const rows = Math.max(1, Math.min(3, message.split("\n").length + Math.floor(message.length / 72)));
  const isChinese = language === "zh-CN";

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <GameOverlayFrame label={isChinese ? `与${resident.name}交谈` : `Conversation with ${resident.name}`} position="bottom" escapeHint={isChinese ? "Escape 不会结束交流；请使用结束交流按钮。" : "Escape does not end the conversation; use End conversation."}>
      <section data-testid="dialogue-overlay" className="grid max-h-[76vh] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-2 sm:flex-nowrap sm:gap-3 border-b border-stone-200 px-4 py-3 sm:px-5">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <Portrait name={speakerName} url={speakerPortrait} testId="dialogue-speaker-portrait" />
            <div className="min-w-0">
              <p className="truncate font-black text-stone-950" aria-live="polite">{speakerName}</p>
              <p className="text-[11px] text-stone-500">{generationLabel(latest?.generation_mode ?? resident.generation_mode, language)}</p>
              <p data-testid="dialogue-time-paused" className="text-[11px] font-bold text-amber-800">
                {isChinese ? "对话中 · 岛屿时间已暂停" : "Conversation · Island time paused"}
              </p>
            </div>
          </div>
          <div className="flex w-full shrink-0 justify-end gap-2 sm:w-auto">
            <button data-testid="dialogue-history-button" type="button" onClick={() => setHistoryOpen((value) => !value)} aria-expanded={historyOpen} className="focus-ring inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 text-xs font-bold text-stone-800 hover:bg-stone-50">
              <History className="h-4 w-4" aria-hidden="true" />{isChinese ? "记录" : "History"}
            </button>
            <button data-overlay-primary data-testid="dialogue-end" type="button" onClick={onEnd} disabled={!canEnd || busy} className="focus-ring inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-red-200 bg-white px-3 text-xs font-bold text-red-800 hover:bg-red-50 disabled:opacity-50">
              <X className="h-4 w-4" aria-hidden="true" />{isChinese ? "结束交流" : "End conversation"}
            </button>
          </div>
        </header>

        <div className={`overflow-y-auto px-4 py-3 sm:px-5 ${!historyOpen && residentPortraitUrl?.includes("/holiday-art/") ? "sm:grid sm:grid-cols-[150px_minmax(0,1fr)] sm:items-center sm:gap-5" : ""}`}>
          {!historyOpen && residentPortraitUrl?.includes("/holiday-art/") ? <div data-testid="dialogue-resident-illustration" className="hidden sm:block"><HolidayIllustration id={`resident.${resident.agent_id}.closeup`} compact/></div> : null}
          {historyOpen ? (
            <div data-testid="dialogue-history" role="log" aria-live="polite" className="mx-auto max-w-3xl space-y-2">
              {turns.map((turn, index) => <HistoryTurn key={`${turn.turn_id ?? turn.created_at ?? index}`} turn={turn} resident={resident} language={language} participantPortraitUrl={participantPortraitUrl} residentPortraitUrl={residentPortraitUrl} />)}
            </div>
          ) : (
            <div data-testid="dialogue-current-line" aria-live="polite" className="mx-auto max-w-3xl rounded-2xl border border-stone-200 bg-white px-4 py-4 text-base leading-7 text-stone-800 shadow-sm sm:px-5 sm:text-lg">
              {latest?.content ?? (isChinese ? "你们的交流刚刚开始。" : "Your conversation has just begun.")}
            </div>
          )}
        </div>

        <form onSubmit={onSubmit} className="border-t border-stone-200 bg-white px-3 py-3 sm:px-5">
          <label htmlFor="dialogue-message" className="sr-only">{isChinese ? "输入要说的话" : "Say something to this resident"}</label>
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea
              id="dialogue-message"
              data-testid="dialogue-input"
              rows={rows}
              maxLength={1000}
              value={message}
              onFocus={onMessageFocus}
              onChange={(event) => onMessageChange(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={busy}
              placeholder={isChinese ? "输入内容；Enter 发送，Shift+Enter 换行" : "Type a message; Enter sends, Shift+Enter adds a line"}
              className="focus-ring min-h-11 flex-1 resize-none rounded-xl border border-stone-300 px-3 py-2.5 text-sm leading-5 disabled:bg-stone-100"
            />
            <button type="submit" aria-label={isChinese ? "发送" : "Send"} disabled={!message.trim() || busy} className="focus-ring inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-xl bg-teal-800 px-3 text-sm font-bold text-white hover:bg-teal-900 disabled:opacity-50 sm:min-w-28">
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
              <span className="hidden sm:inline">{busy ? isChinese ? "发送中" : "Sending" : isChinese ? "发送" : "Send"}</span>
            </button>
          </div>
        </form>
      </section>
    </GameOverlayFrame>
  );
}

export function Portrait({ name, url, testId }: { name: string; url?: string; testId?: string }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = Boolean(url && failedUrl !== url);
  return (
    <span data-testid={testId} className="relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-teal-900 to-cyan-600 text-lg font-black text-white shadow-inner">
      {name.slice(0, 1).toUpperCase()}
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={resolveApiAssetUrl(url!)} alt="" className="absolute inset-0 h-full w-full object-cover object-top" onError={() => setFailedUrl(url!)} />
      ) : null}
    </span>
  );
}

function HistoryTurn({ turn, resident, language, participantPortraitUrl, residentPortraitUrl }: { turn: WorldConversationTurn; resident: WorldResident; language: Language; participantPortraitUrl?: string; residentPortraitUrl?: string }) {
  const participant = turn.speaker_type === "participant" || turn.speaker_type === "user";
  const name = participant ? language === "zh-CN" ? "你" : "You" : turn.speaker_name ?? resident.name;
  return (
    <div data-testid="conversation-turn" data-speaker-type={participant ? "participant" : "agent"} className={`flex items-end gap-2 ${participant ? "flex-row-reverse" : ""}`}>
      <Portrait name={name} url={participant ? participantPortraitUrl : residentPortraitUrl} />
      <div className={`max-w-[82%] rounded-2xl px-3 py-2 text-sm leading-6 ${participant ? "bg-teal-800 text-white" : "border border-stone-200 bg-stone-100 text-stone-800"}`}>
        <p className="mb-0.5 text-[10px] font-black opacity-70">{name}</p><p>{turn.content}</p>
      </div>
    </div>
  );
}

function generationLabel(mode: string | null | undefined, language: Language) {
  if (!mode) return language === "zh-CN" ? "岛民交流" : "Resident conversation";
  if (mode === "llm") return language === "zh-CN" ? "AI 生成回复" : "AI-generated reply";
  if (mode === "fallback") return language === "zh-CN" ? "安全备用回复" : "Safe fallback reply";
  return language === "zh-CN" ? "规则生成回复" : "Rule-generated reply";
}
