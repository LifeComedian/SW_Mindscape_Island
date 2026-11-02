"use client";

import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import type { Language } from "@/lib/i18n";
import {
  resolveApiAssetUrl,
  type WorldActor,
  type WorldLocation,
  type WorldMap,
  type WorldVisuals,
} from "@/lib/api";

import { MapActorMarker } from "./MapActorMarker";
import {
  MapLocationMarker,
  type MapLocationStatus,
} from "./MapLocationMarker";

type Props = {
  map: WorldMap;
  locations: WorldLocation[];
  actors: WorldActor[];
  visuals?: WorldVisuals | null;
  language: Language;
  currentLocationId: string;
  selectedLocationId: string | null;
  selectedActorId: string | null;
  statusForLocation: (location: WorldLocation) => MapLocationStatus;
  statusLabelForLocation: (status: MapLocationStatus) => string;
  onSelectLocation: (locationId: string) => void;
  onSelectActor: (actor: WorldActor) => void;
  stageMode?: boolean;
  editable?: boolean;
  openingHours?:Record<string,{hours:string;open:boolean}>;
  onMoveLocation?: (locationId: string, x: number, y: number) => void;
};

export function IslandMap({
  map,
  locations,
  actors,
  visuals,
  language,
  currentLocationId,
  selectedLocationId,
  selectedActorId,
  statusForLocation,
  statusLabelForLocation,
  onSelectLocation,
  onSelectActor,
  stageMode = false,
  editable = false,
  openingHours,
  onMoveLocation,
}: Props) {
  const draggingLocationId = useRef<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [failedMapUrl, setFailedMapUrl] = useState<string | null>(null);
  const locationsById = new Map(
    locations.map((location) => [location.location_id, location]),
  );
  const locationName = (location: WorldLocation) =>
    location.translations?.[language]?.name ??
    (language === "zh-CN" ? location.name_zh_cn : location.name) ??
    location.name;
  const slotUrl = (slotId: string) => {
    const url = visuals?.slots[slotId]?.asset?.url;
    return url ? resolveApiAssetUrl(url) : undefined;
  };
  const mapImageUrl = slotUrl("map.image");
  const illustrated = Boolean(visuals?.slots["map.image"]?.asset_key?.startsWith("map.island"));
  const showMapImage = Boolean(mapImageUrl && failedMapUrl !== mapImageUrl);

  const moveDraggedLocation = (event: PointerEvent<SVGSVGElement>) => {
    if (!editable || !draggingLocationId.current || !onMoveLocation) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(map.width, ((event.clientX - bounds.left) / bounds.width) * map.width));
    const y = Math.max(0, Math.min(map.height, ((event.clientY - bounds.top) / bounds.height) * map.height));
    onMoveLocation(draggingLocationId.current, Math.round(x), Math.round(y));
  };
  const viewportWidth = map.width / zoom;
  const viewportHeight = map.height / zoom;
  const viewportX = (map.width - viewportWidth) / 2;
  const viewportY = (map.height - viewportHeight) / 2;

  return (
    <div className={`relative flex flex-col overflow-auto bg-sky-50 shadow-inner ${stageMode ? "game-stage-enter h-full w-full" : "rounded-xl border border-sky-200"}`}>
      {mapImageUrl ? <link rel="preload" as="image" href={mapImageUrl} /> : null}
      <div className="relative z-10 m-2 flex shrink-0 self-end rounded-xl sm:absolute sm:left-3 sm:top-3 sm:m-0 border border-stone-300 bg-white/95 p-1 shadow-md backdrop-blur">
        <button
          data-testid="map-zoom-out"
          type="button"
          aria-label={language === "zh-CN" ? "缩小地图" : "Zoom map out"}
          onClick={() => setZoom((value) => Math.max(1, Number((value - 0.25).toFixed(2))))}
          disabled={zoom <= 1}
          className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-lg text-stone-700 hover:bg-stone-100 disabled:opacity-35"
        >
          <ZoomOut className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          data-testid="map-reset-view"
          type="button"
          aria-label={language === "zh-CN" ? "重置地图视图" : "Reset map view"}
          onClick={() => setZoom(1)}
          className="focus-ring inline-flex h-9 min-w-9 items-center justify-center gap-1 rounded-lg px-2 text-xs font-bold text-stone-700 hover:bg-stone-100"
        >
          <Maximize2 className="h-4 w-4" aria-hidden="true" />
          <span>{Math.round(zoom * 100)}%</span>
        </button>
        <button
          data-testid="map-zoom-in"
          type="button"
          aria-label={language === "zh-CN" ? "放大地图" : "Zoom map in"}
          onClick={() => setZoom((value) => Math.min(1.75, Number((value + 0.25).toFixed(2))))}
          disabled={zoom >= 1.75}
          className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-lg text-stone-700 hover:bg-stone-100 disabled:opacity-35"
        >
          <ZoomIn className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <svg
        data-testid="island-map"
        viewBox={`${viewportX} ${viewportY} ${viewportWidth} ${viewportHeight}`}
        role="img"
        aria-label={language === "zh-CN" ? "岛屿地图" : "Island map"}
        className={illustrated ? "block h-auto min-h-0 w-full flex-1" : stageMode ? "h-full w-full" : "h-auto w-full"}
        preserveAspectRatio="xMidYMid meet"
        onPointerMove={moveDraggedLocation}
        onPointerUp={(event) => {
          draggingLocationId.current = null;
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={() => { draggingLocationId.current = null; }}
      >
        <rect width={map.width} height={map.height} fill="#bae6fd" />
        <polygon
          points={map.land_polygon.map((point) => point.join(",")).join(" ")}
          fill="#d9f99d"
          stroke="#65a30d"
          strokeWidth="8"
          strokeLinejoin="round"
        />
        {showMapImage ? (
          <image
            data-testid="map-background-image"
            href={mapImageUrl}
            width={map.width}
            height={map.height}
            preserveAspectRatio="xMidYMid slice"
            onError={() => setFailedMapUrl(mapImageUrl!)}
          />
        ) : null}
        {(!showMapImage || editable ? map.paths : []).map((path) => (
          <polyline
            key={path.path_id}
            data-testid={`map-path-${path.path_id}`}
            points={path.points.map((point) => point.join(",")).join(" ")}
            fill="none"
            stroke={
              path.from_location_id === currentLocationId ||
              path.to_location_id === currentLocationId
                ? "#0f766e"
                : "#a8a29e"
            }
            strokeWidth="9"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="13 10"
            opacity="0.8"
          />
        ))}
        {map.location_nodes.map((node) => {
          const location = locationsById.get(node.location_id);
          if (!location) return null;
          const status = statusForLocation(location);
          return (
            <MapLocationMarker
              key={node.location_id}
              node={node}
              compact={illustrated}
              name={locationName(location)}
                hours={openingHours?.[node.location_id]?.hours}
              status={status}
              statusLabel={statusLabelForLocation(status)}
              selected={selectedLocationId === node.location_id}
              onSelect={() => onSelectLocation(node.location_id)}
              imageUrl={slotUrl(`locations.${node.location_id}.map_thumbnail`)}
              onDragStart={editable ? (event) => {
                event.preventDefault();
                onSelectLocation(node.location_id);
                draggingLocationId.current = node.location_id;
                event.currentTarget.ownerSVGElement?.setPointerCapture(event.pointerId);
              } : undefined}
            />
          );
        })}
        {actors.map((actor) => {
          const colocatedActors = actors.filter((item) => item.location_id === actor.location_id);
          const index = colocatedActors.findIndex(item => item.actor_id===actor.actor_id);
          const node = map.location_nodes.find(n=>n.location_id===actor.location_id);
          const displayedActor = illustrated && node ? {...actor,x:node.x+(index%4-(Math.min(colocatedActors.length,4)-1)/2)*31,y:node.y+87+Math.floor(index/4)*32} : actor;
          return (
            <MapActorMarker
              key={actor.actor_id}
              actor={displayedActor}
              selected={selectedActorId === actor.actor_id}
              onSelect={() => onSelectActor(actor)}
              imageUrl={slotUrl(`actors.${actor.actor_id}.map_thumbnail`)}
              labelIndex={colocatedActors.findIndex((item) => item.actor_id === actor.actor_id)}
              labelCount={colocatedActors.length}
            />
          );
        })}
      </svg>
      {illustrated ? <div data-testid="map-location-list" className="grid shrink-0 grid-cols-2 gap-2 border-t border-stone-200 bg-white p-3 sm:hidden">{locations.map(location=><button key={location.location_id} type="button" onClick={()=>onSelectLocation(location.location_id)} className="focus-ring min-h-11 rounded-lg border border-stone-200 px-2 text-left text-xs font-bold text-stone-800"><span className="block">{locationName(location)}</span><span className="text-[10px] font-normal text-teal-800">{statusLabelForLocation(statusForLocation(location))}</span></button>)}</div> : null}
      <div className="pointer-events-none absolute bottom-3 left-3 hidden max-w-[calc(100%-1.5rem)] flex-wrap gap-1.5 rounded-lg border border-white/70 bg-stone-950/75 px-2.5 py-2 text-[10px] font-bold text-white shadow sm:flex">
        <span>◎ {language === "zh-CN" ? "当前位置" : "Current"}</span>
        <span>→ {language === "zh-CN" ? "可前往" : "Reachable"}</span>
        <span>× {language === "zh-CN" ? "关闭" : "Closed"}</span>
        <span>· {language === "zh-CN" ? "不可达" : "Unavailable"}</span>
      </div>
    </div>
  );
}
