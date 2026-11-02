"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type ScaleOption = { value: number; label: string };
type Format = { format_id: "island" | "questionnaire"; label: string };
type Item = { number: number; text: string };

export type FormatExperiencePayload = {
  instrument_id: string;
  instrument_version: string;
  instrument_sha256: string;
  language: string;
  title: string;
  instructions: string;
  scale_options: ScaleOption[];
  formats: Format[];
  items: Item[];
  all_items_optional: boolean;
  explicit_skip_required: boolean;
};

type Props = {
  initialState: string;
  initialRevision: number;
  initialInstrument: FormatExperiencePayload | null;
};

type CommandResponse = {
  state: string;
  revision: number;
  current_step_path: string;
};

type Choice = number | "skipped";

function requestKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    const code = body?.detail?.code ?? body?.code ?? "format_feedback_request_failed";
    throw new Error(code);
  }
  return body;
}

export default function FormatExperienceFeedback({
  initialState,
  initialRevision,
  initialInstrument,
}: Props) {
  const router = useRouter();
  const [state, setState] = useState(initialState);
  const [revision, setRevision] = useState(initialRevision);
  const [instrument, setInstrument] = useState(initialInstrument);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInstrument = async () => {
    const response = await fetch("/study/api/format-feedback", { cache: "no-store" });
    setInstrument((await responseBody(response)) as FormatExperiencePayload);
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/study/api/begin-format-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: requestKey("begin-format-feedback"),
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      setState(result.state);
      setRevision(result.revision);
      await loadInstrument();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "format_feedback_start_failed");
    } finally {
      setBusy(false);
    }
  };

  const choiceKey = (formatId: string, itemNumber: number) => `${formatId}-${itemNumber}`;
  const requiredCount = (instrument?.formats.length ?? 2) * (instrument?.items.length ?? 6);
  const completedCount = Object.keys(choices).length;

  const skipAll = () => {
    if (!instrument) return;
    const skipped: Record<string, Choice> = {};
    for (const format of instrument.formats) {
      for (const item of instrument.items) {
        skipped[choiceKey(format.format_id, item.number)] = "skipped";
      }
    }
    setChoices(skipped);
    setError(null);
  };

  const submit = async () => {
    if (!instrument || completedCount !== requiredCount) {
      setError(`请对全部 ${requiredCount} 个评价项作答，或明确选择“跳过此项”。`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const ratings = instrument.formats.flatMap((format) =>
        instrument.items.map((item) => {
          const choice = choices[choiceKey(format.format_id, item.number)];
          return {
            format_id: format.format_id,
            item_number: item.number,
            value: choice === "skipped" ? null : choice,
            skipped: choice === "skipped",
          };
        }),
      );
      const response = await fetch("/study/api/format-feedback-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: requestKey("format-feedback-submit"),
          ratings,
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      router.replace(result.current_step_path);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "format_feedback_submit_failed");
    } finally {
      setBusy(false);
    }
  };

  if (state === "questionnaire_completed") {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">查看结果之前</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
          先评价两种体验方式
        </h1>
        <p className="mt-5 leading-7 text-slate-600">
          接下来请分别回顾虚拟岛屿互动与人格问卷。完成这一步以前，系统不会显示任何个人结果摘要。
        </p>
        <div className="mt-6 rounded-2xl bg-slate-50 p-5 text-sm leading-6 text-slate-600">
          每一题都可以跳过。系统会把“跳过”单独记录，不会用中间分数代替。
        </div>
        <button
          type="button"
          onClick={start}
          disabled={busy}
          data-testid="begin-format-feedback"
          className="mt-7 w-full rounded-2xl bg-teal-700 px-5 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-60"
        >
          {busy ? "正在载入…" : "开始体验评价"}
        </button>
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
      </section>
    );
  }

  if (!instrument) {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-8 text-slate-600">
        正在恢复体验评价…
      </section>
    );
  }

  return (
    <section className="w-full rounded-3xl border border-teal-100 bg-white p-5 shadow-sm sm:p-9">
      <header>
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p className="font-semibold text-teal-700">结果展示前 · Appendix A5</p>
          <p className="text-slate-500" data-testid="format-feedback-progress">
            已处理 {completedCount} / {requiredCount}
          </p>
        </div>
        <h1 className="mt-3 text-2xl font-semibold text-slate-900" data-testid="study-step">
          {instrument.title}
        </h1>
        <p className="mt-3 leading-7 text-slate-600">{instrument.instructions}</p>
        <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-600">
          {instrument.scale_options.map((option) => (
            <span key={option.value} className="rounded-full bg-slate-100 px-3 py-1.5">
              {option.value}{option.label ? ` ${option.label}` : ""}
            </span>
          ))}
        </div>
      </header>

      <div className="mt-7 space-y-5">
        {instrument.items.map((item) => (
          <fieldset key={item.number} className="rounded-2xl border border-slate-200 p-4 sm:p-5">
            <legend className="px-1 font-medium leading-7 text-slate-900">
              {item.number}. {item.text}
            </legend>
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              {instrument.formats.map((format) => {
                const key = choiceKey(format.format_id, item.number);
                const selected = choices[key];
                return (
                  <div key={format.format_id} className="rounded-xl bg-slate-50 p-3">
                    <p className="text-sm font-semibold text-slate-700">{format.label}</p>
                    <div className="mt-2 grid grid-cols-7 gap-1.5">
                      {instrument.scale_options.map((option) => (
                        <label
                          key={option.value}
                          data-testid={`format-${format.format_id}-${item.number}-${option.value}`}
                          className={`flex min-h-10 cursor-pointer items-center justify-center rounded-lg border text-sm font-semibold ${selected === option.value ? "border-teal-700 bg-teal-50 text-teal-800" : "border-slate-200 bg-white text-slate-600"}`}
                          title={`${option.value}${option.label ? ` ${option.label}` : ""}`}
                        >
                          <input
                            type="radio"
                            name={key}
                            value={option.value}
                            checked={selected === option.value}
                            onChange={() => {
                              setChoices((current) => ({ ...current, [key]: option.value }));
                              setError(null);
                            }}
                            className="sr-only"
                            data-testid={`format-input-${format.format_id}-${item.number}-${option.value}`}
                          />
                          {option.value}
                        </label>
                      ))}
                    </div>
                    <label
                      data-testid={`format-${format.format_id}-${item.number}-skip`}
                      className={`mt-2 flex cursor-pointer items-center justify-center rounded-lg border px-3 py-2 text-xs font-medium ${selected === "skipped" ? "border-slate-500 bg-slate-200 text-slate-800" : "border-slate-200 bg-white text-slate-500"}`}
                    >
                      <input
                        type="radio"
                        name={key}
                        checked={selected === "skipped"}
                        onChange={() => {
                          setChoices((current) => ({ ...current, [key]: "skipped" }));
                          setError(null);
                        }}
                        className="sr-only"
                        data-testid={`format-input-${format.format_id}-${item.number}-skip`}
                      />
                      跳过此项
                    </label>
                  </div>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>

      {error ? <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p> : null}
      <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:justify-between">
        <button
          type="button"
          onClick={skipAll}
          disabled={busy}
          data-testid="format-feedback-skip-all"
          className="rounded-xl border border-slate-300 px-5 py-3 font-semibold text-slate-700 disabled:opacity-50"
        >
          全部跳过
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={busy}
          data-testid="format-feedback-submit"
          className="rounded-xl bg-teal-700 px-6 py-3 font-semibold text-white disabled:opacity-60"
        >
          {busy ? "正在保存…" : "保存并准备两份结果"}
        </button>
      </div>
      <p className="mt-6 border-t border-slate-100 pt-4 text-xs text-slate-500">
        评价版本：{instrument.instrument_version}
      </p>
    </section>
  );
}
