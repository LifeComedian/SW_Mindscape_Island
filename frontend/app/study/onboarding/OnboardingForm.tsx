"use client";

import { FormEvent, useEffect, useState, useSyncExternalStore } from "react";
import { PlayerAppearance } from "@/components/game/PlayerAppearance";
import { postV5 } from "@/lib/holiday-v5";
import { useRouter } from "next/navigation";

type Props = {
  v5Enabled?: boolean;
  optionalBaseline?: boolean;
  revision: number;
  initialContactReceived: boolean;
  initialProfileCompleted: boolean;
  initialResearchId: string | null;
  fixtureWorldAvailable: boolean;
};

type CommandPayload = {
  current_step_path?: string;
  research_id?: string | null;
  revision?: number;
  world_session_id?: number | null;
};

export default function OnboardingForm({
  revision, v5Enabled=false, optionalBaseline=false,
  initialContactReceived,
  initialProfileCompleted,
  initialResearchId,
  fixtureWorldAvailable,
}: Props) {
  const [gender,setGender] = useState<"male"|"female"|"">("");
  const router = useRouter();
  const hydrated = useSyncExternalStore(() => () => undefined, () => true, () => false);
  const [contactReceived, setContactReceived] = useState(initialContactReceived);
  const [profileCompleted, setProfileCompleted] = useState(initialProfileCompleted);
  const [researchId, setResearchId] = useState(initialResearchId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [workflowRevision, setWorkflowRevision] = useState(revision);
  const [baselineReady,setBaselineReady]=useState(!optionalBaseline || initialProfileCompleted);

  useEffect(()=>{
    if(optionalBaseline && contactReceived && !profileCompleted) {
      void fetch("/study/api/begin-baseline",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).then(r=>{if(!r.ok)throw new Error();setBaselineReady(true);}).catch(()=>setError("开始时间未能保存，请刷新后再提交。"));
    }
  },[optionalBaseline,contactReceived,profileCompleted]);

  async function send(command: string, body: Record<string, unknown>): Promise<CommandPayload> {
    const response = await fetch(`/study/api/${command}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = (await response.json()) as CommandPayload;
    if (!response.ok) throw new Error(command);
    return payload;
  }

  async function submitContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const payload = await send("contact", {
        email: String(form.get("email") ?? ""),
        idempotency_key: `contact_${crypto.randomUUID().replaceAll("-", "")}`,
      });
      setResearchId(payload.research_id ?? null);
      setContactReceived(true);
    } catch {
      setError("邮箱未能安全保存。请确认格式并检查网络后重试。");
    } finally {
      setPending(false);
    }
  }

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const payload = await send("onboarding", {
        nickname: String(form.get("nickname") ?? ""),
        gaming_frequency_code: String(form.get("gaming_frequency_code") ?? ""),
        social_game_experience_code: String(form.get("social_game_experience_code") ?? ""),
        ai_text_frequency_code: String(form.get("ai_text_frequency_code") ?? ""),
        expected_revision: revision,
        idempotency_key: `onboarding_${crypto.randomUUID().replaceAll("-", "")}`,
      });
      setResearchId(payload.research_id ?? researchId);
      setProfileCompleted(true);
      if (typeof payload.revision === "number") setWorkflowRevision(payload.revision);
    } catch {
      setError("开始前信息未能提交。昵称不能包含邮箱、电话号码、学号或其他身份信息。");
    } finally {
      setPending(false);
    }
  }

  async function startIsland() {
    setPending(true);
    setError("");
    try {
      const payload = await send("start-island", {
        expected_revision: workflowRevision,
        idempotency_key: `start_island_${crypto.randomUUID().replaceAll("-", "")}`,
      });
      if (!payload.world_session_id) throw new Error("missing-world-session");
      if(v5Enabled && gender) await postV5(payload.world_session_id,"profile",{gender,idempotency_key:`v5-appearance-${payload.world_session_id}-${gender}`});
      localStorage.setItem("session_id", String(payload.world_session_id));
      router.push("/island?study=1");
    } catch {
      setError("岛屿暂时无法进入，请刷新后重试。已保存的进度不会丢失。");
      setPending(false);
    }
  }

  if (profileCompleted) {
    return (
      <section className="rounded-2xl border border-teal-200 bg-teal-50 p-6" aria-live="polite">
        <p className="text-sm font-semibold text-teal-800">准备完成</p>
        <h2 className="mt-2 text-2xl font-semibold text-slate-950">欢迎来到 MindScape Island</h2>
        <p className="mt-3 leading-7 text-slate-700">您的研究编号是 <strong data-testid="research-id">{researchId}</strong>。请妥善记录该编号；它可用于研究完成后的数据删除请求。</p>
        <p className="mt-3 leading-7 text-slate-700">您将被邀请到一座现实风格的小岛，{process.env.NEXT_PUBLIC_MEETING_DEMO === "true" ? "体验第一天的演示。" : "度过七个游戏日的假期。"}这里没有唯一目标、正确路线或最佳选择；可以按自己的兴趣探索、交谈、接受或拒绝邀请，也可以暂停或退出。</p>
        <p className="mt-3 text-sm text-slate-600">岛上居民均为 AI 控制的虚拟角色，不是真人、治疗师或研究人员。请勿在任何自由文字中输入可识别身份的信息。</p>
        {v5Enabled && <PlayerAppearance value={gender} onChange={setGender}/>}
        {fixtureWorldAvailable ? (
          <button type="button" onClick={() => void startIsland()} disabled={!hydrated || pending || (v5Enabled && !gender)} className="focus-ring mt-6 w-full rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60" data-testid="start-island">
            {pending ? "正在准备岛屿…" : process.env.NEXT_PUBLIC_MEETING_DEMO === "true" ? "开始第一天演示" : "开始七日假期"}
          </button>
        ) : (
          <button type="button" disabled className="mt-6 w-full cursor-not-allowed rounded-xl bg-slate-300 px-5 py-3 font-semibold text-slate-600" data-testid="start-island-disabled">正式内容尚未发布</button>
        )}
        {error ? <p role="alert" className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p> : null}
      </section>
    );
  }

  return (
    <div>
      {!contactReceived ? (
        <form onSubmit={submitContact} className="rounded-2xl border border-slate-200 p-6">
          <h2 className="text-xl font-semibold text-slate-950">报名联系安排</h2>
          <p className="mt-3 leading-7 text-slate-600">您符合本研究的参与条件。如果愿意报名，请提供一个常用电子邮箱，用于安排研究、发送必要提醒、发放补偿，以及处理退出或数据删除请求。邮箱将与研究数据分开加密保存，不会存入游戏资料或发送给 AI。</p>
          <label className="mt-5 block font-medium" htmlFor="study-email">电子邮箱</label>
          <input id="study-email" name="email" type="email" required autoComplete="email" className="focus-ring mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" />
          <button type="submit" disabled={!hydrated || pending} className="focus-ring mt-5 w-full rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60" data-testid="contact-submit">{pending ? "正在安全保存…" : "提交并获取研究编号"}</button>
        </form>
      ) : (
        <form onSubmit={submitProfile} className="rounded-2xl border border-slate-200 p-6">
          <p className="text-sm font-semibold text-teal-700">研究编号：<span data-testid="research-id">{researchId}</span></p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">开始前的简短问题</h2>
          <p className="mt-3 leading-7 text-slate-600">以下问题用于帮助研究团队理解参与者以往的游戏和人工智能互动经验。不会要求您的姓名。{optionalBaseline ? "经验题均可跳过；昵称留空将自动分配。" : ""}</p>
          <label className="mt-5 block font-medium" htmlFor="nickname">游戏昵称</label>
          <p className="mt-1 text-sm text-amber-800">请勿使用真实姓名、邮箱、电话号码、学号或其他能够识别您身份的信息。</p>
          <input id="nickname" name="nickname" required={!optionalBaseline} maxLength={20} autoComplete="off" className="focus-ring mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" />

          <label className="mt-5 block font-medium" htmlFor="gaming-frequency">过去12个月中，您玩电子游戏的频率大约是？</label>
          <select id="gaming-frequency" name="gaming_frequency_code" required defaultValue="" className="focus-ring mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3">
            <option value="" disabled>请选择</option>{optionalBaseline ? <option value="skipped">跳过此题</option> : null}<option value="never">从不</option><option value="lt_monthly">少于每月1次</option><option value="monthly_1_3">每月1–3次</option><option value="weekly_1_4">每周1–4次</option><option value="weekly_5_plus">每周5次或更多</option>
          </select>
          <label className="mt-5 block font-medium" htmlFor="social-experience">您以往体验叙事、生活模拟或社区互动类游戏的总时长大约是？</label>
          <select id="social-experience" name="social_game_experience_code" required defaultValue="" className="focus-ring mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3">
            <option value="" disabled>请选择</option>{optionalBaseline ? <option value="skipped">跳过此题</option> : null}<option value="never">从未体验</option><option value="lt_5h">少于5小时</option><option value="5_20h">5–20小时</option><option value="gt_20h">超过20小时</option><option value="unsure">不确定</option>
          </select>
          <label className="mt-5 block font-medium" htmlFor="ai-frequency">在参加本研究前，您与聊天机器人或人工智能角色进行文字互动的频率大约是？</label>
          <select id="ai-frequency" name="ai_text_frequency_code" required defaultValue="" className="focus-ring mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3">
            <option value="" disabled>请选择</option>{optionalBaseline ? <option value="skipped">跳过此题</option> : null}<option value="never">从未</option><option value="once_twice">仅1–2次</option><option value="occasional">偶尔（少于每月1次）</option><option value="monthly">每月数次</option><option value="weekly_plus">每周或更频繁</option>
          </select>
          <button type="submit" disabled={!hydrated || pending || !baselineReady} className="focus-ring mt-6 w-full rounded-xl bg-teal-700 px-5 py-3 font-semibold text-white disabled:opacity-60" data-testid="onboarding-submit">{pending ? "正在提交…" : "确认并阅读入岛说明"}</button>
        </form>
      )}
      {error ? <p role="alert" className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p> : null}
    </div>
  );
}
