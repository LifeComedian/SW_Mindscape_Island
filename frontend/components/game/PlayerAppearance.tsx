"use client";
import Image from "next/image";
export function PlayerAppearance({value,onChange}:{value:string;onChange:(v:'male'|'female')=>void}){
  return <fieldset className="my-5 rounded-2xl border bg-white p-4"><legend className="px-2 font-bold">选择你在岛上的形象</legend><p className="mb-3 text-sm text-stone-600">这是本次假期的游戏角色形象，居民会使用你选择的角色性别称呼你。</p><div className="grid grid-cols-2 gap-4">{(['male','female'] as const).map(g=><button type="button" key={g} aria-pressed={value===g} data-testid={`player-${g}`} onClick={()=>onChange(g)} className={`rounded-xl border p-3 ${value===g?'border-teal-700 bg-teal-50 ring-2 ring-teal-600':''}`}><Image unoptimized loading="eager" width={1086} height={1448} src={`/v5/player-${g}.png`} alt={g==='male'?'男玩家画像':'女玩家画像'} className="mx-auto h-48 w-full object-contain"/><span>{g==='male'?'男角色':'女角色'}</span></button>)}</div></fieldset>;
}
