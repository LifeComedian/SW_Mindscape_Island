"use client";
import {useState} from "react";
import type {StageChoice} from "@/lib/api";
import type {Language} from "@/lib/i18n";
export function StageInputChoice({choice, language, disabled, onExecute}: {choice: StageChoice; language: Language; disabled: boolean; onExecute: (inputs: Record<string, string | boolean>) => void}) {
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const fields = choice.input_fields ?? [];
  return <div className="space-y-2 rounded border bg-white p-3">
    <p className="text-sm">{choice.label[language] ?? choice.label.en}</p>
    {fields.map(f => f.value_type === "boolean" ? <label key={f.input_id} className="flex gap-2 text-xs"><input type="checkbox" checked={values[f.input_id] === true} onChange={e => setValues(v => ({...v, [f.input_id]: e.target.checked}))} />{language === "zh-CN" ? "我同意把这段自述发布到岛内公开留言。" : "Publish this statement to the island feed."}</label> : <label key={f.input_id} className="block text-sm">{language === "zh-CN" ? "我的文字" : "My note"}<textarea maxLength={f.max_length ?? 500} value={String(values[f.input_id] ?? "")} onChange={e => setValues(v => ({...v, [f.input_id]: e.target.value}))} className="focus-ring min-h-20 w-full rounded border p-2" /></label>)}
    <button type="button" disabled={disabled || fields.some(f => f.required && !(typeof values[f.input_id] === "string" ? String(values[f.input_id]).trim() : values[f.input_id]))} onClick={() => onExecute(values)} className="focus-ring rounded bg-teal-700 px-3 py-2 text-white disabled:opacity-50">{language === "zh-CN" ? "确认保存并继续" : "Save and continue"}</button>
  </div>;
}
