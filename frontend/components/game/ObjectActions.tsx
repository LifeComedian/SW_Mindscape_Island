"use client";
import {useState} from "react";
import type {WorldActionDescriptor} from "@/lib/api";
import type {Language} from "@/lib/i18n";

type Descriptor = Exclude<WorldActionDescriptor, string>;
export function ObjectActions({actions, objectId, language, disabled, onExecute, onReadPublicNotes}: {
  actions: WorldActionDescriptor[]; objectId: string; language: Language; disabled: boolean;
  onExecute: (actionId: string, inputs: Record<string, string | boolean>) => Promise<boolean>;
  onReadPublicNotes?: () => void;
}) {
  const [selected, setSelected] = useState<Descriptor | null>(null);
  const [text, setText] = useState("");
  const [publish, setPublish] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const options = actions.filter((a): a is Descriptor => typeof a !== "string" && a.action_type === "defined_action" && Boolean(a.target_object_ids?.includes(objectId)) && !["act_48_choice_1", "act_48_choice_3"].includes(a.action_id ?? ""));
  const label = (a: Descriptor) => typeof a.label === "string" ? a.label : a.label?.[language] ?? a.label?.en ?? a.action_id;
  const field = selected?.inputs?.find(i => i.value_type === "free_text");
  const needsPublication = selected?.inputs?.some(i => i.input_id === "publish");
  async function save() {
    if (!selected?.action_id || !field || !text.trim() || needsPublication && !publish) return;
    if (await onExecute(selected.action_id, {[field.input_id]: text.trim(), ...(needsPublication ? {publish: true} : {})})) {
      setSavedMessage(needsPublication ? "已发布到手机动态，并保存到登岛日志。" : "已保存到你的登岛日志。只有你可以查看这段私人文字。");
      setSelected(null); setText(""); setPublish(false);
    }
  }
  return <div className="space-y-2 sm:col-span-2">
    {savedMessage ? <p role="status" className="rounded-lg bg-teal-50 p-3 text-sm text-teal-900">{savedMessage}</p> : null}
    {["obj_13", "obj_30"].includes(objectId) && onReadPublicNotes ? <button type="button" onClick={onReadPublicNotes} disabled={disabled} className="focus-ring min-h-11 w-full rounded-lg border border-teal-300 bg-teal-50 p-3 text-left text-xs font-bold text-teal-950">查看岛上公开留言（手机动态）</button> : null}
    {options.map(a => <button key={a.action_id} type="button" data-testid={`object-action-${a.action_id}`} disabled={disabled || a.enabled === false} onClick={() => {if (a.inputs?.length) {setSelected(a); setPublish(false);} else if (a.action_id) void onExecute(a.action_id, {});}} className="focus-ring min-h-11 w-full rounded-lg border border-teal-300 bg-teal-50 p-3 text-left text-xs font-bold text-teal-950 disabled:opacity-50">{label(a)}</button>)}
    {selected && field ? <div className="space-y-2 rounded-lg border bg-white p-3">
      <label className="block text-sm">{label(selected)}<textarea aria-label={language === "zh-CN" ? "我的文字" : "My note"} maxLength={field.max_length ?? 500} value={text} onChange={e => setText(e.target.value)} className="focus-ring mt-2 min-h-24 w-full rounded border p-2" /></label>
      <p className="text-xs text-stone-600">{language === "zh-CN" ? "文字按你的自述保存，不自动视作世界事实。" : "Saved as your statement, not an independently verified event."}</p>
      {needsPublication ? <label className="flex gap-2 text-xs"><input type="checkbox" checked={publish} onChange={e => setPublish(e.target.checked)} />{language === "zh-CN" ? "我愿意把这段文字发布到岛内公开留言中。" : "Publish this note to the island's public feed."}</label> : <p className="text-xs">{language === "zh-CN" ? "私人记录：居民不会自动读取。" : "Private: residents cannot read it automatically."}</p>}
      <div className="flex gap-2"><button type="button" disabled={disabled || !text.trim() || Boolean(needsPublication && !publish)} onClick={() => void save()} className="focus-ring rounded border px-3 py-2 disabled:opacity-50">{language === "zh-CN" ? "保存" : "Save"}</button><button type="button" disabled={disabled} onClick={() => setSelected(null)} className="focus-ring rounded border px-3 py-2">{language === "zh-CN" ? "取消" : "Cancel"}</button></div>
    </div> : null}
  </div>;
}
