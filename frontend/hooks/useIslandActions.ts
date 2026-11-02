"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  performWorldAction,
  type WorldActionInput,
  type WorldActionType,
  type WorldSnapshot,
} from "@/lib/api";
import type { Language } from "@/lib/i18n";

type ActionOptions = Omit<WorldActionInput, "action_type" | "idempotency_key" | "language">;

export function useIslandActions({
  sessionId,
  language,
  onSnapshot,
  onRefresh,
  onStart,
  onSuccess,
  onError,
}: {
  sessionId: number | null;
  language: Language;
  onSnapshot: (snapshot: WorldSnapshot) => void;
  onRefresh: () => Promise<void> | void;
  onStart: () => void;
  onSuccess: (result: Awaited<ReturnType<typeof performWorldAction>>) => void;
  onError: (message?:string) => void;
}) {
  const running=useRef(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [pendingAction,setPendingAction]=useState<{signature:string;key:string}|null>(null);
  useEffect(()=>{const timer=setTimeout(()=>{
    try{const storageKey=`island-pending:${sessionId}`;
      const saved=JSON.parse(localStorage.getItem(storageKey)??sessionStorage.getItem(storageKey)??'null');
      if(saved?.signature&&saved?.key){localStorage.setItem(storageKey,JSON.stringify(saved));setPendingAction(saved);}
      else setPendingAction(null);
      sessionStorage.removeItem(storageKey);
    }catch{}
  },0);return()=>clearTimeout(timer);},[sessionId]);

  const runAction = useCallback(async (actionType: WorldActionType, options: ActionOptions = {}, requestLanguage:Language=language) => {
    if (!sessionId || busyAction || running.current) return false;
    running.current=true;
    const signature=JSON.stringify({actionType,options,language:requestLanguage});
    const storageKey=`island-pending:${sessionId}`;
    let key=createIdempotencyKey();
    try {
      const old=JSON.parse(localStorage.getItem(storageKey)??sessionStorage.getItem(storageKey)??'null');
      if(old?.signature&&old.signature!==signature){setPendingAction(old);running.current=false;onError('请先点击“重试上次岛屿操作”，核对上次操作的保存结果。');return false;}
      if(old?.signature===signature)key=old.key;
      localStorage.setItem(storageKey,JSON.stringify({signature,key}));
      sessionStorage.removeItem(storageKey);
    } catch {running.current=false;onError();return false;}
    setBusyAction(`${actionType}:${options.target_location_id ?? options.target_agent_id ?? options.target_object_id ?? ""}`);
    onStart();
    try {
      const result = await performWorldAction(sessionId, {
        ...options,
        action_type: actionType,
        idempotency_key: key,
        language:requestLanguage,
      });
      if (isWorldSnapshot(result.world)) onSnapshot(result.world);
      try {localStorage.removeItem(storageKey);sessionStorage.removeItem(storageKey);} catch {}
      setPendingAction(null);
      await Promise.resolve(onRefresh()).catch(()=>undefined);
      onSuccess(result);
      return true;
    } catch (error) {
      if(error instanceof ApiError && (error.code==='action_not_applied'||error.status>=400 && error.status<500 && ![408,429].includes(error.status))){
        try{localStorage.removeItem(storageKey);sessionStorage.removeItem(storageKey);}catch{} setPendingAction(null);
      }else setPendingAction({signature,key});
      onError(error instanceof ApiError && error.code==='action_not_applied'?'这次操作未保存，已解除等待。你可以重新操作或继续探索。':undefined);
      return false;
    } finally {
      running.current=false;
      setBusyAction(null);
    }
  }, [busyAction, language, onError, onRefresh, onSnapshot, onStart, onSuccess, sessionId]);

  const retryPending=useCallback(async()=>{
    if(!pendingAction)return false;
    try{const old=JSON.parse(pendingAction.signature);return await runAction(old.actionType,old.options,old.language);}catch{onError();return false;}
  },[pendingAction,runAction,onError]);
  return { busyAction, setBusyAction, runAction, pendingAction, retryPending };
}

function createIdempotencyKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isWorldSnapshot(value: unknown): value is WorldSnapshot {
  return Boolean(value && typeof value === "object" && "world" in value && "session" in value);
}
