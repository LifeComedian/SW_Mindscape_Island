"use client";
import {useState} from "react";
import type {ObjectItem} from "@/lib/api";
import {GalleryWork} from "./GalleryWork";

export function BookReader({item,initialPage=0,disabled,onFinish}:{item:ObjectItem;initialPage?:number;disabled:boolean;onFinish:(page:number)=>Promise<boolean>}){
 const pages=item.pages?.length?item.pages:[item.text];
 const [page,setPage]=useState(Math.max(0,Math.min(pages.length-1,initialPage)));
 const button="focus-ring min-h-11 rounded-xl border bg-white px-4 py-3 disabled:opacity-40";
 return <section aria-label="书籍正文" className="space-y-4">
  <GalleryWork item={{...item,text:pages[page]}}/>
  <p className="text-sm leading-6 text-stone-600">{item.attribution}</p>
  <nav aria-label="翻阅书页" className="flex flex-wrap items-center justify-between gap-3">
   <button className={button} disabled={page===0} onClick={()=>setPage(p=>p-1)}>上一页</button>
   <span aria-live="polite">第 {page+1} / {pages.length} 页</span>
   <button className={button} disabled={page===pages.length-1} onClick={()=>setPage(p=>p+1)}>下一页</button>
  </nav>
  <button className={button} disabled={disabled} onClick={()=>void onFinish(page)}>读完并放好书</button>
 </section>;
}
