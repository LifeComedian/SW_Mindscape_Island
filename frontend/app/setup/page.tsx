"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { createSession } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

export default function SetupPage() {
  const router = useRouter();
  const { language, t } = useLanguage();
  const [nickname, setNickname] = useState("");
  const [consent, setConsent] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [worldVersion, setWorldVersion] = useState("");
  const [worldOptions, setWorldOptions] = useState<{
    default_world_version: string;
    options: Array<{
      world_version: string;
      content_pack_version: string;
      location_count: number;
      resident_count: number;
    }>;
  } | null>(null);
  const autoSubmittedRef = useRef(false);

  const startSession = useCallback(async () => {
    setError("");

    const submittedNickname = nickname.trim();

    if (!submittedNickname || !consent) {
      setError(t("error.setupRequired"));
      return;
    }

    setIsSubmitting(true);
    try {
      const session = await createSession(
        submittedNickname,
        consent,
        worldVersion || undefined,
      );
      if (!session.session_id) {
        setError(t("error.invalidSession"));
        return;
      }
      localStorage.setItem("session_id", String(session.session_id));
      localStorage.setItem("nickname", session.nickname);
      router.push(`/island?session_id=${session.session_id}`);
    } catch {
      setError(t("error.createSession"));
    } finally {
      setIsSubmitting(false);
    }
  }, [consent, nickname, router, t, worldVersion]);

  useEffect(() => {
    let cancelled = false;
    fetch("/setup/world-options", { cache: "no-store" })
      .then(async (response) => {
        if (response.status === 404) return null;
        if (!response.ok) throw new Error(`World options returned ${response.status}`);
        return response.json() as Promise<NonNullable<typeof worldOptions>>;
      })
      .then((result) => {
        if (!cancelled && result) setWorldOptions(result);
      })
      .catch(() => {
        // The selector is an optional local-development surface.
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const queryNickname = String(params.get("nickname") ?? "").trim();
    const queryConsent = params.get("consent") === "on";

    if (!queryNickname || !queryConsent || autoSubmittedRef.current) {
      return;
    }

    autoSubmittedRef.current = true;
    setNickname(queryNickname);
    setConsent(true);

    async function continueNativeSubmit() {
      setError("");
      setIsSubmitting(true);
      try {
        const session = await createSession(queryNickname, true);
        if (!session.session_id) {
          setError(t("error.invalidSession"));
          return;
        }
        localStorage.setItem("session_id", String(session.session_id));
        localStorage.setItem("nickname", session.nickname);
        router.replace(`/island?session_id=${session.session_id}`);
      } catch {
        setError(t("error.createSession"));
        router.replace("/setup");
      } finally {
        setIsSubmitting(false);
      }
    }

    continueNativeSubmit();
  }, [router, t]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    startSession();
  }

  return (
    <main className="min-h-screen px-5 pb-8 pt-20 sm:px-8">
      <div className="mx-auto max-w-3xl">
        <Link
          href="/"
          className="focus-ring inline-flex items-center gap-2 rounded-md px-2 py-2 text-sm font-medium text-stone-700 hover:text-stone-950"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t("setup.back")}
        </Link>

        <section className="mt-8 rounded-lg border border-stone-200 bg-white p-6 shadow-sm">
          <h1 className="text-3xl font-bold text-stone-950">{t("setup.title")}</h1>
          <p className="mt-3 text-sm leading-6 text-stone-600">
            {t("setup.description")}
          </p>

          <form data-testid="session-setup" action="/setup/start" method="post" onSubmit={handleSubmit} className="mt-7 space-y-5">
            <div>
              <label htmlFor="nickname" className="text-sm font-semibold text-stone-900">
                {t("setup.nickname")}
              </label>
              <input
                id="nickname"
                name="nickname"
                type="text"
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                maxLength={80}
                required
                placeholder={t("setup.nicknamePlaceholder")}
                className="focus-ring mt-2 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-stone-950 placeholder:text-stone-400"
              />
            </div>

            <label className="flex items-start gap-3 rounded-lg border border-stone-200 bg-stone-50 p-4">
              <input
                name="consent"
                type="checkbox"
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
                required
                className="mt-1 h-4 w-4 rounded border-stone-300 text-teal-700 focus:ring-teal-700"
              />
              <span className="text-sm leading-6 text-stone-700">
                {t("setup.consent")}
              </span>
            </label>

            {worldOptions ? (
              <div
                data-testid="development-world-selector"
                className="rounded-lg border border-amber-300 bg-amber-50 p-4"
              >
                <label htmlFor="world-version" className="text-sm font-semibold text-stone-900">
                  {language === "zh-CN" ? "开发用世界内容包" : "Development world content pack"}
                </label>
                <p className="mt-1 text-xs leading-5 text-stone-600">
                  {language === "zh-CN"
                    ? "仅列出后端已安装并通过校验的 JSON 内容包。普通参与者不会看到此选项。"
                    : "Only installed and validated JSON packs are listed. Participants do not see this control."}
                </p>
                <select
                  id="world-version"
                  name="world_version"
                  data-testid="world-version-select"
                  value={worldVersion}
                  onChange={(event) => setWorldVersion(event.target.value)}
                  className="focus-ring mt-3 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm"
                >
                  <option value="">
                    {language === "zh-CN" ? "系统默认" : "System default"} ({worldOptions.default_world_version})
                  </option>
                  {worldOptions.options.map((option) => (
                    <option key={option.world_version} value={option.world_version}>
                      {option.world_version} · {option.content_pack_version} · {option.location_count} places · {option.resident_count} agents
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            {error ? (
              <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {error}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={isSubmitting}
              className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md bg-teal-700 px-5 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-stone-300"
            >
              {isSubmitting ? t("setup.creating") : t("setup.start")}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
            <input type="hidden" name="language" value={language} />
          </form>
        </section>
      </div>
    </main>
  );
}
