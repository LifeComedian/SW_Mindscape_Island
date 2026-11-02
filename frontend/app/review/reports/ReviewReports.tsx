"use client";
import { useEffect,useState } from "react";
import IslandRecap from "@/app/study/components/IslandRecap";
import type {CurrentResultPayload} from "@/app/study/components/RandomizedResultsFlow";
type Results={nickname:string;state:string;reports:CurrentResultPayload['report'][];questionnaire_submitted:boolean;recovery_code:string};

export default function ReviewReports(){
  const [data,setData]=useState<Results|null>(null);const [error,setError]=useState('');
  useEffect(()=>{void fetch('/review/api/reports',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(async r=>{const p=await r.json();if(!r.ok)throw new Error(p.detail?.message??'请返回体验入口，选择需要查看的存档。');setData(p);}).catch(e=>setError(e.message));},[]);
  return <main className="min-h-screen bg-[#f4f8f5] px-5 py-10"><div className="mx-auto max-w-5xl space-y-7"><header><a className="text-sm font-semibold text-teal-800 underline" href="/review">← 返回存档与重新开始</a><h1 className="mt-5 text-3xl font-semibold">{data?.nickname??'本轮体验'}的报告</h1><p className="mt-3 leading-7 text-slate-600">以下内容来自本轮体验，独立于正式研究数据保存。可以返回入口保留本轮记录，再开始一轮新的体验。</p></header>
    {error&&<p role="alert" className="rounded-xl bg-red-50 p-5 text-red-800">{error}</p>}
    {!data&&!error&&<p>正在读取报告…</p>}
    {data?.reports.map((report,index)=><article className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-9" key={index}><p className="text-sm font-semibold text-teal-700">{report.report_kind==='game_estimate'?'岛屿观察':'BFI-2 人格问卷'}</p><h2 className="mt-2 text-2xl font-semibold">{report.title}</h2><p className="mt-3 text-sm leading-7 text-slate-500">{report.source}</p>
      {report.recap&&<IslandRecap data={report.recap}/>}
      {report.letter_paragraphs?<div className="mt-7 space-y-7 rounded-2xl bg-[#fffdf7] p-6 text-lg leading-9">{report.letter_paragraphs.map((p,i)=><section key={i}><p>{p.text}</p><details className="mt-3 text-sm leading-7 text-slate-600"><summary className="cursor-pointer">这段观察来自哪里</summary>{p.evidence.map((e,j)=><p key={j} className="mt-2">{e.description}</p>)}</details></section>)}</div>:<p className="mt-6 whitespace-pre-wrap leading-8">{report.summary}</p>}
      {!!report.dimensions.length&&<div className="mt-7 grid gap-4 sm:grid-cols-2">{report.dimensions.map(d=><div key={d.domain_id} className="rounded-xl border p-4"><p className="font-semibold">{d.label} {d.value!==null&&<span className="float-right">{d.value.toFixed(2)} / {d.maximum??5}</span>}</p><p className="mt-2 text-sm leading-6 text-slate-600">{d.description}</p></div>)}</div>}
      <p className="mt-6 text-sm leading-7 text-slate-600">{report.uncertainty_note}</p>
    </article>)}
    {data&&!data.reports.length&&<p className="rounded-2xl bg-white p-6">本轮还没有可展示的报告。请返回存档继续体验。</p>}
    {data?.questionnaire_submitted&&!data.reports.some(r=>r.report_kind==='questionnaire')&&<p className="rounded-xl bg-amber-50 p-5">本轮问卷未完整作答，因此没有生成 BFI-2 分数。</p>}
    <a className="inline-block rounded-xl bg-teal-800 px-6 py-3 font-semibold text-white" href="/review">返回存档 / 开始新的体验</a>
  </div></main>;
}
