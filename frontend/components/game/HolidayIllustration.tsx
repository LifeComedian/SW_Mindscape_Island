"use client";
import Image from 'next/image';
import {useState} from 'react';
import {holidayArt} from '@/lib/holiday-art';
import {useHolidayNight} from './HolidayNight';

/** Display the full illustration without cropping. */
export function HolidayIllustration({id,alt,compact=false,staticDay=false}:{id:string;alt?:string;compact?:boolean;staticDay?:boolean}) {
  const night=useHolidayNight();
  const asset=holidayArt(id,night&&!staticDay);
  const [failed,setFailed]=useState('');
  if(!asset || failed===id)return <div role="status" className="rounded-2xl border bg-stone-50 p-5 text-sm text-stone-600">{alt??asset?.title??'插画'} · 图片暂未加载。{asset&&<button type="button" className="ml-3 underline" onClick={()=>setFailed('')}>重新加载</button>}</div>;
  return <figure data-testid="holiday-illustration" data-art-id={id} className="overflow-hidden rounded-2xl border border-stone-200 bg-[#f4efe4]">
    <Image unoptimized src={asset.url} width={asset.width} height={asset.height} loading="eager" alt={alt??asset.title} onError={()=>setFailed(id)} className={`block h-auto w-full object-contain ${compact?'max-h-64 sm:max-h-72':''}`}/>
  </figure>;
}
