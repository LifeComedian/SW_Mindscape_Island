import { IslandGameShell } from "@/components/game/IslandGameShell";
import { redirect } from "next/navigation";
import { readAuthoritativeStudyStep } from "@/lib/study-workflow";

export default async function IslandPage({
  searchParams,
}: {
  searchParams: Promise<{ study?: string }>;
}) {
  const params = await searchParams;
  const current = await readAuthoritativeStudyStep();
  // Use study mode whenever study cookies are present.
  if (!current && params.study !== "1" && process.env.STUDY_RUNTIME_ENV !== "production") return <IslandGameShell />;
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/island") redirect(current.current_step_path);
  if (!current.world_session_id) redirect("/study/onboarding?status=world_required");
  return <IslandGameShell initialSessionId={current.world_session_id} studyMode />;
}
