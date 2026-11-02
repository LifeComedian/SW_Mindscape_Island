import { NextResponse } from "next/server";

import {
  STUDY_COOKIE_MAX_AGE_SECONDS,
  STUDY_RECOVERY_COOKIE,
  STUDY_SESSION_COOKIE,
  studyBackendBaseUrl,
  readAuthoritativeStudyStep,
} from "@/lib/study-workflow";

type BootstrapBody = {
  language?: unknown;
  idempotencyKey?: unknown;
  invitationCode?: unknown;
};

type BackendBootstrap = {
  study_session_id: string;
  state: string;
  revision: number;
  recovery_token: string | null;
  recovery_token_issued: boolean;
  replayed: boolean;
  current_step_path: string;
};

export async function POST(request: Request) {
  const existing = await readAuthoritativeStudyStep();
  if (existing) return NextResponse.json(existing, { headers: { "Cache-Control": "no-store" } });
  let body: BootstrapBody;
  try {
    body = (await request.json()) as BootstrapBody;
  } catch {
    return NextResponse.json({ code: "invalid_json" }, { status: 400 });
  }

  const language = body.language === "en" ? "en" : "zh-CN";
  const idempotencyKey =
    typeof body.idempotencyKey === "string" ? body.idempotencyKey.trim() : "";
  if (!/^[A-Za-z0-9_-]{12,120}$/.test(idempotencyKey)) {
    return NextResponse.json({ code: "invalid_idempotency_key" }, { status: 422 });
  }

  const backendResponse = await fetch(`${studyBackendBaseUrl()}/study/sessions/bootstrap`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language, idempotency_key: idempotencyKey,
      invitation_code: typeof body.invitationCode === "string" ? body.invitationCode.trim() : undefined }),
  });
  const payload = (await backendResponse.json()) as BackendBootstrap | { detail?: unknown };
  if (!backendResponse.ok) {
    return NextResponse.json(payload, { status: backendResponse.status });
  }

  const bootstrap = payload as BackendBootstrap;
  if (!bootstrap.recovery_token) {
    return NextResponse.json(
      { code: "recovery_token_not_reissued" },
      { status: 409 },
    );
  }

  const response = NextResponse.json({
    study_session_id: bootstrap.study_session_id,
    state: bootstrap.state,
    revision: bootstrap.revision,
    current_step_path: bootstrap.current_step_path,
  });
  const cookieOptions = {
    httpOnly: true,
    sameSite: "strict" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: STUDY_COOKIE_MAX_AGE_SECONDS,
  };
  response.cookies.set(STUDY_SESSION_COOKIE, bootstrap.study_session_id, cookieOptions);
  response.cookies.set(STUDY_RECOVERY_COOKIE, bootstrap.recovery_token, cookieOptions);
  return response;
}
