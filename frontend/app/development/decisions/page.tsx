"use client";

import { useState } from "react";
import { commitResidentDecision, previewResidentDecision, type ResidentDecisionPreview } from "@/lib/api";

export default function DecisionsPage() {
  const [sessionId, setSessionId] = useState("");
  const [agentId, setAgentId] = useState("1");
  const [kind, setKind] = useState("atomic_action");
  const [preview, setPreview] = useState<ResidentDecisionPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [commitKey, setCommitKey] = useState("");
  async function run(commit = false) {
    if (busy || Number(sessionId) < 1 || Number(agentId) < 1) return;
    setBusy(true); setError("");
    try {
      const result = commit && preview
        ? await commitResidentDecision(Number(sessionId), Number(agentId), preview.audit_id, commitKey)
        : await previewResidentDecision(Number(sessionId), Number(agentId), kind);
      setPreview(result);
      if (!commit) setCommitKey(crypto.randomUUID());
    } catch {
      setError("操作未确认。请核对 Session、居民编号和开发开关；世界变化后需要重新预览。");
    } finally { setBusy(false); }
  }
  return <main className="mx-auto max-w-2xl space-y-5 p-6">
    <h1 className="text-2xl font-bold">居民动作单步验收</h1>
    <p>仅用于启用开发入口的本地测试世界。先查看合法选择，再提交；预览不会执行动作。</p>
    <label className="block">Session 编号<input className="ml-3 rounded border p-2" type="number" min="1" value={sessionId} onChange={(event) => {setSessionId(event.target.value); setPreview(null);}} /></label>
    <label className="block">居民编号<input className="ml-3 rounded border p-2" type="number" min="1" value={agentId} onChange={(event) => {setAgentId(event.target.value); setPreview(null);}} /></label>
    <label className="block">决策场景<select className="ml-3 rounded border p-2" value={kind} onChange={(event) => {setKind(event.target.value); setPreview(null);}}>
      {(["atomic_action", "stage_action", "invitation_response", "reschedule", "event_preference", "dialogue", "record_expression"]).map((item) => <option key={item}>{item}</option>)}
    </select></label>
    <button className="focus-ring rounded border px-4 py-3" disabled={busy} onClick={() => void run()}>生成动作预览</button>
    {preview ? <section className="space-y-3 rounded border p-4">
      <p>状态：{preview.status}；来源：{preview.generation_mode}</p>
      <p>{preview.preview?.summary ?? preview.expression}</p>
      {preview.preview ? <details><summary className="cursor-pointer">规范选择与参数</summary><pre className="overflow-auto text-sm">{JSON.stringify(preview.preview, null, 2)}</pre></details> : null}
      {preview.status === "shadow" ? <button className="focus-ring rounded border px-4 py-3" disabled={busy} onClick={() => void run(true)}>确认并提交一次</button> : null}
    </section> : null}
    {error ? <p role="alert">{error}</p> : null}
  </main>;
}
