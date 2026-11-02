"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type ComparisonOption = {
  value: "island" | "questionnaire" | "about_same" | "unsure";
  label: string;
};
type Item = { number: number; text: string };

export type ComparativeFeedbackPayload = {
  instrument_id: string;
  instrument_version: string;
  instrument_sha256: string;
  language: string;
  title: string;
  instructions: string;
  options: ComparisonOption[];
  items: Item[];
  open_feedback_title: string;
  open_feedback_items: Item[];
  all_items_optional: boolean;
  explicit_skip_required: boolean;
  open_feedback_max_length: number;
  not_applicable_items?: number[];
  appendix?: string;
};

type Props = {
  initialState: string;
  initialRevision: number;
  initialInstrument: ComparativeFeedbackPayload | null;
};

type CommandResponse = {
  state: string;
  revision: number;
  current_step_path: string;
};

type ComparisonChoice = ComparisonOption["value"] | "skipped" | "not_applicable";

function requestKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    const code = body?.detail?.code ?? body?.code ?? "comparative_feedback_request_failed";
    throw new Error(code);
  }
  return body;
}

export default function ComparativeFeedback({
  initialState,
  initialRevision,
  initialInstrument,
}: Props) {
  const router = useRouter();
  const [state, setState] = useState(initialState);
  const [revision, setRevision] = useState(initialRevision);
  const [instrument, setInstrument] = useState(initialInstrument);
  const [comparisons, setComparisons] = useState<Record<number, ComparisonChoice>>({});
  const [openValues, setOpenValues] = useState<Record<number, string>>({});
  const [openSkipped, setOpenSkipped] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInstrument = async () => {
    const response = await fetch("/study/api/comparison", { cache: "no-store" });
    setInstrument((await responseBody(response)) as ComparativeFeedbackPayload);
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/study/api/begin-comparison", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: requestKey("begin-comparison"),
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      setState(result.state);
      setRevision(result.revision);
      await loadInstrument();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "comparative_feedback_start_failed");
    } finally {
      setBusy(false);
    }
  };

  const skipAll = () => {
    if (!instrument) return;
    setComparisons(Object.fromEntries(instrument.items.map((item) => [item.number, "skipped"])));
    setOpenValues({});
    setOpenSkipped(Object.fromEntries(instrument.open_feedback_items.map((item) => [item.number, true])));
    setError(null);
  };

  const comparisonDone = instrument?.items.filter((item) => instrument.not_applicable_items?.includes(item.number) || comparisons[item.number]).length ?? 0;
  const openDone = instrument?.open_feedback_items.filter((item) => {
    return openSkipped[item.number] || Boolean(openValues[item.number]?.trim());
  }).length ?? 0;
  const total = (instrument?.items.length ?? 10) + (instrument?.open_feedback_items.length ?? 6);
  const completed = comparisonDone + openDone;

  const submit = async () => {
    if (!instrument || completed !== total) {
      setError(`请处理全部 ${total} 个可选项目：作答或明确选择“跳过此项”。`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/study/api/comparison-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: requestKey("comparison-submit"),
          comparisons: instrument.items.map((item) => ({
            item_number: item.number,
            choice: instrument.not_applicable_items?.includes(item.number) ? "not_applicable" : comparisons[item.number],
          })),
          open_feedback: instrument.open_feedback_items.map((item) => ({
            item_number: item.number,
            value: openSkipped[item.number] ? null : openValues[item.number]?.trim(),
            skipped: Boolean(openSkipped[item.number]),
          })),
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      router.replace(result.current_step_path);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "comparative_feedback_submit_failed");
    } finally {
      setBusy(false);
    }
  };

  if (state === "result_two_rated") {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">两份结果均已评价</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
          最后比较两种研究方式
        </h1>
        <p className="mt-5 leading-7 text-slate-600">
          接下来可以直接比较虚拟岛屿互动和人格问卷，也可以逐项跳过。开放题不要求您解释任何偏好。
        </p>
        <button
          type="button"
          onClick={start}
          disabled={busy}
          data-testid="begin-comparison"
          className="mt-7 w-full rounded-2xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60"
        >
          {busy ? "正在载入…" : "开始综合反馈"}
        </button>
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
      </section>
    );
  }

  if (!instrument) {
    return <section className="w-full rounded-3xl border border-teal-100 bg-white p-8 text-slate-600">正在恢复综合反馈…</section>;
  }

  return (
    <section className="w-full rounded-3xl border border-teal-100 bg-white p-5 shadow-sm sm:p-9">
      <header>
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p className="font-semibold text-teal-700">附录 {instrument.appendix ?? "A7"} · 所有适用项目均可跳过</p>
          <p className="text-slate-500" data-testid="comparison-progress">已处理 {completed} / {total}</p>
        </div>
        <h1 className="mt-3 text-2xl font-semibold text-slate-900" data-testid="study-step">{instrument.title}</h1>
        <p className="mt-3 leading-7 text-slate-600">{instrument.instructions}</p>
      </header>

      <div className="mt-7 space-y-4">
        {instrument.items.map((item) => instrument.not_applicable_items?.includes(item.number) ? (
          <div key={item.number} data-testid={`comparison-${item.number}-not-applicable`} className="rounded-2xl border border-slate-200 bg-slate-50 p-5"><p>{item.number}. {item.text}</p><p className="mt-2 text-sm text-slate-600">不适用：有报告未生成，无需评价。</p></div>
        ) : (
          <fieldset key={item.number} className="rounded-2xl border border-slate-200 p-4 sm:p-5">
            <legend className="px-1 font-medium leading-7 text-slate-900">{item.number}. {item.text}</legend>
            <div className="mt-3 grid gap-2 sm:grid-cols-5">
              {[...instrument.options, { value: "skipped" as const, label: "跳过此项" }].map((option) => {
                const selected = comparisons[item.number] === option.value;
                return (
                  <label
                    key={option.value}
                    className={`flex min-h-12 cursor-pointer items-center justify-center rounded-xl border px-3 py-2 text-center text-sm font-medium ${selected ? "border-teal-700 bg-teal-50 text-teal-800" : "border-slate-200 bg-white text-slate-600"}`}
                    data-testid={`comparison-${item.number}-${option.value}`}
                  >
                    <input
                      type="radio"
                      name={`comparison-${item.number}`}
                      checked={selected}
                      onChange={() => {
                        setComparisons((current) => ({ ...current, [item.number]: option.value }));
                        setError(null);
                      }}
                      className="sr-only"
                    />
                    {option.label}
                  </label>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>

      <section className="mt-9 border-t border-slate-200 pt-8" aria-labelledby="open-feedback-heading">
        <h2 id="open-feedback-heading" className="text-xl font-semibold text-slate-900">{instrument.open_feedback_title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          请不要填写姓名、邮箱、手机号或其他可直接识别您的信息。您无需解释不喜欢某份结果的原因。
        </p>
        <div className="mt-5 space-y-5">
          {instrument.open_feedback_items.map((item) => {
            const skipped = Boolean(openSkipped[item.number]);
            return (
              <fieldset key={item.number} className="rounded-2xl border border-slate-200 p-4 sm:p-5">
                <legend className="px-1 text-sm font-medium leading-6 text-slate-900">{item.number}. {item.text}</legend>
                <textarea
                  value={openValues[item.number] ?? ""}
                  disabled={skipped}
                  maxLength={instrument.open_feedback_max_length}
                  onChange={(event) => {
                    setOpenValues((current) => ({ ...current, [item.number]: event.target.value }));
                    setOpenSkipped((current) => ({ ...current, [item.number]: false }));
                    setError(null);
                  }}
                  data-testid={`open-feedback-${item.number}`}
                  className="mt-3 min-h-28 w-full resize-y rounded-xl border border-slate-300 px-3 py-2 text-sm leading-6 text-slate-800 outline-none focus:border-teal-600 disabled:bg-slate-100"
                  placeholder="可选填写"
                />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                  <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={skipped}
                      onChange={(event) => {
                        setOpenSkipped((current) => ({ ...current, [item.number]: event.target.checked }));
                        if (event.target.checked) {
                          setOpenValues((current) => ({ ...current, [item.number]: "" }));
                        }
                        setError(null);
                      }}
                      data-testid={`open-feedback-${item.number}-skip`}
                    />
                    跳过此项
                  </label>
                  <span>{(openValues[item.number] ?? "").length} / {instrument.open_feedback_max_length}</span>
                </div>
              </fieldset>
            );
          })}
        </div>
      </section>

      {error ? <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p> : null}
      <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:justify-between">
        <button type="button" onClick={skipAll} disabled={busy} data-testid="comparison-skip-all" className="rounded-xl border border-slate-300 px-5 py-3 font-semibold text-slate-700 disabled:opacity-50">全部跳过</button>
        <button type="button" onClick={submit} disabled={busy} data-testid="comparison-submit" className="rounded-xl bg-teal-700 px-6 py-3 font-semibold text-white disabled:opacity-60">{busy ? "正在保存…" : "保存并查看研究结束说明"}</button>
      </div>
      <p className="mt-6 border-t border-slate-100 pt-4 text-xs text-slate-500">评价版本：{instrument.instrument_version}</p>
    </section>
  );
}
