export type CompletionReceiptPayload = {
  status: "completed";
  title: string;
  message: string;
  completed_at: string;
  research_id: string;
  completion_code: string;
  reward_amount_yuan: number;
  claim_by: string | null;
  contact_email: string;
  contact_wechat: string;
  claim_note: string;
  screenshot_note: string;
  screenshot_required: false;
  screenshot_uploaded: false;
};

export default function CompletionReceipt({ receipt }: { receipt: CompletionReceiptPayload }) {
  return (
    <section className="w-full overflow-hidden rounded-3xl border border-teal-100 bg-white shadow-sm" data-testid="completion-receipt">
      <div className="bg-teal-700 px-6 py-8 text-white sm:px-10">
        <p className="text-sm font-semibold text-teal-100">MindScape Island</p>
        <h1 className="mt-2 text-3xl font-semibold" data-testid="study-step">{receipt.title}</h1>
      </div>
      <div className="p-6 sm:p-10">
        <p className="leading-7 text-slate-600">{receipt.message}</p>
        <dl className="mt-7 grid gap-4 sm:grid-cols-2">
          <div className="rounded-2xl bg-slate-50 p-5">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">研究编号</dt>
            <dd className="mt-2 break-all font-mono text-lg font-semibold text-slate-900" data-testid="completion-research-id">{receipt.research_id}</dd>
          </div>
          <div className="rounded-2xl bg-slate-50 p-5">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">完成时间</dt>
            <dd className="mt-2 text-sm font-medium leading-6 text-slate-900" data-testid="completion-time">{receipt.completed_at}</dd>
          </div>
        </dl>
        <div className="mt-4 rounded-2xl border-2 border-dashed border-teal-200 bg-teal-50 p-5 text-center">
          <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">完成码</p>
          <p className="mt-2 select-all break-all font-mono text-2xl font-bold tracking-wider text-teal-950" data-testid="completion-code">{receipt.completion_code}</p>
        </div>
        <p className="mt-6 rounded-2xl border border-slate-200 p-4 text-sm leading-7 text-slate-600" data-testid="screenshot-note">{receipt.screenshot_note}</p>
        <div className="mt-4 rounded-2xl bg-teal-50 p-4 text-sm leading-7" data-testid="reward-instructions">
          <p className="font-semibold">完成补偿：{receipt.reward_amount_yuan} 元</p>
          <p>{receipt.claim_note}</p>
          {receipt.claim_by ? <p>请于 {new Date(receipt.claim_by).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", hour12: false})}（北京时间）前联系。</p> : null}
          <p>邮箱：<a className="underline" href={`mailto:${receipt.contact_email}`}>{receipt.contact_email}</a></p>
          <p>微信：<span className="select-all">{receipt.contact_wechat}</span></p>
        </div>
        <p className="mt-5 text-center text-sm font-medium text-slate-600">您现在可以安全关闭本页面。</p>
      </div>
    </section>
  );
}
