"use client";
import {HolidayIllustration} from "./HolidayIllustration";
import {SketchPreview} from "./SketchCanvas";
import {Piece} from "./PlayPieces";
import type {ObjectItem} from "@/lib/api";


export function GalleryWork({item,compact=false}:{item:ObjectItem;compact?:boolean}){
  const pieces=item.design?.pieces??[];
  const free=item.design?.mode==='freecraft';
  const flower=pieces.some(p=>["daisy","warm","leaf","mint","rosemary","dandelion","jasmine","lavender","cosmos","sunflower","rose","tulip","hydrangea","lily"].includes(p.kind));
  const vase=item.design?.vessel==='bright'||(!item.design?.vessel&&item.name.includes('小陶瓶'));
  const book=Boolean(item.pages?.length);
  return <article className={`${book&&!compact?'grid items-start gap-5 md:grid-cols-[220px_minmax(0,1fr)]':'space-y-3'} rounded-2xl border border-stone-200 bg-[#fffaf0] p-4`}>
    {item.art_id&&<div className={book?'mx-auto w-full max-w-[260px]':''}><HolidayIllustration id={item.art_id} alt={item.name} compact={compact} staticDay/></div>}
    {(pieces.length>0)&&<svg viewBox={free?"0 0 600 400":"0 0 400 300"} aria-label={item.name+"，实际保存的作品"} className="mx-auto w-full max-w-xl rounded-xl bg-[#eee3cb]">
      <path d="M0 215H400M0 256H400" stroke="#d4c09c"/>
      {flower&&<>{vase?<><path d="M180 225Q190 245 170 259Q165 281 200 281Q235 281 230 259Q210 245 220 225Z" fill="#c98d64" stroke="#8d6549"/><ellipse cx="200" cy="225" rx="20" ry="5" fill="#76593f"/></>:<><path d="M145 233Q150 279 200 278Q250 279 255 233Z" fill="#ede4ca" stroke="#a78a65"/><ellipse cx="200" cy="233" rx="55" ry="12" fill="#c5b78f"/></>}
        {pieces.map((p,i)=><path key={i} d={`M${200+(i%3-1)*8} 239Q${p.x*4+8} 208 ${p.x*(free?6:4)} ${p.y*(free?4:3)}`} stroke="#748363" strokeWidth="2.5" fill="none"/>)}</>}
      {pieces.map((p,i)=><g key={i} transform={`translate(${p.x*(free?6:4)} ${p.y*(free?4:3)}) rotate(${p.angle??0}) scale(${flower?1.3:free?1.8:1.7})`}><Piece kind={p.kind}/></g>)}
      {item.strokes?.map((s,i)=><polyline key={i} points={s.map(([x,y])=>`${x*4},${y*3}`).join(" ")} fill="none" stroke="#355f59" strokeWidth="3"/>)}
    </svg>}
    {item.strokes&&<SketchPreview strokes={item.strokes} styles={item.stroke_styles} label={item.name+"，实际保存的作品"}/>}
    {!compact&&<div className="space-y-3"><h4 className="text-xl font-semibold">{item.name}</h4>
      <p className="whitespace-pre-wrap text-base leading-8">{item.text}</p>
      {item.author&&!book&&<p className="text-sm text-stone-600">{item.author==="participant"?"你的作品":"居民的作品"}{item.day!=null?` · 第${item.day}天保存`:""}</p>}
      {item.source_url&&<a href={item.source_url} target="_blank" rel="noreferrer" className="underline">阅读原始文本与出处</a>}
    </div>}
  </article>;
}
