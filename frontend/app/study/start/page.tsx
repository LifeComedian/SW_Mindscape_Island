import StudyBootstrapButton from "./StudyBootstrapButton";
import { readAuthoritativeStudyStep } from "@/lib/study-workflow";

export default async function StudyStartPage() {
  const current = await readAuthoritativeStudyStep();
  const fixtureEnabled =
    process.env.NODE_ENV !== "production" &&
    process.env.STUDY_TEST_FIXTURES_ENABLED === "true";
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16">
      <section className="w-full rounded-3xl border border-slate-200 bg-white p-7 shadow-sm sm:p-10">
        <p className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-teal-700">
          MindScape Island
        </p>
        <h1 className="text-3xl font-semibold text-slate-900">{process.env.DELIVERY_MEETING_DEMO === "true" ? "潮栖岛 · 第一天演示" : "MindScape Island 研究入口"}</h1>
        <p className="mt-4 leading-7 text-slate-600">
          点击开始后，您将先阅读完整的电子知情同意书。作出同意选择前，系统不会记录资格回答、联系方式或参与者生成的研究数据。
        </p>
        <div className="mt-7">
          <StudyBootstrapButton
            resumePath={current?.current_step_path}
            fixtureEnabled={fixtureEnabled}
            invitationRequired={process.env.STUDY_RUNTIME_ENV === "production" || process.env.STUDY_INVITATION_REQUIRED === "true"}
          />
        </div>
        <p className="mt-5 text-xs leading-5 text-slate-500">
          安全恢复凭证只保存在 HttpOnly Cookie 中，不写入地址栏或浏览器本地存储。
        </p>
      </section>
    </main>
  );
}
