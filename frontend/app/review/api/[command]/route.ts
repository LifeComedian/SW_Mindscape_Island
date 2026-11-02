import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { REVIEW_ACCOUNT, REVIEW_TOKEN, reviewRequest } from "@/lib/reviewer";
import { STUDY_SESSION_COOKIE, STUDY_RECOVERY_COOKIE } from "@/lib/study-workflow";

const PUBLIC_FIELDS = ["study_session_id", "current_step_path", "nickname", "recovery_code", "state"] as const;

export async function GET(_request: Request, context: {params:Promise<{command:string}>}) {
  const {command}=await context.params;
  if (process.env.REVIEW_MODE!=="true" || !["visits","notice"].includes(command)) return NextResponse.json({code:"not_found"},{status:404});
  try {
    const backend=await reviewRequest(command);
    return new NextResponse(await backend.text(),{status:backend.status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
  } catch { return NextResponse.json({detail:{message:"服务暂时不可用，请稍后重试。"}},{status:503}); }
}

export async function POST(request: Request, context: {params:Promise<{command:string}>}) {
  const {command}=await context.params;
  if (process.env.REVIEW_MODE!=="true" || !["access","start","resume","recover","reports","logout"].includes(command)) return NextResponse.json({code:"not_found"},{status:404});
  const store=await cookies();
  if (command==="logout") {
    const response=NextResponse.json({ok:true});
    for (const name of [REVIEW_ACCOUNT,REVIEW_TOKEN,STUDY_SESSION_COOKIE,STUDY_RECOVERY_COOKIE]) response.cookies.set(name,"",{httpOnly:true,secure:process.env.NODE_ENV==="production",sameSite:"strict",path:"/",maxAge:0});
    return response;
  }
  let body: Record<string,unknown>;
  try { body=await request.json(); } catch {return NextResponse.json({code:"invalid_request"},{status:400});}
  if (!body || typeof body!=="object" || Array.isArray(body)) return NextResponse.json({code:"invalid_request"},{status:400});
  if (command==="reports" && !body.session_id) body.session_id=store.get(STUDY_SESSION_COOKIE)?.value;
  try {
    const backend=await reviewRequest(command,body);
    const payload=await backend.json();
    if (!backend.ok) return NextResponse.json(payload,{status:backend.status});
    if (command==="reports") return NextResponse.json(payload,{headers:{"Cache-Control":"no-store"}});
    const safe:Record<string,unknown>={ok:true};
    for (const key of PUBLIC_FIELDS) if (key in payload) safe[key]=payload[key];
    const response=NextResponse.json(safe,{headers:{"Cache-Control":"no-store"}});
    const options={httpOnly:true,secure:process.env.NODE_ENV==="production",sameSite:"strict" as const,path:"/",maxAge:180*86400};
    if (payload.account_id && payload.account_token) {
      response.cookies.set(REVIEW_ACCOUNT,payload.account_id,options);
      response.cookies.set(REVIEW_TOKEN,payload.account_token,options);
    }
    if (payload.study_session_id && payload.recovery_token) {
      response.cookies.set(STUDY_SESSION_COOKIE,payload.study_session_id,options);
      response.cookies.set(STUDY_RECOVERY_COOKIE,payload.recovery_token,options);
    } else if (command==="access") {
      for (const name of [STUDY_SESSION_COOKIE,STUDY_RECOVERY_COOKIE]) response.cookies.set(name,"",{...options,maxAge:0});
    }
    return response;
  } catch {return NextResponse.json({detail:{message:"连接中断，请重试；重复点击不会重复创建同一次体验。"}},{status:503});}
}
