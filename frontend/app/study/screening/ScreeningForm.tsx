"use client";

import { FormEvent, useState, useSyncExternalStore } from "react";

type Props = { revision: number };

const QUESTIONS = [
  ["age_18_or_older", "您是否已满18周岁？"],
  ["located_in_mainland_china", "您在完成本次研究时是否位于中国大陆境内？"],
  ["reads_chinese_and_has_computer", "您是否能够阅读中文，并能够使用电脑通过研究链接完成一次约60分钟的在线研究？"],
  ["accepts_ai_interaction_and_recording", "您是否愿意与由人工智能控制的虚拟角色互动，并允许系统按照知情同意书中的说明记录您的游戏行为、选择以及您主动输入的文字，用于本研究分析？"],
] as const;

export default function ScreeningForm({ revision }: Props) {
  const hydrated = useSyncExternalStore(() => () => undefined, () => true, () => false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const answers = Object.fromEntries(
      QUESTIONS.map(([name]) => [name, form.get(name) === "yes"]),
    );
    try {
      const response = await fetch("/study/api/screening", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...answers,
          expected_revision: revision,
          idempotency_key: `screening_${crypto.randomUUID().replaceAll("-", "")}`,
        }),
      });
      const payload = (await response.json()) as { current_step_path?: string };
      if (!response.ok || !payload.current_step_path) throw new Error("screening_failed");
      window.location.assign(payload.current_step_path);
    } catch {
      setPending(false);
      setError("资格判断未成功提交，请检查网络后重试。页面不会因失败而改变您的研究阶段。");
    }
  }

  return (
    <form onSubmit={submit} className="space-y-7">
      {QUESTIONS.map(([name, question], index) => (
        <fieldset key={name} className="rounded-2xl border border-slate-200 p-5">
          <legend className="px-1 font-medium leading-7 text-slate-900">{index + 1}. {question}</legend>
          <div className="mt-3 flex gap-6">
            <label className="flex items-center gap-2"><input required type="radio" name={name} value="yes" />是</label>
            <label className="flex items-center gap-2"><input required type="radio" name={name} value="no" />否</label>
          </div>
        </fieldset>
      ))}
      {error ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p> : null}
      <button type="submit" disabled={!hydrated || pending} className="focus-ring w-full rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60" data-testid="screening-submit">{pending ? "正在判断…" : "提交资格筛选"}</button>
    </form>
  );
}
