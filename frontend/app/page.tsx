"use client";

import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { useLanguage } from "@/lib/i18n";

export default function LandingPage() {
  const { t } = useLanguage();

  return (
    <main className="min-h-screen px-5 pb-8 pt-20 sm:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-6xl flex-col justify-center gap-10">
        <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
          <section>
            <p className="text-sm font-semibold uppercase tracking-normal text-teal-700">
              {t("landing.eyebrow")}
            </p>
            <h1 className="mt-4 max-w-3xl text-4xl font-bold leading-tight text-stone-950 sm:text-5xl">
              {t("landing.title")}
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-stone-700">
              {t("landing.description")}
            </p>

            <div className="mt-6 flex max-w-2xl items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-950">
              <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              <p className="text-sm leading-6">
                {t("landing.notice")}
              </p>
            </div>

            <Link
              href="/setup"
              className="focus-ring mt-7 inline-flex min-h-11 items-center gap-2 rounded-md bg-teal-700 px-5 text-sm font-semibold text-white transition hover:bg-teal-800"
            >
              {t("landing.start")}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </section>

          <section className="rounded-lg border border-stone-200 bg-white p-5 shadow-soft">
            <div className="flex items-center justify-between border-b border-stone-200 pb-4">
              <div>
                <p className="text-sm font-semibold text-stone-950">
                  {t("landing.preview")}
                </p>
                <p className="text-xs text-stone-500">{t("landing.staticPosts")}</p>
              </div>
              <div className="flex -space-x-2">
                {["M", "L", "C"].map((name) => (
                  <span
                    key={name}
                    className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-teal-700 text-xs font-bold text-white"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-5 space-y-4">
              <PreviewPost
                name="Mira"
                role={t("landing.miraRole")}
                text={t("landing.miraPost")}
              />
              <PreviewPost
                name="Leo"
                role={t("landing.leoRole")}
                text={t("landing.leoPost")}
              />
              <PreviewPost
                name="Chen"
                role={t("landing.novaRole")}
                text={t("landing.novaPost")}
              />
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

function PreviewPost({
  name,
  role,
  text,
}: {
  name: string;
  role: string;
  text: string;
}) {
  return (
    <article className="rounded-lg border border-stone-200 p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-stone-900 text-sm font-bold text-white">
          {name.charAt(0)}
        </div>
        <div>
          <p className="text-sm font-semibold text-stone-950">{name}</p>
          <p className="text-xs text-stone-500">{role}</p>
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-stone-700">{text}</p>
    </article>
  );
}
