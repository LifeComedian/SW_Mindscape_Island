"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { changePlayerPlan, changeInteractionFocus, getStageCards, getNarratives, sendStageAction, type NarrativeProjection, type StageCard, type StageOperation } from "@/lib/api";
import type { Language } from "@/lib/i18n";
import {StageInputChoice} from "@/components/game/StageInputChoice";

type Props = {
  open: boolean; onClose: () => void; onCountChange: (count: number) => void; day: number;
  sessionId: number;
  worldRevision: number;
  language: Language;
  disabled: boolean;
  onWorldChanged: () => void;
};

export function ModularStagePanel({ sessionId, worldRevision, language, disabled, onWorldChanged, open, onClose, onCountChange, day }: Props) {
  const [cards, setCards] = useState<StageCard[]>([]);
  const [narrative, setNarrative] = useState<NarrativeProjection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [discussionText, setDiscussionText] = useState("");
  const [feedback, setFeedback] = useState("");
  const [seen, setSeen] = useState<string[]>([]);
  const [focusEnabled, setFocusEnabled] = useState(false);
  const [focus, setFocus] = useState<{runtimeId: number; token: string} | null>(null);
  const focusRuntimeId = focus?.runtimeId;
  const focusToken = focus?.token;
  const worldChangeCallback = useRef(onWorldChanged);
  useEffect(() => { worldChangeCallback.current = onWorldChanged; }, [onWorldChanged]);
  const requestSerial = useRef(0);
  const alive = useRef(true);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus({preventScroll: true});
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {event.preventDefault(); closeButtonRef.current?.click(); return;}
      if (event.key !== "Tab") return;
      const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), summary, a[href]') ?? []).filter(el => el.getClientRects().length > 0);
      const first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
      if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
    }
    window.addEventListener("keydown", keyboard);
    return () => {window.removeEventListener("keydown", keyboard); previous?.focus({preventScroll: true});};
  }, [open]);
  // Reuse the operation key for retries; reset it after conflicts.
  const pending = useRef<{ runtimeId: number; body: Parameters<typeof sendStageAction>[2] } | null>(null);
  const load = useCallback(async () => {
    const serial = ++requestSerial.current;
    try {
      const [result, projection] = await Promise.all([getStageCards(sessionId), getNarratives(sessionId)]);
      if (alive.current && serial === requestSerial.current) {
        setCards(result.cards);
        setNarrative(projection);
        setFocusEnabled(Boolean(result.interaction_time_policy));
        const restored = result.interaction_focus;
        setFocus(restored ? {runtimeId: restored.runtime_id, token: restored.focus_token} : null);
      }
    } catch {
      if (alive.current && serial === requestSerial.current) setError(language === "zh-CN" ? "活动同步失败，可刷新重试。" : "Activity sync failed. Refresh to retry.");
    }
  }, [language, sessionId]);

  useEffect(() => {
    alive.current = true;
    const timer = window.setTimeout(() => void load(), 0);
    return () => { alive.current = false; window.clearTimeout(timer); };
  }, [load, worldRevision]);

  useEffect(() => {
    if (!focusRuntimeId) return;
    const poll = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 4_000);
    return () => window.clearInterval(poll);
  }, [focusRuntimeId, load]);

  useEffect(() => {
    if (!focusRuntimeId || !focusToken) return;
    const timer = window.setInterval(() => {
      void changeInteractionFocus(sessionId, { operation: "renew", runtime_id: focusRuntimeId,
        focus_token: focusToken, idempotency_key: crypto.randomUUID() }).catch(() => {
          setFocus(null); worldChangeCallback.current();
        });
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [focusRuntimeId, focusToken, sessionId]);

  async function toggleFocus(card: StageCard) {
    setBusy(true);
    ++requestSerial.current;
    try {
      const result = await changeInteractionFocus(sessionId, { operation: focus ? "release" : "acquire",
        runtime_id: card.runtime_id, focus_token: focus?.token, idempotency_key: crypto.randomUUID() });
      setFocus(focus ? null : {runtimeId: card.runtime_id, token: result.focus_token});
      setFeedback(focus ? "讨论已结束，可以继续活动。" : "你已加入讨论。岛屿时间暂停，可以在下面输入想对在场居民说的话。");
      setError(""); onWorldChanged();
      return true;
    } catch {
      setError(language === "zh-CN" ? "讨论焦点同步失败，请重试。" : "Discussion focus could not be updated. Retry.");
      return false;
    } finally { setBusy(false); }
  }

  async function act(card: StageCard, operation: StageOperation, choiceId?: string, inputs?: Record<string, string | boolean>) {
    if (busy || disabled) return;
    setBusy(true);
    setError("");
    ++requestSerial.current;
    let token = focus?.token;
    if (focusEnabled && (card.kind === "decision" || card.kind === "closure" || card.needs_confirmation) && focus?.runtimeId !== card.runtime_id && !operation.includes("publication")) {
      try {
        const result = await changeInteractionFocus(sessionId, {operation: "acquire", runtime_id: card.runtime_id, idempotency_key: crypto.randomUUID()});
        token = result.focus_token;
        setFocus({runtimeId: card.runtime_id, token});
      } catch {setError("活动已经变化，请重新打开任务后重试。"); setBusy(false); return;}
    }
    pending.current = { runtimeId: card.runtime_id, body: {
      operation, choice_id: choiceId, expected_revision: card.revision,
      inputs,
      focus_token: token,
      idempotency_key: crypto.randomUUID(), language,
    } };
    await submitPending();
  }

  async function submitPending() {
    const request = pending.current;
    if (!request) return;
    setBusy(true);
    try {
      const next = await sendStageAction(sessionId, request.runtimeId, request.body);
      if (!alive.current) return;
      pending.current = null;
      if (request.body.operation === "discuss") setDiscussionText("");
      if (["execute", "finish"].includes(request.body.operation) && request.body.focus_token) {
        await changeInteractionFocus(sessionId, {operation: "release", runtime_id: request.runtimeId, focus_token: request.body.focus_token, idempotency_key: crypto.randomUUID()}); setFocus(null);
      }
      setCards((previous) => previous.map((card) => card.runtime_id === next.runtime_id ? next : card));
      setError("");
      setFeedback(next.feedback ?? (request.body.operation === "suggest" ? "已选好这一项。确认后开始。" : request.body.operation === "confirm" ? "选择已确认，请执行当前环节。" : "本步已完成，看看接下来的安排。"));
      onWorldChanged();
    } catch (caught) {
      if (!alive.current) return;
      const http = caught as { status?: number };
      if (http.status) {
        pending.current = null;
        await load();
      }
      setError(language === "zh-CN" ? "操作未确认，请重试；活动发生变化时会重新同步。" : "The action was not confirmed. Retry; changed activities will be resynced.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function planAction(card: StageCard, operation: NonNullable<StageCard["plan_controls"]>[number]) {
    if (busy || disabled || card.plan_revision === undefined) return;
    setBusy(true);
    try {
      await changePlayerPlan(sessionId, card.commitment_id, card.plan_revision, operation);
      setFeedback(({start: "活动开始了，请选择下面的具体步骤。", arrive: "你已到场，可以参与当前环节。", leave: "你已离开活动，仍可自由探索。", cancel: "活动已取消。", accept: "已接受邀请。", withdraw: "已退出报名。"})[operation]);
      setError(""); await load(); onWorldChanged();
    } catch {
      setError(language === "zh-CN" ? "活动条件已变化，请刷新后重试；双方同意并到场后才能开始。" : "Conditions changed. Refresh and retry; everyone must agree and arrive first.");
      await load();
    } finally {setBusy(false);}
  }

  const visible = cards.filter((card) => (card.status === "active" || card.status === "waiting") && card.viewer_response === "accepted");
  const signatures = [`guide:${day}`, ...visible.map(c => `${c.runtime_id}:${c.stage_id}:${c.status}:${c.plan_status}`)];
  const signatureKey = signatures.join("|");
  useEffect(() => {const timer = window.setTimeout(() => {try {setSeen(JSON.parse(sessionStorage.getItem(`tasks-seen:${sessionId}`) ?? "[]"));} catch {setSeen([]);}}, 0); return () => window.clearTimeout(timer);}, [sessionId]);
  useEffect(() => {
    const keys = signatureKey.split("|");
    const timer = window.setTimeout(() => {if (open) {setSeen(previous => {const next = Array.from(new Set([...previous, ...keys])); sessionStorage.setItem(`tasks-seen:${sessionId}`, JSON.stringify(next)); return next;});}}, 0);
    return () => window.clearTimeout(timer);
  }, [open, signatureKey, sessionId]);
  useEffect(() => {onCountChange(signatureKey.split("|").filter(k => !seen.includes(k)).length);}, [signatureKey, seen, onCountChange]);
  const completed = cards.filter((card) => (card.status === "completed" || card.status === "failed") && card.facts.length > 0);
  const label = (value: StageCard["label"]) => value[language] ?? value.en ?? "";
  const choosing = (card: StageCard) => card.kind === "decision" || card.needs_confirmation === true;
  const buttonClass = "focus-ring min-h-11 rounded-lg border border-stone-300 bg-white px-3 py-2 text-left text-sm font-semibold hover:bg-stone-50 disabled:opacity-50";
  if (!open) return null;
  const privacy = (card: StageCard) => <details className="text-sm">
    <summary className="focus-ring cursor-pointer py-2">{language === "zh-CN" ? "活动记录的公开范围" : "Activity record visibility"}</summary>
    <p className="my-2 text-xs text-stone-600">{language === "zh-CN" ? "所有亲历者同意后，记录才可公开。撤回后，其他人不能再获得这些记录。" : "Records can be public after all witnesses agree. Withdrawal stops new readers from acquiring them."}</p>
    <div className="flex flex-wrap gap-2">
      <button type="button" className={buttonClass} disabled={busy || disabled} onClick={() => void act(card, "allow_publication")}>{language === "zh-CN" ? "同意公开记录" : "Allow public records"}</button>
      <button type="button" className={buttonClass} disabled={busy || disabled} onClick={() => void act(card, "revoke_publication")}>{language === "zh-CN" ? "撤回公开许可" : "Withdraw public permission"}</button>
    </div>
  </details>;

  return <div className="fixed inset-0 z-[95] flex items-center justify-center bg-stone-950/60 p-4"><aside ref={dialogRef} role="dialog" aria-modal="true" aria-label="任务" data-testid="modular-stage-panel" className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-stone-50 p-5 shadow-xl">
    <div className="sticky top-0 z-10 flex items-center justify-between bg-stone-50 pb-3"><h1 className="text-xl font-bold">任务</h1><button ref={closeButtonRef} type="button" className={buttonClass} disabled={busy} onClick={async () => {if (focus) {const card = cards.find(c => c.runtime_id === focus.runtimeId); if (card && !await toggleFocus(card)) return;} onClose();}}>关闭任务</button></div>
    <section className="rounded-xl border bg-white p-4"><p className="text-xs font-semibold text-teal-800">今日引导 · 可自由选择</p><h2 className="mt-1 font-bold">{["", "熟悉小岛", "选个地方逛逛", "和居民聊聊兴趣", "约人一起玩", "写下今天的见闻", "重访喜欢的角落", "向小岛道别"][day]}</h2><p className="mt-2 text-sm leading-6">{["", "从客房出发看看小岛。今晚有欢迎派对，具体邀请请在手机的邀约页查看，接受后会加入下方安排。", "在地图上选一个想去的地方，点开物品看看可以做什么。", "点击一位在场居民，可以聊聊各自喜欢的事。", "打开手机邀约页，选择一个活动邀请居民；也可以继续独自探索。", "回到客房写一段日记，或者在手机动态里分享今天的见闻。", "看看日志，回到喜欢的地方，或和熟悉的居民再聊一会儿。", "今天是度假的最后一天。篝火晚会的邀请在手机里；结束七日体验后会继续进入量表和反馈环节。"][day]}</p></section>
    {feedback ? <p role="status" className="my-3 whitespace-pre-wrap rounded-xl border border-teal-200 bg-teal-50 p-4 leading-7">{feedback}</p> : null}
    {!visible.length ? <p className="my-4 text-sm text-stone-600">还没有已接受的活动安排。收到的邀请可在手机“邀约”中查看。</p> : null}
    {focus ? <button type="button" className={`${buttonClass} mt-2`} disabled={busy || disabled} onClick={() => {
      const card = cards.find((item) => item.runtime_id === focus.runtimeId);
      if (card) void toggleFocus(card);
    }}>{language === "zh-CN" ? "结束讨论，恢复时间" : "End discussion and resume time"}</button> : null}
    {open ? visible.map((card) => <section key={card.runtime_id} aria-label={label(card.label)} className="mt-3 space-y-3 border-t border-stone-200 pt-3">
      <h2 className="font-bold">{label(card.activity_label ?? card.label)}</h2><p className="text-sm text-teal-800">{label(card.location_label ?? {})} · 当前环节：{label(card.label)}</p>
      {card.status === "waiting" ? <p className="text-sm">{language === "zh-CN" ? `约定第 ${card.scheduled_day} 天 ${String(Math.floor((card.scheduled_time_minutes ?? 0) / 60)).padStart(2, "0")}:${String((card.scheduled_time_minutes ?? 0) % 60).padStart(2, "0")}。等待回应或到场；可继续自由活动。` : "Waiting for responses or arrival. You can keep exploring."}</p> : null}
      {card.missed_stages?.length ? <p className="text-xs text-stone-600">{language === "zh-CN" ? "已错过的环节未计为参加。你可以从当前环节开始。" : "Missed phases remain uncompleted. Join the current phase."}</p> : null}
      <div className="flex flex-wrap gap-2">{card.plan_controls?.filter(operation => operation !== "accept").map(operation => <button key={operation} type="button" className={buttonClass} disabled={busy || disabled} onClick={() => void planAction(card, operation)}>{language === "zh-CN" ? ({start: "开始活动", arrive: "我已到场", leave: "提前离开", cancel: "取消活动", accept: "接受邀请", withdraw: "退出报名"})[operation] : operation}</button>)}</div>
      {focusEnabled && !focus && card.is_present && card.status === "active" && (choosing(card) || card.kind === "closure") ? <button type="button" className={buttonClass} disabled={busy || disabled} onClick={() => void toggleFocus(card)}>
        {focus ? (language === "zh-CN" ? "结束讨论，恢复时间" : "End discussion and resume time") : (language === "zh-CN" ? "进入讨论，暂停世界" : "Enter discussion and pause the world")}
      </button> : null}
      {focus?.runtimeId === card.runtime_id ? <section className="space-y-3 rounded-xl border border-teal-300 bg-white p-4" aria-label="活动讨论">
        <h3 className="font-bold">一起聊聊 · {label(card.activity_label ?? card.label)}</h3>
        <div role="log" className="max-h-64 space-y-3 overflow-auto">{card.discussion?.map(turn => <article key={turn.id}><p className="text-sm"><strong>你：</strong>{turn.text}</p><p className="mt-1 text-sm leading-6"><strong>{turn.speaker}：</strong>{turn.reply}</p></article>)}</div>
        <label className="block text-sm">想说的话<textarea aria-label="活动讨论内容" value={discussionText} maxLength={500} onChange={e => setDiscussionText(e.target.value)} className="mt-2 min-h-20 w-full rounded border p-2" /></label>
        <button type="button" className={buttonClass} disabled={busy || disabled || !discussionText.trim()} onClick={() => void act(card, "discuss", undefined, {message: discussionText.trim()})}>{busy ? "居民正在回应…" : "发送给在场居民"}</button>
      </section> : null}
      {!card.is_present ? <p className="text-sm text-stone-700">{language === "zh-CN" ? "到达活动地点并登记到场后，可参与当前阶段。" : "Reach the activity location and record your arrival to join the current stage."}</p> : null}
      {card.proposal ? <p role="status" className="text-sm">{language === "zh-CN" ? "当前建议：" : "Current suggestion: "}{label(card.choices.find((choice) => choice.choice_id === card.proposal?.choice_id)?.label ?? {})}</p> : null}
      <div className="grid gap-2">
        {(choosing(card) && card.proposal && card.can_confirm ? [] : card.choices).map((choice) => !choosing(card) && choice.input_fields?.length ? <StageInputChoice key={`${card.stage_id}:${choice.choice_id}`} choice={choice} language={language} disabled={busy || disabled || !card.is_present || !card.can_finish} onExecute={inputs => void act(card, "execute", choice.choice_id, inputs)} /> : <button key={choice.choice_id} type="button" className={buttonClass} disabled={busy || disabled || !card.is_present || (!choosing(card) && !card.can_finish)} onClick={() => void act(card, choosing(card) ? "suggest" : card.kind === "action" ? "execute" : "finish", choice.choice_id)}>
          {choosing(card) ? (language === "zh-CN" ? "选择：" : "Choose: ") : card.kind === "action" ? (language === "zh-CN" ? "执行：" : "Carry out: ") : ""}{label(choice.label)}
        </button>)}
        {choosing(card) && card.proposal && card.can_confirm ? <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonClass} disabled={busy || disabled} onClick={() => void act(card, "confirm", card.proposal!.choice_id)}>{language === "zh-CN" ? "确认当前建议" : "Confirm current suggestion"}</button>
          <button type="button" className={buttonClass} disabled={busy || disabled} onClick={() => void act(card, "reject")}>{language === "zh-CN" ? "重新讨论" : "Reopen discussion"}</button>
        </div> : null}
      </div>
      {card.kind === "decision" && !card.can_confirm ? <p className="text-xs text-stone-600">{language === "zh-CN" ? "建议提交后，由拥有决定权的角色确认。" : "The role with decision authority confirms submitted suggestions."}</p> : null}
      {card.facts.length ? privacy(card) : null}
    </section>) : null}
    {open && completed.length ? <details className="mt-3 border-t border-stone-200 pt-3">
      <summary className="focus-ring cursor-pointer py-2 font-semibold">{language === "zh-CN" ? "已结束的活动" : "Ended activities"}</summary>
      {completed.map((card) => <section key={card.runtime_id} className="my-3"><h2 className="font-semibold">{label(card.activity_label ?? card.label)} · {card.status === "completed" ? (language === "zh-CN" ? "已完成" : "Completed") : (language === "zh-CN" ? "未完成" : "Not completed")}</h2>{privacy(card)}</section>)}
    </details> : null}
    {open && narrative?.arcs.length ? <details className="mt-3 border-t border-stone-200 pt-3"><summary className="focus-ring cursor-pointer py-2 font-semibold">{language === "zh-CN" ? "社区近况" : "Community progress"}</summary>
      <p className="text-xs">{language === "zh-CN" ? "依据你亲历或实际阅读的记录；可以不参与。" : "Based on records you experienced or read. Participation is optional."}</p>
      {narrative.arcs.map(arc => <p key={arc.arc_id} className="mt-2 text-sm">{arc.label[language] ?? arc.label.en}：{language === "zh-CN" ? ({completed: "已完成", partial: "部分进展", unresolved: "未解决", unobserved: "尚无已知进展"}[arc.status] ?? arc.status) : arc.status}</p>)}
    </details> : null}
    {error ? <div role="alert" className="mt-3 text-sm text-red-800">{error}<button type="button" className={`${buttonClass} ml-2`} disabled={busy || disabled} onClick={() => void (pending.current ? submitPending() : load())}>{language === "zh-CN" ? "重试" : "Retry"}</button></div> : null}
    {busy ? <p role="status" className="mt-2 text-sm">{language === "zh-CN" ? "正在保存…" : "Saving…"}</p> : null}
  </aside></div>;
}
