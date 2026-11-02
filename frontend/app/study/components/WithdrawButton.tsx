"use client";

import { useState, useSyncExternalStore } from "react";

export default function WithdrawButton({ revision }: { revision: number }) {
  const hydrated = useSyncExternalStore(() => () => undefined, () => true, () => false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function withdraw() {
    if (!window.confirm("您确定要退出本研究吗？退出不需要说明理由。")) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch("/study/api/withdraw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          idempotency_key: `withdraw_${crypto.randomUUID().replaceAll("-", "")}`,
        }),
      });
      const payload = (await response.json()) as { current_step_path?: string };
      if (!response.ok || !payload.current_step_path) throw new Error("withdraw_failed");
      window.location.assign(payload.current_step_path);
    } catch {
      setPending(false);
      setError("退出请求未成功，请检查网络后重试。您的当前进度仍然保留。");
    }
  }

  return (
    <div className="mt-6 border-t border-slate-200 pt-5">
      <button type="button" disabled={!hydrated || pending} onClick={withdraw} className="focus-ring text-sm font-medium text-slate-600 underline underline-offset-4 disabled:opacity-50" data-testid="study-withdraw">{pending ? "正在退出…" : "退出研究"}</button>
      {error ? <p role="alert" className="mt-3 text-sm text-red-800">{error}</p> : null}
    </div>
  );
}
