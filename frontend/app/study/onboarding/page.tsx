import { redirect } from "next/navigation";

import { readAuthoritativeStudyStep, readOnboardingStatus } from "@/lib/study-workflow";
import OnboardingForm from "./OnboardingForm";
import WithdrawButton from "@/app/study/components/WithdrawButton";

export default async function OnboardingPage() {
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/study/onboarding") redirect(current.current_step_path);
  const status = await readOnboardingStatus();
  if (!status) redirect(current.current_step_path === "/study/onboarding" ? "/study/start?status=session_required" : current.current_step_path);
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10">
        <p className="text-sm font-semibold text-teal-700">符合资格</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">研究编号与入岛准备</h1>
        <div className="mt-8"><OnboardingForm optionalBaseline={status.items_optional} v5Enabled={["chaoxi-holiday-v5","chaoxi-holiday-v6"].includes(status.world_version ?? process.env.HOLIDAY_WORLD_VERSION ?? "")} revision={current.revision} initialContactReceived={status.contact_received} initialProfileCompleted={status.profile_completed} initialResearchId={status.research_id} fixtureWorldAvailable={status.study_world_available ?? (process.env.NODE_ENV !== "production" && process.env.STUDY_TEST_FIXTURES_ENABLED === "true" && ["test", "development"].includes(process.env.STUDY_RUNTIME_ENV ?? ""))} /></div>
        <WithdrawButton revision={current.revision} />
      </section>
    </main>
  );
}
