"use client";

import {
  CalendarDays,
  Clock3,
  DoorOpen,
  Map,
  MapPin,
  Menu,
  Pause,
  Smartphone,
  Play,
} from "lucide-react";
import type { ReactNode } from "react";

type Props = {
  language: "en" | "zh-CN";
  dayLabel: string;
  timeLabel: string;
  locationLabel: string;
  worldView: "map" | "scene";
  canEnterScene: boolean;
  simulationMode: "running" | "paused";
  simulationBusy: boolean;
  busy: boolean;
  attention: boolean;
  timePausedForConversation: boolean;
  canPassTime: boolean;
  onToggleSimulation: () => void;
  onPassTime: () => void;
  onShowMap: () => void;
  onEnterScene: () => void;
  onOpenMenu: () => void;
  onOpenPhone: () => void;
  onOpenTasks: () => void;
  taskCount: number;
  phoneOpen: boolean;
  unreadSocialCount: number;
};

export function GameHud({
  language,
  dayLabel,
  timeLabel,
  locationLabel,
  worldView,
  canEnterScene,
  simulationMode,
  simulationBusy,
  busy,
  attention,
  timePausedForConversation,
  canPassTime,
  onToggleSimulation,
  onPassTime,
  onShowMap,
  onEnterScene,
  onOpenMenu,
  onOpenPhone,
  onOpenTasks, taskCount,
  phoneOpen,
  unreadSocialCount,
}: Props) {
  const isChinese = language === "zh-CN";
  return (
    <header
      data-testid="game-hud"
      className="rounded-2xl border border-teal-950/15 bg-teal-950 px-3 py-3 text-white shadow-lg sm:px-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs sm:text-sm">
          <HudFact icon={<CalendarDays className="h-4 w-4" />} text={dayLabel} />
          <span data-testid="world-clock">
            <HudFact icon={<Clock3 className="h-4 w-4" />} text={timeLabel} />
          </span>
          <button
            data-testid="pass-time-button"
            type="button"
            onClick={onPassTime}
            disabled={!canPassTime || busy}
            title={timePausedForConversation ? (isChinese ? "对话中，岛屿时间已暂停" : "Island time is paused during the conversation") : undefined}
            className="focus-ring inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-white/25 bg-white/10 px-2.5 font-bold text-teal-50 hover:bg-white/20 disabled:opacity-50"
          >
            <Clock3 className="h-4 w-4" aria-hidden="true" />
            {isChinese ? "消磨时间" : "Pass time"}
          </button>
          {timePausedForConversation ? (
            <span data-testid="conversation-time-paused" className="rounded-full bg-amber-300 px-2.5 py-1.5 text-[11px] font-black text-stone-950" role="status">
              {isChinese ? "对话中 · 岛屿时间已暂停" : "Conversation · Island time paused"}
            </span>
          ) : null}
          <HudFact icon={<MapPin className="h-4 w-4" />} text={locationLabel} />
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-1.5 sm:w-auto sm:justify-end sm:gap-2">
          <button data-testid="tasks-button" type="button" onClick={onOpenTasks} aria-haspopup="dialog" className="focus-ring relative min-h-11 rounded-lg border border-white/25 bg-white/10 px-2 text-xs font-bold sm:px-3 sm:text-sm">任务{taskCount > 0 ? <span className="absolute -right-1 -top-2 rounded-full bg-rose-500 px-1.5 text-xs">{taskCount}</span> : null}</button>
          <button
            data-testid="social-phone-button"
            type="button"
            onClick={onOpenPhone}
            aria-haspopup="dialog"
            aria-expanded={phoneOpen}
            className="focus-ring relative inline-flex min-h-11 min-w-11 justify-center items-center gap-1.5 rounded-lg border border-white/25 bg-white/10 px-2 text-xs font-bold sm:px-3 hover:bg-white/20 sm:text-sm"
          >
            <Smartphone className="h-4 w-4" aria-hidden="true" />
            {isChinese ? "手机" : "Phone"}
            {unreadSocialCount > 0 ? (
              <span className="absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-500 px-1 text-[11px] font-black text-white" aria-label={isChinese ? `${unreadSocialCount} 条未读动态` : `${unreadSocialCount} unread updates`}>
                {unreadSocialCount > 99 ? "99+" : unreadSocialCount}
              </span>
            ) : null}
          </button>
          <button
            data-testid="simulation-toggle"
            type="button"
            onClick={onToggleSimulation}
            disabled={simulationBusy || busy}
            aria-pressed={simulationMode === "paused"}
            className="focus-ring inline-flex min-h-11 min-w-11 justify-center items-center gap-1.5 rounded-lg border border-white/25 bg-white/10 px-2 text-xs font-bold sm:px-3 hover:bg-white/20 disabled:opacity-50 sm:text-sm"
          >
            {simulationMode === "running" ? (
              <Pause className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Play className="h-4 w-4" aria-hidden="true" />
            )}
            <span className="sr-only sm:not-sr-only">{simulationMode === "running"
              ? isChinese ? "暂停" : "Pause"
              : isChinese ? "继续" : "Resume"}</span>
          </button>
          {worldView === "scene" ? (
            <button
              data-testid="map-view-tab"
              type="button"
              onClick={onShowMap}
              disabled={busy}
              className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-lg bg-amber-300 px-2 text-xs font-bold sm:px-3 text-stone-950 hover:bg-amber-200 sm:text-sm"
            >
              <Map className="h-4 w-4" aria-hidden="true" />
              {isChinese ? "返回地图" : "Back to map"}
            </button>
          ) : (
            <button
              data-testid="scene-view-tab"
              type="button"
              onClick={onEnterScene}
              disabled={!canEnterScene || busy}
              className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-lg bg-amber-300 px-2 text-xs font-bold sm:px-3 text-stone-950 hover:bg-amber-200 disabled:opacity-50 sm:text-sm"
            >
              <DoorOpen className="h-4 w-4" aria-hidden="true" />
              {isChinese ? "进入当前地点" : "Enter current place"}
            </button>
          )}
          <button
            data-testid="game-menu-button"
            type="button"
            onClick={onOpenMenu}
            disabled={busy}
            aria-haspopup="dialog"
            className="focus-ring inline-flex min-h-11 min-w-11 justify-center items-center gap-1.5 rounded-lg border border-white/25 bg-white/10 px-2 text-xs font-bold sm:px-3 hover:bg-white/20 disabled:opacity-50 sm:text-sm"
          >
            <Menu className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only sm:not-sr-only">{isChinese ? "菜单" : "Menu"}</span>
            {attention ? <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-300 px-1 text-[11px] font-black text-stone-950" aria-label={isChinese ? "有待处理内容" : "Pending activity"}>!</span> : null}
          </button>
        </div>
      </div>
    </header>
  );
}

function HudFact({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <span className="inline-flex min-h-9 max-w-full items-center gap-1.5 rounded-lg bg-black/20 px-2.5 text-teal-50">
      <span aria-hidden="true">{icon}</span>
      <span className="truncate">{text}</span>
    </span>
  );
}
