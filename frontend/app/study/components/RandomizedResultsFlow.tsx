"use client";

import { useState } from "react";
import IslandRecap, {type Recap} from "./IslandRecap";
import { useRouter } from "next/navigation";

type ScaleOption = { value: number; label: string };
type EvaluationItem = { number: number; text: string };
type EvaluationInstrument = {
  instrument_version: string;
  title: string;
  instructions: string;
  scale_options: ScaleOption[];
  items: EvaluationItem[];
};
type Dimension = {
  domain_id: string;
  label: string;
  status: string;
  value: number | null;
  maximum: number | null;
  description: string;
};
type Report = {
  report_kind: "game_estimate" | "questionnaire";
  title: string;
  source: string;
  summary: string;
  dimensions: Dimension[];
  scale_note: string;
  uncertainty_note: string;
  limitations: string[];
  fixture_only: boolean;
  watermark: string | null;
  integrity_sha256: string;
  evidence?: {source_id:string;day:number;minute:number;description:string;location:string}[];
  recap?: Recap;
  letter_paragraphs?: {text:string;evidence:{source_id:string;description:string}[]}[];
};
export type CurrentResultPayload = {
  position: number;
  total: number;
  evaluation_instrument: EvaluationInstrument;
  report: Report;
};
type Props = {
  initialState: string;
  initialRevision: number;
  initialResult: CurrentResultPayload | null;
  totalAvailable?: number;
};
type CommandResponse = {
  state: string;
  revision: number;
  current_step_path: string;
};
type RevealResponse = CommandResponse & CurrentResultPayload;
type Choice = number | "skipped";

function requestKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    const code = body?.detail?.code ?? body?.code ?? "result_request_failed";
    throw new Error(code);
  }
  return body;
}

export default function RandomizedResultsFlow({
  initialState,
  initialRevision,
  initialResult, totalAvailable=2,
}: Props) {
  const router = useRouter();
  const [state, setState] = useState(initialState);
  const [revision, setRevision] = useState(initialRevision);
  const [current, setCurrent] = useState(initialResult);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reveal = async (position: 1 | 2) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/study/api/view-result-${position === 1 ? "one" : "two"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: requestKey(`view-result-${position}`),
        }),
      });
      const result = (await responseBody(response)) as RevealResponse;
      setState(result.state);
      setRevision(result.revision);
      setCurrent({
        position: result.position,
        total: result.total,
        evaluation_instrument: result.evaluation_instrument,
        report: result.report,
      });
      setChoices({});
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "result_reveal_failed");
    } finally {
      setBusy(false);
    }
  };

  const skipAll = () => {
    if (!current) return;
    setChoices(
      Object.fromEntries(current.evaluation_instrument.items.map((item) => [String(item.number), "skipped"])),
    );
    setError(null);
  };

  const submitRating = async () => {
    if (!current || Object.keys(choices).length !== 4) {
      setError("请对四个评价项作答，或明确选择“跳过此项”。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const ratings = current.evaluation_instrument.items.map((item) => {
        const choice = choices[String(item.number)];
        return {
          item_number: item.number,
          value: choice === "skipped" ? null : choice,
          skipped: choice === "skipped",
        };
      });
      const response = await fetch("/study/api/result-rating", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: requestKey(`rate-result-${current.position}`),
          ratings,
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      setState(result.state);
      setRevision(result.revision);
      setCurrent(null);
      setChoices({});
      if (result.state === "result_two_rated" || result.state === "comparative_feedback") {
        router.replace(result.current_step_path);
        router.refresh();
      } else {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "result_rating_failed");
    } finally {
      setBusy(false);
    }
  };

  if (state === "results_ready") {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">{totalAvailable === 2 ? "两份可用结果 · 随机顺序" : "一份可用结果"}</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
          结果已准备好
        </h1>
        <p className="mt-5 leading-7 text-slate-600">
          {totalAvailable===2 ? "系统已经固定展示顺序。每次只显示一份结果，评价后查看下一份。" : "另一份报告不可用，因此只展示可用报告；不需要评价未生成的报告。"}
        </p>
        <p className="mt-4 rounded-2xl bg-slate-50 p-5 text-sm leading-6 text-slate-600">
          结果是非诊断性的研究摘要，页面不会用颜色或标签暗示哪一份更正确。
        </p>
        <button
          type="button"
          onClick={() => reveal(1)}
          disabled={busy}
          data-testid="view-result-one"
          className="mt-7 w-full rounded-2xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60"
        >
          {busy ? "正在载入…" : "查看第一份结果"}
        </button>
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
      </section>
    );
  }

  if (state === "result_one_rated") {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">第一份评价已保存</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
          准备查看第二份结果
        </h1>
        <p className="mt-5 leading-7 text-slate-600">
          第一份结果和评价已经冻结。第二份结果来自另一种研究形式，并使用相同的中性展示结构。
        </p>
        <button
          type="button"
          onClick={() => reveal(2)}
          disabled={busy}
          data-testid="view-result-two"
          className="mt-7 w-full rounded-2xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60"
        >
          {busy ? "正在载入…" : "查看第二份结果"}
        </button>
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
      </section>
    );
  }

  if (!current) {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-8 text-slate-600">
        正在恢复当前允许查看的结果…
      </section>
    );
  }

  const { report, evaluation_instrument: instrument } = current;
  return (
    <div className="w-full space-y-6">
      <article className="rounded-3xl border border-teal-100 bg-white p-5 shadow-sm sm:p-9" data-testid="result-report">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-semibold text-teal-700">第 {current.position} / {current.total} 份结果</p>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">非诊断性研究摘要</span>
        </div>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900" data-testid="result-title">{report.title}</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600" data-testid="result-source">{report.source}</p>
        {report.watermark ? (
          <p className="mt-5 rounded-2xl border border-slate-300 bg-slate-50 p-4 text-sm font-semibold text-slate-700" data-testid="fixture-watermark">
            {report.watermark}{report.fixture_only ? ' · 当前内容仅用于验证研究流程。' : ''}
          </p>
        ) : null}
        {report.recap&&<div className="mt-8"><IslandRecap data={report.recap}/></div>}
        {report.letter_paragraphs ? <div className="mt-7 space-y-7 rounded-2xl bg-[#fffdf7] p-5 text-lg leading-9 text-slate-800 sm:p-8" data-testid="island-letter">
          {report.letter_paragraphs.map((paragraph,index)=><section key={index}>
            <p className="whitespace-pre-wrap">{paragraph.text}</p>
            {!!paragraph.evidence.length&&<details className="mt-3 border-l-2 border-teal-100 pl-4 text-sm leading-7 text-slate-600">
              <summary className="cursor-pointer">这段观察来自哪里</summary>
              {paragraph.evidence.map(item=><p key={item.source_id} className="mt-2">{item.description}</p>)}
            </details>}
          </section>)}
        </div> : <div className="mt-6 rounded-2xl bg-slate-50 p-5 text-sm leading-7 text-slate-700">
          {report.summary.split("\n").map((line, index) => <p key={index}>{line}</p>)}
        </div>}
        {!report.letter_paragraphs&&<section className="mt-7" aria-labelledby="dimension-heading">
          <h2 id="dimension-heading" className="text-lg font-semibold text-slate-900">{report.report_kind === 'game_estimate' ? '观察与证据不足的说明' : '连续维度'}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{report.scale_note}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {report.dimensions.map((dimension) => (
              <div key={dimension.domain_id} className="rounded-2xl border border-slate-200 p-4" data-testid={`dimension-${dimension.domain_id}`}>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="font-semibold text-slate-900">{dimension.label}</h3>
                  <span className="text-sm font-semibold text-slate-700">
                    {dimension.value === null ? "未估计" : `${Number(dimension.value).toFixed(2)} / ${Number(dimension.maximum).toFixed(2)}`}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{dimension.description}</p>
              </div>
            ))}
          </div>
        </section>}
        {report.evidence?.length ? <details className="mt-7 rounded-2xl border border-teal-200 p-5" data-testid="report-evidence"><summary className="cursor-pointer font-semibold">查看这份观察使用的记录（{report.evidence.length}条）</summary><ul className="mt-3 space-y-3">{report.evidence.map(e=><li key={e.source_id} className="text-sm leading-6">第{e.day}天 {String(Math.floor(e.minute/60)).padStart(2,'0')}:{String(e.minute%60).padStart(2,'0')} · {e.location} · {e.description}<span className="ml-2 text-xs text-slate-500">记录 {e.source_id}</span></li>)}</ul><p className="mt-3 text-sm text-slate-500">这些是规则整理后的线索，不是对原话的逐字引用，也不等于稳定人格。</p></details> : null}
        <section className="mt-7 rounded-2xl border border-slate-200 p-5">
          <h2 className="font-semibold text-slate-900">不确定性与限制</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{report.uncertainty_note}</p>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-600">
            {report.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          </ul>
        </section>
        <p className="mt-5 break-all border-t border-slate-100 pt-4 text-xs text-slate-400">结果完整性：{report.integrity_sha256}</p>
      </article>

      <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-9" aria-labelledby="rating-heading">
        <p className="text-sm font-semibold text-slate-600">报告评价 · 评价对象：{report.title}</p>
        <h2 id="rating-heading" className="mt-2 text-2xl font-semibold text-slate-900">{instrument.title}</h2>
        <p className="mt-3 leading-7 text-slate-600">{instrument.instructions}</p>
        <div className="mt-6 space-y-4">
          {instrument.items.map((item) => {
            const selected = choices[String(item.number)];
            return (
              <fieldset key={item.number} className="rounded-2xl border border-slate-200 p-4">
                <legend className="px-1 text-sm font-medium leading-6 text-slate-900">{item.number}. {item.text}</legend>
                <div className="mt-3 grid grid-cols-7 gap-1.5">
                  {instrument.scale_options.map((option) => (
                    <label
                      key={option.value}
                      data-testid={`result-rating-${item.number}-${option.value}`}
                      className={`flex min-h-10 cursor-pointer items-center justify-center rounded-lg border text-sm font-semibold ${selected === option.value ? "border-teal-700 bg-teal-50 text-teal-800" : "border-slate-200 text-slate-600"}`}
                      title={`${option.value}${option.label ? ` ${option.label}` : ""}`}
                    >
                      <input
                        type="radio"
                        name={`result-rating-${item.number}`}
                        checked={selected === option.value}
                        onChange={() => {
                          setChoices((existing) => ({ ...existing, [String(item.number)]: option.value }));
                          setError(null);
                        }}
                        className="sr-only"
                        data-testid={`result-rating-input-${item.number}-${option.value}`}
                      />
                      {option.value}
                    </label>
                  ))}
                </div>
                <label
                  data-testid={`result-rating-${item.number}-skip`}
                  className={`mt-2 flex cursor-pointer items-center justify-center rounded-lg border px-3 py-2 text-xs font-medium ${selected === "skipped" ? "border-slate-500 bg-slate-200 text-slate-800" : "border-slate-200 text-slate-500"}`}
                >
                  <input
                    type="radio"
                    name={`result-rating-${item.number}`}
                    checked={selected === "skipped"}
                    onChange={() => {
                      setChoices((existing) => ({ ...existing, [String(item.number)]: "skipped" }));
                      setError(null);
                    }}
                    className="sr-only"
                    data-testid={`result-rating-input-${item.number}-skip`}
                  />
                  跳过此项
                </label>
              </fieldset>
            );
          })}
        </div>
        {error ? <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p> : null}
        <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:justify-between">
          <button type="button" onClick={skipAll} disabled={busy} data-testid="result-rating-skip-all" className="rounded-xl border border-slate-300 px-5 py-3 font-semibold text-slate-700 disabled:opacity-50">全部跳过</button>
          <button type="button" onClick={submitRating} disabled={busy} data-testid="result-rating-submit" className="rounded-xl bg-teal-700 px-6 py-3 font-semibold text-white disabled:opacity-60">
            {busy ? "正在保存…" : current.position === 1 ? "保存评价并继续" : "保存第二份评价"}
          </button>
        </div>
      </section>
    </div>
  );
}
