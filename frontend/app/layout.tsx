import type { Metadata } from "next";
import type { ReactNode } from "react";

import LanguageSwitcher from "@/components/LanguageSwitcher";
import ReviewToolbar from "@/components/ReviewToolbar";
import { LanguageProvider } from "@/lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "MindScape Island Research Prototype",
  description: "A private simulated island community for naturalistic interaction research.",
  icons: { icon: "/island-icon.svg" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang={process.env.REVIEW_MODE === "true" ? "zh-CN" : "en"}>
      <body>
        <LanguageProvider>
          {process.env.DELIVERY_MEETING_DEMO === "true" && <div data-testid="meeting-demo-banner" className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-950">第一天演示版 · 仅用于项目展示 · 研究版保留七天流程</div>}
          {process.env.REVIEW_MODE === "true" ? <ReviewToolbar /> : <LanguageSwitcher />}
          {children}
        </LanguageProvider>
      </body>
    </html>
  );
}
