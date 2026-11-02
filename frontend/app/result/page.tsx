"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, Download, Home, Map } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { exportSessionUrl, getSessionWorld } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

export default function ResultPage() {
  const router = useRouter();
  const { language, t } = useLanguage();
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const validateSession = useCallback(async (candidateSessionId: number) => {
    try {
      const snapshot = await getSessionWorld(candidateSessionId, language);
      if (snapshot.session.status === "active") {
        router.replace(`/island?session_id=${candidateSessionId}`);
        return;
      }
      if (snapshot.session.status !== "completed") {
        router.replace("/setup");
        return;
      }
      setSessionId(candidateSessionId);
    } catch {
      setError(t("result.error"));
    }
  }, [language, router, t]);

  useEffect(() => {
    const storedSessionId = Number(localStorage.getItem("session_id"));
    if (!Number.isInteger(storedSessionId) || storedSessionId <= 0) {
      router.replace("/setup");
      return;
    }
    const validationTimer = window.setTimeout(() => {
      void validateSession(storedSessionId);
    }, 0);
    return () => window.clearTimeout(validationTimer);
  }, [router, validateSession]);

  function retryValidation() {
    const storedSessionId = Number(localStorage.getItem("session_id"));
    if (Number.isInteger(storedSessionId) && storedSessionId > 0) {
      void validateSession(storedSessionId);
    } else {
      router.replace("/setup");
    }
  }

  function restartSession() {
    localStorage.removeItem("session_id");
    localStorage.removeItem("nickname");
    router.push("/");
  }

  if (!sessionId) {
    return (
      <main className="flex min-h-screen items-center justify-center px-5">
        {error ? (
          <div role="alert" className="rounded-lg border border-red-200 bg-white p-6 text-center shadow-sm">
            <p className="text-sm text-red-800">{error}</p>
            <button type="button" onClick={retryValidation} className="focus-ring mt-4 rounded-md bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800">
              {t("result.retry")}
            </button>
          </div>
        ) : (
          <p role="status" className="rounded-lg border border-stone-200 bg-white px-5 py-4 text-sm text-stone-600 shadow-sm">
            {t("result.loading")}
          </p>
        )}
      </main>
    );
  }

  return (
    <main className="min-h-screen px-5 pb-8 pt-20 sm:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href={"/island?session_id=" + sessionId}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-stone-700 hover:text-stone-950"
          >
            <Map className="h-4 w-4" aria-hidden="true" />
            {t("result.back")}
          </Link>
          <a
            data-testid="result-export"
            href={exportSessionUrl(sessionId, "json", "island")}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-md border border-stone-300 bg-white px-4 text-sm font-semibold text-stone-800 transition hover:bg-stone-50"
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            {t("result.download")}
          </a>
          <button
            data-testid="restart-session"
            type="button"
            onClick={restartSession}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white transition hover:bg-teal-800"
          >
            <Home className="h-4 w-4" aria-hidden="true" />
            {t("result.restart")}
          </button>
        </div>

        <header className="mt-8 border-b border-stone-200 pb-5">
          <p className="text-sm font-semibold uppercase tracking-normal text-teal-700">
            {t("result.eyebrow")}
          </p>
          <h1 className="mt-2 text-3xl font-bold text-stone-950">
            {t("result.title")}
          </h1>
          <p className="mt-2 text-sm leading-6 text-stone-600">
            {t("result.description")}
          </p>
        </header>

        <section className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-6">
          <CheckCircle2 className="h-8 w-8 text-emerald-700" aria-hidden="true" />
          <h2 className="mt-4 text-lg font-bold text-emerald-950">
            {t("result.neutralTitle")}
          </h2>
          <p className="mt-2 text-sm leading-6 text-emerald-900">
            {t("result.neutralDescription")}
          </p>
        </section>
      </div>
    </main>
  );
}
