import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import {
  STUDY_RECOVERY_COOKIE,
  STUDY_SESSION_COOKIE,
  studyBackendBaseUrl,
} from "@/lib/study-workflow";


export async function POST() {
  const fixtureEnabled =
    process.env.NODE_ENV !== "production" &&
    process.env.STUDY_TEST_FIXTURES_ENABLED === "true" &&
    ["test", "development"].includes(process.env.STUDY_RUNTIME_ENV ?? "");
  if (!fixtureEnabled) {
    return NextResponse.json({ code: "fixture_not_available" }, { status: 404 });
  }
  const store = await cookies();
  const sessionId = store.get(STUDY_SESSION_COOKIE)?.value;
  const token = store.get(STUDY_RECOVERY_COOKIE)?.value;
  if (!sessionId || !token) {
    return NextResponse.json({ code: "study_session_required" }, { status: 401 });
  }
  const response = await fetch(
    `${studyBackendBaseUrl()}/study/test-fixtures/sessions/${encodeURIComponent(sessionId)}/complete-island-calendar`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "X-Study-Recovery-Token": token },
    },
  );
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
