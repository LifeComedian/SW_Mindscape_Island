"use client";
import { useEffect } from "react";
import { usePathname } from "next/navigation";

export default function ReviewToolbar() {
  const path=usePathname();
  useEffect(()=>{
    const renew=()=>{if(document.visibilityState==="visible") void fetch('/review/api/visits',{cache:'no-store'}).catch(()=>{});};
    renew();const timer=setInterval(renew,300000);
    return()=>clearInterval(timer);
  },[]);
  if(path.startsWith('/review'))return null;
  return <div className="fixed bottom-3 right-3 z-[90] flex gap-2 rounded-xl border border-teal-200 bg-white/95 px-3 py-2 text-sm shadow-lg"><span className="text-teal-800">评审体验</span><a className="font-semibold underline" href="/review">存档与重新开始</a></div>;
}
