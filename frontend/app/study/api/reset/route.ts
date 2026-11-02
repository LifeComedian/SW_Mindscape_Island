import { NextResponse } from "next/server";

import {
  STUDY_RECOVERY_COOKIE,
  STUDY_SESSION_COOKIE,
} from "@/lib/study-workflow";

export async function GET(request: Request) {
  const resetEnabled =
    process.env.NODE_ENV !== "production" &&
    process.env.STUDY_TEST_FIXTURES_ENABLED === "true" &&
    ["test", "development"].includes(process.env.STUDY_RUNTIME_ENV ?? "");

  if (!resetEnabled) {
    return NextResponse.json({ code: "fixture_not_available" }, { status: 404 });
  }

  const response = NextResponse.redirect(
    new URL("/study/start?status=reset", request.url),
    303,
  );
  const expiredCookie = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: false,
    path: "/",
    maxAge: 0,
  };
  response.cookies.set(STUDY_SESSION_COOKIE, "", expiredCookie);
  response.cookies.set(STUDY_RECOVERY_COOKIE, "", expiredCookie);
  return response;
}
