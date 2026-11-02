"use client";
import {useState} from 'react';
import type {ObjectExperience,ObjectOperation} from '@/lib/api';
import {HolidayIllustration} from './HolidayIllustration';
import {ItemPicture} from './PlayPieces';

const button='focus-ring min-h-11 rounded-xl border border-teal-200 bg-white px-4 py-3 font-semibold hover:bg-teal-50 disabled:opacity-40';
export function DiningPanel({action,data,disabled,onExecute,onEnjoy}:{action:ObjectOperation;data:ObjectExperience;disabled:boolean;onExecute:(payload:Record<string,unknown>)=>Promise<boolean>;onEnjoy:()=>void}){
  const [cart,setCart]=useState<Record<string,number>>({});
  const [seat,setSeat]=useState('');
  const venue=action.venue!;
  const order=data.state.orders?.[venue];
  const active=!!order&&['preparing','served'].includes(order.status);
  const alreadyOrdered=active&&(!order.group?.startsWith('activity:')||!!order.contributions?.participant);
  const seated=data.state.rest_seats?.[venue]||(active?order?.seat:null);
  const seats=data.seats[venue]??[];
  const total=action.items.reduce((sum,i)=>sum+(cart[i.id]??0)*(i.price??0),0);
  return <section className="space-y-4" data-testid="dining-panel">
    {action.kind==='order'&&<>
      <p>先点餐饮，再关闭菜单，点击场景里的桌位选择座位。</p>
      <div className="grid gap-3 sm:grid-cols-3">{action.items.map(i=><article key={i.id} className="space-y-3 rounded-xl border bg-amber-50 p-3">
        {i.art_id?<HolidayIllustration id={i.art_id} alt={i.name} compact staticDay/>:<ItemPicture kind={i.id}/>}
        <h5 className="font-bold">{i.name} · ¥{i.price??0}</h5><p className="text-sm">{i.text}</p>
        <label className="flex items-center justify-between gap-2">{i.name}份数<input aria-label={`${i.name}份数`} type="number" min={0} max={9} className="w-16 rounded border bg-white p-2" disabled={disabled||alreadyOrdered} value={cart[i.id]??0} onChange={e=>setCart({...cart,[i.id]:Math.max(0,Math.min(9,Math.floor(Number(e.target.value)||0)))})}/></label>
      </article>)}</div>
      <p>合计 ¥{total}</p>
      <button className={button} disabled={disabled||alreadyOrdered||action.can_order===false||!Object.values(cart).some(Boolean)} onClick={()=>void onExecute({command:'confirm',cart:Object.fromEntries(Object.entries(cart).filter(([,n])=>n>0))}).then(ok=>{if(ok)setCart({});})}>确认点单</button>
      {action.can_order===false&&<p role="status">{action.order_unavailable_reason}</p>}
    </>}
    {active&&<div role="status" className="rounded-xl bg-teal-50 p-4"><p>{order.status==='preparing'?'点单已保存。请关闭菜单，到桌位选择座位。':'餐饮已送到桌边，可以享用了。'}</p><p>{order.selections?.join('；')}</p></div>}
    {action.kind==='seat'&&<>
      <p>选一个喜欢的位置，也可以不点单，只坐下来看看风景。</p>
      <div className="grid gap-3 sm:grid-cols-2">{seats.map(s=><button key={s.id} className={`${button} ${seat===s.id?'ring-2 ring-teal-700':''}`} aria-pressed={seat===s.id} disabled={disabled} onClick={()=>setSeat(s.id)}>
        <HolidayIllustration id={`view.${venue}.${s.id}`} alt={s.name} compact staticDay/><span>{s.name}</span><span className="block text-sm font-normal">{s.text}</span>
      </button>)}</div>
      <button className={button} disabled={disabled||!seat} onClick={()=>void onExecute({seat})}>在这里坐下</button>
    </>}
    {seated&&action.kind!=='order'&&<div data-testid="seat-view" className="space-y-2"><h5 className="font-bold">从{seats.find(s=>s.id===seated)?.name??'座位'}望出去</h5><HolidayIllustration id={`view.${venue}.${seated}`} alt="座位前的风景"/></div>}
    {order?.status==='served'&&action.kind!=='order'&&<div data-testid="ordered-food" className="space-y-3 rounded-2xl bg-[#f2e7ce] p-4"><h5 className="font-bold">你桌上的餐饮</h5><div className="grid gap-3 sm:grid-cols-2">{Object.entries(order.cart).map(([id,n])=>{
      const item=order.items?.[id];
      return <article key={id} className="rounded-xl bg-white/70 p-3">{item?.art_id?<HolidayIllustration id={item.art_id} alt={item.name} compact staticDay/>:<ItemPicture kind={id}/>}<p className="mt-2 font-semibold">{item?.name??'已点餐品'} ×{n}</p>{item?.text&&<p className="text-sm">{item.text}</p>}</article>;
    })}</div>{action.kind==='seat'&&<button className={button} disabled={disabled} onClick={onEnjoy}>{venue==='cafe'?'享用饮品':'用餐'}</button>}</div>}
    {action.kind==='consume'&&<><button className={button} disabled={disabled||order?.status!=='served'} onClick={()=>void onExecute({})}>{action.name}</button>{!order&&<p>先到菜单点单，再到桌位选择座位。</p>}{order?.status==='finished'&&<p role="status">已经享用完了，记录已保存，可以继续逛逛。</p>}</>}
    {action.kind==='leave'&&<button className={button} disabled={disabled} onClick={()=>void onExecute({})}>{action.name}</button>}
  </section>;
}
