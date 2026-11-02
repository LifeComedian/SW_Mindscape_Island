import type {Language} from "@/lib/i18n";
export function ObjectResult({state, objectId, language}: {state: unknown; objectId: string; language: Language}) {
  const runtime = (state && typeof state === "object" ? (state as Record<string, unknown>).modular_runtime : undefined) as {object_states?: Record<string, Record<string, unknown>>} | undefined;
  const entries = Object.entries(runtime?.object_states?.[objectId] ?? {}).filter(([key, value]) => typeof value === "string" && (key === "result" || /^act_\d+$|^phase_\d+_choice$/.test(key)));
  if (!entries.length) return null;
  const visible = entries.some(([key]) => key === 'result') ? entries.filter(([key]) => key === 'result') : entries;
  return <section role="status" className="space-y-2 rounded-lg border border-teal-200 bg-white p-3 text-sm" data-testid="object-result"><h4 className="font-bold">{language === "zh-CN" ? "刚刚发生了什么" : "What happened"}</h4>{visible.map(([key, value]) => <p key={key} className="whitespace-pre-line leading-6">{String(value)}</p>)}</section>;
}
