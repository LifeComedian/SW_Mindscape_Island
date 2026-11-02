import { NextRequest, NextResponse } from "next/server";


const API_BASE_URL = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);


export async function GET(request: NextRequest) {
  const enabled = ["1", "true", "yes", "on"].includes(
    (process.env.WORLD_VERSION_SELECTOR_ENABLED ?? "").trim().toLowerCase(),
  );
  if (!enabled || !LOCAL_HOSTS.has(request.nextUrl.hostname)) {
    return new Response("Not found", { status: 404 });
  }

  const response = await fetch(`${API_BASE_URL}/development/world-options`, {
    cache: "no-store",
  });
  if (!response.ok) {
    return new Response("World options are unavailable", { status: response.status });
  }
  return NextResponse.json(await response.json());
}
