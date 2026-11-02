import { redirect } from "next/navigation";
import ExitInformation from '@/app/study/components/ExitInformation';
import { readAuthoritativeStudyStep } from "@/lib/study-workflow";

export default async function WithdrawnPage() {
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/study/withdrawn") redirect(current.current_step_path);
  return <main className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-16"><section className="w-full rounded-3xl border border-slate-200 bg-white p-8 shadow-sm"><h1 className="text-3xl font-semibold">您已退出研究</h1><p className="mt-4 leading-7 text-slate-600">退出不会带来处罚，也不会影响您的课程、就业、学业指导、大学服务或与研究人员的关系。您不需要说明退出理由。有关按已完成比例计算补偿和数据删除的安排，将依照知情同意书处理。</p><ExitInformation revised={current.workflow_version === 'experience-workflow-20261021-v1'} /></section></main>;
}
