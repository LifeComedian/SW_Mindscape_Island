"use client";

import { CalendarDays, Clock3, MapPin, Newspaper, Pause, Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

type Props = {
  eyebrow: string;
  title: string;
  subtitle: string;
  feedHref: string;
  feedLabel: string;
  refreshLabel: string;
  refreshingLabel: string;
  exportHref: string;
  exportLabel: string;
  finishLabel: string;
  finishingLabel: string;
  dayLabel: string;
  timeLabel: string;
  locationLabel: string;
  refreshing: boolean;
  finishing: boolean;
  busy: boolean;
  canFinish: boolean;
  simulationMode: "running" | "paused";
  simulationBusy: boolean;
  simulationLabel: string;
  onRefresh: () => void;
  onFinish: () => void;
  onToggleSimulation: () => void;
};

export function WorldHeader({
  eyebrow,
  title,
  subtitle,
  feedHref,
  feedLabel,
  refreshLabel,
  refreshingLabel,
  exportHref,
  exportLabel,
  finishLabel,
  finishingLabel,
  dayLabel,
  timeLabel,
  locationLabel,
  refreshing,
  finishing,
  busy,
  canFinish,
  simulationMode,
  simulationBusy,
  simulationLabel,
  onRefresh,
  onFinish,
  onToggleSimulation,
}: Props) {
  return (
    <header className="overflow-hidden rounded-xl border border-teal-900/10 bg-gradient-to-br from-teal-950 via-teal-900 to-cyan-800 p-6 text-white shadow-lg sm:p-8">
      <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-teal-100">{eyebrow}</p>
          <h1 className="mt-2 text-3xl font-bold sm:text-4xl">{title}</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-teal-50">{subtitle}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={feedHref} className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border border-white/30 bg-white/10 px-4 text-sm font-semibold text-white hover:bg-white/20">
            <Newspaper className="h-4 w-4" aria-hidden="true" />
            {feedLabel}
          </Link>
          <button type="button" onClick={onRefresh} disabled={refreshing || busy} className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md bg-white px-4 text-sm font-semibold text-teal-950 hover:bg-teal-50 disabled:opacity-60">
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
            {refreshing ? refreshingLabel : refreshLabel}
          </button>
          <button
            data-testid="simulation-toggle"
            type="button"
            onClick={onToggleSimulation}
            disabled={simulationBusy || busy || !canFinish}
            aria-pressed={simulationMode === "paused"}
            className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border border-white/30 bg-white/10 px-4 text-sm font-semibold text-white hover:bg-white/20 disabled:opacity-60"
          >
            {simulationMode === "running" ? (
              <Pause className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Play className="h-4 w-4" aria-hidden="true" />
            )}
            {simulationLabel}
          </button>
          <a data-testid="island-export" href={exportHref} className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border border-white/30 bg-white/10 px-4 text-sm font-semibold text-white hover:bg-white/20">
            {exportLabel}
          </a>
          <button data-testid="finish-session" type="button" onClick={onFinish} disabled={!canFinish || busy} className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border border-white/30 bg-white/10 px-4 text-sm font-semibold text-white hover:bg-white/20 disabled:opacity-60">
            {finishing ? finishingLabel : finishLabel}
          </button>
        </div>
      </div>
      <div className="mt-6 flex flex-wrap gap-3 text-sm">
        <HeaderPill icon={<CalendarDays className="h-4 w-4" />} text={dayLabel} />
        <span data-testid="world-clock">
          <HeaderPill icon={<Clock3 className="h-4 w-4" />} text={timeLabel} />
        </span>
        <HeaderPill icon={<MapPin className="h-4 w-4" />} text={locationLabel} />
      </div>
    </header>
  );
}

function HeaderPill({ icon, text }: { icon: ReactNode; text: string }) {
  return <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-black/10 px-3 py-2 text-teal-50">{icon}{text}</span>;
}
