import { NextRequest, NextResponse } from "next/server";


const API_BASE_URL = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const CONSENT_VERSION = "v0.3";


export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const nickname = String(formData.get("nickname") ?? "").trim();
  const consent = formData.get("consent") === "on";
  const language = formData.get("language") === "zh-CN" ? "zh-CN" : "en";
  const worldVersion = String(formData.get("world_version") ?? "").trim();
  const isChinese = language === "zh-CN";

  if (!nickname || !consent) {
    return new Response(
      isChinese
        ? "请输入昵称并勾选同意事项后再开始。"
        : "Nickname and consent are required to start.",
      {
      status: 400,
      },
    );
  }

  const response = await fetch(`${API_BASE_URL}/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      nickname,
      consent,
      consent_version: CONSENT_VERSION,
      ...(worldVersion ? { world_version: worldVersion } : {}),
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    const message = isChinese
      ? `无法创建会话，后端状态码：${response.status}`
      : `Could not create session. Backend status: ${response.status}`;
    return new Response(message, { status: response.status });
  }

  const session = await response.json();
  if (!session.session_id) {
    return new Response(
      isChinese
        ? "后端没有返回有效的会话编号。"
        : "Backend did not return a valid session id.",
      {
      status: 502,
      },
    );
  }

  const redirectUrl = new URL(
    `/island?session_id=${session.session_id}&language=${language}`,
    request.url,
  );
  return NextResponse.redirect(redirectUrl, 303);
}
