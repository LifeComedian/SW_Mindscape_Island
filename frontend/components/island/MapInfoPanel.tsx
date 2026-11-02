"use client";

import { Footprints, MessageCircle } from "lucide-react";

import type { WorldActor, WorldLocation } from "@/lib/api";
import type { Language } from "@/lib/i18n";
import type { MapLocationStatus } from "./MapLocationMarker";

type Props = {
  language: Language;
  location: WorldLocation | null;
  locationStatus: MapLocationStatus | null;
  locationStatusLabel: string;
  actor: WorldActor | null;
  actorLocationName?: string;
  locationOccupants?: string[];
  locationRelationLabel?: string;
  canTravel: boolean;
  canApproach: boolean;
  busy: boolean;
  onTravel: (locationId: string) => void;
  onApproach: (agentId: number) => void;
};

export function MapInfoPanel({
  language,
  location,
  locationStatus,
  locationStatusLabel,
  actor,
  actorLocationName,
  locationOccupants = [],
  locationRelationLabel,
  canTravel,
  canApproach,
  busy,
  onTravel,
  onApproach,
}: Props) {
  if (!location && !actor) {
    return (
      <p className="text-sm leading-6 text-stone-500">
        {language === "zh-CN"
          ? "点击地点或人物标记查看简介。"
          : "Select a location or person marker to see a short profile."}
      </p>
    );
  }

  if (actor) {
    return (
      <div data-testid="map-actor-info" className="space-y-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-teal-700">
            {actor.is_current_participant
              ? language === "zh-CN" ? "你自己" : "You"
              : actor.role ?? (language === "zh-CN" ? "岛民" : "Resident")}
          </p>
          <h3 className="mt-1 text-lg font-bold text-stone-950">{actor.name}</h3>
        </div>
        <p className="text-sm leading-6 text-stone-600">{actor.public_summary}</p>
        <dl className="space-y-2 text-xs text-stone-600">
          <div className="flex justify-between gap-3">
            <dt>{language === "zh-CN" ? "当前位置" : "Location"}</dt>
            <dd className="font-semibold text-stone-800">
              {actorLocationName ?? actor.location_id}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>{language === "zh-CN" ? "当前活动" : "Activity"}</dt>
            <dd className="text-right font-semibold text-stone-800">{actor.current_activity}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>{language === "zh-CN" ? "交流状态" : "Conversation"}</dt>
            <dd className="text-right font-semibold text-stone-800">
              {actor.is_current_participant
                ? language === "zh-CN" ? "这是你" : "This is you"
                : canApproach
                  ? language === "zh-CN" ? "可以交流" : "Available"
                  : language === "zh-CN" ? "需要处于同一地点" : "Must share a location"}
            </dd>
          </div>
        </dl>
        {!actor.is_current_participant && actor.agent_id != null ? (
          <button
            type="button"
            onClick={() => onApproach(actor.agent_id!)}
            disabled={!canApproach || busy}
            className="focus-ring inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
          >
            <MessageCircle className="h-4 w-4" aria-hidden="true" />
            {language === "zh-CN" ? "靠近并交谈" : "Approach and talk"}
          </button>
        ) : null}
      </div>
    );
  }

  const name = location!.translations?.[language]?.name ??
    (language === "zh-CN" ? location!.name_zh_cn : location!.name) ?? location!.name;
  const description = location!.translations?.[language]?.description ??
    (language === "zh-CN" ? location!.description_zh_cn : location!.description) ?? "";
  return (
    <div data-testid="map-location-info" className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-lg font-bold text-stone-950">{name}</h3>
        {locationStatus ? (
          <span data-location-status={locationStatus} className="rounded-full bg-stone-100 px-2 py-1 text-[11px] font-bold text-stone-600">
            {locationStatusLabel}
          </span>
        ) : null}
      </div>
      <p className="text-sm leading-6 text-stone-600">{description}</p>
      <dl className="space-y-2 rounded-lg bg-white/80 p-3 text-xs text-stone-600">
        <div className="flex justify-between gap-3">
          <dt>{language === "zh-CN" ? "开放状态" : "Open status"}</dt>
          <dd className="font-semibold text-stone-800">{locationStatusLabel}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt>{language === "zh-CN" ? "路线" : "Route"}</dt>
          <dd className="text-right font-semibold text-stone-800">
            {locationRelationLabel ?? (language === "zh-CN" ? "距离未知" : "Distance unavailable")}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt>{language === "zh-CN" ? "当前人物" : "People here"}</dt>
          <dd className="text-right font-semibold text-stone-800">
            {locationOccupants.length
              ? locationOccupants.join(language === "zh-CN" ? "、" : ", ")
              : language === "zh-CN" ? "暂无" : "No one visible"}
          </dd>
        </div>
      </dl>
      <button
        type="button"
        data-testid={`travel-${location!.location_id}`}
        onClick={() => onTravel(location!.location_id)}
        disabled={!canTravel || busy}
        className="focus-ring inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
      >
        <Footprints className="h-4 w-4" aria-hidden="true" />
        {language === "zh-CN" ? "前往此地" : "Travel here"}
      </button>
    </div>
  );
}
