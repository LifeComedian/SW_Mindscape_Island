"use client";
import {useState} from "react";
import {requestJson} from "@/lib/api";
import {SceneDialog} from "./SceneDialog";
import {HolidayNight} from "./HolidayNight";
import {HolidayIllustration} from "./HolidayIllustration";

export function DayBoundary({sid,day,total,onContinue}:{sid:number;day:number;total:number;onContinue:()=>Promise<void>}){
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  async function next(){
    if(busy)return;
    setBusy(true);setError("");
    try{
      await requestJson(`/sessions/${sid}/world/v5/next-day`,{method:"POST",body:JSON.stringify({
        day,idempotency_key:`v6-next-day:${sid}:${day}`
      })});
      await onContinue();
    }catch{setError("暂时没有连接成功，今天的记录已保留。请重试。");}
    finally{setBusy(false);}
  }
  return <HolidayNight night><main className="min-h-screen bg-[#122a3a] p-4 pt-24"><SceneDialog title={day<total?`第${day}天 · 晚安`:"七日假期 · 告别"}>
    <HolidayIllustration id={day<total?"location.guest_room":"activity.bonfire-goodbye"}/>
    <p className="my-6 text-lg leading-8">{day<total?"今天的记录已经保存。休息一下，准备好后再开启明天。":"这七天的记录已经保存。准备好后，继续完成离岛问卷与反馈。"}</p>
    <p className="mb-5 text-sm text-stone-600">每日自由活动时间为 08:00—22:00；点击后才会继续。</p>
    {error&&<p role="alert" className="mb-4 text-rose-700">{error}</p>}
    <button disabled={busy} onClick={()=>void next()} className="focus-ring w-full rounded-xl bg-teal-900 p-4 text-lg font-bold text-white disabled:opacity-50">{busy?"正在保存…":day<total?`进入第${day+1}天 · 08:00`:"结束假期，继续离岛流程"}</button>
  </SceneDialog></main></HolidayNight>;
}
