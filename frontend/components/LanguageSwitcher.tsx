"use client";

import { Languages } from "lucide-react";
import { usePathname } from "next/navigation";

import { useLanguage } from "@/lib/i18n";

export default function LanguageSwitcher() {
  const { language, setLanguage, t } = useLanguage();
  const path = usePathname();
  if (path === "/island" || path.startsWith("/study")) return null;
  const nextLanguage = language === "en" ? "zh-CN" : "en";
  const buttonText =
    language === "en"
      ? t("language.switchToChinese")
      : t("language.switchToEnglish");

  return (
    <button
      type="button"
      onClick={() => setLanguage(nextLanguage)}
      title={t("language.switchLabel")}
      aria-label={`${t("language.switchLabel")}: ${buttonText}`}
      className="focus-ring fixed right-4 top-4 z-50 inline-flex min-h-10 items-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-semibold text-stone-800 shadow-sm transition hover:bg-stone-50"
    >
      <Languages className="h-4 w-4 text-teal-700" aria-hidden="true" />
      {buttonText}
    </button>
  );
}
