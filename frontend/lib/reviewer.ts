import "server-only";
import { cookies } from "next/headers";
import { studyBackendBaseUrl } from "./study-workflow";

export const REVIEW_ACCOUNT = "mindscape_review_account";
export const REVIEW_TOKEN = "mindscape_review_account_token";

export async function reviewRequest(command: string, body?: unknown) {
  const store = await cookies();
  return fetch(`${studyBackendBaseUrl()}/study/review/${command}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: {"Content-Type":"application/json", "X-Review-Account":store.get(REVIEW_ACCOUNT)?.value ?? "", "X-Review-Token":store.get(REVIEW_TOKEN)?.value ?? ""},
    ...(body === undefined ? {} : {body:JSON.stringify(body)}),
  });
}
