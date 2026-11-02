import Link from "next/link";
import { redirect } from "next/navigation";

import { readAuthoritativeStudyStep } from "@/lib/study-workflow";

export default async function IneligiblePage() {
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/study/ineligible") {
    redirect(current.current_step_path);
  }

  const resetEnabled =
    process.env.NODE_ENV !== "production" &&
    process.env.STUDY_TEST_FIXTURES_ENABLED === "true" &&
    ["test", "development"].includes(process.env.STUDY_RUNTIME_ENV ?? "");

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16">
      <section className="w-full rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-3xl font-semibold">资格筛选已完成</h1>
        <p className="mt-4 leading-7 text-slate-600">
          感谢您的兴趣。根据您刚才的回答，您目前不符合本研究的参与条件。您的逐题筛选回答不会进入研究数据集，并已在资格判断后删除。系统不会要求您提供联系方式。
        </p>
        {resetEnabled ? (
          <Link
            href="/study/api/reset"
            className="mt-7 inline-flex rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white hover:bg-teal-800"
            data-testid="study-test-reset"
          >
            重新开始本地测试
          </Link>
        ) : null}
      </section>
    </main>
  );
}
