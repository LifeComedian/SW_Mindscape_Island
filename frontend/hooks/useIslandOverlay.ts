"use client";

import { useState } from "react";

export function useIslandOverlay() {
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [selectedMapActorId, setSelectedMapActorId] = useState<string | null>(null);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [worldView, setWorldView] = useState<"map" | "scene">("map");

  const clearMapSelection = () => {
    setSelectedAgentId(null);
    setSelectedMapActorId(null);
    setSelectedObjectId(null);
  };

  return {
    selectedAgentId,
    setSelectedAgentId,
    selectedLocationId,
    setSelectedLocationId,
    selectedMapActorId,
    setSelectedMapActorId,
    selectedObjectId,
    setSelectedObjectId,
    worldView,
    setWorldView,
    clearMapSelection,
  };
}
