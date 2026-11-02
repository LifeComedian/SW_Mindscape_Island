"use client";

import { useState } from "react";

type Props = {
  resumePath?: string;
  fixtureEnabled?: boolean;
  invitationRequired?: boolean;
};

function createAttemptId(): string {
  return `browser_${crypto.randomUUID().replaceAll("-", "")}`;
}

export default function StudyBootstrapButton({ resumePath, fixtureEnabled = false, invitationRequired = false }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [invitationCode, setInvitationCode] = useState("");

  async function begin() {
    if (resumePath) {
      window.location.assign(resumePath);
      return;
    }
    setPending(true);
    setError("");
    try {
      const response = await fetch("/study/api/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          language: "zh-CN",
          idempotencyKey: createAttemptId(),
          invitationCode: invitationCode.trim() || undefined,
        }),
      });
      const payload = (await response.json()) as {
        current_step_path?: string;
        code?: string;
      };
      if (!response.ok || !payload.current_step_path) {
        throw new Error(payload.code ?? "bootstrap_failed");
      }
      window.location.assign(payload.current_step_path);
    } catch {
      setError("暂时无法进入。请核对邀请码，稍后重试；已使用、过期或丢失进度时请联系研究者恢复。");
      setPending(false);
    }
  }

  async function beginFixture() {
    setPending(true);
    setError("");
    try {
      const response = await fetch("/study/api/test-fixture", { method: "POST" });
      const payload = (await response.json()) as { current_step_path?: string };
      if (!response.ok || !payload.current_step_path) throw new Error("fixture_failed");
      window.location.assign(payload.current_step_path);
    } catch {
      setError("测试夹具不可用。");
      setPending(false);
    }
  }

  return (
    <div className="space-y-3">
      {invitationRequired && !resumePath ? (
        <label className="block text-sm font-medium text-stone-800">
          邀请码（或研究者提供的恢复码）
          <input value={invitationCode} onChange={(event) => setInvitationCode(event.target.value)}
            type="password" autoComplete="off" maxLength={100} spellCheck={false}
            className="focus-ring mt-2 w-full rounded-lg border border-stone-300 px-3 py-3"
            data-testid="study-invitation" />
          <span className="mt-2 block text-xs font-normal text-stone-600">验证后可阅读知情同意书，再决定是否参与。邀请码只使用一次；在本浏览器可继续未完成的流程。</span>
        </label>
      ) : null}
      <button
        type="button"
        className="focus-ring w-full rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white hover:bg-teal-800 disabled:cursor-wait disabled:opacity-60"
        disabled={pending || (invitationRequired && !resumePath && !invitationCode.trim())}
        onClick={begin}
        data-testid="study-bootstrap"
      >
        {pending ? "正在建立安全会话…" : resumePath ? "继续当前流程" : "开始并阅读知情同意书"}
      </button>
      {fixtureEnabled && !resumePath ? (
        <button
          type="button"
          onClick={beginFixture}
          disabled={pending}
          className="focus-ring w-full rounded-xl border border-amber-400 bg-amber-50 px-5 py-3 font-semibold text-amber-950 disabled:opacity-60"
          data-testid="study-test-fixture"
        >
          仅限测试：跳到入岛准备
        </button>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
