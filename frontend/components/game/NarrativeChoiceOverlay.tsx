"use client";

import { Armchair, Clock3, Footprints, Handshake, Map, MessageCircle, Phone, Search, SkipForward, Utensils } from "lucide-react";
import { useState, type ReactNode } from "react";

import type {
  WorldActionType,
  WorldEvent,
  WorldEventAction,
  WorldScenario,
  WorldScenarioOption,
} from "@/lib/api";
import { resolveApiAssetUrl } from "@/lib/api";
import type { Language } from "@/lib/i18n";
import { GameOverlayFrame } from "./GameOverlayFrame";

type ScenarioKind = "seating" | "conflict" | "unsupported";

type DeclarativeEventModel = {
  kind: "event";
  instanceId: string;
  sourceType: string;
  title: string;
  stimulus: string;
  actions: WorldEventAction[];
  metadata?: Record<string, unknown>;
};

type LegacyScenarioModel = {
  kind: "scenario";
  instanceId: string;
  sourceType: ScenarioKind;
  title: string;
  stimulus: string;
  seats: WorldScenarioOption[];
};

export function adaptDeclarativeEvent(
  event: WorldEvent,
  language: Language,
): DeclarativeEventModel {
  return {
    kind: "event",
    instanceId: String(event.event_instance_id),
    sourceType: event.event_type,
    title:
      event.titles?.[language] ??
      (language === "zh-CN" ? event.title_zh_cn : event.title) ??
      event.title ??
      event.title_zh_cn ??
      (language === "zh-CN" ? "岛屿事件" : "Island event"),
    stimulus:
      event.stimuli?.[language] ??
      (language === "zh-CN" ? event.stimulus_text_zh_cn : event.stimulus_text) ??
      event.stimulus_text ??
      event.stimulus_text_zh_cn ??
      "",
    actions: event.actions ?? [],
    metadata: event.metadata,
  };
}

export function adaptLegacyScenario(
  scenario: WorldScenario,
  scenarioKind: ScenarioKind,
  seats: WorldScenarioOption[],
  language: Language,
): LegacyScenarioModel {
  const fallbackTitle = scenarioKind === "seating"
    ? language === "zh-CN" ? "选择座位" : "Choose a seat"
    : scenarioKind === "conflict"
      ? language === "zh-CN" ? "现场状况" : "A situation unfolds"
      : language === "zh-CN" ? "暂不支持的场景" : "Unsupported scene";
  return {
    kind: "scenario",
    instanceId: String(scenario.scenario_instance_id),
    sourceType: scenarioKind,
    title:
      (language === "zh-CN" ? scenario.title_zh_cn : scenario.title) ??
      scenario.title ??
      scenario.title_zh_cn ??
      fallbackTitle,
    stimulus:
      (language === "zh-CN"
        ? scenario.description_zh_cn ?? scenario.prompt_zh_cn
        : scenario.description ?? scenario.prompt) ??
      scenario.stimulus_text ??
      scenario.description ??
      scenario.prompt ??
      scenario.description_zh_cn ??
      scenario.prompt_zh_cn ??
      "",
    seats,
  };
}

export function NarrativeChoiceOverlay({
  language,
  event,
  scenario,
  scenarioKind,
  seats,
  selectedSeatId,
  locationName,
  locationSceneUrl,
  eventNpcName,
  eventNpcPortraitUrl,
  eventResponse,
  customResponse,
  busy,
  canAction,
  onEventResponseChange,
  onCustomResponseChange,
  onEventAction,
  onScenarioResponse,
  onSeatView,
  onSeatSelect,
  onScenarioSkip,
}: {
  language: Language;
  event?: WorldEvent | null;
  scenario?: WorldScenario | null;
  scenarioKind: ScenarioKind;
  seats: WorldScenarioOption[];
  selectedSeatId: string;
  locationName: string;
  locationSceneUrl?: string;
  eventNpcName?: string;
  eventNpcPortraitUrl?: string;
  eventResponse: string;
  customResponse: string;
  busy: boolean;
  canAction: (actionType: WorldActionType, targetId?: string | number) => boolean;
  onEventResponseChange: (value: string) => void;
  onCustomResponseChange: (value: string) => void;
  onEventAction: (action: WorldEventAction) => void;
  onScenarioResponse: (response: "clarify" | "negotiate" | "leave" | "custom") => void;
  onSeatView: (seatId: string) => void;
  onSeatSelect: (seatId: string, actionType: "seat_select" | "seat_change") => void;
  onScenarioSkip: () => void;
}) {
  const isChinese = language === "zh-CN";
  const model = event
    ? adaptDeclarativeEvent(event, language)
    : scenario
      ? adaptLegacyScenario(scenario, scenarioKind, seats, language)
      : null;
  const [textActionId, setTextActionId] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);

  if (!model) return null;

  return (
    <GameOverlayFrame
      label={model.title}
      escapeHint={isChinese ? "请先选择一个选项；Escape 不会替你作出选择。" : "Choose an option; Escape does not make a choice for you."}
    >
      <section
        data-testid={model.kind === "event" ? "active-event" : "active-scenario"}
        data-event-type={model.kind === "event" ? model.sourceType : undefined}
        data-event-instance-id={model.kind === "event" ? model.instanceId : undefined}
        data-scenario-type={model.kind === "scenario" ? model.sourceType : undefined}
        data-scenario-instance-id={model.kind === "scenario" ? model.instanceId : undefined}
        className="p-5 sm:p-7"
      >
        <SceneContext name={locationName} imageUrl={locationSceneUrl} language={language} />
        <p className="text-xs font-black uppercase tracking-[0.16em] text-amber-800">
          {model.kind === "event"
            ? isChinese ? "岛屿事件" : "Island event"
            : isChinese ? "剧情选择" : "Story choice"}
        </p>
        <h2 className="mt-1 text-2xl font-black text-stone-950">{model.title}</h2>
        {model.stimulus ? <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-stone-700">{model.stimulus}</p> : null}
        {model.kind === "event" && eventNpcResponse(model.metadata, language) ? (
          <div data-testid="event-npc-response" className="mt-4 flex gap-3 rounded-xl border border-teal-200 bg-teal-50 p-3">
            <div className="relative grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-full bg-gradient-to-br from-teal-700 to-amber-400 text-sm font-black text-white">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {eventNpcPortraitUrl ? <img src={resolveApiAssetUrl(eventNpcPortraitUrl)} alt="" className="h-full w-full object-cover" /> : (eventNpcName?.slice(0, 1) ?? "NPC")}
            </div>
            <div>
              <p className="text-xs font-black uppercase tracking-wide text-teal-800">{eventNpcName ?? (isChinese ? "岛上居民" : "Island resident")}</p>
              <p className="mt-1 text-sm leading-6 text-stone-800">{eventNpcResponse(model.metadata, language)}</p>
            </div>
          </div>
        ) : null}
        <p className="sr-only">{model.kind === "event" ? `Event ${model.sourceType}, instance ${model.instanceId}` : `Scenario ${model.sourceType}, instance ${model.instanceId}`}</p>

        {model.kind === "event" ? (
          <div className="mt-6 space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              {model.actions.map((action, index) => {
                const selected = textActionId === action.action_id;
                const disabled = action.enabled === false || !canAction("event_action") || busy;
                return (
                  <button
                    key={action.action_id}
                    data-overlay-primary={index === 0 ? "" : undefined}
                    data-event-action-id={action.action_id}
                    type="button"
                    aria-pressed={action.requires_text ? selected : undefined}
                    disabled={disabled}
                    onClick={() => {
                      if (action.requires_text) setTextActionId(action.action_id);
                      else onEventAction(action);
                    }}
                    className={`focus-ring min-h-12 rounded-xl border px-4 py-3 text-left text-sm font-black disabled:opacity-50 ${selected ? "border-teal-600 bg-teal-50 text-teal-950" : "border-stone-300 bg-white text-stone-800 hover:border-teal-500"}`}
                  >
                    <span className="flex items-start gap-2">
                      <span className="mt-0.5 text-teal-700" aria-hidden="true">{eventActionIcon(action.kind)}</span>
                      <span>
                        <span className="block">{eventActionLabel(action, language)}</span>
                        {eventActionDetail(action, language) ? <span className="mt-1 block text-xs font-medium leading-5 text-stone-500">{eventActionDetail(action, language)}</span> : null}
                      </span>
                    </span>
                    <span className="sr-only"> ({action.action_id})</span>
                  </button>
                );
              })}
            </div>
            {textActionId ? (
              <div className="rounded-xl border border-teal-200 bg-teal-50/70 p-3">
                <label htmlFor="event-response" className="text-sm font-bold text-stone-800">
                  {isChinese ? "补充你的回应" : "Add your response"}
                </label>
                <textarea
                  id="event-response"
                  data-testid="event-response"
                  rows={3}
                  maxLength={1000}
                  value={eventResponse}
                  onChange={(event) => onEventResponseChange(event.target.value)}
                  className="focus-ring mt-2 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  data-event-action-id={`${textActionId}:submit`}
                  disabled={!eventResponse.trim() || busy}
                  onClick={() => {
                    const action = model.actions.find((item) => item.action_id === textActionId);
                    if (action) onEventAction(action);
                  }}
                  className="focus-ring mt-2 min-h-11 rounded-lg bg-teal-800 px-4 text-sm font-black text-white disabled:opacity-50"
                >
                  {isChinese ? "提交回应" : "Submit response"}
                </button>
              </div>
            ) : null}
          </div>
        ) : model.sourceType === "unsupported" ? (
          <div data-testid="unsupported-scenario" role="status" className="mt-5 rounded-xl border border-stone-200 bg-stone-100 px-4 py-3 text-sm leading-6 text-stone-600">
            {isChinese ? "这个旧场景没有可识别的通用选项。它仍保持原始状态，不会被自动提交。" : "This legacy scene has no recognized generic choices. Its original state remains unchanged."}
          </div>
        ) : model.sourceType === "seating" ? (
          <div className="mt-6 space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {model.seats.map((seat, index) => {
                const seatId = optionId(seat);
                const selected = seatId === selectedSeatId;
                const actionType = selectedSeatId && !selected ? "seat_change" : "seat_select";
                return (
                  <article key={seatId} data-testid={`seat-${seatId}`} className={`rounded-xl border p-4 ${selected ? "border-teal-500 bg-teal-50" : "border-stone-200 bg-white"}`}>
                    <div className="flex items-center gap-2"><Armchair className="h-4 w-4 text-teal-700" aria-hidden="true" /><h3 className="font-black text-stone-950">{optionLabel(seat, language)}</h3></div>
                    {optionDescription(seat, language) ? <p className="mt-2 text-xs leading-5 text-stone-600">{optionDescription(seat, language)}</p> : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button data-overlay-primary={index === 0 ? "" : undefined} data-action="seat-view" type="button" onClick={() => onSeatView(seatId)} disabled={seat.available === false || !canAction("seat_view", seatId) || busy} className="focus-ring min-h-10 rounded-lg border border-stone-300 px-3 text-xs font-bold text-stone-700 disabled:opacity-50">{isChinese ? "查看座位" : "View seat"}</button>
                      {!selected ? <button data-action={actionType === "seat_change" ? "seat-change" : "seat-select"} type="button" onClick={() => onSeatSelect(seatId, actionType)} disabled={seat.available === false || !canAction(actionType, seatId) || busy} className="focus-ring min-h-10 rounded-lg bg-teal-800 px-3 text-xs font-bold text-white disabled:opacity-50">{selectedSeatId ? isChinese ? "更换座位" : "Change seat" : isChinese ? "选择座位" : "Select seat"}</button> : null}
                    </div>
                  </article>
                );
              })}
            </div>
            <SkipButton language={language} disabled={!canAction("scenario_skip") || busy} onClick={onScenarioSkip} />
          </div>
        ) : (
          <div className="mt-6 space-y-4">
            {selectedSeatId && model.seats.length ? (
              <div className="rounded-xl border border-stone-200 bg-stone-100 p-3">
                <p className="mb-2 text-xs font-black uppercase tracking-wide text-stone-600">{isChinese ? "当前座位" : "Current seat"}</p>
                <div className="flex flex-wrap gap-2">
                  {model.seats.map((seat) => {
                    const seatId = optionId(seat);
                    const selected = seatId === selectedSeatId;
                    return <button key={seatId} data-testid={`seat-change-${seatId}`} type="button" disabled={selected || seat.available === false || !canAction("seat_change", seatId) || busy} onClick={() => onSeatSelect(seatId, "seat_change")} className="focus-ring min-h-10 rounded-lg border border-stone-300 bg-white px-3 text-xs font-bold disabled:opacity-50">{optionLabel(seat, language)}{selected ? isChinese ? " · 当前" : " · Current" : ""}</button>;
                  })}
                </div>
              </div>
            ) : null}
            <div className="grid gap-2 sm:grid-cols-3">
              <ChoiceButton primary label={isChinese ? "先澄清情况" : "Clarify"} icon={<Search className="h-4 w-4" />} responseCode="clarify" disabled={!canAction("scenario_response") || busy} onClick={() => onScenarioResponse("clarify")} />
              <ChoiceButton label={isChinese ? "协商解决" : "Negotiate"} icon={<Handshake className="h-4 w-4" />} responseCode="negotiate" disabled={!canAction("scenario_response") || busy} onClick={() => onScenarioResponse("negotiate")} />
              <ChoiceButton label={isChinese ? "离开现场" : "Leave"} icon={<Footprints className="h-4 w-4" />} responseCode="leave" disabled={!canAction("scenario_response") || busy} onClick={() => onScenarioResponse("leave")} />
            </div>
            <button type="button" aria-expanded={customOpen} onClick={() => setCustomOpen((value) => !value)} className="focus-ring min-h-11 w-full rounded-xl border border-stone-300 bg-white px-4 text-left text-sm font-bold text-stone-800">{isChinese ? "用自己的话回应" : "Use my own words"}</button>
            {customOpen ? (
              <div className="rounded-xl border border-teal-200 bg-teal-50/70 p-3">
                <label className="text-sm font-bold text-stone-800" htmlFor="scenario-response">{isChinese ? "用自己的话回应" : "Use my own words"}</label>
                <textarea id="scenario-response" rows={3} maxLength={1000} value={customResponse} onChange={(event) => onCustomResponseChange(event.target.value)} className="focus-ring mt-2 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm" />
                <button data-action="scenario-response" data-response-code="custom" type="button" onClick={() => onScenarioResponse("custom")} disabled={!customResponse.trim() || !canAction("scenario_response") || busy} className="focus-ring mt-2 min-h-11 rounded-lg bg-teal-800 px-4 text-sm font-black text-white disabled:opacity-50">{isChinese ? "提交回应" : "Submit response"}</button>
              </div>
            ) : null}
            <SkipButton language={language} disabled={!canAction("scenario_skip") || busy} onClick={onScenarioSkip} />
          </div>
        )}
      </section>
    </GameOverlayFrame>
  );
}

function SceneContext({ name, imageUrl, language }: { name: string; imageUrl?: string; language: Language }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = Boolean(imageUrl && failedUrl !== imageUrl);
  return (
    <div data-testid="narrative-scene-context" className="relative mb-5 flex min-h-24 items-end overflow-hidden rounded-xl bg-gradient-to-br from-teal-950 via-teal-800 to-amber-600 p-4 text-white">
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img data-testid="narrative-scene-image" src={resolveApiAssetUrl(imageUrl!)} alt="" className="absolute inset-0 h-full w-full object-cover" onError={() => setFailedUrl(imageUrl!)} />
      ) : null}
      <div className="absolute inset-0 bg-gradient-to-t from-stone-950/75 to-transparent" />
      <p className="relative text-sm font-black"><span className="sr-only">{language === "zh-CN" ? "当前地点：" : "Current place: "}</span>{name}</p>
    </div>
  );
}

function ChoiceButton({ primary, label, icon, responseCode, disabled, onClick }: { primary?: boolean; label: string; icon: ReactNode; responseCode: string; disabled: boolean; onClick: () => void }) {
  return <button data-overlay-primary={primary ? "" : undefined} data-action="scenario-response" data-response-code={responseCode} type="button" onClick={onClick} disabled={disabled} className="focus-ring flex min-h-12 items-center justify-center gap-2 rounded-xl border border-stone-300 bg-white px-3 text-sm font-black text-stone-800 hover:border-teal-500 disabled:opacity-50">{icon}{label}</button>;
}

function SkipButton({ language, disabled, onClick }: { language: Language; disabled: boolean; onClick: () => void }) {
  return <button data-action="scenario-skip" type="button" onClick={onClick} disabled={disabled} className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-xl border border-stone-300 bg-white px-4 text-sm font-bold text-stone-700 disabled:opacity-50"><SkipForward className="h-4 w-4" aria-hidden="true" />{language === "zh-CN" ? "跳过场景" : "Skip scene"}</button>;
}

function eventActionLabel(action: WorldEventAction, language: Language) {
  return action.labels?.[language] ?? (language === "zh-CN" ? action.label_zh_cn : action.label) ?? action.label ?? action.label_zh_cn ?? action.action_id.replaceAll("_", " ");
}

function eventNpcResponse(metadata: Record<string, unknown> | undefined, language: Language) {
  const raw = metadata?.npc_response;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return "";
  const text = (raw as Record<string, unknown>).text;
  if (!text || typeof text !== "object" || Array.isArray(text)) return "";
  const localized = text as Record<string, unknown>;
  const value = localized[language] ?? localized.en ?? localized["zh-CN"];
  return typeof value === "string" ? value : "";
}

function eventActionIcon(kind?: string) {
  if (kind === "inspect_object") return <Search className="h-4 w-4" />;
  if (kind === "select_seat" || kind === "move_position") return <Armchair className="h-4 w-4" />;
  if (kind === "start_conversation" || kind === "send_message" || kind === "continue_conversation") return <MessageCircle className="h-4 w-4" />;
  if (kind === "contact_npc") return <Phone className="h-4 w-4" />;
  if (kind === "check_map") return <Map className="h-4 w-4" />;
  if (kind === "wait") return <Clock3 className="h-4 w-4" />;
  if (kind === "complete_event") return <Utensils className="h-4 w-4" />;
  if (kind === "leave_location" || kind === "change_goal") return <Footprints className="h-4 w-4" />;
  return <Handshake className="h-4 w-4" />;
}

function eventActionDetail(action: WorldEventAction, language: Language) {
  const target = action.target_object_id;
  const details: Record<string, { en: string; "zh-CN": string }> = {
    group_table: { en: "Three residents are chatting here.", "zh-CN": "三位居民正在这里聊天。" },
    single_npc_table: { en: "One nearby diner; conversation is optional.", "zh-CN": "旁边只有一位客人，是否交谈都可以。" },
    central_empty_table: { en: "An open table within view of the room.", "zh-CN": "餐厅中央一张视野开阔的空桌。" },
    corner_table: { en: "A table by the wall, farther from occupied seats.", "zh-CN": "靠墙的位置，离有人用餐的桌子更远。" },
    takeaway_counter: { en: "Take the meal outdoors or carry it with you.", "zh-CN": "可以把餐点带到室外或随身带走。" },
  };
  return target && details[target] ? details[target][language] : "";
}

function optionId(option: WorldScenarioOption) {
  return String(option.target_object_id ?? option.object_id ?? option.option_id ?? option.id ?? option.value ?? "");
}

function optionLabel(option: WorldScenarioOption, language: Language) {
  if (option.label && typeof option.label === "object") return option.label[language] ?? option.label.en ?? option.label["zh-CN"] ?? optionId(option);
  const direct = (language === "zh-CN" ? option.label_zh_cn : option.label) ?? option.label ?? option.label_zh_cn;
  return typeof direct === "string" ? direct : optionId(option).replaceAll("_", " ");
}

function optionDescription(option: WorldScenarioOption, language: Language) {
  if (option.description && typeof option.description === "object") return option.description[language] ?? option.description.en ?? option.description["zh-CN"] ?? "";
  return (language === "zh-CN" ? option.description_zh_cn : option.description) ?? option.description ?? option.description_zh_cn ?? "";
}
