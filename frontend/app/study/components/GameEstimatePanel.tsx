"use client";

import { useState } from "react";
import Link from "next/link";

type CommandResponse = {
  state: string;
  revision: number;
  current_step_path: string;
  replayed: boolean;
};

type AssessmentStatus = {
  state: string;
  revision: number;
  job_status: string;
  attempt_count?: number;
  last_error_code?: string;
  package_id?: string;
  package_version?: string;
  package_sha256?: string;
  input_sha256?: string;
  output_sha256?: string;
  fixture_only: boolean;
  frozen_at?: string;
};

type Props = {
  initialState: string;
  initialRevision: number;
  allowUnavailableContinue?: boolean;
};

function commandKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function postCommand(command: string, revision: number): Promise<CommandResponse> {
  const response = await fetch(`/study/api/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      expected_revision: revision,
      idempotency_key: commandKey(command),
    }),
  });
  const body = (await response.json()) as CommandResponse & {
    code?: string;
    detail?: { code?: string };
  };
  if (!response.ok) {
    throw new Error(body.detail?.code ?? body.code ?? "assessment_request_failed");
  }
  return body;
}

export default function GameEstimatePanel({ initialState, initialRevision, allowUnavailableContinue=false }: Props) {
  const [state, setState] = useState(initialState);
  const [revision, setRevision] = useState(initialRevision);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<AssessmentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const processEstimate = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      let activeState = state;
      let activeRevision = revision;
      if (activeState === "island_completed" || activeState === "game_estimate_failed") {
        const begun = await postCommand("begin-game-estimate", activeRevision);
        activeState = begun.state;
        activeRevision = begun.revision;
        setState(activeState);
        setRevision(activeRevision);
      }
      if (activeState !== "game_estimate_processing") {
        throw new Error("assessment_not_ready");
      }
      const completed = await postCommand("run-game-estimate", activeRevision);
      setState(completed.state);
      setRevision(completed.revision);
      const statusResponse = await fetch("/study/api/game-estimate", { cache: "no-store" });
      if (!statusResponse.ok) throw new Error("assessment_status_unavailable");
      setStatus((await statusResponse.json()) as AssessmentStatus);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "assessment_request_failed");
      const currentResponse = await fetch("/study/api/current-step", { cache: "no-store" });
      if (currentResponse.ok) {
        const current = (await currentResponse.json()) as { state: string; revision: number };
        setState(current.state);
        setRevision(current.revision);
      }
    } finally {
      setBusy(false);
    }
  };

  const frozen = state === "game_estimate_frozen" || state === "game_estimate_insufficient";
  const failed = state === "game_estimate_failed";

  return (
    <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
      <p className="text-sm font-semibold tracking-wide text-teal-700">{process.env.NEXT_PUBLIC_MEETING_DEMO === "true" ? "第一天演示已结束" : "七日体验已结束"}</p>
      <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
        {frozen ? "岛屿报告已准备好，接下来填写量表" : failed ? "报告暂时未能生成" : "正在整理你的岛屿旅程"}
      </h1>
      <p className="mt-5 leading-7 text-slate-600">
        你的岛屿体验已经结束。岛屿报告会先单独生成并保存，然后进入心理量表。提交问卷后，你会查看可用的报告，并分享自己的感受。报告未生成或问卷未全部作答时，会如实说明。
      </p>

      {status?.fixture_only ? (
        <div
          className="mt-6 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm font-semibold text-amber-900"
          data-testid="fixture-watermark"
        >
          本轮使用测试报告验证完整流程，不是根据你的游戏表现生成的正式评估。
        </div>
      ) : null}

      {frozen ? (
        <div className="mt-6 rounded-2xl bg-emerald-50 p-5 text-sm text-emerald-950">
          <div>
            <p className="mt-1 font-semibold" data-testid="estimate-status">
              {state === "game_estimate_insufficient" ? "本次可整理的观察有限，已保存记录与说明；未评人格分数不代表低分。你仍可继续后面的流程。" : "你的岛屿观察报告已生成，依据本次行为与交流整理，不提供人格分数。接下来的量表答案不会改变它。"}
            </p>
          </div>
          {status?.fixture_only ? <details className="mt-3 text-xs text-emerald-700">
            <summary>本地测试校验信息</summary>
            <p className="mt-1 break-all font-mono text-xs" data-testid="estimate-output-hash">
              {status?.output_sha256 ?? "已由服务端保存"}
            </p>
          </details> : null}
        </div>
      ) : (
        <button
          type="button"
          onClick={processEstimate}
          disabled={busy}
          data-testid="process-game-estimate"
          className="mt-7 w-full rounded-2xl bg-teal-700 px-5 py-3 font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "正在整理，请稍候…" : failed ? "重新生成报告" : state === "game_estimate_processing" ? "继续整理报告" : "整理我的岛屿旅程"}
        </button>
      )}

      {error ? (
        <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">
          报告暂时未能完成，请稍后重试。你的旅程进度已经保存。（{error}）
        </p>
      ) : null}

      {failed && allowUnavailableContinue ? <button type="button" disabled={busy} data-testid="continue-without-game-report" className="mt-5 w-full rounded-xl border px-5 py-3" onClick={async()=>{setBusy(true);try{const result=await postCommand("begin-questionnaire",revision);window.location.assign(result.current_step_path);}catch{setError("暂时无法继续，请刷新后重试。");setBusy(false);}}}>不重试，继续问卷（该报告记为不可用）</button> : null}
      {frozen ? <Link href="/study/questionnaire" data-testid="continue-questionnaire" className="mt-7 block rounded-2xl bg-teal-700 px-5 py-3 text-center font-semibold text-white hover:bg-teal-800">继续填写心理量表</Link> : null}

      <p className="mt-6 text-xs leading-5 text-slate-500">
        可用报告会在问卷提交后展示。本页只负责准备报告。
      </p>
    </section>
  );
}
