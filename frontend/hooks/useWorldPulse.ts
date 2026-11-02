"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { sendWorldPulse, type WorldSnapshot } from "@/lib/api";
import type { Language } from "@/lib/i18n";

type PendingPulse = {
  idempotencyKey: string;
  expectedRevision: number;
};

type Options = {
  sessionId: number | null;
  language: Language;
  revision: number | undefined;
  intervalMs: number | undefined;
  canPulse: boolean;
  sessionActive: boolean;
  blocked: boolean;
  requestInFlightRef: MutableRefObject<boolean>;
  onSnapshot: (snapshot: WorldSnapshot) => void;
};

function pulseKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `foreground-pulse-${crypto.randomUUID()}`;
  }
  return `foreground-pulse-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Send one bounded server-owned pulse at a time while this page is eligible.
 * A network failure retains the key and revision so retry cannot advance twice.
 */
export function useWorldPulse({
  sessionId,
  language,
  revision,
  intervalMs,
  canPulse,
  sessionActive,
  blocked,
  requestInFlightRef,
  onSnapshot,
}: Options) {
  const [isPulsing, setIsPulsing] = useState(false);
  const pendingPulse = useRef<PendingPulse | null>(null);
  const revisionRef = useRef(revision);
  const mounted = useRef(true);

  useEffect(() => {
    revisionRef.current = revision;
  }, [revision]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const requestPulse = useCallback(async () => {
    if (
      !sessionId ||
      !sessionActive ||
      !canPulse ||
      blocked ||
      requestInFlightRef.current ||
      document.visibilityState !== "visible" ||
      !navigator.onLine
    ) {
      return;
    }
    const currentRevision = revisionRef.current;
    if (currentRevision === undefined) return;

    const pending = pendingPulse.current ?? {
      idempotencyKey: pulseKey(),
      expectedRevision: currentRevision,
    };
    pendingPulse.current = pending;
    requestInFlightRef.current = true;
    if (mounted.current) setIsPulsing(true);
    try {
      const result = await sendWorldPulse(sessionId, {
        idempotency_key: pending.idempotencyKey,
        expected_revision: pending.expectedRevision,
        source: "foreground_timer",
        language,
      });
      pendingPulse.current = null;
      if (mounted.current) onSnapshot(result.world);
    } catch {
      // Keep the pending key for a safe idempotent retry on the next eligible tick.
    } finally {
      requestInFlightRef.current = false;
      if (mounted.current) setIsPulsing(false);
    }
  }, [blocked, canPulse, language, onSnapshot, requestInFlightRef, sessionActive, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const delay = Math.max(8_000, intervalMs ?? 10_000);
    let cancelled = false;
    let timeoutId: number | null = null;
    const scheduleNext = () => {
      if (cancelled) return;
      timeoutId = window.setTimeout(async () => {
        await requestPulse();
        scheduleNext();
      }, delay);
    };
    scheduleNext();
    const resumeIfEligible = () => {
      if (document.visibilityState === "visible" && navigator.onLine) {
        void requestPulse();
      }
    };
    document.addEventListener("visibilitychange", resumeIfEligible);
    window.addEventListener("online", resumeIfEligible);
    return () => {
      cancelled = true;
      if (timeoutId != null) window.clearTimeout(timeoutId);
      document.removeEventListener("visibilitychange", resumeIfEligible);
      window.removeEventListener("online", resumeIfEligible);
    };
  }, [intervalMs, requestPulse, sessionId]);

  return { isPulsing };
}
