"use client";

import { MessageCircleMore } from "lucide-react";
import { useCallback, useEffect, useState, type KeyboardEvent } from "react";

import type {
  WorldActor,
  WorldConversation,
  WorldConversationTurn,
  WorldInteractionPoint,
  WorldLocation,
  WorldSceneLayout,
  WorldVisuals,
} from "@/lib/api";
import { resolveApiAssetUrl } from "@/lib/api";
import type { Language } from "@/lib/i18n";

const OBJECT_COLORS: Record<string, string> = {
  desk: "#92400e", notice: "#ca8a04", garden: "#15803d", table: "#a16207",
  books: "#7c3aed", bench: "#78716c", railing: "#64748b", counter: "#0f766e",
  shelf: "#7c2d12", display: "#be123c", landmark: "#475569", seat: "#57534e",
};

const ACTOR_COLORS: Record<string, string> = {
  participant_gold: "#f59e0b", resident_teal: "#0d9488", resident_blue: "#2563eb",
  resident_amber: "#d97706", resident_rose: "#e11d48", resident_violet: "#7c3aed",
};

const PALETTES: Record<string, { sky: string; ground: string; accent: string }> = {
  ocean_teal: { sky: "#a5f3fc", ground: "#99f6e4", accent: "#0f766e" },
  sand_warm: { sky: "#fef3c7", ground: "#fdba74", accent: "#b45309" },
  forest_green: { sky: "#d1fae5", ground: "#bef264", accent: "#15803d" },
  harbor_blue: { sky: "#dbeafe", ground: "#7dd3fc", accent: "#1d4ed8" },
  sunset_rose: { sky: "#ffe4e6", ground: "#fed7aa", accent: "#be123c" },
  neutral_stone: { sky: "#e7e5e4", ground: "#d6d3d1", accent: "#57534e" },
};

type Props = {
  language: Language;
  location: WorldLocation;
  layout: WorldSceneLayout;
  actors: WorldActor[];
  visuals?: WorldVisuals | null;
  interactionPoints: WorldInteractionPoint[];
  ambientConversations: WorldConversation[];
  selectedObjectId: string | null;
  selectedActorId: string | null;
  busy: boolean;
  promptInitiatorAgentId?: number | null;
  adjacentThumbnailUrls?: string[];
  onInspect: (point: WorldInteractionPoint) => void;
  onHotspotInspect?: (point: WorldInteractionPoint, hotspotId: string, logCode: string) => void;
  onSelectActor: (actor: WorldActor) => void;
  onOpenWorldLog?: () => void;
};

export function LocationScene({
  language, location, layout, actors, visuals, interactionPoints,
  ambientConversations, selectedObjectId, selectedActorId, busy,
  promptInitiatorAgentId = null, adjacentThumbnailUrls = [], onInspect, onHotspotInspect, onSelectActor,
}: Props) {
  const [failedSceneUrl, setFailedSceneUrl] = useState<string | null>(null);
  const namesVisible = true;
  const [dismissedBubbleKeys, setDismissedBubbleKeys] = useState<Set<string>>(() => new Set());
  const pointById = new Map(interactionPoints.map((point) => [point.object_id, point]));
  const locationLabel = localizeLocation(location, language);
  const locationDescription = localizeLocationDescription(location, language);
  const sceneSlot = visuals?.slots[`locations.${location.location_id}.scene_image`];
  const sceneUrl = sceneSlot?.asset?.url ? resolveApiAssetUrl(sceneSlot.asset.url) : undefined;
  const showSceneImage = Boolean(sceneUrl && failedSceneUrl !== sceneUrl);
  const illustrated = Boolean(sceneSlot?.asset_key?.startsWith("location."));
  const palette = PALETTES[sceneSlot?.fallback_palette_key ?? "sunset_rose"] ?? PALETTES.neutral_stone;
  const visibleAmbient = ambientConversations.filter((conversation) =>
    conversation.conversation_kind === "resident_resident" &&
    conversation.visibility === "public" &&
    (!conversation.location_id || conversation.location_id === location.location_id),
  );
  const bubbles = [...visibleAmbient].sort((left, right) => {
    const leftTurn = left.turns?.at(-1);
    const rightTurn = right.turns?.at(-1);
    return conversationTurnOrder(rightTurn) - conversationTurnOrder(leftTurn);
  }).map((conversation) => {
    const turn = conversation.turns?.at(-1);
    const speaker = turn ? actors.find((actor) => actor.agent_id === Number(turn.speaker_id)) : undefined;
    return turn && speaker ? { conversation, turn, speaker } : null;
  }).filter((item): item is { conversation: WorldConversation; turn: WorldConversationTurn; speaker: WorldActor } => Boolean(item)).slice(0, 3);
  const displayedBubbles = bubbles.filter(({ conversation, turn }) =>
    !dismissedBubbleKeys.has(conversationBubbleKey(conversation, turn)) && !(location.location_id==='guest_room' && Number(turn.speaker_id)>=9),
  );
  const dismissBubble = useCallback((key: string) => {
    setDismissedBubbleKeys((current) => {
      if (current.has(key)) return current;
      const next = new Set(current);
      next.add(key);
      return next;
    });
  }, []);
  const outdoorVisitors = location.location_id==='guest_room' ? actors.filter(a=>(a.agent_id??0)>=9) : [];
  const sortedActors = actors.filter(a=>!outdoorVisitors.includes(a)).sort((left, right) =>
    (left.scene_y ?? Number.MAX_SAFE_INTEGER) - (right.scene_y ?? Number.MAX_SAFE_INTEGER) || left.actor_id.localeCompare(right.actor_id),
  );

  const actorAssetUrl = (actor: WorldActor) => {
    const url = visuals?.slots[`actors.${actor.actor_id}.map_thumbnail`]?.asset?.url;
    return url ? resolveApiAssetUrl(url) : undefined;
  };

  return (
    <div data-testid="location-stage" data-location-id={location.location_id} style={{ backgroundColor: illustrated ? "#faf8f3" : palette.ground }} className={`relative flex w-full flex-col overflow-hidden rounded-xl border border-stone-200 shadow-sm ${illustrated ? "lg:h-full" : "h-full min-h-[420px]"}`}>
      {adjacentThumbnailUrls.map((url) => <link key={url} rel="prefetch" as="image" href={resolveApiAssetUrl(url)} />)}
      <div className={illustrated ? "relative w-full overflow-hidden lg:min-h-0 lg:flex-1" : "relative min-h-[340px] flex-1 overflow-hidden"}>
      <svg data-testid="location-scene" data-scene-location={location.location_id} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={language === "zh-CN" ? `${locationLabel}场景` : `${locationLabel} scene`} preserveAspectRatio="xMidYMid meet" className={illustrated ? "block h-auto w-full lg:h-full" : "h-full w-full"}>
        <defs>
          <linearGradient id={`scene-palette-${safeSvgId(location.location_id)}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={palette.sky} />
            <stop offset="1" stopColor={palette.ground} />
          </linearGradient>
        </defs>
        <rect width={layout.width} height={layout.height} fill={`url(#scene-palette-${safeSvgId(location.location_id)})`} />
        <path d={`M 0 ${layout.height * 0.68} Q ${layout.width * 0.5} ${layout.height * 0.54} ${layout.width} ${layout.height * 0.68} L ${layout.width} ${layout.height} L 0 ${layout.height} Z`} fill={palette.ground} opacity="0.85" />
        {showSceneImage ? <image data-testid="scene-background-image" href={sceneUrl} width={layout.width} height={layout.height} preserveAspectRatio="xMidYMid meet" onError={() => setFailedSceneUrl(sceneUrl!)} /> : (
          <foreignObject x="20" y="16" width={layout.width - 40} height="72" className="pointer-events-none">
            <div className="flex h-full flex-col justify-center rounded-2xl border border-white/70 bg-white/65 px-5 shadow-md backdrop-blur-sm">
              <p className="truncate text-lg font-black text-stone-950">{locationLabel}</p>
              <p className="mt-0.5 line-clamp-2 text-xs leading-4 text-stone-700">{locationDescription}</p>
            </div>
          </foreignObject>
        )}
        <g aria-label={language === "zh-CN" ? "场景交互点" : "Scene interaction points"}>
          {(layout.hotspots ?? []).map((hotspot) => {
            const point = pointById.get(hotspot.target_object_id);
            if (!point) return null;
            const label = hotspot.label?.[language] ?? hotspot.label?.en ?? interactionPointName(point, language);
            const activate = () => {
              if (onHotspotInspect) onHotspotInspect(point, hotspot.hotspot_id, hotspot.log_code);
              else onInspect(point);
            };
            const handleKeyDown = (event: KeyboardEvent<SVGGElement>) => {
              if (!busy && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); activate(); }
            };
            return (
              <g key={hotspot.hotspot_id} role="button" tabIndex={busy ? -1 : 0} data-testid={`scene-hotspot-${hotspot.hotspot_id}`} aria-label={label} aria-disabled={busy} onClick={busy ? undefined : activate} onKeyDown={handleKeyDown} className="cursor-pointer outline-none focus-visible:[filter:drop-shadow(0_0_8px_#f59e0b)]">
                <title>{label}</title>
                {hotspot.shape === "circle"
                  ? <circle cx={hotspot.x} cy={hotspot.y} r={hotspot.radius ?? 24} fill="transparent" stroke="transparent" strokeWidth="3" />
                  : <rect x={hotspot.x} y={hotspot.y} width={hotspot.width ?? 48} height={hotspot.height ?? 48} fill="transparent" stroke="transparent" strokeWidth="3" />}
              </g>
            );
          })}
          {Object.entries(layout.interaction_point_positions).map(([objectId, position]) => {
            const point = pointById.get(objectId);
            if (!point) return null;
            return <SceneObject key={objectId} illustrated={illustrated} point={point} x={position[0]} y={position[1]} language={language} selected={selectedObjectId === objectId} disabled={busy} onInspect={() => onInspect(point)} />;
          })}
        </g>
        <g aria-label={language === "zh-CN" ? "场景人物" : "People in scene"}>
          {sortedActors.map((actor) => <SceneActor key={actor.actor_id} illustrated={illustrated} actor={actor} selected={selectedActorId === actor.actor_id} onSelect={() => onSelectActor(actor)} imageUrl={actorAssetUrl(actor)} showName={namesVisible} hasPrompt={actor.agent_id != null && actor.agent_id === promptInitiatorAgentId} language={language} />)}
        </g>
      </svg>

      </div>
      {outdoorVisitors.length>0&&<div data-testid="inn-outdoor-visitors" className="flex shrink-0 flex-wrap items-center gap-3 border-t border-stone-300 bg-[#e3dac5] p-3"><span className="text-sm text-stone-700">民宿外廊 · 其他客房入口</span>{outdoorVisitors.map(actor=><button key={actor.actor_id} data-testid={`visitor-outdoor-${actor.agent_id}`} disabled={busy} onClick={()=>onSelectActor(actor)} className="focus-ring flex items-center gap-2 rounded-xl bg-white/80 px-3 py-2 text-sm font-semibold"><img src={actorAssetUrl(actor)} alt="" className="h-12 w-12 rounded-full object-cover"/>{actor.name}</button>)}</div>}
      {illustrated ? <div data-testid="scene-actions" className="shrink-0 space-y-3 border-t border-stone-200 bg-white px-3 py-3 sm:px-4">
        <div className="flex flex-wrap items-center justify-between gap-1"><h2 className="text-sm font-bold text-stone-900">{locationLabel}</h2><p className="text-xs text-stone-500">{language === "zh-CN" ? "点击画面标记，或选择下方内容" : "Select a pin or an item below"}</p></div>
        <div className="flex flex-wrap gap-2">{interactionPoints.map(point => <button key={point.object_id} type="button" data-testid={`scene-action-${point.object_id}`} disabled={busy} aria-pressed={selectedObjectId===point.object_id} onClick={() => onInspect(point)} className="focus-ring min-h-11 rounded-lg border border-stone-300 bg-stone-50 px-3 text-sm font-medium text-stone-800 hover:border-teal-600 hover:bg-teal-50 disabled:opacity-50">{interactionPointName(point,language)}</button>)}</div>
        {actors.some(actor => !actor.is_current_participant) ? <div className="flex flex-wrap items-center gap-2 border-t border-stone-100 pt-2"><span className="text-xs text-stone-500">{language === "zh-CN" ? "在这里" : "Here"}</span>{actors.filter(actor => !actor.is_current_participant).map(actor => <button key={actor.actor_id} disabled={busy} type="button" onClick={() => onSelectActor(actor)} className="focus-ring min-h-11 rounded-lg px-3 text-sm font-bold text-teal-800 hover:bg-teal-50 disabled:opacity-50">{actor.name}{actor.agent_id===promptInitiatorAgentId ? " · !" : ""}</button>)}</div> : null}
      </div> : null}
      {displayedBubbles.length ? (
        <div data-testid="ambient-bubbles" aria-live="polite" aria-label={language === "zh-CN" ? "附近的公开交谈" : "Nearby public conversations"} className="relative z-20 grid shrink-0 grid-flow-col auto-cols-[minmax(260px,1fr)] gap-2 overflow-x-auto border-t border-stone-300/80 bg-stone-100/95 p-2 shadow-[0_-8px_24px_rgba(41,37,36,0.12)] sm:p-3">
          {displayedBubbles.map(({ conversation, turn, speaker }) => {
            const bubbleKey = conversationBubbleKey(conversation, turn);
            return <AmbientBubble key={bubbleKey} bubbleKey={bubbleKey} conversation={conversation} turn={turn} speaker={speaker} language={language} onExpired={dismissBubble} />;
          })}
        </div>
      ) : null}
    </div>
  );
}

function AmbientBubble({ bubbleKey, conversation, turn, speaker, language, onExpired }: { bubbleKey: string; conversation: WorldConversation; turn: WorldConversationTurn; speaker: WorldActor; language: Language; onExpired: (key: string) => void }) {
  const [phase, setPhase] = useState<"visible" | "fading" | "hidden">("visible");
  useEffect(() => {
    const fadeTimer = window.setTimeout(() => setPhase("fading"), 3_500);
    const hideTimer = window.setTimeout(() => setPhase("hidden"), 8_000);
    const expireTimer = window.setTimeout(() => onExpired(bubbleKey), 9_000);
    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(hideTimer);
      window.clearTimeout(expireTimer);
    };
  }, [bubbleKey, onExpired]);
  return (
    <article data-testid="ambient-bubble" data-conversation-id={conversation.conversation_id} data-speaker-agent-id={speaker.agent_id ?? undefined} aria-hidden={phase === "hidden"} className={`game-bubble-enter pointer-events-none min-w-0 rounded-2xl border-2 border-stone-700 bg-white/95 px-3 py-2 text-stone-900 shadow-md transition-opacity motion-reduce:transition-none ${phase === "visible" ? "opacity-100 duration-500" : phase === "fading" ? "opacity-40 duration-[4500ms]" : "opacity-0 duration-500"}`}>
      <div className="flex items-start gap-2">
        <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-teal-800 text-xs font-black text-white" aria-hidden="true">{speaker.name.slice(0, 1).toUpperCase()}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[10px] font-black uppercase tracking-wide text-teal-800">{turn.speaker_name ?? speaker.name}</p>
          <p className="mt-0.5 line-clamp-2 text-xs leading-4">{turn.content}</p>
        </div>
        <MessageCircleMore className="mt-1 h-4 w-4 shrink-0 text-stone-500" aria-hidden="true" />
      </div>
      <span className="sr-only">{language === "zh-CN" ? "公开交谈" : "Public conversation"}</span>
    </article>
  );
}

function conversationTurnOrder(turn: WorldConversationTurn | undefined) {
  if (!turn) return 0;
  if (typeof turn.turn_id === "number") return turn.turn_id;
  const createdAt = turn.created_at ? Date.parse(turn.created_at) : Number.NaN;
  return Number.isFinite(createdAt) ? createdAt : 0;
}

function conversationBubbleKey(conversation: WorldConversation, turn: WorldConversationTurn) {
  return `${conversation.conversation_id}:${turn.turn_id ?? turn.content}`;
}

function SceneObject({ illustrated, point, x, y, language, selected, disabled, onInspect }: { illustrated: boolean; point: WorldInteractionPoint; x: number; y: number; language: Language; selected: boolean; disabled: boolean; onInspect: () => void }) {
  const rendererKey = String(point.renderer_key ?? point.type ?? "object");
  const color = OBJECT_COLORS[rendererKey] ?? "#57534e";
  const entryLabels: Record<string,string> = {welcome_table:"欢迎桌（室内）",bonfire_table:"篝火桌入口"};
  const name = illustrated && language === "zh-CN" ? entryLabels[point.object_id] ?? interactionPointName(point, language) : interactionPointName(point, language);
  const labelY = point.object_id === "welcome_table" ? 33 : -24;
  const labelWidth = Math.min(140, Math.max(44, name.length * (language === "zh-CN" ? 13 : 7) + 16));
  const handleKeyDown = (event: KeyboardEvent<SVGGElement>) => {
    if (!disabled && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onInspect(); }
  };
  return (
    <g role="button" tabIndex={disabled ? -1 : 0} data-testid={`scene-object-${point.object_id}`} aria-label={name} aria-pressed={selected} aria-disabled={disabled} onClick={disabled ? undefined : onInspect} onKeyDown={handleKeyDown} transform={`translate(${x} ${y})`} className={disabled ? "cursor-wait" : "cursor-pointer outline-none focus-visible:[filter:drop-shadow(0_0_7px_#f59e0b)]"}>
      <title>{`${name}: ${interactionPointDescription(point, language)}`}</title>
      {illustrated ? <>
        <circle r="22" fill="transparent" />
        <circle r={selected ? 13 : 10} fill={selected ? "#0f766e" : "#fff"} stroke="#0f766e" strokeWidth="2.5" />
        <path d="M -4 0 H 4 M 0 -4 V 4" stroke={selected ? "#fff" : "#0f766e"} strokeWidth="2" />
        <rect x={-labelWidth/2} y={labelY-15} width={labelWidth} height="22" rx="7" fill="#fff" fillOpacity="0.96" stroke="#d6d3d1" />
        <text y={labelY} textAnchor="middle" fontSize="12" fontWeight="700" fill="#292524" className="pointer-events-none">{name}</text>
      </> : <>
      {selected ? <circle r="34" fill="none" stroke="#f59e0b" strokeWidth="5" /> : null}
      <rect x="-25" y="-22" width="50" height="44" rx="8" fill={color} stroke="#fff" strokeWidth="4" />
      <circle r="5" fill="#fff" />
      <text y="43" textAnchor="middle" fontSize="14" fontWeight="700" fill="#292524" stroke="#fff" strokeWidth="4" paintOrder="stroke" className="pointer-events-none">{name}</text>
      </>}
    </g>
  );
}

function SceneActor({ illustrated, actor, selected, onSelect, imageUrl, showName, hasPrompt, language }: { illustrated: boolean; actor: WorldActor; selected: boolean; onSelect: () => void; imageUrl?: string; showName: boolean; hasPrompt: boolean; language: Language }) {
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);
  if (actor.scene_x == null || actor.scene_y == null) return null;
  const color = ACTOR_COLORS[actor.marker_color_key] ?? "#57534e";
  const showImage = Boolean(imageUrl && failedImageUrl !== imageUrl);
  const handleKeyDown = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(); }
  };
  return (
    <g role="button" tabIndex={0} data-testid={`scene-actor-${actor.actor_type}-${actor.agent_id ?? "self"}`} aria-label={`${actor.name}: ${actor.current_activity ?? ""}`} aria-pressed={selected} onClick={onSelect} onKeyDown={handleKeyDown} style={{ transform: `translate(${actor.scene_x}px, ${actor.scene_y}px)` }} className="cursor-pointer outline-none transition-transform duration-300 motion-reduce:transition-none focus-visible:[filter:drop-shadow(0_0_8px_#f59e0b)]">
      <title>{`${actor.name}: ${actor.current_activity ?? ""}`}</title>
      {illustrated ? <>
        <circle cy="-13" r="22" fill="#fffaf0" stroke={selected || actor.is_current_participant ? "#b45309" : "#0f766e"} strokeWidth="2.5" />
        {showImage ? <>
          <defs><clipPath id={`presence-${safeSvgId(actor.actor_id)}`}><circle cy="-13" r="20" /></clipPath></defs>
          <image href={imageUrl} x="-20" y="-33" width="40" height="54" preserveAspectRatio="xMidYMin slice" clipPath={`url(#presence-${safeSvgId(actor.actor_id)})`} onError={() => setFailedImageUrl(imageUrl!)} />
        </> : <text y="-8" textAnchor="middle" fontSize="13" fill="#134e4a">{actor.name.slice(0,1)}</text>}
        {showName ? <text data-testid="scene-actor-name" y="22" textAnchor="middle" fontSize="12" fontWeight="700" fill="#292524" stroke="#fff" strokeWidth="4" paintOrder="stroke">{actor.is_current_participant ? (language === "zh-CN" ? "你" : "You") : actor.name}</text> : null}
      </> : <>
      {selected ? <circle cy="-18" r="29" fill="none" stroke="#f59e0b" strokeWidth="5" /> : null}
      {actor.is_current_participant ? <path d="M 0 -47 L 8 -39 L 0 -31 L -8 -39 Z" fill="#fbbf24" stroke="#7c2d12" strokeWidth="2" /> : null}
      {showImage ? (
        <>
          <circle cy="-23" r="18" fill={color} stroke={actor.is_current_participant ? "#fef3c7" : "#fff"} strokeWidth="4" />
          <defs><clipPath id={`scene-actor-${safeSvgId(actor.actor_id)}`}><circle cy="-23" r="17" /></clipPath></defs>
          <image href={imageUrl} x="-17" y="-40" width="34" height="34" preserveAspectRatio="xMidYMid slice" clipPath={`url(#scene-actor-${safeSvgId(actor.actor_id)})`} onError={() => setFailedImageUrl(imageUrl!)} />
        </>
      ) : <><circle cy="-23" r="18" fill={color} stroke={actor.is_current_participant ? "#fef3c7" : "#fff"} strokeWidth="4" /><text y="-18" textAnchor="middle" fontSize="13" fontWeight="900" fill="#fff" className="pointer-events-none">{actor.name.slice(0, 1).toUpperCase()}</text></>}
      <path d="M -19 3 Q 0 -10 19 3 L 23 38 L -23 38 Z" fill={color} stroke={actor.is_current_participant ? "#fef3c7" : "#fff"} strokeWidth="3" />
      {showName ? <text data-testid="scene-actor-name" y="62" textAnchor="middle" fontSize="14" fontWeight="800" fill="#292524" stroke="#fff" strokeWidth="5" paintOrder="stroke" className="pointer-events-none">{actor.name}</text> : null}
      </>}
      {hasPrompt ? <g data-testid={`scene-prompt-indicator-${actor.agent_id}`} aria-label={language === "zh-CN" ? `${actor.name}想和你交谈` : `${actor.name} wants to talk`}><circle cx="24" cy="-48" r="12" fill="#fef3c7" stroke="#92400e" strokeWidth="2" /><text x="24" y="-44" textAnchor="middle" fontSize="14" fontWeight="900" fill="#92400e">!</text></g> : null}
    </g>
  );
}

export function interactionPointName(point: WorldInteractionPoint, language: Language) {
  const source = point.name ?? point.label;
  if (source && typeof source === "object") return source[language] ?? source.en ?? source["zh-CN"] ?? point.object_id;
  return (language === "zh-CN" ? point.label_zh_cn : source) ?? source ?? point.label_zh_cn ?? point.object_id.replaceAll("_", " ");
}

export function interactionPointDescription(point: WorldInteractionPoint, language: Language) {
  if (point.description && typeof point.description === "object") return point.description[language] ?? point.description.en ?? point.description["zh-CN"] ?? "";
  return (language === "zh-CN" ? point.description_zh_cn : point.description) ?? point.description ?? point.description_zh_cn ?? "";
}

function localizeLocation(location: WorldLocation, language: Language) {
  return location.translations?.[language]?.name ?? (language === "zh-CN" ? location.name_zh_cn : location.name) ?? location.name;
}

function localizeLocationDescription(location: WorldLocation, language: Language) {
  return location.translations?.[language]?.description ?? (language === "zh-CN" ? location.description_zh_cn : location.description) ?? location.description ?? location.description_zh_cn ?? "";
}

function safeSvgId(value: string) { return value.replaceAll(/[^A-Za-z0-9_-]/g, "-"); }