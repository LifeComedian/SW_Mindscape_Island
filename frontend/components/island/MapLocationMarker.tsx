"use client";

import { useState, type KeyboardEvent, type PointerEvent } from "react";

import type { WorldMapLocationNode } from "@/lib/api";

export type MapLocationStatus =
  | "current"
  | "reachable"
  | "closed"
  | "unreachable";

const ICON_GLYPHS: Record<string, string> = {
  cottage: "⌂",
  homes: "▥",
  square: "◇",
  harbor: "⚓",
  restaurant: "♨",
  shop: "▣",
  lighthouse: "✦",
};

const STATUS_COLORS: Record<
  MapLocationStatus,
  { fill: string; stroke: string; text: string }
> = {
  current: { fill: "#0f766e", stroke: "#fef3c7", text: "#ffffff" },
  reachable: { fill: "#f8fafc", stroke: "#0f766e", text: "#134e4a" },
  closed: { fill: "#e7e5e4", stroke: "#78716c", text: "#57534e" },
  unreachable: { fill: "#f5f5f4", stroke: "#a8a29e", text: "#78716c" },
};

const STATUS_GLYPHS: Record<MapLocationStatus, string> = {
  current: "◎",
  reachable: "→",
  closed: "×",
  unreachable: "·",
};

type Props = {
  node: WorldMapLocationNode;
  name: string;
  status: MapLocationStatus;
  statusLabel: string;
  selected: boolean;
  onSelect: () => void;
  onDragStart?: (event: PointerEvent<SVGGElement>) => void;
  imageUrl?: string;
  compact?: boolean;
  hours?:string;
};

export function MapLocationMarker({
  node,
  name,
  status,
  statusLabel,
  selected,
  onSelect,
  onDragStart,
  imageUrl,
  compact = false,
  hours,
}: Props) {
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);
  const imageFailed = Boolean(imageUrl && failedImageUrl === imageUrl);
  const color = STATUS_COLORS[status];
  const radius = node.click_radius;
  const handleKeyDown = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };

  return (
    <g
      role="button"
      tabIndex={0}
      data-testid={`map-location-${node.location_id}`}
      data-location-status={status}
      aria-label={`${name}: ${statusLabel}${hours?' · '+hours:''}`}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      onPointerDown={onDragStart}
      className="cursor-pointer outline-none focus-visible:[filter:drop-shadow(0_0_7px_#f59e0b)]"
    >
      <title>{`${name} — ${statusLabel}`}</title>
      {selected ? (
        <circle
          cx={node.x}
          cy={node.y}
          r={radius + 9}
          fill="none"
          stroke="#f59e0b"
          strokeWidth="5"
          opacity="0.9"
        />
      ) : null}
      <circle
        cx={node.x}
        cy={node.y}
        r={radius}
        fill={color.fill}
        stroke={color.stroke}
        strokeWidth={status === "current" ? 5 : 4}
      />
      {imageUrl && !imageFailed ? (
        <>
          <defs>
            <clipPath id={`location-clip-${node.location_id}`}>
              <circle cx={node.x} cy={node.y} r={Math.max(1, radius - 3)} />
            </clipPath>
          </defs>
          <image
            href={imageUrl}
            x={node.x - radius}
            y={node.y - radius}
            width={radius * 2}
            height={radius * 2}
            preserveAspectRatio="xMidYMid slice"
            clipPath={`url(#location-clip-${node.location_id})`}
            onError={() => setFailedImageUrl(imageUrl)}
          />
        </>
      ) : <text
        x={node.x}
        y={node.y + 7}
        textAnchor="middle"
        fontSize="22"
        fontWeight="700"
        fill={color.text}
        aria-hidden="true"
      >
        {ICON_GLYPHS[node.icon_key] ?? "•"}
      </text>}
      <text
        x={node.x + node.label_offset[0]}
        y={node.y + node.label_offset[1]}
        textAnchor="middle"
        fontSize={compact ? 15 : 18}
        fontWeight="700"
        fill="#1c1917"
        stroke="#ffffff"
        strokeWidth="5"
        paintOrder="stroke"
        className="pointer-events-none"
      >
        {name}
      </text>
      {hours&&<text x={node.x+node.label_offset[0]} y={node.y+node.label_offset[1]+46} textAnchor="middle" fontSize="11" fontWeight="700" fill="#1c1917" stroke="white" strokeWidth="4" paintOrder="stroke">{hours}</text>}
      {!compact || selected || status === "current" || status === "closed" ? <g className="pointer-events-none" aria-hidden="true">
        <rect
          x={node.x + node.label_offset[0] - Math.max(34, statusLabel.length * 5.5)}
          y={node.y + node.label_offset[1] + 8}
          width={Math.max(68, statusLabel.length * 11)}
          height="19"
          rx="9.5"
          fill="#1c1917"
          opacity="0.82"
        />
        <text
          x={node.x + node.label_offset[0]}
          y={node.y + node.label_offset[1] + 22}
          textAnchor="middle"
          fontSize="10"
          fontWeight="800"
          fill="#ffffff"
        >
          {`${STATUS_GLYPHS[status]} ${statusLabel}`}
        </text>
      </g> : null}
    </g>
  );
}
