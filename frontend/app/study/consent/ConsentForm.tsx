"use client";

import { useState, useSyncExternalStore } from "react";

import {
  CONSENT_PLAIN_TEXT,
  CONSENT_SECTIONS,
  CONSENT_DOCUMENT_SHA256,
  CONSENT_VERSION,
} from "@/lib/study-consent-content";

export type ConsentDocument = {version:string;document_sha256:string;sections:{title:string;paragraphs:string[];bullets?:string[]}[];plain_text:string};
type Props = { revision: number; document?: ConsentDocument | null };

function idempotency(prefix: string) {
  return `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
}

export default function ConsentForm({ revision, document }: Props) {
  const version=document?.version ?? CONSENT_VERSION;
  const hash=document?.document_sha256 ?? CONSENT_DOCUMENT_SHA256;
  const sections=document?.sections ?? CONSENT_SECTIONS;
  const plainText=document?.plain_text ?? CONSENT_PLAIN_TEXT;
  const hydrated = useSyncExternalStore(() => () => undefined, () => true, () => false);
  const [pending, setPending] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState("");

  async function decide(action: "accept" | "decline") {
    setPending(action);
    setError("");
    try {
      const response = await fetch("/study/api/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          consent_version: version,
          document_sha256: hash,
          expected_revision: revision,
          idempotency_key: idempotency(`consent_${action}`),
        }),
      });
      const payload = (await response.json()) as { current_step_path?: string };
      if (!response.ok || !payload.current_step_path) throw new Error("consent_failed");
      window.location.assign(payload.current_step_path);
    } catch {
      setPending(null);
      setError("提交未成功。您的选择尚未改变，请检查网络后重试。");
    }
  }

  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10 print:border-0 print:p-0 print:shadow-none">
      <header className="border-b border-slate-200 pb-7">
        <p className="text-sm font-semibold text-teal-700">电子知情同意书</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">参加研究知情同意书（电子版）</h1>
        <dl className="mt-6 grid gap-4 rounded-2xl bg-slate-50 p-5 text-sm sm:grid-cols-2">
          <div className="sm:col-span-2"><dt className="text-slate-500">研究题目</dt><dd className="mt-1">人工智能代理虚拟岛屿体验（MindScape Island）与标准化人格问卷的比较：行为、语言与用户体验指标的探索性研究</dd></div>
          <div><dt className="text-slate-500">研究人员</dt><dd className="mt-1">Weitian Xue；导师：Yucheng Jin</dd></div>
          <div><dt className="text-slate-500">版本</dt><dd className="mt-1">{version}</dd></div>
          <div className="sm:col-span-2"><dt className="text-slate-500">联系邮箱</dt><dd className="mt-1">researcher@example.invalid；mentor@example.invalid</dd></div>
        </dl>
        <div className="mt-5 flex flex-wrap gap-3 print:hidden">
          <a href={`data:text/plain;charset=utf-8,${encodeURIComponent(plainText)}`} download={`MindScape-Island-知情同意书-${version}.txt`} className="focus-ring rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium">下载文本副本</a>
          <button type="button" onClick={() => window.print()} className="focus-ring rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium">打印或另存为 PDF</button>
        </div>
      </header>

      <div className="space-y-8 py-8 leading-7 text-slate-700">
        {sections.map((section) => (
          <section key={section.title} aria-labelledby={`consent-${section.title}`}>
            <h2 id={`consent-${section.title}`} className="text-xl font-semibold text-slate-950">{section.title}</h2>
            {section.paragraphs?.map((paragraph) => <p key={paragraph} className="mt-3">{paragraph}</p>)}
            {section.bullets ? <ul className="mt-3 list-disc space-y-2 pl-6">{section.bullets.map((item) => <li key={item}>{item}</li>)}</ul> : null}
          </section>
        ))}
      </div>

      <section className="rounded-2xl border border-teal-200 bg-teal-50 p-5 print:border-slate-300 print:bg-white">
        <h2 className="text-xl font-semibold text-slate-950">电子同意</h2>
        <p className="mt-3 leading-7 text-slate-700">点击“同意并继续”表示：您已阅读并理解以上信息；您有机会提出问题；您自愿同意参加本研究；您理解接下来仍需通过资格筛选。点击“不同意并退出”将结束页面，网站不会记录资格回答、联系信息或参与者生成的研究数据。</p>
        <p className="mt-3 text-sm text-slate-600">您可以在作出选择前下载或打印本知情同意书。</p>
        {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
        <div className="mt-5 grid gap-3 sm:grid-cols-2 print:hidden">
          <button type="button" disabled={!hydrated || pending !== null} onClick={() => decide("accept")} className="focus-ring rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60" data-testid="consent-accept">{pending === "accept" ? "正在提交…" : "同意并继续"}</button>
          <button type="button" disabled={!hydrated || pending !== null} onClick={() => decide("decline")} className="focus-ring rounded-xl border border-slate-300 px-5 py-3 font-semibold text-slate-800 disabled:opacity-60" data-testid="consent-decline">{pending === "decline" ? "正在退出…" : "不同意并退出"}</button>
        </div>
      </section>
    </article>
  );
}
