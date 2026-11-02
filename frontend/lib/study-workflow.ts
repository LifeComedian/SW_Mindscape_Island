import "server-only";

import { cookies } from "next/headers";

export const STUDY_SESSION_COOKIE = process.env.REVIEW_MODE === "true" ? "mindscape_review_session_id" : "mindscape_study_id";
export const STUDY_RECOVERY_COOKIE = process.env.REVIEW_MODE === "true" ? "mindscape_review_session_token" : "mindscape_study_recovery";
export const STUDY_COOKIE_MAX_AGE_SECONDS = 14 * 24 * 60 * 60;

export type StudyCurrentStep = {
  study_session_id: string;
  state: string;
  revision: number;
  language: "zh-CN" | "en";
  current_step_path: string;
  terminal: boolean;
  can_withdraw: boolean;
  allowed_actions: string[];
  study_contract_version: string;
  workflow_version: string;
  world_session_id?: number;
};

export function studyBackendBaseUrl(): string {
  return (
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://127.0.0.1:8000"
  ).replace(/\/$/, "");
}

export async function readAuthoritativeStudyStep(): Promise<StudyCurrentStep | null> {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(STUDY_SESSION_COOKIE)?.value;
  const recoveryToken = cookieStore.get(STUDY_RECOVERY_COOKIE)?.value;
  if (!sessionId || !recoveryToken) return null;

  const response = await fetch(
    `${studyBackendBaseUrl()}/study/sessions/${encodeURIComponent(sessionId)}/current-step`,
    {
      cache: "no-store",
      headers: { "X-Study-Recovery-Token": recoveryToken },
    },
  );
  if (!response.ok) return null;
  return (await response.json()) as StudyCurrentStep;
}

export type OnboardingStatus = {
  contact_received: boolean;
  items_optional?: boolean;
  study_world_available?: boolean;
  world_version?: string;
  profile_completed: boolean;
  research_id: string | null;
};

export async function readOnboardingStatus(): Promise<OnboardingStatus | null> {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(STUDY_SESSION_COOKIE)?.value;
  const recoveryToken = cookieStore.get(STUDY_RECOVERY_COOKIE)?.value;
  if (!sessionId || !recoveryToken) return null;
  const response = await fetch(
    `${studyBackendBaseUrl()}/study/sessions/${encodeURIComponent(sessionId)}/onboarding-status`,
    {
      cache: "no-store",
      headers: { "X-Study-Recovery-Token": recoveryToken },
    },
  );
  if (!response.ok) return null;
  return (await response.json()) as OnboardingStatus;
}

export async function readQuestionnaireInstrument<T>(): Promise<T | null> {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(STUDY_SESSION_COOKIE)?.value;
  const recoveryToken = cookieStore.get(STUDY_RECOVERY_COOKIE)?.value;
  if (!sessionId || !recoveryToken) return null;
  const response = await fetch(
    `${studyBackendBaseUrl()}/study/sessions/${encodeURIComponent(sessionId)}/questionnaire`,
    {
      cache: "no-store",
      headers: { "X-Study-Recovery-Token": recoveryToken },
    },
  );
  if (!response.ok) return null;
  return (await response.json()) as T;
}

export async function readProtectedStudyResource<T>(command: string): Promise<T | null> {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(STUDY_SESSION_COOKIE)?.value;
  const recoveryToken = cookieStore.get(STUDY_RECOVERY_COOKIE)?.value;
  if (!sessionId || !recoveryToken) return null;
  const response = await fetch(
    `${studyBackendBaseUrl()}/study/sessions/${encodeURIComponent(sessionId)}/${command}`,
    {
      cache: "no-store",
      headers: { "X-Study-Recovery-Token": recoveryToken },
    },
  );
  if (!response.ok) return null;
  return (await response.json()) as T;
}

export async function readFormatFeedbackInstrument<T>(): Promise<T | null> {
  return readProtectedStudyResource<T>("format-feedback");
}

export async function readCurrentResult<T>(): Promise<T | null> {
  return readProtectedStudyResource<T>("current-result");
}

export async function readComparativeFeedback<T>(): Promise<T | null> {
  return readProtectedStudyResource<T>("comparison");
}

export async function readDebrief<T>(): Promise<T | null> {
  return readProtectedStudyResource<T>("debrief");
}

export async function readCompletionReceipt<T>(): Promise<T | null> {
  return readProtectedStudyResource<T>("completion");
}
