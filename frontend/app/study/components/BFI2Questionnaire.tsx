"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type InstrumentItem = { number: number; text: string };
type ScaleOption = { value: number; label: string };
export type InstrumentPayload = {
  instrument_id: string;
  instrument_version: string;
  instrument_sha256: string;
  language: string;
  title: string;
  instructions: string;
  item_stem: string;
  scale_options: ScaleOption[];
  items: InstrumentItem[];
  source_notice: string;
  draft_revision: number;
  draft_answers: Record<string, number>;
  answer_count: number;
  required_answer_count: number;
  scoring_key_exposed: boolean;
  items_optional?: boolean;
  draft_skipped_items?: number[];
};

type Props = {
  initialState: string;
  initialRevision: number;
  initialInstrument: InstrumentPayload | null;
  optionalItems?: boolean;
  reviewMode?: boolean;
};

type CommandResponse = {
  state: string;
  revision: number;
  current_step_path: string;
};

const ITEMS_PER_PAGE = 10;

function requestKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    const code = body?.detail?.code ?? body?.code ?? "questionnaire_request_failed";
    throw new Error(code);
  }
  return body;
}

export default function BFI2Questionnaire({
  initialState,
  initialRevision,
  initialInstrument, optionalItems=false, reviewMode=false,
}: Props) {
  const router = useRouter();
  const [state, setState] = useState(initialState);
  const [studyRevision, setStudyRevision] = useState(initialRevision);
  const [instrument, setInstrument] = useState<InstrumentPayload | null>(initialInstrument);
  const [answers, setAnswers] = useState<Record<string, number>>(
    initialInstrument?.draft_answers ?? {},
  );
  const [skipped,setSkipped]=useState<number[]>(initialInstrument?.draft_skipped_items ?? []);
  const optional=instrument?.items_optional ?? optionalItems;
  const [draftRevision, setDraftRevision] = useState(initialInstrument?.draft_revision ?? 0);
  const [pageIndex, setPageIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadInstrument = async () => {
    const response = await fetch("/study/api/questionnaire", { cache: "no-store" });
    const payload = (await responseBody(response)) as InstrumentPayload;
    setInstrument(payload);
    setAnswers(payload.draft_answers ?? {});
    setSkipped(payload.draft_skipped_items ?? []);
    setDraftRevision(payload.draft_revision);
  };

  useEffect(() => {
    if (state !== "questionnaire_active") return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [state]);

  const currentItems = useMemo(
    () => instrument?.items.slice(pageIndex * ITEMS_PER_PAGE, (pageIndex + 1) * ITEMS_PER_PAGE) ?? [],
    [instrument, pageIndex],
  );
  const answeredCount = Object.keys(answers).length;
  const totalPages = instrument ? Math.ceil(instrument.items.length / ITEMS_PER_PAGE) : 6;

  const startQuestionnaire = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/study/api/begin-questionnaire", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: studyRevision,
          idempotency_key: requestKey("begin-questionnaire"),
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      setState(result.state);
      setStudyRevision(result.revision);
      await loadInstrument();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "questionnaire_start_failed");
    } finally {
      setBusy(false);
    }
  };

  const serializedAnswers = () =>
    Object.entries(answers)
      .map(([itemNumber, value]) => ({ item_number: Number(itemNumber), value }))
      .sort((left, right) => left.item_number - right.item_number);

  const saveDraft = async () => {
    const response = await fetch("/study/api/questionnaire-draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_draft_revision: draftRevision,
        idempotency_key: requestKey("questionnaire-draft"),
        answers: serializedAnswers(),
        skipped_items: optional ? skipped : [],
      }),
    });
    const saved = (await responseBody(response)) as { draft_revision: number; answer_count: number };
    setDraftRevision(saved.draft_revision);
    setNotice(`已安全保存 ${saved.answer_count} / 60 题`);
  };

  const nextPage = async () => {
    const missing = currentItems.filter((item) => answers[String(item.number)] === undefined && !(optional && skipped.includes(item.number)));
    if (missing.length > 0) {
      setError(`请先作答或跳过本页尚未处理的题目：${missing.map((item) => item.number).join("、")}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await saveDraft();
      setPageIndex((current) => Math.min(current + 1, totalPages - 1));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "questionnaire_save_failed");
    } finally {
      setBusy(false);
    }
  };

  const submit = async (skipRemaining=false) => {
    const submittedSkips=optional && skipRemaining ? Array.from({length:60},(_,i)=>i+1).filter(n=>answers[String(n)]===undefined) : skipped;
    if (optional ? answeredCount+submittedSkips.length!==60 : answeredCount !== 60) {
      setError(`仍有 ${60 - answeredCount} 题未完成。请返回对应页面作答。`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/study/api/questionnaire-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: studyRevision,
          idempotency_key: requestKey("questionnaire-submit"),
          answers: serializedAnswers(),
          skipped_items: optional ? submittedSkips : [],
        }),
      });
      const result = (await responseBody(response)) as CommandResponse;
      setState(result.state);
      setStudyRevision(result.revision);
      router.replace(result.current_step_path);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "questionnaire_submit_failed");
    } finally {
      setBusy(false);
    }
  };

  if (state === "game_estimate_frozen" || state === "game_estimate_insufficient") {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">标准化问卷</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
          大五人格问卷第二版（BFI-2）
        </h1>
        <p className="mt-5 leading-7 text-slate-600">
          {optional ? `接下来共有60个描述，每题均可跳过，预计约10分钟。未答满60题时不生成完整问卷报告，但仍可继续${reviewMode ? '。' : '，补偿资格不受影响。'}` : "接下来共有60个必答描述，预计约10分钟。"} 请按照你此刻对自己的认识作答；没有正确或错误答案。
        </p>
        <div className="mt-6 rounded-2xl bg-slate-50 p-5 text-sm leading-6 text-slate-600">
          问卷结果由固定计分规则生成，不会交给语言模型重算或改写。提交后答案将冻结，不能重新作答来选择不同结果。
        </div>
        <button
          type="button"
          onClick={startQuestionnaire}
          disabled={busy}
          data-testid="begin-questionnaire"
          className="mt-7 w-full rounded-2xl bg-teal-700 px-5 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-60"
        >
          {busy ? "正在载入…" : "开始问卷"}
        </button>
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
      </section>
    );
  }

  if (!instrument) {
    return (
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-8 text-slate-600">
        正在恢复问卷与已保存的回答…
        {error ? <p className="mt-4 text-rose-700" role="alert">{error}</p> : null}
      </section>
    );
  }

  return (
    <section className="w-full rounded-3xl border border-teal-100 bg-white p-5 shadow-sm sm:p-9">
      <header>
        <div className="flex items-center justify-between gap-4 text-sm">
          <p className="font-semibold text-teal-700">BFI-2 · 第 {pageIndex + 1} / {totalPages} 页</p>
          <p className="text-slate-500" data-testid="questionnaire-progress">已答 {answeredCount} / 60</p>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
          <div className="h-full rounded-full bg-teal-600 transition-all" style={{ width: `${(answeredCount / 60) * 100}%` }} />
        </div>
        <h1 className="mt-5 text-2xl font-semibold text-slate-900" data-testid="study-step">{instrument.title}</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">{reviewMode ? instrument.instructions.replace('，补偿资格不受影响', '') : instrument.instructions}</p>
      </header>

      <div className="mt-5 grid grid-cols-5 gap-1 rounded-xl bg-slate-50 p-3 text-center text-xs text-slate-600 sm:gap-3">
        {instrument.scale_options.map((option) => (
          <div key={option.value}>
            <span className="font-semibold text-slate-800">{option.value}</span>
            <span className="hidden sm:block">{option.label}</span>
          </div>
        ))}
      </div>

      <div className="mt-6 space-y-4">
        {currentItems.map((item) => (
          <fieldset key={item.number} className="rounded-2xl border border-slate-200 p-4">
            <legend className="px-1 text-sm font-medium leading-6 text-slate-900">
              {item.number}. {instrument.item_stem}：{item.text}
            </legend>
            <div className="mt-3 grid grid-cols-5 gap-2">
              {instrument.scale_options.map((option) => {
                const selected = answers[String(item.number)] === option.value;
                return (
                  <label
                    key={option.value}
                    className={`flex min-h-11 cursor-pointer items-center justify-center rounded-xl border text-sm font-semibold transition ${selected ? "border-teal-700 bg-teal-50 text-teal-800" : "border-slate-200 text-slate-600 hover:border-teal-300"}`}
                    title={`${option.value} ${option.label}`}
                    data-testid={`answer-${item.number}-${option.value}`}
                  >
                    <input
                      type="radio"
                      disabled={busy}
                      name={`item-${item.number}`}
                      value={option.value}
                      checked={selected}
                      onChange={() => {
                        setAnswers((current) => ({ ...current, [String(item.number)]: option.value }));
                        setSkipped(current=>current.filter(n=>n!==item.number));
                        setNotice(null);
                        setError(null);
                      }}
                      className="sr-only"
                      data-testid={`answer-input-${item.number}-${option.value}`}
                    />
                    <span aria-hidden="true">{option.value}</span>
                    <span className="sr-only">{option.label}</span>
                  </label>
                );
              })}
            </div>
            {optional ? <button type="button" disabled={busy} data-testid={`questionnaire-skip-${item.number}`} aria-pressed={skipped.includes(item.number)} onClick={()=>{setAnswers(current=>{const next={...current};delete next[String(item.number)];return next;});setSkipped(current=>Array.from(new Set([...current,item.number])));setError(null);}} className="mt-3 rounded-lg border px-4 py-2 text-sm">{skipped.includes(item.number) ? "已跳过此题" : "跳过此题"}</button> : null}
          </fieldset>
        ))}
      </div>

      {error ? <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p> : null}
      {notice ? <p className="mt-5 text-sm text-emerald-700" role="status">{notice}</p> : null}

      <div className="mt-7 flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
        <button
          type="button"
          onClick={() => {
            setPageIndex((current) => Math.max(0, current - 1));
            setError(null);
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
          disabled={pageIndex === 0 || busy}
          className="rounded-xl border border-slate-300 px-5 py-3 font-semibold text-slate-700 disabled:opacity-40"
        >
          上一页
        </button>
        {pageIndex < totalPages - 1 ? (
          <button
            type="button"
            onClick={nextPage}
            disabled={busy}
            data-testid="questionnaire-next"
            className="rounded-xl bg-teal-700 px-6 py-3 font-semibold text-white disabled:opacity-60"
          >
            {busy ? "正在保存…" : "保存并进入下一页"}
          </button>
        ) : (
          <button
            type="button"
            onClick={()=>void submit()}
            disabled={busy}
            data-testid="questionnaire-submit"
            className="rounded-xl bg-teal-700 px-6 py-3 font-semibold text-white disabled:opacity-60"
          >
            {busy ? "正在提交并计分…" : "提交问卷并冻结答案"}
          </button>
        )}
      </div>

      {optional ? <button type="button" disabled={busy} onClick={()=>void submit(true)} data-testid="questionnaire-skip-remaining" className="mt-5 w-full rounded-xl border border-slate-300 px-5 py-3">跳过剩余未答题并提交（保留已答 {answeredCount} 题）</button> : null}
      <p className="mt-7 border-t border-slate-100 pt-5 text-xs leading-5 text-slate-500">
        {instrument.source_notice} · 量表版本：{instrument.instrument_version}
      </p>
    </section>
  );
}
