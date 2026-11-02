import { redirect } from "next/navigation";

import { readAuthoritativeStudyStep } from "@/lib/study-workflow";
import ScreeningForm from "./ScreeningForm";
import WithdrawButton from "@/app/study/components/WithdrawButton";

export default async function ScreeningPage() {
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/study/screening") redirect(current.current_step_path);
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">同意后资格确认</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">参与资格筛选</h1>
        <p className="mt-4 leading-7 text-slate-600">感谢您考虑参加本研究。以下问题仅用于确认您是否符合本研究的参与条件，预计用时约2分钟。请根据您完成本次研究时的实际情况作答。</p>
        <p className="mt-3 text-sm text-slate-500">仅当四个问题均回答“是”时才符合资格。不符合资格者的逐题回答会在资格判断后立即删除，且系统不会要求其提供联系信息。</p>
        <div className="mt-8"><ScreeningForm revision={current.revision} /></div>
        <WithdrawButton revision={current.revision} />
      </section>
    </main>
  );
}
