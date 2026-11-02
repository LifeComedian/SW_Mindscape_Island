import { NextResponse } from "next/server";

import {
  STUDY_COOKIE_MAX_AGE_SECONDS,
  STUDY_RECOVERY_COOKIE,
  STUDY_SESSION_COOKIE,
  studyBackendBaseUrl,
} from "@/lib/study-workflow";

export async function POST() {
  if (
    process.env.NODE_ENV === "production" ||
    process.env.STUDY_TEST_FIXTURES_ENABLED !== "true"
  ) {
    return NextResponse.json({ code: "fixture_not_available" }, { status: 404 });
  }
  const idempotencyKey = `browser_fixture_${crypto.randomUUID().replaceAll("-", "")}`;
  const backend = await fetch(
    `${studyBackendBaseUrl()}/study/test-fixtures/eligible-onboarding`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: "zh-CN", idempotency_key: idempotencyKey }),
    },
  );
  const payload = (await backend.json()) as {
    study_session_id?: string;
    recovery_token?: string | null;
    current_step_path?: string;
  };
  if (!backend.ok || !payload.study_session_id || !payload.recovery_token) {
    return NextResponse.json(payload, { status: backend.status });
  }
  const response = NextResponse.json({ current_step_path: payload.current_step_path });
  const options = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: false,
    path: "/",
    maxAge: STUDY_COOKIE_MAX_AGE_SECONDS,
  };
  response.cookies.set(STUDY_SESSION_COOKIE, payload.study_session_id, options);
  response.cookies.set(STUDY_RECOVERY_COOKIE, payload.recovery_token, options);
  return response;
}
