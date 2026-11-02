import { redirect } from "next/navigation";

import { readAuthoritativeStudyStep, readProtectedStudyResource } from "@/lib/study-workflow";
import ConsentForm, { type ConsentDocument } from "./ConsentForm";

export default async function ConsentPage() {
  const current = await readAuthoritativeStudyStep();
  if (!current) redirect("/study/start?status=session_required");
  if (current.current_step_path !== "/study/consent") redirect(current.current_step_path);
  const document=current.workflow_version === "experience-workflow-20261021-v1" ? await readProtectedStudyResource<ConsentDocument>("consent-content") : null;
  if(current.workflow_version === "experience-workflow-20261021-v1" && !document) throw new Error("Consent document unavailable");
  return <main className="mx-auto max-w-4xl px-4 py-12 sm:px-6"><ConsentForm revision={current.revision} document={document} /></main>;
}
