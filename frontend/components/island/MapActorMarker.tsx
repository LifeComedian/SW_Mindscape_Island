"use client";

import { useState, type KeyboardEvent } from "react";

import type { WorldActor } from "@/lib/api";

const MARKER_COLORS: Record<string, string> = {
  participant_gold: "#f59e0b",
  resident_teal: "#0d9488",
  resident_blue: "#2563eb",
  resident_amber: "#d97706",
  resident_rose: "#e11d48",
  resident_violet: "#7c3aed",
  resident_default: "#57534e",
};

type Props = {
  actor: WorldActor;
  selected: boolean;
  onSelect: () => void;
  imageUrl?: string;
  labelIndex?: number;
  labelCount?: number;
};

export function MapActorMarker({ actor, selected, onSelect, imageUrl, labelIndex = 0, labelCount = 1 }: Props) {
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);
  const imageFailed = Boolean(imageUrl && failedImageUrl === imageUrl);
  if (actor.x == null || actor.y == null) return null;
  const color = MARKER_COLORS[actor.marker_color_key] ?? MARKER_COLORS.resident_default;
  const labelWidth = Math.max(62, actor.name.length * 9 + 24);
  const labelX = labelCount > 1 && labelIndex % 2 === 1 ? -labelWidth - 17 : 17;
  const labelY = labelCount > 1 ? 18 + Math.floor(labelIndex / 2) * 25 : 17;
  const handleKeyDown = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };

  return (
    <g className="group">
      <g
        role="button"
        tabIndex={0}
        data-testid={`map-actor-${actor.actor_type}-${actor.agent_id ?? "self"}`}
        aria-label={actor.name}
        aria-pressed={selected}
        onClick={onSelect}
        onKeyDown={handleKeyDown}
        className="cursor-pointer outline-none focus-visible:[filter:drop-shadow(0_0_7px_#f59e0b)]"
        transform={`translate(${actor.x} ${actor.y})`}
      >
        <title>{`${actor.name}: ${actor.current_activity ?? ""}`}</title>
        {selected ? <circle r="18" fill="none" stroke="#fef3c7" strokeWidth="4" /> : null}
        {imageUrl && !imageFailed ? (
          <>
            <circle r="13" fill={color} stroke="#fff" strokeWidth="3" />
            <defs>
              <clipPath id={`actor-clip-${actor.actor_id.replaceAll(":", "-")}`}>
                <circle r="13" />
              </clipPath>
            </defs>
            <image href={imageUrl} x="-13" y="-13" width="26" height="26" preserveAspectRatio="xMidYMin slice" clipPath={`url(#actor-clip-${actor.actor_id.replaceAll(":", "-")})`} onError={() => setFailedImageUrl(imageUrl)} />
            <circle r="13" fill="none" stroke="#fff" strokeWidth="3" />
          </>
        ) : actor.is_current_participant ? (
          <path d="M 0 -13 L 12 0 L 0 13 L -12 0 Z" fill={color} stroke="#fff" strokeWidth="3" />
        ) : (
          <circle r="12" fill={color} stroke="#fff" strokeWidth="3" />
        )}
        {!imageUrl || imageFailed ? <text y="4" textAnchor="middle" fontSize="10" fontWeight="800" fill="#fff" className="pointer-events-none">{actor.name.slice(0, 1).toUpperCase()}</text> : null}
      </g>
      <g
        transform={`translate(${actor.x} ${actor.y})`}
        className={`pointer-events-none transition-opacity duration-150 motion-reduce:transition-none ${selected ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"}`}
        aria-hidden="true"
      >
        <line
          x1={labelX < 0 ? -10 : 10}
          y1="8"
          x2={labelX < 0 ? labelX + labelWidth : labelX}
          y2={labelY + 10.5}
          stroke="#1c1917"
          strokeWidth="2"
          opacity="0.65"
        />
        <rect
          x={labelX}
          y={labelY}
          width={labelWidth}
          height="21"
          rx="10.5"
          fill="#1c1917"
          opacity="0.88"
        />
        <circle cx={labelX + 9} cy={labelY + 10.5} r="3" fill="#86efac" />
        <text
          x={labelX + 16}
          y={labelY + 14}
          textAnchor="start"
          fontSize="10"
          fontWeight="800"
          fill="#ffffff"
        >
          {actor.name}
        </text>
      </g>
    </g>
  );
}
