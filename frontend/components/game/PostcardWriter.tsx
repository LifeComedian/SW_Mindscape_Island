"use client";
import {useState} from 'react';
import type {ObjectOperation} from '@/lib/api';
import {HolidayIllustration} from './HolidayIllustration';

export function PostcardWriter({action,disabled,onSave}:{action:ObjectOperation;disabled:boolean;onSave:(payload:Record<string,unknown>)=>Promise<boolean>}){
 const [face,setFace]=useState('');
 const [text,setText]=useState('');
 const [publicDisplay,setPublicDisplay]=useState(false);
 const chosen=action.items.find(i=>i.id===face);
 const status=action.postcard_status!;
 if(status.written_today)return <p role="status" className="rounded-xl bg-teal-50 p-4">今天已经写过一张明信片了，明天再来写吧。</p>;
 if(!status.can_write)return <p role="status">这次旅行的明信片已经用完了。</p>;
 return <section aria-label="写明信片" className="space-y-4">
  <p className="text-sm text-stone-600">每天可以写一张。先挑选一张还没有人用过的卡片。</p>
  <div aria-label="可选明信片" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
   {action.items.map((i,index)=><button key={i.id} type="button" aria-label={`选择第${index+1}张明信片`} aria-pressed={face===i.id} disabled={disabled} onClick={()=>setFace(i.id)} className={`focus-ring overflow-hidden rounded-xl border bg-white p-2 text-sm disabled:opacity-50 ${face===i.id?'ring-2 ring-teal-700':''}`}>
    <HolidayIllustration id={i.art_id!} alt={`明信片图案${index+1}`} compact staticDay/>
   </button>)}
  </div>
  {chosen&&<div data-testid="postcard-preview" className="overflow-hidden rounded-xl border bg-[#fff9e9]">
   <HolidayIllustration id={chosen.art_id!} alt="已选择的明信片图案" staticDay/>
   <p className="whitespace-pre-wrap p-5 leading-8">{text||'你的文字会写在这张卡片上。'}</p>
  </div>}
  <textarea aria-label="明信片正文" placeholder="写下想留住的片段……" disabled={disabled} maxLength={500} value={text} onChange={e=>setText(e.target.value)} className="min-h-40 w-full rounded-xl border bg-[#fff9e9] p-4 leading-8"/>
  <label className="flex items-center gap-2"><input type="checkbox" disabled={disabled} checked={publicDisplay} onChange={e=>setPublicDisplay(e.target.checked)}/>公开展示在明信片架上</label>
  <button type="button" className="focus-ring rounded-xl border bg-white px-4 py-3 disabled:opacity-40" disabled={disabled||!chosen||!text.trim()} onClick={()=>void onSave({command:'save',face_id:face,text,public:publicDisplay})}>保存明信片</button>
 </section>;
}
