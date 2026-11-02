"use client";
import {useState} from 'react';
import type {ObjectItem} from '@/lib/api';

export function SnackPurchase({item,disabled,onBuy}:{item:ObjectItem;disabled:boolean;onBuy:(payload:Record<string,unknown>)=>Promise<boolean>}){
  const [quantity,setQuantity]=useState(1);
  const [receipt,setReceipt]=useState('');
  const valid=Number.isInteger(quantity)&&quantity>=1&&quantity<=9;
  async function buy(){
    if(disabled||!valid)return;
    setReceipt('');
    if(await onBuy({command:'buy',item:item.id,quantity})){
      setReceipt(`已购买 ${item.name} × ${quantity}，合计 ¥${(item.price??0)*quantity}。`);
      setQuantity(1);
    }
  }
  return <section aria-label="购买零食" className="space-y-3 rounded-xl border border-teal-200 bg-teal-50 p-4">
    <label className="flex items-center gap-3">购买数量<input aria-label="购买数量" type="number" min={1} max={9} step={1} value={quantity} disabled={disabled} onChange={e=>setQuantity(e.target.valueAsNumber||0)} className="w-20 rounded border bg-white p-2"/></label>
    <p>{item.name} · 单价 ¥{item.price} · 合计 ¥{valid?(item.price??0)*quantity:0}</p>
    <button type="button" disabled={disabled||!valid} onClick={()=>void buy()} className="focus-ring min-h-11 rounded-xl bg-teal-800 px-5 py-3 font-semibold text-white disabled:opacity-40">确认购买</button>
    {receipt&&<p role="status">{receipt}</p>}
  </section>;
}
