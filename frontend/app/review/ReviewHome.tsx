"use client";
import { useEffect, useRef, useState } from "react";

type Visit={session_id:string;nickname:string;state:string;created_at:string;day:number;reports_ready:boolean};
type Opened={recovery_code:string;nickname:string;current_step_path:string;study_session_id:string};
const button="rounded-xl bg-teal-800 px-5 py-3 font-semibold text-white hover:bg-teal-900 disabled:cursor-wait disabled:opacity-50";
const input="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-100";

async function command(name:string,body:unknown){
  const response=await fetch(`/review/api/${name}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail?.message??'操作未完成，请稍后重试。');
  return data;
}

export default function ReviewHome(){
  const [authenticated,setAuthenticated]=useState<boolean|null>(null);
  const [visits,setVisits]=useState<Visit[]>([]);
  const [notice,setNotice]=useState('');
  const [code,setCode]=useState('');
  const [nickname,setNickname]=useState('');
  const [accepted,setAccepted]=useState(false);
  const [recovery,setRecovery]=useState('');
  const [opened,setOpened]=useState<Opened|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [copied,setCopied]=useState(false);
  const accessKey=useRef('');const startKey=useRef('');

  async function load(){
    const response=await fetch('/review/api/visits',{cache:'no-store'});
    if(response.status===401){setAuthenticated(false);setVisits([]);return;}
    if(!response.ok)throw new Error('暂时无法读取存档，请刷新后重试。');
    const data=await response.json();setAuthenticated(true);setVisits(data.visits);
  }
  useEffect(()=>{
    void load().catch(e=>setError(e.message));
    void fetch('/review/api/notice',{cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error('体验说明暂时无法加载，请刷新页面。');setNotice((await r.json()).text);}).catch(e=>setError(e.message));
  },[]);

  async function start(){
    if(!nickname.trim()||!accepted||!notice){setError('请填写昵称，并阅读、同意体验说明。');return;}
    if(visits.length>0&&!window.confirm('开始一轮新的体验？之前的存档和报告会保留，可随时返回。'))return;
    setBusy(true);setError('');setOpened(null);setCopied(false);
    try{
      if(!authenticated){
        accessKey.current ||= crypto.randomUUID();
        await command('access',{code,request_key:accessKey.current});setAuthenticated(true);setCode('');
      }
      startKey.current ||= crypto.randomUUID();
      const result=await command('start',{nickname:nickname.trim(),accepted,request_key:startKey.current});
      setOpened(result);startKey.current='';await load();
    }catch(e){setError(e instanceof Error?e.message:'创建失败，请重试。');}
    finally{setBusy(false);}
  }
  async function resume(visit:Visit,mode:'continue'|'report'|'code'){
    setBusy(true);setError('');setCopied(false);
    try{
      const result=await command('resume',{session_id:visit.session_id});
      if(mode==='code')setOpened(result);
      else window.location.assign(mode==='report'?'/review/reports':result.current_step_path);
    }catch(e){setError(e instanceof Error?e.message:'恢复失败，请重试。');}
    finally{setBusy(false);}
  }
  async function recover(){
    setBusy(true);setError('');setCopied(false);
    try{const result=await command('recover',{code:recovery});setOpened(result);setRecovery('');await load();}
    catch(e){setError(e instanceof Error?e.message:'恢复失败，请重试。');}
    finally{setBusy(false);}
  }
  function saveCode(){
    if(!opened)return;
    const data=`MindScape Island 个人恢复码\n昵称：${opened.nickname}\n网址：${location.origin}/review\n恢复码：${opened.recovery_code}\n\n这是个人存档的访问凭证，请勿转发。\n`;
    const url=URL.createObjectURL(new Blob([data],{type:'text/plain;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='MindScape-Island-恢复码.txt';link.click();URL.revokeObjectURL(url);
  }

  return <main className="min-h-screen bg-[#f4f8f5] px-5 py-10 text-slate-800"><div className="mx-auto max-w-4xl space-y-6">
    <header className="rounded-3xl bg-teal-900 px-7 py-9 text-white sm:px-10"><p className="text-sm tracking-[0.2em] text-teal-200">项目评审 · 可重复体验</p><h1 className="mt-3 text-3xl font-semibold sm:text-4xl">MindScape Island <span className="whitespace-nowrap font-normal">潮汐岛</span></h1><p className="mt-4 max-w-2xl leading-7 text-teal-50">在岛上度过七个虚拟日，与居民交谈、探索和创作。每一轮都有独立存档；关闭页面后可以回来继续，也可以重新开始。</p></header>
    {error&&<p role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">{error}</p>}
    {opened&&<section className="rounded-3xl border-2 border-teal-400 bg-white p-7" data-testid="review-recovery"><h2 className="text-xl font-semibold">{opened.nickname}的个人恢复码</h2><p className="mt-2 text-sm leading-6 text-slate-600">同一浏览器会自动保存进度。换设备或清理缓存后，可用这份恢复码找回本轮体验和之前的存档。</p><code className="mt-4 block select-all break-all rounded-xl bg-teal-50 p-4 text-sm">{opened.recovery_code}</code><div className="mt-4 flex flex-wrap gap-3"><button className={button} onClick={()=>window.location.assign(opened.current_step_path)}>进入本轮体验</button><button className="rounded-xl border px-4 py-3" onClick={saveCode}>下载恢复码</button><button className="rounded-xl border px-4 py-3" onClick={()=>void navigator.clipboard.writeText(opened.recovery_code).then(()=>setCopied(true)).catch(()=>setError('请选中上方恢复码手动复制，或下载保存。'))}>{copied?'已复制':'复制恢复码'}</button></div><p className="mt-3 text-xs text-slate-500">恢复码可访问你的记录，请自行保管，不要与公共体验口令一起转发。</p></section>}
    {authenticated===null&&<p className="p-4">正在读取体验记录…</p>}
    {visits.length>0&&<section className="rounded-3xl border border-slate-200 bg-white p-7"><h2 className="text-xl font-semibold">我的体验记录</h2><div className="mt-5 space-y-3">{visits.map(v=><article key={v.session_id} className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-slate-50 p-4"><div><p className="font-semibold">{v.nickname} · {v.reports_ready?'报告已生成':`第 ${v.day} 天`}</p><p className="mt-1 text-xs text-slate-500">{new Date(v.created_at).toLocaleString('zh-CN',{hour12:false})}</p></div><div className="flex flex-wrap gap-2"><button disabled={busy} className={button} onClick={()=>void resume(v,'continue')}>{v.reports_ready?'查看报告':'继续体验'}</button><button disabled={busy} className="rounded-xl border px-3 py-2 text-sm" onClick={()=>void resume(v,'code')}>保存恢复码</button></div></article>)}</div></section>}
    <section className="rounded-3xl border border-slate-200 bg-white p-7"><h2 className="text-xl font-semibold">{visits.length?'开始新的体验':'开始体验'}</h2><div className="mt-5 grid gap-4 sm:grid-cols-2">
      {!authenticated&&<label className="space-y-2"><span className="text-sm font-medium">公共体验口令</span><input className={input} type="password" autoComplete="off" value={code} onChange={e=>setCode(e.target.value)} placeholder="填写学校收到的体验口令"/></label>}
      <label className="space-y-2"><span className="text-sm font-medium">本轮昵称</span><input className={input} maxLength={20} value={nickname} onChange={e=>{setNickname(e.target.value);startKey.current='';}} placeholder="例如：海边旅人"/></label>
    </div><p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm leading-7">{notice||'正在加载体验说明…'}</p><label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1 h-4 w-4" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/><span>我已阅读上述说明，同意保存本次体验记录及相应的模型处理。</span></label><button className={`${button} mt-5`} disabled={busy||!notice||authenticated===null} onClick={()=>void start()}>{busy?'正在处理…':visits.length?'创建新存档':'创建存档并进入'}</button></section>
    <section className="rounded-3xl border border-slate-200 bg-white p-7"><h2 className="text-lg font-semibold">用个人恢复码找回存档</h2><p className="mt-2 text-sm text-slate-600">换了浏览器、设备，或清理过缓存，可以在这里恢复。</p><div className="mt-4 flex flex-col gap-3 sm:flex-row"><input aria-label="个人恢复码" className={input} type="password" autoComplete="off" placeholder="RV- 开头的个人恢复码" value={recovery} onChange={e=>setRecovery(e.target.value)}/><button className={`${button} whitespace-nowrap`} disabled={busy||!recovery.trim()} onClick={()=>void recover()}>恢复存档</button></div></section>
    <footer className="pb-8 text-center text-sm text-slate-500">评审体验记录独立保存，不计入正式研究。{authenticated&&<button className="ml-3 underline" onClick={()=>void command('logout',{}).then(()=>location.reload())}>退出本浏览器</button>}</footer>
  </div></main>;
}
