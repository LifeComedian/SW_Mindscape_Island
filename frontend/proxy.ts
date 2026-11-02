import { NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  const productionStudy = process.env.STUDY_RUNTIME_ENV === "production";
  const path = request.nextUrl.pathname;
  const reviewer = process.env.REVIEW_MODE === "true";
  if (reviewer && ["/", "/study/start", "/study/consent", "/study/screening", "/study/onboarding"].includes(path)) {
    return NextResponse.redirect(new URL("/review", request.url));
  }
  if (!reviewer && path.startsWith("/review")) return NextResponse.json({code:"not_found"}, {status:404});
  if (productionStudy) {
    if (path === "/") return NextResponse.redirect(new URL("/study/start", request.url));
    if (/^\/(setup|development|studio|game|feed|results)(\/|$)/.test(path) || path.startsWith("/study/api/test-")) {
      return NextResponse.json({ code: "not_found" }, { status: 404 });
    }
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
    // Next dev can normalize nextUrl to localhost even when the browser uses
    // 127.0.0.1. For local development, compare against the actual loopback Host.
    const host = request.headers.get("host") ?? "";
    const localOrigin = /^((127\.0\.0\.1)|(localhost))(:[0-9]+)?$/.test(host)
      ? `http://${host}`
      : request.nextUrl.origin;
    const expected = process.env.STUDY_PUBLIC_ORIGIN || (productionStudy ? "" : localOrigin);
    if (!expected || request.headers.get("origin") !== expected || request.headers.get("sec-fetch-site") === "cross-site") {
      return NextResponse.json({ code: "origin_rejected" }, { status: 403 });
    }
  }
  const response = NextResponse.next();
  if (path.startsWith("/study") || path.startsWith("/review") || path === "/island") {
    response.headers.set("Cache-Control", "no-store");
    response.headers.set("Referrer-Policy", "no-referrer");
  }
  if (reviewer && request.method === "GET") {
    for (const name of ["mindscape_review_account", "mindscape_review_account_token", "mindscape_review_session_id", "mindscape_review_session_token"]) {
      const value = request.cookies.get(name)?.value;
      if (value) response.cookies.set(name, value, {httpOnly:true, secure:process.env.NODE_ENV === "production", sameSite:"strict", path:"/", maxAge:180*86400});
    }
  }
  return response;
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
