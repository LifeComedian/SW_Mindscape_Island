"use client";

import Link from "next/link";
import {postV5} from "@/lib/holiday-v5";
import {HolidayIllustration} from "./HolidayIllustration";
import {SceneDialog} from "./SceneDialog";
import {V5Companion} from "./V5Companion";
import {HolidayActivities} from "./HolidayActivities";
import { useRouter } from "next/navigation";
import {
  Anchor,
  CalendarDays,
  Eye,
  LoaderCircle,
  X,
} from "lucide-react";
import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ApiError,
  changeInteractionFocus,
  finishSession as finishSessionApi,
  getWorldPhone,
  visitHolidayPhone,
  getDayReview,
  type DayReview,
  respondToWorldInteractionPrompt,
  sendWorldConversation,
  setWorldSimulationMode,
  startWorldConversation,
  type WorldActionType,
  type WorldConversation,
  type WorldEvent,
  type WorldEventAction,
  type WorldInteractionPoint,
  type WorldLocation,
  type WorldResident,
  type WorldScenario,
  type WorldScenarioOption,
  type WorldSnapshot,
} from "@/lib/api";
import { useWorldPulse } from "@/hooks/useWorldPulse";
import { useIslandWorld } from "@/hooks/useIslandWorld";
import { useIslandActions } from "@/hooks/useIslandActions";
import { useIslandOverlay } from "@/hooks/useIslandOverlay";
import { type Language, useLanguage } from "@/lib/i18n";
import { IslandMap } from "@/components/island/IslandMap";
import {
  interactionPointDescription,
  interactionPointName,
  LocationScene,
} from "@/components/island/LocationScene";
import { MapInfoPanel } from "@/components/island/MapInfoPanel";
import type { MapLocationStatus } from "@/components/island/MapLocationMarker";
import { GameHud } from "@/components/game/GameHud";
import { WorldStage } from "@/components/game/WorldStage";
import { GameMenuDrawer } from "@/components/game/GameMenuDrawer";
import { DialogueOverlay } from "@/components/game/DialogueOverlay";
import { InteractionPromptOverlay } from "@/components/game/InteractionPromptOverlay";
import { NarrativeChoiceOverlay } from "@/components/game/NarrativeChoiceOverlay";
import { PassTimeDialog } from "@/components/game/PassTimeDialog";
import { SocialPhoneOverlay } from "@/components/social/SocialPhoneOverlay";
import { ModularStagePanel } from "@/components/game/ModularStagePanel";
import { ObjectExplorer } from "@/components/game/ObjectExplorer";
import { ObjectActions } from "@/components/game/ObjectActions";
import { PlayerRecords } from "@/components/game/PlayerRecords";
import { DayReviewDialog } from "@/components/game/DayReviewDialog";
import {HolidayNight} from "./HolidayNight";
import {DayBoundary} from "./DayBoundary";
import { ObjectResult } from "@/components/game/ObjectResult";

type IslandGameShellProps = {
  initialSessionId?: number | null;
  studyMode?: boolean;
};

export function IslandGameShell({ initialSessionId = null, studyMode = false }: IslandGameShellProps) {
  const router = useRouter();
  const { language, setLanguage, t } = useLanguage();
  const {
    setSelectedAgentId,
    selectedLocationId,
    setSelectedLocationId,
    selectedMapActorId,
    setSelectedMapActorId,
    selectedObjectId,
    setSelectedObjectId,
    worldView,
    setWorldView,
  } = useIslandOverlay();
  const [message, setMessage] = useState("");
  const [customResponse, setCustomResponse] = useState("");
  const [eventResponse, setEventResponse] = useState("");
  const [notice, setNotice] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [saveMessage,setSaveMessage]=useState('');
  const saving=useRef(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [activityActive, setActivityActive] = useState(false);
  const [dayTransition, setDayTransition] = useState<number | null>(null);
  const [taskCount, setTaskCount] = useState(0);
  const [logOpen, setLogOpen] = useState(false);
  const [dayReview, setDayReview] = useState<DayReview | null>(null);
  const [passTimeOpen, setPassTimeOpen] = useState(false);
  const [passTimeMinutes, setPassTimeMinutes] = useState(15);
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [phoneFilter, setPhoneFilter] = useState<"all" | "invitations">("all");
  const [unreadSocialCount, setUnreadSocialCount] = useState(0);
  const [shortChatOffer, setShortChatOffer] = useState<WorldResident | null>(null);
  const conversationStartedAt = useRef(0);
  const scenarioShownAt = useRef(0);
  const eventShownAt = useRef(0);
  const interactionPromptShownAt = useRef(0);
  const {
    sessionId,
    sessionResolved,
    snapshot,
    locations,
    isLoading,
    error,
    syncWarning,
    requestInFlight: worldRequestInFlight,
    setError,
    applyWorldSnapshot,
    loadWorld,
  } = useIslandWorld({
    language,
    loadError: t("island.errorLoad"),
    syncWarning: language === "zh-CN"
      ? "自动同步暂时失败，正在保留上一次地图状态。"
      : "Live sync is temporarily unavailable; the last map state is retained.",
    initialSessionId,
  });
  useEffect(() => {
    if (snapshot?.world.world_version?.startsWith("chaoxi-holiday") && language !== "zh-CN") setLanguage("zh-CN");
  }, [snapshot?.world.world_version, language, setLanguage]);

  const { busyAction, setBusyAction, runAction, pendingAction, retryPending } = useIslandActions({
    sessionId,
    language,
    onSnapshot: applyWorldSnapshot,
    onRefresh: () => sessionId ? loadWorld(sessionId, true) : undefined,
    onStart: () => {
      setError("");
      setNotice("");
    },
    onSuccess: (result) => {
      const message = result.flow_messages?.at(-1);
      setNotice(message?.[language] ?? message?.en ?? message?.["zh-CN"] ?? t("island.actionSaved"));
    },
    onError: (message) => setError(message??t("island.errorAction")),
  });

  async function saveProgress(){
    if(!sessionId||busyAction||saving.current)return;
    if(pendingAction){setSaveMessage('请先重试上次岛屿操作，确认结果后再保存。');return;}
    saving.current=true;setBusyAction('save');setSaveMessage('正在保存…');
    try{
      const result=await postV5<{day:number;minute:number;saved_at:string}>(sessionId,'save',{idempotency_key:crypto.randomUUID()});
      const time=`${Math.floor(result.minute/60).toString().padStart(2,'0')}:${(result.minute%60).toString().padStart(2,'0')}`;
      setSaveMessage(`已保存至第 ${result.day} 天 ${time}。现在可以关闭页面，下次用同一浏览器打开原入口继续。`);
    }catch{setSaveMessage('暂时无法确认保存，请保持页面并重试。');}
    finally{saving.current=false;setBusyAction(null);}
  }

  const currentLocationId =
    snapshot?.world.current_location_id ??
    snapshot?.world.participant_location_id ??
    snapshot?.current_location?.location_id ??
    "";
  const currentLocation =
    snapshot?.current_location ??
    locations.find((location) => location.location_id === currentLocationId) ??
    null;
  const residents = snapshot?.visible_residents !== undefined
    ? snapshot.visible_residents
    : (snapshot?.residents ?? []).filter(
        (resident) =>
          resident.is_visible !== false &&
          resident.visible !== false &&
          (!resident.current_location_id ||
            resident.current_location_id === currentLocationId),
      );
  const [v5Portrait,setV5Portrait] = useState<string>();
  const participantPortraitUrl = v5Portrait ??
    snapshot?.visuals?.slots["actors.participant.dialogue_portrait"]?.asset?.url;
  const selectedLocation =
    locations.find((location) => location.location_id === selectedLocationId) ?? null;
  const selectedMapActor =
    snapshot?.actors?.find((actor) => actor.actor_id === selectedMapActorId) ?? null;
  const sceneLayout =
    snapshot?.map?.scene_layouts.find(
      (layout) => layout.location_id === currentLocationId,
    ) ?? null;
  const currentInteractionPoints =
    snapshot?.interaction_points ?? currentLocation?.interaction_points ?? [];
  const selectedInteractionPoint =
    currentInteractionPoints.find((point) => point.object_id === selectedObjectId) ?? null;
  const sceneActors = (snapshot?.actors ?? []).filter(
    (actor) => actor.location_id === currentLocationId,
  );
  const adjacentThumbnailUrls = currentLocation?.connected_location_ids?.flatMap((locationId) => {
    const url = snapshot?.visuals?.slots[`locations.${locationId}.map_thumbnail`]?.asset?.url;
    return url ? [url] : [];
  }) ?? [];
  const selectedLocationOccupants = selectedLocation
    ? (snapshot?.actors ?? [])
        .filter((actor) => actor.location_id === selectedLocation.location_id)
        .map((actor) => actor.name)
    : [];
  const scenario = snapshot?.active_scenario ?? null;
  const activeEvent = snapshot?.active_event ?? null;
  const activeGoal = activeWorldGoal(snapshot?.world);
  const eventNpcId = eventResponseNpcId(activeEvent);
  const eventNpcResident = eventNpcId == null
    ? null
    : (snapshot?.residents ?? []).find((resident) => resident.agent_id === eventNpcId) ?? null;
  const eventNpcPortraitUrl = eventNpcResident
    ? snapshot?.visuals?.slots[`actors.resident:${eventNpcResident.agent_id}.dialogue_portrait`]?.asset?.url
    : undefined;
  const pendingInteractionPrompt = snapshot?.pending_interaction_prompt ?? null;
  const pendingInteractionPromptId = pendingInteractionPrompt?.prompt_id ?? null;
  const promptInitiator = pendingInteractionPrompt
    ? (snapshot?.residents ?? []).find(
        (resident) => resident.agent_id === pendingInteractionPrompt.initiator_agent_id,
      ) ?? null
    : null;
  const scenarioKind = getScenarioKind(scenario);
  const seats = scenarioKind === "unsupported"
    ? []
    : getScenarioSeats(
        scenario,
        snapshot?.interaction_points ?? currentLocation?.interaction_points,
      );
  const selectedSeatId =
    getSelectedSeatId(scenario) ||
    [...(snapshot?.recent_actions ?? [])]
      .reverse()
      .find((action) =>
        ["seat_select", "seat_change"].includes(action.action_type),
      )?.target_object_id ||
    "";
  const activeParticipantConversation = useMemo(
    () => (snapshot?.conversations ?? []).find(
      (item): item is WorldConversation =>
        "turns" in item &&
        item.status === "active" &&
        item.conversation_kind !== "resident_resident",
    ) ?? null,
    [snapshot?.conversations],
  );
  const activeConversationAgentId = activeParticipantConversation
    ? conversationResidentId(activeParticipantConversation)
    : null;
  const conversationFocusToken = activeParticipantConversation?.metadata?.focus_token as string | undefined;
  const focusedConversationId = activeParticipantConversation ? Number(activeParticipantConversation.conversation_id) : null;
  useEffect(() => {
    if (!sessionId || !conversationFocusToken || !focusedConversationId) return;
    const renew = () => void changeInteractionFocus(sessionId, {
      operation: "renew", conversation_id: focusedConversationId, focus_token: conversationFocusToken,
      idempotency_key: crypto.randomUUID(),
    }).catch(() => void loadWorld(sessionId, true));
    const timer = window.setInterval(renew, 60_000);
    return () => window.clearInterval(timer);
  }, [sessionId, conversationFocusToken, focusedConversationId, loadWorld]);
  const dialogueAgentId = activeConversationAgentId;
  const dialogueResident = dialogueAgentId == null
    ? null
    : (snapshot?.residents ?? []).find(
        (resident) => resident.agent_id === dialogueAgentId,
      ) ?? {
        agent_id: dialogueAgentId,
        name: `${language === "zh-CN" ? "居民" : "Resident"} ${dialogueAgentId}`,
      };
  const dialogueTurns = activeParticipantConversation?.turns ?? [];
  const dialogueResidentPortraitUrl = dialogueResident
    ? snapshot?.visuals?.slots[`actors.resident:${dialogueResident.agent_id}.dialogue_portrait`]?.asset?.url
    : undefined;
  const overlayKind = scenario
    ? "scenario"
    : activeEvent
      ? "event"
      : pendingInteractionPrompt
        ? "prompt"
        : dialogueResident
          ? "dialogue"
          : null;

  const simulationMode = snapshot?.simulation?.mode ?? "running";
  const { isPulsing } = useWorldPulse({
    sessionId,
    language,
    revision: snapshot?.revision,
    intervalMs: snapshot?.simulation?.pulse_interval_hint_ms,
    canPulse: snapshot?.simulation?.can_pulse === true,
    sessionActive: snapshot?.session.status === "active",
    blocked: Boolean(
      busyAction || pendingAction || scenario || activeEvent || activeParticipantConversation || phoneOpen || tasksOpen || menuOpen || logOpen || selectedObjectId || activityActive || dayTransition || dayReview,
    ),
    requestInFlightRef: worldRequestInFlight,
    onSnapshot: applyWorldSnapshot,
  });

  useEffect(() => {
    scenarioShownAt.current = Date.now();
    const resetTimer = window.setTimeout(() => setCustomResponse(""), 0);
    return () => window.clearTimeout(resetTimer);
  }, [scenario?.scenario_instance_id, scenario?.stage]);

  useEffect(() => {
    eventShownAt.current = Date.now();
    const resetTimer = window.setTimeout(() => setEventResponse(""), 0);
    return () => window.clearTimeout(resetTimer);
  }, [activeEvent?.event_instance_id, activeEvent?.metadata?.stage_id]);

  useEffect(() => {
    if (pendingInteractionPromptId) interactionPromptShownAt.current = Date.now();
  }, [pendingInteractionPromptId]);

  useEffect(() => {
    if (!overlayKind) return;
    const closeTimer = window.setTimeout(() => {
      setMenuOpen(false);
      setPassTimeOpen(false);
    }, 0);
    return () => window.clearTimeout(closeTimer);
  }, [overlayKind]);

  useEffect(() => {
    if (
      overlayKind ||
      passTimeOpen ||
      !(selectedLocationId || selectedMapActorId || selectedObjectId)
    ) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedLocationId(null);
      setSelectedMapActorId(null);
      setSelectedAgentId(null);
      setSelectedObjectId(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [
    overlayKind,
    passTimeOpen,
    selectedLocationId,
    selectedMapActorId,
    selectedObjectId,
    setSelectedAgentId,
    setSelectedLocationId,
    setSelectedMapActorId,
    setSelectedObjectId,
  ]);

  useEffect(() => {
    if (!sessionId || snapshot?.world.can_finish || snapshot?.session.status !== "active") return;
    let cancelled = false;
    void getWorldPhone(sessionId)
      .then((feed) => {
        if (!cancelled) {
          setUnreadSocialCount(
            phoneOpen ? 0 : feed.posts.filter(item => item.post_id > Number(sessionStorage.getItem(`phone-seen:${sessionId}`) ?? 0) && (item.post_type !== "invitation" || ["proposed","accepted","in_progress"].includes(item.status))).length,
          );
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [
    sessionId,
    snapshot?.world.current_day,
    snapshot?.world.current_time_minutes,
    snapshot?.world.can_finish,
    snapshot?.session.status,
    phoneOpen,
  ]);

  const actionAllowed = useCallback(
    (actionType: WorldActionType, targetId?: string | number) => {
      if (!snapshot) {
        return false;
      }
      if (snapshot?.session.status && snapshot.session.status !== "active") {
        return false;
      }
      const available = snapshot.available_actions ?? [];
      if (available.length === 0) return false;
      return available.some((action) => {
        if (typeof action === "string") return action === actionType;
        if (action.action_type !== actionType || action.enabled === false) return false;
        if (targetId === undefined) return true;
        const descriptorTarget =
          action.target_id ??
          action.target_location_id ??
          action.target_agent_id ??
          action.target_object_id;
        return descriptorTarget == null || String(descriptorTarget) === String(targetId);
      });
    },
    [snapshot],
  );

  const locationStatus = useCallback(
    (location: WorldLocation): MapLocationStatus => {
      if (location.location_id === currentLocationId) return "current";
      if(snapshot?.world.location_hours?.[location.location_id]?.open===false)return "closed";
      if (location.is_open === false) return "closed";
      const hasRoute = Boolean(
        shortestLocationPath(locations, currentLocationId, location.location_id),
      );
      return hasRoute && actionAllowed("move", location.location_id)
        ? "reachable"
        : "unreachable";
    },
    [actionAllowed, currentLocationId, locations,snapshot?.world.location_hours],
  );

  const locationStatusLabel = useCallback(
    (status: MapLocationStatus) => {
      const labels: Record<MapLocationStatus, string> = language === "zh-CN"
        ? { current: "当前位置", reachable: "可以前往", closed: "暂未开放", unreachable: "目前不可达" }
        : { current: "Current", reachable: "Reachable", closed: "Closed", unreachable: "Unavailable" };
      return labels[status];
    },
    [language],
  );
  const selectedLocationRelation = selectedLocation
    ? describeLocationRelation(
        locations,
        currentLocationId,
        selectedLocation.location_id,
        locationStatus(selectedLocation),
        snapshot?.world.participant_move_minutes_per_edge ?? 15,
        language,
      )
    : undefined;

  async function moveTo(locationId: string) {
    setSelectedAgentId(null);
    setSelectedMapActorId(null);
    setSelectedObjectId(null);
    setSelectedLocationId(locationId);
    const moved = await runAction("move", { target_location_id: locationId });
    if (moved) setWorldView("scene");
  }

  async function approachResident(resident: WorldResident, durationMinutes: 5 | 10 = 10) {
    if (!sessionId || busyAction) return;
    setSelectedAgentId(resident.agent_id);
    conversationStartedAt.current = Date.now();
    setBusyAction("conversation_start");
    setError("");
    setNotice("");
    try {
      const result = await startWorldConversation(sessionId, {
        agent_id: resident.agent_id,
        duration_minutes: durationMinutes,
        idempotency_key: createIdempotencyKey(),
        language,
      });
      if (isWorldSnapshot(result.world)) applyWorldSnapshot(result.world);
      setShortChatOffer(null);
      setMenuOpen(false);
      if (sceneLayout) setWorldView("scene");
    } catch (caught) {
      setSelectedAgentId(null);
      setError(conversationErrorMessage(caught, resident.name, language));
      if (durationMinutes === 10 && caught instanceof ApiError && (caught.message.includes("Conversation time conflicts") || caught.message.includes("not enough game time"))) setShortChatOffer(resident);
      await loadWorld(sessionId, true);
    } finally {
      setBusyAction(null);
    }
  }

  function inspectInteractionPoint(point: WorldInteractionPoint, hotspotId?: string, logCode?: string) {
    setSelectedObjectId(point.object_id);
    setSelectedLocationId(null);
    setSelectedMapActorId(null);
    void runAction("observe", {
      target_object_id: point.object_id,
      ...(hotspotId ? { metadata: { source: "image_hotspot", hotspot_id: hotspotId, log_code: logCode ?? "hotspot_select" } } : {}),
    });
  }

  function closeContextCard() {
    setSelectedLocationId(null);
    setSelectedMapActorId(null);
    setSelectedAgentId(null);
    setSelectedObjectId(null);
  }

  function openPassTime() {
    if (busyAction || overlayKind || !actionAllowed("wait")) return;
    setMenuOpen(false);
    setPassTimeOpen(true);
  }

  async function submitPassTime() {
    const waited = await runAction("wait", {
      metadata: { minutes: passTimeMinutes },
    });
    if (waited) setPassTimeOpen(false);
  }

  function openSocialPhone() {
    closeContextCard();
    setTasksOpen(false);
    setMenuOpen(false);
    setPhoneFilter("all");
    setPhoneOpen(true);
    setUnreadSocialCount(0);
    if (sessionId) void visitHolidayPhone(sessionId).catch(() => undefined);
  }

  async function endCurrentDay(confirmed = false) {
    if (busyAction) return;
    if (snapshot?.session.status !== "active") {
      setMenuOpen(false);
      setNotice(language === "zh-CN" ? "当前会话已结束，不能再推进日期。" : "This session has ended, so the day cannot advance.");
      return;
    }
    const totalDays = snapshot?.world.total_days ?? 1;
    const currentDay = snapshot?.world.current_day ?? 1;
    if (currentDay >= totalDays && snapshot?.world.can_finish) {
      setMenuOpen(false);
      setNotice(language === "zh-CN" ? "这已经是最后一个可游玩的日期。" : "This is already the final playable day.");
      return;
    }
    const participantHome = locations.find((location) => location.location_id === (snapshot?.world.rest_location_id ?? "participant_home"));
    if (!participantHome) {
      setMenuOpen(false);
      setNotice(language === "zh-CN" ? "当前世界没有配置可用于结束一天的住处。" : "This world has no participant home configured for ending a day.");
      return;
    }
    if (!confirmed && sessionId && snapshot?.world.rest_location_id !== "participant_home") {
      setBusyAction("day-review");
      try {
        setDayReview(await getDayReview(sessionId, language));
        setMenuOpen(false);
      } catch {setError(language === "zh-CN" ? "今日记录暂时无法读取，请稍后重试。" : "Today's records could not be loaded. Please retry.");}
      finally {setBusyAction(null);}
      return;
    }
    if (currentLocationId !== participantHome.location_id) {
      setMenuOpen(false);
      setWorldView("map");
      setSelectedLocationId(participantHome.location_id);
      const returnedHome = await runAction("move", {
        target_location_id: participantHome.location_id,
      });
      if (!returnedHome) return;
    }
    const ended = await runAction("end_day", {metadata: {confirm_leave_arrangements: confirmed, reviewed_plan_ids: dayReview?.pending_arrangements.map(p => p.plan_id) ?? []}});
    if (ended) {
      setMenuOpen(false);
      setDayReview(null);
      if(snapshot?.world.world_version==="chaoxi-holiday-v6"){
        setNotice("");return;
      }
      if (currentDay < totalDays) setDayTransition(currentDay + 1);
      setNotice(currentDay >= totalDays ? (language === "zh-CN" ? "七日假期已结束，准备好后可以离岛。" : "Your stay is complete. Depart when ready.") : (language === "zh-CN" ? "新的一天开始了。" : "A new day has begun."));
    }
  }

  async function submitConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!sessionId || !dialogueResident || !trimmed || busyAction) return;
    setBusyAction("conversation");
    setError("");
    setNotice("");
    try {
      const result = await sendWorldConversation(sessionId, {
        ...(activeParticipantConversation
          ? { conversation_id: Number(activeParticipantConversation.conversation_id), focus_token: conversationFocusToken }
          : {}),
        agent_id: dialogueResident.agent_id,
        message: trimmed,
        idempotency_key: createIdempotencyKey(),
        language,
        response_latency_ms: elapsed(conversationStartedAt.current),
      });
      if (isWorldSnapshot(result.world)) applyWorldSnapshot(result.world);
      setMessage("");
      window.setTimeout(() => {
        conversationStartedAt.current = Date.now();
      }, 0);
      await loadWorld(sessionId, true);
      setNotice(t("island.conversationSaved"));
    } catch (caught) {
      setError(conversationErrorMessage(caught, dialogueResident.name, language));
      await loadWorld(sessionId, true);
    } finally {
      setBusyAction(null);
    }
  }

  async function endResidentConversation() {
    if (!dialogueResident || !activeParticipantConversation || busyAction) return;
    const ended = await runAction("end_conversation", {
      target_agent_id: dialogueResident.agent_id,
      metadata: { focus_token: activeParticipantConversation.metadata?.focus_token },
    });
    if (!ended) return;
    setSelectedAgentId(null);
    setMessage("");
  }

  async function respondToInteractionPrompt(
    response: "accept" | "later" | "decline",
  ) {
    if (!sessionId || !pendingInteractionPrompt || busyAction) return;
    setBusyAction(`interaction-prompt:${response}`);
    setError("");
    setNotice("");
    try {
      const result = await respondToWorldInteractionPrompt(
        sessionId,
        pendingInteractionPrompt.prompt_id,
        {
          response,
          idempotency_key: createIdempotencyKey(),
          language,
          response_latency_ms: elapsed(interactionPromptShownAt.current),
        },
      );
      applyWorldSnapshot(result.world);
      if (response === "accept") {
        setSelectedAgentId(pendingInteractionPrompt.initiator_agent_id);
        conversationStartedAt.current = Date.now();
        setMenuOpen(false);
        if (sceneLayout) setWorldView("scene");
      }
      setNotice(
        language === "zh-CN"
          ? response === "accept"
            ? "已接受邀请，对方先开始了交谈。"
            : response === "later"
              ? "已告诉对方稍后再聊。"
              : "已婉拒这次邀请。"
          : response === "accept"
            ? "Invitation accepted; the resident started the conversation."
            : response === "later"
              ? "You asked to talk later."
              : "You declined the invitation.",
      );
    } catch {
      setError(
        language === "zh-CN"
          ? "这条交流邀请已不可用，请刷新后重试。"
          : "This invitation is no longer available. Refresh and try again.",
      );
      await loadWorld(sessionId, true);
    } finally {
      setBusyAction(null);
    }
  }

  async function finishIslandSession() {
    if (!sessionId || busyAction || snapshot?.session.status !== "active") return;
    if (snapshot.world.can_finish === false) {
      setMenuOpen(false);
      setNotice(
        snapshot.world.departure_prompt?.[language]
          ?? (language === "zh-CN" ? "请完成最后一天后再离岛。" : "Complete the final day before leaving the island."),
      );
      return;
    }
    setBusyAction("finish");
    setError("");
    setNotice("");
    try {
      if (studyMode) {
        const currentResponse = await fetch("/study/api/current-step", { cache: "no-store" });
        if (!currentResponse.ok) throw new Error("study-state-unavailable");
        const current = await currentResponse.json() as { revision: number; state: string; current_step_path: string };
        if (current.current_step_path !== "/island") {
          router.push(current.current_step_path);
          return;
        }
        let pending: { revision: number } = current;
        if (current.state !== "island_departure_pending") {
          const requestResponse = await fetch("/study/api/request-departure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_revision: current.revision,
              idempotency_key: `departure_request_${crypto.randomUUID().replaceAll("-", "")}`,
            }),
          });
          if (!requestResponse.ok) throw new Error("departure-request-failed");
          pending = await requestResponse.json() as { revision: number };
        }
        const confirmed = window.confirm(
          language === "zh-CN"
            ? (snapshot.world.total_days === 1 ? "确认结束第一天演示并进入问卷吗？确认后游戏记录将冻结。" : "确认结束七日假期并离开小岛吗？确认后游戏记录将冻结，不能继续互动。")
            : "End the seven-day stay and leave the island? Your game record will be frozen and no further interaction will be possible.",
        );
        if (!confirmed) {
          const cancelResponse = await fetch("/study/api/cancel-departure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_revision: pending.revision,
              idempotency_key: `departure_cancel_${crypto.randomUUID().replaceAll("-", "")}`,
            }),
          });
          if (!cancelResponse.ok) throw new Error("departure-cancel-failed");
          setNotice(language === "zh-CN" ? "已返回小岛，可以继续探索。" : "You returned to the island and can continue exploring.");
          return;
        }
        const confirmResponse = await fetch("/study/api/confirm-departure", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: pending.revision,
            idempotency_key: `departure_confirm_${crypto.randomUUID().replaceAll("-", "")}`,
          }),
        });
        if (!confirmResponse.ok) throw new Error("departure-confirm-failed");
        setSelectedAgentId(null);
        router.push("/study/game-processing");
        return;
      }
      await finishSessionApi(sessionId);
      setSelectedAgentId(null);
      router.push("/result");
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "study_departure_required") {
        router.push("/island?study=1");
        return;
      }
      setError(t("island.errorFinish"));
    } finally {
      setBusyAction(null);
    }
  }

  async function toggleSimulation() {
    if (!sessionId || !snapshot || busyAction || snapshot.revision === undefined) return;
    const nextMode = simulationMode === "running" ? "paused" : "running";
    setBusyAction("simulation");
    setError("");
    try {
      const result = await setWorldSimulationMode(sessionId, {
        mode: nextMode,
        idempotency_key: createIdempotencyKey(),
        expected_revision: snapshot.revision,
        language,
      });
      applyWorldSnapshot(result.world);
    } catch {
      setError(t("island.errorAction"));
      await loadWorld(sessionId, true);
    } finally {
      setBusyAction(null);
    }
  }

  function respondToScenario(responseCode: "clarify" | "negotiate" | "leave" | "custom") {
    if (!scenario || scenarioKind !== "conflict") return;
    const responseText = responseCode === "custom" ? customResponse.trim() : undefined;
    if (responseCode === "custom" && !responseText) return;
    void runAction("scenario_response", {
      scenario_instance_id: scenario.scenario_instance_id,
      response_text: responseText,
      response_latency_ms: elapsed(scenarioShownAt.current),
      metadata: {
        response_code: responseCode,
        response_type: responseCode === "custom" ? "free_text" : responseCode,
      },
    });
  }

  function respondToEvent(action: WorldEventAction) {
    if (!activeEvent || !action.action_id || action.enabled === false) return;
    const responseText = action.requires_text ? eventResponse.trim() : undefined;
    if (action.requires_text && !responseText) return;
    const responseLatencyMs = elapsed(eventShownAt.current);
    eventShownAt.current = Date.now();
    setEventResponse("");
    void runAction("event_action", {
      event_instance_id: activeEvent.event_instance_id,
      event_action_id: action.action_id,
      response_text: responseText,
      response_latency_ms: responseLatencyMs,
    });
  }

  if (!sessionResolved || (sessionId && isLoading && !snapshot)) {
    return <CenteredStatus icon={<LoaderCircle className="h-5 w-5 animate-spin" />} text={t("island.loading")} />;
  }

  if(sessionId&&snapshot?.world.day_transition_pending===true){
    return <DayBoundary sid={sessionId} day={snapshot.world.current_day} total={snapshot.world.total_days??7} onContinue={()=>loadWorld(sessionId)}/>;
  }
  if (!sessionId) {
    return (
      <main className="min-h-screen px-5 pb-10 pt-24 sm:px-8">
        <section className="mx-auto max-w-xl rounded-xl border border-amber-200 bg-white p-7 text-center shadow-sm">
          <Anchor className="mx-auto h-9 w-9 text-teal-700" aria-hidden="true" />
          <h1 className="mt-4 text-2xl font-bold text-stone-950">{t("island.noSessionTitle")}</h1>
          <p className="mt-3 text-sm leading-6 text-stone-600">{t("island.noSessionDescription")}</p>
          <Link href="/setup" className="focus-ring mt-6 inline-flex min-h-11 items-center rounded-md bg-teal-700 px-5 text-sm font-semibold text-white hover:bg-teal-800">
            {t("island.createSession")}
          </Link>
        </section>
      </main>
    );
  }

  if (pendingAction && snapshot?.world.can_finish) return <main className="min-h-screen bg-stone-100"><SceneDialog title="恢复上次操作"><p>上次操作的结果尚未确认，请先核对保存结果。</p><button className="focus-ring rounded-xl bg-teal-900 p-4 text-white" disabled={Boolean(busyAction)} onClick={()=>void retryPending()}>重试上次岛屿操作</button></SceneDialog></main>;
  if (snapshot?.world.can_finish && snapshot?.world.world_version?.startsWith('chaoxi-holiday')) return <main className="min-h-screen bg-stone-100"><SceneDialog title={snapshot.world.total_days === 1 ? "第一天演示已结束" : "七日体验已结束"}>{['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '') ? <HolidayIllustration id={snapshot.world.total_days === 1 ? "activity.welcome-wide" : "activity.bonfire-goodbye"} compact/> : null}<p className="py-8 leading-8">{snapshot.world.total_days === 1 ? "第一天演示已完成。接下来可以展示问卷和结果反馈流程；一天的记录不足以验证人格评估效果。" : "谢谢你在岛上度过这七天。接下来进入问卷和结果反馈环节。"}</p>{error ? <p role="alert">{error}</p> : null}<button disabled={Boolean(busyAction)} onClick={()=>void finishIslandSession()} className="focus-ring w-full rounded-xl bg-teal-900 p-4 font-bold text-white disabled:opacity-50">{busyAction ? "正在准备…" : "下一步"}</button></SceneDialog></main>;
  return (
    <HolidayNight night={snapshot?.world.world_version==='chaoxi-holiday-v6'&&(snapshot.world.current_time_minutes??0)>=1080}><main className="min-h-screen overflow-x-hidden px-3 pb-[max(2rem,env(safe-area-inset-bottom))] pt-16 sm:px-5 lg:px-7">
      <div className="mx-auto max-w-[1600px]">
        <GameHud
          language={language}
          dayLabel={`10月${snapshot?.world.current_day ?? 1}日 · 第${snapshot?.world.current_day ?? 1}天`}
          timeLabel={t("island.time", { time: snapshot?.world.current_time ?? "--:--" })}
          locationLabel={currentLocation ? locationName(currentLocation, language) : currentLocationId}
          worldView={worldView}
          canEnterScene={Boolean(sceneLayout && currentLocation)}
          simulationMode={simulationMode}
          simulationBusy={isPulsing || busyAction === "simulation"}
          busy={Boolean(busyAction || overlayKind) || snapshot?.session.status !== "active"}
          attention={Boolean(pendingInteractionPrompt || scenario || activeEvent)}
          timePausedForConversation={snapshot?.simulation?.paused_reason === "active_conversation"}
          canPassTime={Boolean(
            actionAllowed("wait") && !busyAction && !overlayKind && snapshot?.session.status === "active"
          )}
          onToggleSimulation={() => void toggleSimulation()}
          onPassTime={openPassTime}
          onShowMap={() => setWorldView("map")}
          onEnterScene={() => setWorldView("scene")}
          onOpenMenu={() => {
            if (!overlayKind) setMenuOpen(true);
          }}
          onOpenPhone={openSocialPhone}
          phoneOpen={phoneOpen}
          onOpenTasks={() => setTasksOpen(true)} taskCount={taskCount}
          unreadSocialCount={unreadSocialCount}
        />

        {passTimeOpen ? (
          <PassTimeDialog
            language={language}
            minutes={passTimeMinutes}
            currentTime={snapshot?.world.current_time ?? "--:--"}
            busy={Boolean(busyAction)}
            onMinutesChange={setPassTimeMinutes}
            onConfirm={() => void submitPassTime()}
            onClose={() => setPassTimeOpen(false)}
          />
        ) : null}

        <div aria-live="polite" className="pointer-events-none fixed bottom-4 left-3 z-50 flex max-w-[calc(100vw-1.5rem)] flex-col gap-2 sm:left-5 sm:max-w-md">
          {error ? <div role="alert" className="pointer-events-auto flex items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 shadow-lg"><span>{error}</span><button type="button" onClick={() => void loadWorld(sessionId)} className="focus-ring rounded px-2 py-1 font-bold">{t("island.retry")}</button></div> : null}
          {notice ? <p role="status" className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900 shadow-lg">{notice}</p> : null}
          {syncWarning ? <p role="status" className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 shadow-lg">{syncWarning}</p> : null}
          {pendingAction&&<p role="alert" className="pointer-events-auto rounded-xl bg-amber-50 p-3 text-amber-950">上次操作的结果尚未确认，重试会核对同一份记录。<button className="focus-ring ml-3 rounded border px-3 py-2" disabled={Boolean(busyAction)} onClick={()=>void retryPending()}>重试上次岛屿操作</button></p>}
          {busyAction ? <p role="status" className="flex items-center gap-2 rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm text-stone-700 shadow-lg"><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />{t("island.busy")}</p> : null}
        </div>

        {shortChatOffer ? <button type="button" className="focus-ring mx-3 rounded-lg border border-stone-300 bg-white px-4 py-3" disabled={Boolean(busyAction)} onClick={() => void approachResident(shortChatOffer, 5)}>
          {language === "zh-CN" ? `与${shortChatOffer.name}短聊 5 分钟` : `Talk to ${shortChatOffer.name} for 5 minutes`}
        </button> : null}
        {snapshot && ['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '') && <V5Companion sid={sessionId} revision={snapshot.revision ?? 0} day={snapshot.world.current_day} totalDays={snapshot.world.total_days} minute={snapshot.world.current_time_minutes ?? 540} location={currentLocationId ?? ''} blocked={Boolean(busyAction) || activityActive} onChanged={()=>void loadWorld(sessionId,true)} onPortrait={setV5Portrait} onExecute={(action_id,inputs)=>runAction('defined_action',{target_object_id:'guidebook',metadata:{action_id,inputs}})} />}
        {['chaoxi-holiday-v3','chaoxi-holiday-v4','chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot?.world.world_version ?? '') ? <HolidayActivities sessionId={sessionId} revision={snapshot?.revision ?? 0} open={tasksOpen} onClose={()=>setTasksOpen(false)} onCount={setTaskCount} onActive={setActivityActive} onChanged={()=>void loadWorld(sessionId,true)} /> : snapshot?.capabilities?.modular_stages ? <ModularStagePanel
            open={tasksOpen} onClose={() => setTasksOpen(false)} onCountChange={setTaskCount}
            day={snapshot.world.current_day}
            sessionId={sessionId}
            worldRevision={snapshot.revision ?? 0}
            language={language}
            disabled={Boolean(busyAction) || Boolean(overlayKind) || snapshot.session.status !== "active"}
            onWorldChanged={() => void loadWorld(sessionId, true)}
          /> : null}
        {studyMode && snapshot?.world.can_finish && snapshot.session.status === "active" ? <section className="rounded-xl border border-teal-300 bg-teal-50 p-4"><p className="font-bold">七日假期已结束</p><p className="mt-1 text-sm">接下来填写量表、阅读两份反馈并完成体验问卷。</p><button type="button" disabled={Boolean(busyAction)} onClick={() => void finishIslandSession()} className="mt-3 rounded-lg bg-teal-800 px-4 py-2 font-bold text-white disabled:opacity-50">离岛，继续量表与反馈</button></section> : null}
        <WorldStage illustrated={['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot?.world.world_version ?? '')}>
          {snapshot?.map ? (
            <section className={`relative lg:h-full lg:min-h-0 ${['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '') ? "" : "min-h-[480px]"}`} aria-label={language === "zh-CN" ? "岛屿世界舞台" : "Island world stage"}>
              {worldView === "scene" && sceneLayout && currentLocation ? (
                <div key={currentLocationId} className={`game-stage-enter h-full overflow-auto bg-[#f7f5ef] p-2 sm:p-4 lg:min-h-0 ${['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '') ? "" : "min-h-[480px]"}`}>
                  <LocationScene
                    language={language}
                    location={currentLocation}
                    layout={sceneLayout}
                    actors={sceneActors}
                    visuals={snapshot.visuals}
                    interactionPoints={currentInteractionPoints}
                    ambientConversations={snapshot.ambient_conversations ?? []}
                    promptInitiatorAgentId={pendingInteractionPrompt?.initiator_agent_id}
                    adjacentThumbnailUrls={adjacentThumbnailUrls}
                    selectedObjectId={selectedObjectId}
                    selectedActorId={selectedMapActorId}
                    busy={Boolean(busyAction)}
                    onInspect={inspectInteractionPoint}
                    onHotspotInspect={inspectInteractionPoint}
                    onSelectActor={(actor) => {
                      setSelectedObjectId(null);
                      setSelectedLocationId(null);
                      setSelectedMapActorId(actor.actor_id);
                      if (actor.agent_id != null) setSelectedAgentId(actor.agent_id);
                    }}
                    onOpenWorldLog={closeContextCard}
                  />
                </div>
              ) : (
                <IslandMap
                  key="island-map-stage"
                  stageMode
                  map={snapshot.map}
                  locations={locations}
                  actors={snapshot.actors ?? []}
                  visuals={snapshot.visuals}
                  language={language}
                  currentLocationId={currentLocationId}
                  selectedLocationId={selectedLocationId}
                  selectedActorId={selectedMapActorId}
                  statusForLocation={locationStatus}
                  statusLabelForLocation={locationStatusLabel}
                  openingHours={snapshot.world.location_hours}
                  onSelectLocation={(locationId) => {
                    setSelectedObjectId(null);
                    setSelectedMapActorId(null);
                    setSelectedLocationId(locationId);
                  }}
                  onSelectActor={(actor) => {
                    setSelectedObjectId(null);
                    setSelectedLocationId(null);
                    setSelectedMapActorId(actor.actor_id);
                    if (actor.agent_id != null && actor.location_id === currentLocationId) setSelectedAgentId(actor.agent_id);
                  }}
                />
              )}

              {(selectedLocation || selectedMapActor || selectedInteractionPoint) ? (
                <ContextFrame illustrated={['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '')} objectTitle={selectedInteractionPoint ? interactionPointName(selectedInteractionPoint,language) : undefined} onClose={closeContextCard}>
                  {!selectedInteractionPoint ? <button type="button" data-testid="context-card-close" aria-label={language === "zh-CN" ? "关闭简介" : "Close details"} onClick={closeContextCard} className="focus-ring absolute right-2 top-2 z-10 grid h-11 w-11 place-items-center rounded-full border border-stone-300 bg-white text-stone-700 shadow-sm hover:bg-stone-100"><X className="h-5 w-5" aria-hidden="true" /></button> : null}
                  {worldView === "scene" && selectedInteractionPoint ? (
                    <div data-testid="scene-object-info" className="space-y-3">
                      {!['chaoxi-holiday-v4','chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? "") && <div className="relative grid min-h-28 place-items-center overflow-hidden rounded-xl border border-white/70 px-4 py-5 text-center text-white shadow-inner" style={{ background: `linear-gradient(135deg, ${interactionPointColor(selectedInteractionPoint)} 0%, #292524 120%)` }}>
                        <Eye className="h-9 w-9 opacity-90" aria-hidden="true" />
                        <p className="mt-2 text-sm font-black">{interactionPointName(selectedInteractionPoint, language)}</p>
                      </div>}
                      {!['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '')&&<div>
                        <p className="text-xs font-bold uppercase tracking-wide text-amber-700">{language === "zh-CN" ? "可交互地点" : "Interaction point"}</p>
                        <h3 className="mt-1 text-lg font-bold text-stone-950">{interactionPointName(selectedInteractionPoint, language)}</h3>
                      </div>}
                      <p className="text-sm leading-6 text-stone-600">{interactionPointDescription(selectedInteractionPoint, language)}</p>
                      {!['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '') && <ObjectResult state={snapshot.world.state} objectId={selectedInteractionPoint.object_id} language={language} />}
                      {['chaoxi-holiday-v4','chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? "") ? <ObjectExplorer sessionId={sessionId} objectId={selectedInteractionPoint.object_id} revision={snapshot.revision ?? 0} disabled={Boolean(busyAction)} onExecute={(action_id, inputs) => runAction("defined_action", {target_object_id: selectedInteractionPoint.object_id, metadata: {action_id, inputs}})} /> : (
                      <div className="grid gap-2 sm:grid-cols-2">
                        <ObjectActions key={selectedInteractionPoint.object_id} actions={snapshot.available_actions} objectId={selectedInteractionPoint.object_id} language={language} disabled={Boolean(busyAction)} onReadPublicNotes={openSocialPhone} onExecute={(action_id, inputs) => runAction("defined_action", {target_object_id: selectedInteractionPoint.object_id, metadata: {action_id, inputs}})} />
                      </div>
                      )}
                    </div>
                  ) : (
                    <MapInfoPanel
                      language={language}
                      location={worldView === "map" ? selectedLocation : null}
                      locationStatus={worldView === "map" && selectedLocation ? locationStatus(selectedLocation) : null}
                      locationStatusLabel={worldView === "map" && selectedLocation ? locationStatusLabel(locationStatus(selectedLocation)) : ""}
                      locationOccupants={selectedLocationOccupants}
                      locationRelationLabel={selectedLocationRelation}
                      actor={selectedMapActor}
                      actorLocationName={selectedMapActor ? locationDisplayName(locations.find((item) => item.location_id === selectedMapActor.location_id), language) : undefined}
                      canTravel={Boolean(worldView === "map" && selectedLocation && locationStatus(selectedLocation) === "reachable")}
                      canApproach={Boolean(selectedMapActor?.agent_id != null && selectedMapActor.location_id === currentLocationId && actionAllowed("approach", selectedMapActor.agent_id))}
                      busy={Boolean(busyAction)}
                      onTravel={(locationId) => void moveTo(locationId)}
                      onApproach={(agentId) => {
                        const resident = residents.find((item) => item.agent_id === agentId);
                        if (resident) void approachResident(resident);
                      }}
                    />
                  )}
                </ContextFrame>
              ) : null}
            </section>
          ) : (
            <section data-testid="legacy-map-fallback" className="game-stage-enter h-full overflow-y-auto bg-gradient-to-br from-sky-100 to-lime-100 p-5 sm:p-8">
              <h1 className="text-2xl font-black text-stone-950">{language === "zh-CN" ? "岛屿地点" : "Island locations"}</h1>
              <p className="mt-2 text-sm text-stone-600">{language === "zh-CN" ? "选择任意可到达地点即可前往；经过的路径越长，消耗时间越多。" : "Choose any reachable place; longer routes consume more time."}</p>
              <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {locations.map((location) => {
                  const status = locationStatus(location);
                  return <button key={location.location_id} data-testid={`location-${location.location_id}`} type="button" disabled={status !== "reachable" || Boolean(busyAction)} aria-current={status === "current" ? "location" : undefined} onClick={() => void moveTo(location.location_id)} className="focus-ring rounded-xl border border-stone-300 bg-white/90 p-4 text-left shadow-sm hover:border-teal-500 disabled:opacity-60"><span className="block font-bold text-stone-950">{locationName(location, language)}</span><span className="mt-1 block text-xs font-semibold text-stone-600">{locationStatusLabel(status)}</span></button>;
                })}
              </div>
            </section>
          )}

          {followUpText(snapshot?.recent_follow_up, language) ? (
            <div
              data-testid="scene-follow-up-notice"
              data-has-follow-up="true"
              role="status"
              className="pointer-events-none absolute left-3 top-3 z-30 max-w-[min(26rem,calc(100%-1.5rem))] rounded-xl border border-amber-200 bg-amber-50/95 px-4 py-3 text-sm leading-6 text-amber-950 shadow-lg backdrop-blur sm:left-4 sm:top-4"
            >
              <span className="font-black">{language === "zh-CN" ? "新的回响：" : "A new echo: "}</span>
              {followUpText(snapshot?.recent_follow_up, language)}
            </div>
          ) : null}

          {activeGoal ? (
            <div data-testid="active-world-goal" className="pointer-events-none absolute right-3 top-3 z-30 max-w-[min(22rem,calc(100%-1.5rem))] rounded-xl border border-sky-200 bg-sky-50/95 px-4 py-3 text-sm text-sky-950 shadow-lg backdrop-blur sm:right-4 sm:top-4">
              <p className="text-[10px] font-black uppercase tracking-[0.16em] text-sky-700">{language === "zh-CN" ? "当前安排" : "Current plan"}</p>
              <p className="mt-1 font-black">{localizedGoalField(activeGoal, "title", language)}</p>
              <p className="mt-1 text-xs leading-5 text-sky-800">{localizedGoalField(activeGoal, "description", language)}</p>
              {typeof activeGoal.due_time_minutes === "number" ? <p className="mt-1 text-xs font-bold">{language === "zh-CN" ? "时间" : "Time"}: {minutesLabel(activeGoal.due_time_minutes)}</p> : null}
            </div>
          ) : null}

          {overlayKind === "scenario" && scenario ? (
            <NarrativeChoiceOverlay
              key={`scenario:${scenario.scenario_instance_id}:${scenario.stage ?? ""}`}
              language={language}
              scenario={scenario}
              scenarioKind={scenarioKind}
              seats={seats}
              selectedSeatId={selectedSeatId}
              locationName={currentLocation ? locationName(currentLocation, language) : currentLocationId}
              locationSceneUrl={snapshot?.visuals?.slots[`locations.${currentLocationId}.scene_image`]?.asset?.url}
              eventResponse={eventResponse}
              customResponse={customResponse}
              busy={Boolean(busyAction)}
              canAction={actionAllowed}
              onEventResponseChange={setEventResponse}
              onCustomResponseChange={setCustomResponse}
              onEventAction={respondToEvent}
              onScenarioResponse={respondToScenario}
              onSeatView={(seatId) => void runAction("seat_view", {
                target_object_id: seatId,
                scenario_instance_id: scenario.scenario_instance_id,
              })}
              onSeatSelect={(seatId, actionType) => void runAction(actionType, scenarioKind === "seating" ? {
                target_object_id: seatId,
                scenario_instance_id: scenario.scenario_instance_id,
                response_latency_ms: elapsed(scenarioShownAt.current),
              } : {
                target_object_id: seatId,
                response_latency_ms: elapsed(scenarioShownAt.current),
              })}
              onScenarioSkip={() => void runAction("scenario_skip", {
                scenario_instance_id: scenario.scenario_instance_id,
                response_latency_ms: elapsed(scenarioShownAt.current),
              })}
            />
          ) : null}

          {overlayKind === "event" && activeEvent ? (
            <NarrativeChoiceOverlay
              key={`event:${activeEvent.event_instance_id}:${String(activeEvent.metadata?.stage_id ?? "")}`}
              language={language}
              event={activeEvent}
              scenarioKind="unsupported"
              seats={[]}
              selectedSeatId=""
              locationName={currentLocation ? locationName(currentLocation, language) : currentLocationId}
              locationSceneUrl={snapshot?.visuals?.slots[`locations.${currentLocationId}.scene_image`]?.asset?.url}
              eventNpcName={eventNpcResident?.name}
              eventNpcPortraitUrl={eventNpcPortraitUrl}
              eventResponse={eventResponse}
              customResponse={customResponse}
              busy={Boolean(busyAction)}
              canAction={actionAllowed}
              onEventResponseChange={setEventResponse}
              onCustomResponseChange={setCustomResponse}
              onEventAction={respondToEvent}
              onScenarioResponse={respondToScenario}
              onSeatView={() => undefined}
              onSeatSelect={() => undefined}
              onScenarioSkip={() => undefined}
            />
          ) : null}

          {overlayKind === "prompt" && pendingInteractionPrompt ? (
            <InteractionPromptOverlay
              key={`prompt:${pendingInteractionPrompt.prompt_id}`}
              prompt={pendingInteractionPrompt}
              resident={promptInitiator}
              portraitUrl={snapshot?.visuals?.slots[`actors.resident:${pendingInteractionPrompt.initiator_agent_id}.dialogue_portrait`]?.asset?.url}
              language={language}
              busy={Boolean(busyAction)}
              onRespond={(response) => void respondToInteractionPrompt(response)}
            />
          ) : null}

          {overlayKind === "dialogue" && dialogueResident ? (
            <DialogueOverlay
              key={`dialogue:${activeParticipantConversation?.conversation_id ?? dialogueResident.agent_id}`}
              language={language}
              resident={dialogueResident}
              turns={dialogueTurns}
              residentPortraitUrl={dialogueResidentPortraitUrl}
              participantPortraitUrl={participantPortraitUrl}
              message={message}
              busy={Boolean(busyAction)}
              canEnd={actionAllowed("end_conversation", dialogueResident.agent_id)}
              onMessageChange={setMessage}
              onMessageFocus={() => { conversationStartedAt.current = Date.now(); }}
              onSubmit={submitConversation}
              onEnd={() => void endResidentConversation()}
            />
          ) : null}
        </WorldStage>

        {dayReview ? <DayReviewDialog review={dayReview} language={language} busy={Boolean(busyAction)} onClose={() => setDayReview(null)} onConfirm={() => void endCurrentDay(true)} /> : null}
        {dayTransition && !snapshot?.world.can_finish ? <SceneDialog title={`第 ${dayTransition} 天 · 10月${dayTransition}日`}><p className="py-8 text-lg leading-8">早安，新的一天从客房开始。今天也按自己的节奏逛逛吧。</p><button className="focus-ring w-full rounded-xl bg-teal-900 p-4 font-bold text-white" onClick={()=>setDayTransition(null)}>开始这一天</button></SceneDialog> : null}
        {studyMode && snapshot?.world.can_finish ? <SceneDialog title={snapshot.world.total_days === 1 ? "第一天演示已结束" : "七日体验已结束"}>{['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot.world.world_version ?? '') ? <HolidayIllustration id={snapshot.world.total_days === 1 ? "activity.welcome-wide" : "activity.bonfire-goodbye"} compact/> : null}<p className="py-6 leading-8">{snapshot.world.total_days === 1 ? "第一天演示已完成。接下来可以展示问卷和结果反馈流程；一天的记录不足以验证人格评估效果。" : "谢谢你在岛上度过这七天。接下来进入问卷和结果反馈环节。"}</p>{error ? <p role="alert">{error}</p> : null}<button disabled={Boolean(busyAction)} onClick={()=>void finishIslandSession()} className="focus-ring w-full rounded-xl bg-teal-900 p-4 font-bold text-white disabled:opacity-50">{busyAction ? "正在准备…" : "下一步"}</button></SceneDialog> : null}
        <GameMenuDrawer
          open={menuOpen && !overlayKind}
          title={language === "zh-CN" ? "岛屿菜单" : "Island menu"}
          closeLabel={language === "zh-CN" ? "关闭菜单" : "Close menu"}
          onClose={() => setMenuOpen(false)}
        >
          <section data-testid="game-menu-actions" className="mb-6 grid gap-3 rounded-xl border border-stone-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-3">
            <button type="button" data-testid="menu-log" onClick={() => {setMenuOpen(false); setLogOpen(true);}} className="focus-ring min-h-11 rounded-lg border p-3 font-bold">日志</button>
            {['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot?.world.world_version??'')&&<button data-testid="save-progress" type="button" onClick={()=>void saveProgress()} disabled={Boolean(busyAction)||snapshot?.session.status!=='active'} className="focus-ring min-h-11 rounded-lg border border-teal-300 bg-teal-50 p-3 font-bold">{busyAction==='save'?'正在保存…':'保存进度'}</button>}
            {saveMessage&&<p role="status" data-testid="save-progress-status" className="rounded-xl bg-teal-50 p-3">{saveMessage}</p>}
            <button data-testid="menu-end-day" type="button" onClick={() => void endCurrentDay()} disabled={Boolean(busyAction)} className="focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 text-sm font-bold text-amber-950 hover:bg-amber-100 disabled:opacity-50"><CalendarDays className="h-4 w-4" aria-hidden="true" />{t("island.endDay")}</button>
            <button data-testid="finish-session" type="button" title={snapshot?.world.can_finish === false ? snapshot.world.departure_prompt?.[language] : undefined} onClick={() => void finishIslandSession()} disabled={snapshot?.session.status !== "active" || snapshot?.world.can_finish === false || Boolean(busyAction)} className="focus-ring min-h-11 rounded-lg border border-red-200 px-3 text-sm font-bold text-red-800 hover:bg-red-50 disabled:opacity-50">{busyAction === "finish" ? t("island.finishing") : t("island.finish")}</button>
          </section>
        </GameMenuDrawer>
        <GameMenuDrawer open={logOpen} title="登岛日志" closeLabel="关闭日志" onClose={() => setLogOpen(false)}>{logOpen ? <PlayerRecords sessionId={sessionId} language={language} /> : null}</GameMenuDrawer>
        {phoneOpen ? (
          <SocialPhoneOverlay
            v5Enabled={['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(snapshot?.world.world_version ?? '')}
            sessionId={sessionId}
            initialFilter={phoneFilter}
            mutationsDisabled={Boolean(busyAction) || snapshot?.session.status !== 'active'}
            language={language}
            onClose={() => setPhoneOpen(false)}
            onWorldChanged={() => void loadWorld(sessionId, true)}
            onUnreadCountChange={setUnreadSocialCount}
          />
        ) : null}
      </div>
    </main></HolidayNight>
  );
}

function ContextFrame({objectTitle,onClose,children,illustrated=false}: {objectTitle?: string; onClose:()=>void; children:ReactNode; illustrated?:boolean}) {
  if (objectTitle) return <SceneDialog title={objectTitle} onClose={onClose} wide><div data-testid="object-scene">{!illustrated&&<div data-art-slot="object" className="mb-6 rounded-2xl bg-gradient-to-br from-teal-900 via-teal-700 to-stone-500 px-6 py-10 text-2xl font-bold text-white">{objectTitle}</div>}{children}</div></SceneDialog>;
  return <aside data-testid="context-card" className="absolute bottom-3 right-3 z-20 max-h-[72%] w-[min(330px,calc(100%-1.5rem))] overflow-y-auto rounded-2xl border border-white/80 bg-stone-50/95 p-4 pt-14 shadow-2xl backdrop-blur sm:bottom-4 sm:right-4">{children}</aside>;
}

function describeLocationRelation(
  locations: WorldLocation[],
  currentLocationId: string,
  targetLocationId: string,
  status: MapLocationStatus,
  minutesPerEdge: number,
  language: Language,
) {
  if (currentLocationId === targetLocationId) return language === "zh-CN" ? "你正在这里" : "You are here";
  if (status === "closed") return language === "zh-CN" ? "入口关闭" : "Entrance closed";
  const route = shortestLocationPath(locations, currentLocationId, targetLocationId);
  if (!route || status !== "reachable") return language === "zh-CN" ? "没有可用路径" : "No available route";
  const edgeCount = route.length - 1;
  const routeNames = route.map((locationId) => locationDisplayName(
    locations.find((location) => location.location_id === locationId),
    language,
  ) ?? locationId);
  const duration = edgeCount * Math.max(0, minutesPerEdge);
  return language === "zh-CN"
    ? `${edgeCount} 段路 · 约 ${duration} 分钟 · ${routeNames.join(" → ")}`
    : `${edgeCount} leg${edgeCount === 1 ? "" : "s"} · about ${duration} min · ${routeNames.join(" → ")}`;
}

function shortestLocationPath(
  locations: WorldLocation[],
  sourceLocationId: string,
  targetLocationId: string,
) {
  if (!sourceLocationId || !targetLocationId) return null;
  const locationById = new Map(locations.map((location) => [location.location_id, location]));
  if (!locationById.has(sourceLocationId) || !locationById.has(targetLocationId)) return null;
  if (sourceLocationId === targetLocationId) return [sourceLocationId];
  const queue: string[][] = [[sourceLocationId]];
  const visited = new Set([sourceLocationId]);
  while (queue.length) {
    const path = queue.shift()!;
    const current = locationById.get(path.at(-1)!);
    for (const neighborId of [...(current?.connected_location_ids ?? [])].sort()) {
      if (visited.has(neighborId) || !locationById.has(neighborId)) continue;
      const nextPath = [...path, neighborId];
      if (neighborId === targetLocationId) return nextPath;
      visited.add(neighborId);
      queue.push(nextPath);
    }
  }
  return null;
}

function interactionPointColor(point: WorldInteractionPoint) {
  const key = String(point.renderer_key ?? point.type ?? "object");
  const colors: Record<string, string> = {
    desk: "#92400e", notice: "#ca8a04", garden: "#15803d", table: "#a16207",
    books: "#7c3aed", bench: "#78716c", railing: "#64748b", counter: "#0f766e",
    shelf: "#7c2d12", display: "#be123c", landmark: "#475569", seat: "#57534e",
  };
  return colors[key] ?? "#57534e";
}

function CenteredStatus({ icon, text }: { icon: ReactNode; text: string }) {
  return <main className="flex min-h-screen items-center justify-center px-5"><div className="flex items-center gap-3 rounded-lg border border-stone-200 bg-white px-5 py-4 text-sm text-stone-600 shadow-sm">{icon}{text}</div></main>;
}


function locationName(location: WorldLocation, language: Language) {
  return location.translations?.[language]?.name ?? (language === "zh-CN" ? location.name_zh_cn : location.name) ?? location.name;
}

function locationDisplayName(
  location: WorldLocation | undefined,
  language: Language,
) {
  return location ? locationName(location, language) : undefined;
}

function getScenarioKind(
  scenario: WorldScenario | null,
): "seating" | "conflict" | "unsupported" {
  if (!scenario) return "unsupported";
  const marker = `${scenario.scenario_id ?? ""} ${scenario.scenario_type ?? ""} ${scenario.stage ?? ""}`.toLowerCase();
  if (marker.includes("conflict") || marker.includes("order") || marker.includes("booking") || marker.includes("misunderstanding")) return "conflict";
  if (marker.includes("seat") || (scenario.seat_options?.length ?? 0) > 0) return "seating";
  return "unsupported";
}

function getScenarioSeats(scenario: WorldScenario | null, interactionPoints?: WorldInteractionPoint[]) {
  if (!scenario) return [];
  const options = scenario.seat_options ?? scenario.visible_options ?? scenario.options ?? [];
  const isSeatingScenario =
    scenario.scenario_type === "seating" ||
    String(scenario.scenario_id ?? "").toLowerCase().includes("seat");
  const optionSeats = options.filter(
    (option) =>
      Boolean(optionId(option)) &&
      (isSeatingScenario ||
        Boolean(option.object_id || option.target_object_id) ||
        String(option.metadata?.type ?? "").includes("seat")),
  );
  if (optionSeats.length) return optionSeats;
  return (interactionPoints ?? []).filter((point) => point.type === "research_seat" || point.interaction_type === "research_seat").map((point) => ({ object_id: point.object_id, label: point.label, label_zh_cn: point.label_zh_cn, description: point.description, description_zh_cn: point.description_zh_cn, available: point.available, metadata: point.metadata }));
}

function optionId(option: WorldScenarioOption) {
  return String(
    option.target_object_id ??
      option.object_id ??
      option.option_id ??
      option.id ??
      option.value ??
      "",
  );
}

function getSelectedSeatId(scenario: WorldScenario | null) {
  if (!scenario) return "";
  const direct = scenario.selected_seat_id;
  const metadata = scenario.metadata?.selected_seat_id;
  return typeof direct === "string" ? direct : typeof metadata === "string" ? metadata : "";
}

function conversationResidentId(conversation: WorldConversation) {
  const direct = conversation.agent_id ?? conversation.resident_id;
  if (direct != null) return direct;
  const member = conversation.participants?.find(
    (participant) =>
      participant.member_type === "resident" &&
      participant.agent_id != null &&
      !participant.left_at,
  );
  return member?.agent_id ?? conversation.initiator_agent_id ?? null;
}

function followUpText(
  value: WorldSnapshot["recent_follow_up"] | undefined,
  language: Language,
) {
  if (!value) return "";
  if (typeof value === "string") return value;
  const translations = value.translations;
  if (translations && typeof translations === "object") {
    const localized = (translations as Record<string, unknown>)[language];
    if (typeof localized === "string") return localized;
    if (localized && typeof localized === "object" && "content" in localized) {
      const content = (localized as Record<string, unknown>).content;
      if (typeof content === "string") return content;
    }
  }
  for (const key of language === "zh-CN" ? ["content_zh_cn", "message_zh_cn", "description_zh_cn", "response_text", "content", "message", "description", "outcome"] : ["response_text", "content", "message", "description", "summary", "outcome"]) {
    if (typeof value[key] === "string") return value[key] as string;
  }
  return "";
}

function activeWorldGoal(world: WorldSnapshot["world"] | undefined) {
  const state = world?.state;
  if (!state || typeof state !== "object" || Array.isArray(state)) return null;
  const goals = (state as Record<string, unknown>).goals;
  if (!goals || typeof goals !== "object" || Array.isArray(goals)) return null;
  const visibleStatuses = new Set(["active", "rescheduled", "relocated", "rerouted"]);
  return Object.values(goals as Record<string, unknown>).find((goal): goal is Record<string, unknown> => (
    Boolean(goal) &&
    typeof goal === "object" &&
    !Array.isArray(goal) &&
    visibleStatuses.has(String((goal as Record<string, unknown>).status ?? ""))
  )) ?? null;
}

function localizedGoalField(goal: Record<string, unknown>, field: string, language: Language) {
  const value = goal[field];
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const localized = value as Record<string, unknown>;
  const result = localized[language] ?? localized.en ?? localized["zh-CN"];
  return typeof result === "string" ? result : "";
}

function eventResponseNpcId(event: WorldEvent | null) {
  const response = event?.metadata?.npc_response;
  if (!response || typeof response !== "object" || Array.isArray(response)) return null;
  const npcId = (response as Record<string, unknown>).npc_id;
  return typeof npcId === "number" ? npcId : null;
}

function minutesLabel(minutes: number) {
  const hour = Math.floor(minutes / 60).toString().padStart(2, "0");
  const minute = Math.floor(minutes % 60).toString().padStart(2, "0");
  return `${hour}:${minute}`;
}

function createIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `island-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function conversationErrorMessage(
  caught: unknown,
  residentName: string,
  language: Language,
) {
  if (!(caught instanceof ApiError)) {
    return language === "zh-CN" ? "未能保存这段对话，请刷新后重试。" : "The conversation could not be saved. Refresh and try again.";
  }
  if(caught.message.startsWith("系统提示："))return caught.message;
  const detail = caught.message.toLowerCase();
  if(caught.status===409&&detail.includes('conversation time conflicts'))return language==='zh-CN'?`${residentName}正在赶路或有已确认的安排。如果是你们约好的活动，请打开“任务”进入活动后再聊；也可以打开手机私信。`:'There is a journey or confirmed arrangement. For your shared activity, open Tasks and enter it to chat; private messages are also available.';
  if(caught.status===409&&detail.includes('not enough game time'))return language==='zh-CN'?'今天剩下的时间不够长聊，可以试试5分钟短聊或手机私信。':'Try a shorter chat or private messages.';
  if(caught.status===409&&detail.includes('another participant conversation'))return language==='zh-CN'?'还有一段交谈未结束，已同步到界面，请先结束当前交谈。':'End the current conversation first.';
  if (caught.status === 409 && detail.includes("not at the participant")) {
    return language === "zh-CN"
      ? `${residentName} 已经离开这里，对话尚未开始。世界状态已重新同步。`
      : `${residentName} has left this location, so the conversation did not start. The world has been resynced.`;
  }
  if (caught.status === 409 && detail.includes("state changed")) {
    return language === "zh-CN"
      ? "岛屿状态在回复期间发生变化，已重新同步；你可以继续当前对话或结束交流。"
      : "The island changed while the reply was being prepared. It has been resynced; you can continue or end the conversation.";
  }
  if (caught.status === 409 && detail.includes("no longer available")) {
    return language === "zh-CN"
      ? "这段对话已经结束或失效，界面已重新同步。"
      : "This conversation has ended or is no longer available. The view has been resynced.";
  }
  return language === "zh-CN"
    ? `未能保存这段对话（HTTP ${caught.status}）。请刷新后重试。`
    : `The conversation could not be saved (HTTP ${caught.status}). Refresh and try again.`;
}

function isWorldSnapshot(value: unknown): value is WorldSnapshot {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<WorldSnapshot>;
  return Boolean(
    candidate.session &&
    candidate.world &&
    Array.isArray(candidate.locations) &&
    Array.isArray(candidate.residents),
  );
}

function elapsed(startedAt: number) {
  return Math.max(0, Date.now() - startedAt);
}
