import { notFound } from "next/navigation";

import { ContentStudio } from "./ContentStudio";

export const dynamic = "force-dynamic";

export default function StudioPage() {
  const enabled = ["1", "true", "yes", "on"].includes(
    (process.env.CONTENT_STUDIO_ENABLED ?? "").trim().toLowerCase(),
  );
  if (!enabled) notFound();
  return <ContentStudio />;
}
