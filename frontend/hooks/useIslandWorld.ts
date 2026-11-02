"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getLocations,
  getSessionWorld,
  type WorldLocation,
  type WorldSnapshot,
} from "@/lib/api";
import type { Language } from "@/lib/i18n";

type Options = {
  language: Language;
  loadError: string;
  syncWarning: string;
  initialSessionId?: number | null;
};

export function useIslandWorld({ language, loadError, syncWarning: syncWarningText, initialSessionId = null }: Options) {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessionResolved, setSessionResolved] = useState(false);
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [locations, setLocations] = useState<WorldLocation[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [syncWarning, setSyncWarning] = useState("");
  const requestInFlight = useRef(false);
  const appliedRevision = useRef(-1);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = Number(params.get("session_id"));
    const fromStorage = Number(localStorage.getItem("session_id"));
    const activeSessionId = initialSessionId ?? (Number.isInteger(fromUrl) && fromUrl > 0
      ? fromUrl
      : Number.isInteger(fromStorage) && fromStorage > 0
        ? fromStorage
        : null);
    const timer = window.setTimeout(() => {
      if (activeSessionId) {
        if (!initialSessionId) localStorage.setItem("session_id", String(activeSessionId));
        setSessionId(activeSessionId);
      }
      setSessionResolved(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [initialSessionId]);

  const applyWorldSnapshot = useCallback((nextSnapshot: WorldSnapshot) => {
    const nextRevision = nextSnapshot.revision ?? 0;
    if (nextRevision < appliedRevision.current) return false;
    appliedRevision.current = nextRevision;
    setSnapshot(nextSnapshot);
    if (nextSnapshot.locations?.length) setLocations(nextSnapshot.locations);
    setSyncWarning("");
    return true;
  }, []);

  const loadWorld = useCallback(async (activeSessionId: number, quiet = false) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    if (!quiet) {
      setIsLoading(true);
      setError("");
    }
    try {
      const [nextSnapshot, locationCatalog] = await Promise.all([
        getSessionWorld(activeSessionId, language),
        getLocations().catch(() => [] as WorldLocation[]),
      ]);
      const applied = applyWorldSnapshot(nextSnapshot);
      if (applied && !nextSnapshot.locations?.length) setLocations(locationCatalog);
    } catch {
      if (quiet && appliedRevision.current >= 0) setSyncWarning(syncWarningText);
      else setError(loadError);
    } finally {
      requestInFlight.current = false;
      setIsLoading(false);
    }
  }, [applyWorldSnapshot, language, loadError, syncWarningText]);

  useEffect(() => {
    if (!sessionId) return;
    const timer = window.setTimeout(() => void loadWorld(sessionId), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorld, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const poll = () => {
      if (document.visibilityState === "visible") void loadWorld(sessionId, true);
    };
    const intervalId = window.setInterval(poll, 4_000);
    document.addEventListener("visibilitychange", poll);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [loadWorld, sessionId]);

  return {
    sessionId,
    sessionResolved,
    snapshot,
    locations,
    isLoading,
    error,
    syncWarning,
    requestInFlight,
    appliedRevision,
    setError,
    applyWorldSnapshot,
    loadWorld,
  };
}
