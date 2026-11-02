import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import {
  STUDY_RECOVERY_COOKIE,
  STUDY_SESSION_COOKIE,
  studyBackendBaseUrl,
} from "@/lib/study-workflow";

const POST_COMMANDS = new Set([
  "consent",
  "begin-baseline",
  "screening",
  "contact",
  "onboarding",
  "withdraw",
  "start-island",
  "request-departure",
  "cancel-departure",
  "confirm-departure",
  "begin-game-estimate",
  "run-game-estimate",
  "begin-questionnaire",
  "questionnaire-draft",
  "questionnaire-submit",
  "begin-format-feedback",
  "format-feedback-submit",
  "view-result-one",
  "view-result-two",
  "result-rating",
  "begin-comparison",
  "comparison-submit",
  "acknowledge-debrief",
]);
const GET_COMMANDS = new Set([
  "consent-content",
  "exit-information",
  "onboarding-status",
  "current-step",
  "game-estimate",
  "questionnaire",
  "questionnaire-status",
  "format-feedback",
  "results-status",
  "current-result",
  "comparison",
  "debrief",
  "completion",
  "compensation-status",
]);

async function identity() {
  const store = await cookies();
  return {
    sessionId: store.get(STUDY_SESSION_COOKIE)?.value,
    token: store.get(STUDY_RECOVERY_COOKIE)?.value,
  };
}

function unavailable() {
  return NextResponse.json({ code: "study_session_required" }, { status: 401 });
}

export async function POST(
  request: Request,
  context: { params: Promise<{ command: string }> },
) {
  const { command } = await context.params;
  if (!POST_COMMANDS.has(command)) {
    return NextResponse.json({ code: "unknown_command" }, { status: 404 });
  }
  const { sessionId, token } = await identity();
  if (!sessionId || !token) return unavailable();
  const body = await request.text();
  const backend = await fetch(
    `${studyBackendBaseUrl()}/study/sessions/${encodeURIComponent(sessionId)}/${command}`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Study-Recovery-Token": token,
      },
      body,
    },
  );
  return new NextResponse(await backend.text(), {
    status: backend.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ command: string }> },
) {
  const { command } = await context.params;
  if (!GET_COMMANDS.has(command)) {
    return NextResponse.json({ code: "unknown_command" }, { status: 404 });
  }
  const { sessionId, token } = await identity();
  if (!sessionId || !token) return unavailable();
  const backend = await fetch(
    `${studyBackendBaseUrl()}/study/sessions/${encodeURIComponent(sessionId)}/${command}`,
    {
      cache: "no-store",
      headers: { "X-Study-Recovery-Token": token },
    },
  );
  return new NextResponse(await backend.text(), {
    status: backend.status,
    headers: { "Content-Type": "application/json" },
  });
}
