"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export type DebriefPayload = {
  debrief_version: string;
  debrief_sha256: string;
  language: string;
  title: string;
  paragraphs: string[];
  acknowledgement_label: string;
};

type Props = {
  initialRevision: number;
  debrief: DebriefPayload;
};

function requestKey() {
  return `acknowledge-debrief-${crypto.randomUUID()}`;
}

export default function DebriefAndCompletion({ initialRevision, debrief }: Props) {
  const router = useRouter();
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete = async () => {
    if (!acknowledged) {
      setError("请确认您已阅读研究结束说明。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/study/api/acknowledge-debrief", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: initialRevision,
          idempotency_key: requestKey(),
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body?.detail?.code ?? body?.code ?? "debrief_acknowledgement_failed");
      }
      router.replace(body.current_step_path);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "debrief_acknowledgement_failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="w-full rounded-3xl border border-teal-100 bg-white p-6 shadow-sm sm:p-10">
      <p className="text-sm font-semibold text-teal-700">研究结束说明</p>
      <h1 className="mt-2 text-3xl font-semibold text-slate-900" data-testid="study-step">{debrief.title}</h1>
      <div className="mt-6 space-y-5 text-[15px] leading-8 text-slate-700" data-testid="debrief-content">
        {debrief.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </div>
      <label className="mt-8 flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => {
            setAcknowledged(event.target.checked);
            setError(null);
          }}
          data-testid="debrief-acknowledgement"
          className="mt-1"
        />
        <span>{debrief.acknowledgement_label}</span>
      </label>
      {error ? <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p> : null}
      <button
        type="button"
        onClick={complete}
        disabled={busy || !acknowledged}
        data-testid="complete-study"
        className="mt-6 w-full rounded-2xl bg-teal-700 px-6 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? "正在生成完成记录…" : "完成研究并生成完成记录"}
      </button>
      <p className="mt-5 break-all border-t border-slate-100 pt-4 text-xs text-slate-400">说明版本：{debrief.debrief_version}</p>
    </article>
  );
}
