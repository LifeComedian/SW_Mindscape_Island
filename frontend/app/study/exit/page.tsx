import { redirect } from "next/navigation";
import { readAuthoritativeStudyStep } from "@/lib/study-workflow";

export default async function ConsentExitPage() {
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/study/exit") redirect(current.current_step_path);
  return <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16"><section className="w-full rounded-3xl border border-slate-200 bg-white p-8 shadow-sm"><h1 className="text-3xl font-semibold">已退出研究</h1><p className="mt-4 leading-7 text-slate-600">感谢您阅读研究信息。您选择了不同意，研究流程已经结束。系统未记录资格回答、联系方式或参与者生成的研究数据。</p></section></main>;
}
