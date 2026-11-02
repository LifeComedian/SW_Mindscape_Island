"use client";

import type { WorldEvent, WorldEventAction } from "@/lib/api";
import type { Language } from "@/lib/i18n";

type Props = {
  event: WorldEvent;
  language: Language;
  responseText?: string;
  responsePlaceholder?: string;
  disabled?: boolean;
  preview?: boolean;
  onResponseTextChange?: (value: string) => void;
  onAction?: (action: WorldEventAction) => void;
};

export function WorldEventCard({
  event,
  language,
  responseText = "",
  responsePlaceholder = "Optional response",
  disabled = false,
  preview = false,
  onResponseTextChange,
  onAction,
}: Props) {
  return (
    <div
      data-testid={preview ? "studio-event-preview" : "active-event"}
      data-event-type={event.event_type}
      data-event-instance-id={event.event_instance_id}
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-bold text-stone-950">
          {eventTitle(event, language)}
        </h2>
        <span className="rounded-full bg-teal-100 px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-teal-900">
          {event.event_type}
        </span>
        {preview ? (
          <span className="rounded-full bg-amber-100 px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-amber-900">
            Preview
          </span>
        ) : null}
      </div>
      <p className="text-sm leading-6 text-stone-600">
        {eventStimulus(event, language)}
      </p>
      {event.actions?.some((action) => action.requires_text) ? (
        <textarea
          data-testid="event-response"
          value={responseText}
          onChange={(changeEvent) => onResponseTextChange?.(changeEvent.target.value)}
          rows={3}
          maxLength={1000}
          disabled={disabled || preview}
          placeholder={responsePlaceholder}
          className="focus-ring w-full rounded-md border border-stone-300 px-3 py-2 text-sm disabled:bg-stone-50"
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        {(event.actions ?? []).map((action) => (
          <button
            key={action.action_id}
            type="button"
            data-action="event-action"
            data-event-action-id={action.action_id}
            onClick={() => onAction?.(action)}
            disabled={
              preview ||
              disabled ||
              action.enabled === false ||
              Boolean(action.requires_text && !responseText.trim())
            }
            className="focus-ring rounded-md border border-stone-300 bg-white px-4 py-2 text-sm font-semibold text-stone-700 hover:bg-stone-50 disabled:opacity-50"
          >
            {eventActionLabel(action, language)}
          </button>
        ))}
      </div>
    </div>
  );
}

function eventTitle(event: WorldEvent, language: Language) {
  return event.titles?.[language] ??
    (language === "zh-CN" ? event.title_zh_cn : event.title) ??
    event.title ??
    event.title_zh_cn ??
    humanize(event.event_type);
}

function eventStimulus(event: WorldEvent, language: Language) {
  return event.stimuli?.[language] ??
    (language === "zh-CN" ? event.stimulus_text_zh_cn : event.stimulus_text) ??
    event.stimulus_text ??
    event.stimulus_text_zh_cn ??
    "";
}

function eventActionLabel(action: WorldEventAction, language: Language) {
  return action.labels?.[language] ??
    (language === "zh-CN" ? action.label_zh_cn : action.label) ??
    action.label ??
    action.label_zh_cn ??
    humanize(action.action_id);
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
