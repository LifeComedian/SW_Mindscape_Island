import { redirect } from "next/navigation";
import ExitInformation from '@/app/study/components/ExitInformation';

import GameEstimatePanel from "@/app/study/components/GameEstimatePanel";
import BFI2Questionnaire, {
  type InstrumentPayload,
} from "@/app/study/components/BFI2Questionnaire";
import FormatExperienceFeedback, {
  type FormatExperiencePayload,
} from "@/app/study/components/FormatExperienceFeedback";
import RandomizedResultsFlow, {
  type CurrentResultPayload,
} from "@/app/study/components/RandomizedResultsFlow";
import ComparativeFeedback, {
  type ComparativeFeedbackPayload,
} from "@/app/study/components/ComparativeFeedback";
import DebriefAndCompletion, {
  type DebriefPayload,
} from "@/app/study/components/DebriefAndCompletion";
import CompletionReceipt, {
  type CompletionReceiptPayload,
} from "@/app/study/components/CompletionReceipt";
import {
  readAuthoritativeStudyStep,
  readProtectedStudyResource,
  readComparativeFeedback,
  readCompletionReceipt,
  readCurrentResult,
  readDebrief,
  readFormatFeedbackInstrument,
  readQuestionnaireInstrument,
} from "@/lib/study-workflow";

type Props = {
  params: Promise<{ step: string }>;
};

export default async function StudyStepGuardPage({ params }: Props) {
  const { step } = await params;
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (process.env.REVIEW_MODE === "true" && ["format-feedback", "results", "comparison", "debrief", "complete", "withdrawn", "exit", "technical-incomplete"].includes(step)) redirect("/review/reports");

  const requestedPath = `/study/${step}`;
  if (requestedPath !== current.current_step_path) {
    redirect(current.current_step_path);
  }

  if (step === "game-processing") {
    return (
      <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16">
        <GameEstimatePanel
          allowUnavailableContinue={current.workflow_version === "experience-workflow-20261021-v1"}
          initialState={current.state}
          initialRevision={current.revision}
        />
      </main>
    );
  }

  if (step === "questionnaire") {
    const initialInstrument =
      current.state === "questionnaire_active"
        ? await readQuestionnaireInstrument<InstrumentPayload>()
        : null;
    return (
      <main className="mx-auto min-h-screen max-w-3xl px-4 pb-10 pt-20 sm:px-6 sm:py-14">
        <BFI2Questionnaire
          reviewMode={process.env.REVIEW_MODE === "true"}
          optionalItems={current.workflow_version === "experience-workflow-20261021-v1"}
          initialState={current.state}
          initialRevision={current.revision}
          initialInstrument={initialInstrument}
        />
      </main>
    );
  }

  if (step === "format-feedback") {
    const initialInstrument =
      current.state === "pre_result_feedback"
        ? await readFormatFeedbackInstrument<FormatExperiencePayload>()
        : null;
    return (
      <main className="mx-auto min-h-screen max-w-4xl px-4 pb-10 pt-20 sm:px-6 sm:py-14">
        <FormatExperienceFeedback
          initialState={current.state}
          initialRevision={current.revision}
          initialInstrument={initialInstrument}
        />
      </main>
    );
  }

  if (step === "results") {
    const status=await readProtectedStudyResource<{total?:number}>("results-status");
    const initialResult =
      current.state === "result_one_active" || current.state === "result_two_active"
        ? await readCurrentResult<CurrentResultPayload>()
        : null;
    return (
      <main className="mx-auto min-h-screen max-w-4xl px-4 pb-10 pt-20 sm:px-6 sm:py-14">
        <RandomizedResultsFlow
          totalAvailable={status?.total ?? 2}
          initialState={current.state}
          initialRevision={current.revision}
          initialResult={initialResult}
        />
      </main>
    );
  }

  if (step === "comparison") {
    const initialInstrument =
      current.state === "comparative_feedback"
        ? await readComparativeFeedback<ComparativeFeedbackPayload>()
        : null;
    return (
      <main className="mx-auto min-h-screen max-w-5xl px-4 pb-10 pt-20 sm:px-6 sm:py-14">
        <ComparativeFeedback
          initialState={current.state}
          initialRevision={current.revision}
          initialInstrument={initialInstrument}
        />
      </main>
    );
  }

  if (step === "debrief") {
    const debrief = await readDebrief<DebriefPayload>();
    if (!debrief) redirect("/study/start?status=session_required");
    return (
      <main className="mx-auto min-h-screen max-w-3xl px-4 pb-10 pt-20 sm:px-6 sm:py-14">
        <DebriefAndCompletion initialRevision={current.revision} debrief={debrief} />
      </main>
    );
  }

  if (step === "complete") {
    const receipt = await readCompletionReceipt<CompletionReceiptPayload>();
    if (!receipt) redirect("/study/start?status=session_required");
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl items-center px-4 py-12 sm:px-6">
        <CompletionReceipt receipt={receipt} />
      </main>
    );
  }

  if (step === "technical-incomplete") {
    return (
      <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16">
        <section className="w-full rounded-3xl border border-amber-200 bg-white p-8 shadow-sm">
          <p className="text-sm font-semibold text-amber-700">技术中断</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">本次流程因技术问题停止</h1>
          <p className="mt-5 leading-7 text-slate-600">
            这不是您主动退出，也不会抹去已经完成的研究活动。系统仅记录技术中断状态，不会生成虚构的人格结果或继续收集后续回答；补偿资格将依照知情同意材料和已完成进度处理。
          </p>
          <ExitInformation revised={current.workflow_version === 'experience-workflow-20261021-v1'} />
        </section>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16">
      <section className="w-full rounded-3xl border border-teal-100 bg-white p-7 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">受保护的研究步骤</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">
          {current.state}
        </h1>
        <dl className="mt-6 grid gap-3 rounded-2xl bg-slate-50 p-5 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-slate-500">当前流程版本</dt>
            <dd className="mt-1 font-medium text-slate-800">{current.workflow_version}</dd>
          </div>
          <div>
            <dt className="text-slate-500">状态修订号</dt>
            <dd className="mt-1 font-medium text-slate-800" data-testid="study-revision">
              {current.revision}
            </dd>
          </div>
        </dl>
        <p className="mt-6 leading-7 text-slate-600">
          这是由服务端研究状态保护的后续步骤。该页面的正式内容将在对应阶段完成并通过测试后开放。
        </p>
      </section>
    </main>
  );
}
