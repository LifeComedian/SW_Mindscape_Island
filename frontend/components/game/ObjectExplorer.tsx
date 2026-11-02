"use client";
import {useEffect, useMemo, useRef, useState} from "react";
import {getObjectExperience, type ObjectExperience, type ObjectOperation} from "@/lib/api";
import {SketchCanvas} from "./SketchCanvas";
import {DiningPanel} from "./DiningPanel";
import {PostcardWriter} from "./PostcardWriter";
import {SnackPurchase} from "./SnackPurchase";
import {BookReader} from "./BookReader";
import {GalleryWork} from "./GalleryWork";
import {Workshop} from "./Workshop";
import {FreeWoodwork} from "./FreeWoodwork";
import {Huarong} from "./Huarong";
import {TimedVolley} from "./TimedVolley";
import {RopeWorkshop} from "./RopeWorkshop";
import {BeachSearch} from "./BeachSearch";
import {ItemPicture,Court,Piece} from "./PlayPieces";
import {HolidayIllustration} from "./HolidayIllustration";
import {holidayArt} from "@/lib/holiday-art";
import {seenV5,postV5,GROUP_PLAY,type GuidanceSource} from '@/lib/holiday-v5';

const btn="focus-ring min-h-11 rounded-xl border border-teal-200 bg-white px-4 py-3 text-left text-sm font-semibold hover:bg-teal-50 disabled:opacity-40";
type Props={sessionId:number;objectId?:string;initialActionId?:string;revision:number;disabled?:boolean;inActivity?:boolean;runtimeId?:number|null;guidance?:GuidanceSource;onExecute:(id:string,inputs:Record<string,string>)=>Promise<boolean>};
export function ObjectExplorer({sessionId,objectId,initialActionId,revision,disabled=false,inActivity=false,runtimeId=null,guidance="direct",onExecute}:Props){
  const [data,setData]=useState<ObjectExperience|null>(null);
  const [oid,setOid]=useState(objectId??initialActionId?.replace(/^v4_/, '').split('__')[0]??"");
  const [selected,setSelected]=useState(initialActionId?.split('__')[1]??"");
  const [item,setItem]=useState("");
  const [cart,setCart]=useState<Record<string,number>>({});
  const [seat,setSeat]=useState("");
  const [text,setText]=useState("");
  const [publish,setPublish]=useState(false);
  const [strokes,setStrokes]=useState<number[][][]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [chapter,setChapter]=useState('places');
  const [feedback,setFeedback]=useState('');
  const isV5=['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(data?.world_version ?? '');
  const v6=data?.world_version==='chaoxi-holiday-v6';
  const collective=useMemo(()=>v6&&oid==='beach'?{title:'一起寻物 · 2–4人',detail:'在海滩上找物品，也可以和同伴聊聊发现了什么。',recipe:'beach_search'}:v6&&oid==='games'?{title:'UNO · 2–4人',detail:'独自可玩华容道；UNO需要你和1–3位居民。',recipe:'table_game'}:v6&&oid==='volleyball'?{title:'多人垫球练习 · 2–4人',detail:'也可以邀请1–3位居民一起练习，轮流传接。',recipe:'volley_pass'}:GROUP_PLAY[oid],[v6,oid]);
  const exposure=useRef('');
  const pen=useRef(false);
  const inFlight=useRef(false);
  const feedbackPanel=useRef<HTMLDivElement>(null);
  useEffect(()=>{let live=true;void getObjectExperience(sessionId).then(d=>{if(live)setData(d);}).catch(()=>{if(live)setError("互动内容加载失败，请重试。");});return()=>{live=false;};},[sessionId,revision]);
  const object=data?.objects.find(o=>o.id===oid);
  const action=isV5&&oid==='guidebook'?undefined:object?.actions.find(a=>a.id===selected);
  const aid=action?`v4_${oid}__${action.id}`:"";
  const progress=data?.state.progress?.[aid]??{};
  const chosen=action?.items.find(i=>i.id===item);
  const order=action?.venue?data?.state.orders?.[action.venue]:null;
  async function execute(payload:Record<string,unknown>={},override?:ObjectOperation){
    const action=override??object?.actions.find(a=>a.id===selected);
    const aid=action?`v4_${oid}__${action.id}`:"";
    if(!action || inFlight.current || disabled)return false;
    inFlight.current=true;
    setBusy(true);setError("");setFeedback("");
    if(!v6&&!inActivity)requestAnimationFrame(()=>feedbackPanel.current?.scrollIntoView({block:"nearest",behavior:"smooth"}));
    try{
      const raw=JSON.stringify(payload);
      if(raw.length>(v6&&action.kind==='sketch'?180000:12000)){setError("内容过长，请减少笔画或文字后重试。");return false;}
      if(await onExecute(aid,{payload:raw})){
        const refreshed=await getObjectExperience(sessionId).catch(()=>null);
        if(refreshed)setData(refreshed);
        if(isV5 && !['puzzle','volley','huarong','timed_volley','search','book'].includes(action.kind)){
          const narrative=await postV5<{text:string;source:string}>(sessionId,'narration',{atomic_action_id:aid,idempotency_key:crypto.randomUUID()}).catch((e)=>({text:e instanceof Error&&e.message.startsWith('系统提示：')?e.message:'系统提示：描述暂时不可用，已完成的操作仍然保留。',source:'system'}));
          setFeedback(narrative?.text ?? '操作已完成并保存，可以继续浏览。');
          if(['write','sketch','snack','leave','schedule'].includes(action.kind))setSelected('');
        }
        if(v6&&action.kind==='book'){setFeedback('书放回书架了。');setSelected('');}
        return true;
      }
      else setError("这次操作未完成，请查看提示后重试。");
      return false;
    }catch{setError("操作没有完成，请重试。");return false;}
    finally{inFlight.current=false;setBusy(false);}
  }
  function select(a:ObjectOperation){setFeedback("");setSelected(a.id);setItem("");setCart({});setSeat("");setText("");setPublish(false);setStrokes([]);setError("");}
  function drawingPoint(e:React.PointerEvent<SVGSVGElement>){const r=e.currentTarget.getBoundingClientRect();return [Math.round(Math.max(0,Math.min(100,(e.clientX-r.left)/r.width*100))),Math.round(Math.max(0,Math.min(100,(e.clientY-r.top)/r.height*100)))];}
  const locked=busy||disabled||Boolean(object?.unavailable_reason);
  useEffect(()=>{
    if(!isV5||!object)return;
    const signature=`${sessionId}:${data?.day}:${object.id}:${guidance}`;
    if(exposure.current===signature)return;
    exposure.current=signature;
    void seenV5(sessionId,'object',object.id,guidance!=='direct',object.actions.map(a=>`v4_${object.id}__${a.id}`),guidance).catch(()=>{exposure.current='';});
    if(collective&&!inActivity)void seenV5(sessionId,'mechanism',object.id).catch(()=>{});
    if(object.id==='guidebook')void Promise.all([seenV5(sessionId,'guidebook','opened',true),seenV5(sessionId,'guidebook','places',true)]).then(()=>window.dispatchEvent(new Event('v5-guides-changed'))).catch(()=>{});
  },[isV5,object,collective,inActivity,sessionId,data?.day,guidance]);
  function openChapter(value:string){setChapter(value);void seenV5(sessionId,'guidebook',value,true).then(()=>window.dispatchEvent(new Event('v5-guides-changed'))).catch(()=>{});}
  // The ref guard is read only inside the click handler, never during render.
  // eslint-disable-next-line react-hooks/refs
  const confirm=(label:string,payload:Record<string,unknown>,off=false)=><button type="button" className={btn} disabled={locked||off} onClick={()=>void execute(payload)}>{label}</button>;
  const graphical=isV5&&action;
  const workshop=graphical&&['steps','craft'].includes(action.kind);
  const pickItems=action?.items.length?<div aria-label="眼前的物品" className="grid grid-cols-2 gap-3 rounded-2xl bg-[#f3eee2] p-3 sm:grid-cols-3">{action.items.map(i=><button type="button" aria-pressed={item===i.id} key={i.id} className={`focus-ring min-h-32 rounded-xl border bg-white/80 p-3 text-sm font-semibold shadow-sm transition-transform hover:-translate-y-1 disabled:opacity-40 ${item===i.id?'border-teal-700 ring-2 ring-teal-600':'border-white'}`} disabled={locked} onClick={()=>{setItem(i.id);if(isV5&&["read","wall"].includes(action.kind))void execute({item:i.id});}}><span className="block">{v6&&i.art_id?<HolidayIllustration id={i.art_id} compact staticDay={oid==='books'}/>:<ItemPicture kind={i.id}/>}</span>{i.name}{i.price!==undefined&&<span className="block text-amber-800">¥{i.price}</span>}</button>)}</div>:null;
  if(!data)return <p role="status">正在打开互动内容…{error}</p>;
  const liveGame=!!action&&["huarong","timed_volley","search","puzzle","volley"].includes(action.kind);
  const resultPanel=(!liveGame&&(busy||feedback))?<div ref={feedbackPanel} data-testid="object-feedback" role="status" aria-live="polite" aria-busy={busy} className="rounded-2xl border border-teal-300 bg-teal-50 p-5 text-stone-900 shadow-sm"><h4 className="mb-2 font-bold">{chosen?.name??'这次互动'}</h4><p className="whitespace-pre-line leading-8">{busy?'正在加载…':chosen&&feedback.startsWith(chosen.name+'\n')?feedback.slice(chosen.name.length+1):feedback}</p></div>:<div ref={feedbackPanel}/>;
  const islandMap=<div><svg viewBox="0 0 1000 700" role="img" aria-label="岛屿地图缩略图" className="w-full rounded-xl bg-cyan-50">{isV5?<image href={holidayArt('map.island',false)?.url} width="1000" height="700" preserveAspectRatio="xMidYMid meet"/>:<path d="M110 150 L250 70 L500 55 L760 100 L900 250 L870 470 L690 620 L410 650 L160 560 L75 350 Z" fill="#d4e5c4"/>}{!isV5&&data.map?.paths?.map((p,i)=><polyline key={i} points={p.points.map(q=>q.join(',')).join(' ')} fill="none" stroke="#c7ad86" strokeWidth="12"/>)}{data.map?.location_nodes?.map(n=><g key={n.location_id} role="button" tabIndex={0} aria-label={data.locations.find(l=>l.id===n.location_id)?.name} onClick={()=>setItem(n.location_id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' ')setItem(n.location_id);}} className="cursor-pointer"><defs><clipPath id={`guide-location-${n.location_id}`}><circle cx={n.x} cy={n.y} r="39"/></clipPath></defs><circle cx={n.x} cy={n.y} r="43" fill="white" stroke={item===n.location_id?"#0f766e":"#8aa49a"} strokeWidth="5"/><image data-testid={`guide-location-${n.location_id}`} href={holidayArt(`location.${n.location_id}`,false)?.url} x={n.x-39} y={n.y-39} width="78" height="78" clipPath={`url(#guide-location-${n.location_id})`} preserveAspectRatio="xMidYMid slice"/><text x={n.x} y={n.y+52} textAnchor="middle" fontSize="23" fill="#292524" stroke="white" strokeWidth="5" paintOrder="stroke">{data.locations.find(l=>l.id===n.location_id)?.name}</text></g>)}</svg>{item&&<article className="mt-3 rounded-xl bg-teal-50 p-4"><strong>{data.locations.find(l=>l.id===item)?.name}</strong><p>{data.locations.find(l=>l.id===item)?.text}</p>{!isV5&&confirm('记住这个地点',{item})}</article>}</div>;
  return <section data-testid="object-explorer" className={isV5&&!graphical&&object&&objectId&&oid!=='guidebook'?'grid items-start gap-5 md:grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)]':'space-y-4'}>
    {isV5&&object&&oid!=="guidebook"&&!graphical&&<div className="min-w-0"><HolidayIllustration id={`object.${oid}`} compact={oid==='guidebook'} staticDay={oid==='guidebook'}/></div>}
    <div className="min-w-0 space-y-4">
    {!action&&resultPanel}
    {object?.daily_note&&<p className="rounded-xl bg-teal-50 p-4 text-teal-900">{object.daily_note}</p>}
    {object?.unavailable_reason&&<p role="status" className="rounded-xl bg-amber-50 p-4">{object.unavailable_reason}</p>}
    {data.hours?.closing_in!==null&&data.hours?.closing_in!==undefined&&data.hours.closing_in<=15&&<p role="status">还有 {data.hours.closing_in} 分钟打烊。请保存作品，草稿会保留。</p>}

    {isV5&&oid==='guidebook'&&<section className="rounded-xl border bg-white p-4"><h2 className="font-bold">认识潮栖岛</h2>{data.world_version==='chaoxi-holiday-v6'&&<p className="my-3 rounded-xl bg-teal-50 p-3">每天可以从早上8点活动到晚上10点，傍晚6点后天色转暗。一天结束时会停在休息画面，等你点击后再进入下一天。各地点的营业时间见地点介绍。</p>}<div className="my-3 flex gap-2">{[['places','地点'],['residents','居民'],['play','玩法与相约']].map(([id,label])=><button key={id} className={btn} aria-pressed={chapter===id} onClick={()=>openChapter(id)}>{label}</button>)}</div>{chapter==='places'&&<div>{islandMap}</div>}{chapter==='residents'&&data.residents?.map(r=><article className="my-3" key={r.id}><h3 className="font-bold">{r.name}</h3><p>{r.detail}</p></article>)}{chapter==='play'&&<p className="leading-8">可以独处、阅读、制作，也可以和居民聊天。桌游、排球、木作和插花等地点都有多人活动，人数和地点会写在互动点上。现场询问“你愿意和我一起做吗”，或通过手机私信商量；居民可能答应、拒绝或提出其他时间。确认安排后，到手机邀约或任务查看时间，再去现场加入。{v6?'华容道是单人滑块解谜，UNO是多人卡牌游戏。':'单人拼图和多人颜色接龙是两种不同的游戏。'}任务清单只是探索建议，可以随时收起。</p>}</section>}
    {error&&<p role="alert" className="rounded-xl bg-amber-50 p-3">{error}<button className={btn} onClick={()=>void getObjectExperience(sessionId).then(setData)}>重新加载</button></p>}
    {!objectId&&<label className="block">活动中的场所与物品<select aria-label="活动中的场所与物品" className="ml-2 rounded border p-2" disabled={locked} value={oid} onChange={e=>{setOid(e.target.value);setSelected("");}}><option value="">选择一个互动点</option>{data.objects.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></label>}
    {object&&!action&&<div className="grid gap-2">{object.actions.filter(a=>!(isV5&&oid==='guidebook'&&a.kind==='map')&&!(data.separate_dining&&a.venue&&['consume','leave'].includes(a.kind))).map(a=><button type="button" data-testid={`v4-action-${a.id}`} key={a.id} className={btn} disabled={locked||(a.kind==='snack'&&data.day!==object.day)} onClick={()=>select(a)}>{a.name}</button>)}</div>}
    {action&&<div className="space-y-4 rounded-2xl border bg-white p-4" data-art-slot={`objects.${oid}.${action.id}`}>
      <div className="flex items-center justify-between gap-3"><h4 className="font-bold">{action.name}</h4><button type="button" className={btn} disabled={locked} onClick={()=>setSelected("")}>返回{object?.name}</button></div>
      {v6&&oid!=='books'&&['read','wall','book'].includes(action.kind)&&<HolidayIllustration id={`object.${oid}`} compact/>}
      {!action.postcard_status&&action.kind!=='order'&&!workshop&&!(v6&&['book','sketch'].includes(action.kind)&&chosen)&&pickItems}
      {v6&&action.kind==='book'&&chosen&&<button className={btn} onClick={()=>setItem('')}>返回书架，换一本书</button>}
      {v6&&action.kind==='sketch'&&chosen&&<p className="flex items-center justify-between"><span>当前题材：{chosen.name}</span><button className={btn} onClick={()=>setItem('')}>更换题材</button></p>}
      {v6&&chosen&&['read','wall'].includes(action.kind)&&<GalleryWork item={chosen}/>}
      {data.separate_dining&&oid==='shelf'&&chosen&&action.id==='browse'&&<SnackPurchase key={chosen.id} item={chosen} disabled={locked} onBuy={execute}/>}
      {chosen&&!workshop&&!(isV5&&['read','wall','book','sketch'].includes(action.kind))&&<article className="rounded-xl bg-stone-50 p-4"><h5 className="font-bold">{chosen.name}</h5><p className="mt-2 whitespace-pre-line leading-7">{action.kind==='book'?'选择下方页码，接着上次的位置阅读。':chosen.text}</p></article>}
      {!workshop&&resultPanel}
      {['read','wall'].includes(action.kind)&&<>{chosen&&!isV5&&confirm('看完了',{item})}{action.kind==='wall'&&!v6&&data.state.public_cards?.map((c,i)=><blockquote key={i} className="rounded-xl border p-3">10月{c.day}日 · {c.text}</blockquote>)}</>}
      {action.kind==='map'&&islandMap}
      {action.kind==='freecraft'&&<FreeWoodwork sid={sessionId} runtimeId={runtimeId} disabled={locked} progress={progress} onSave={execute}/>}
      {action.kind==='huarong'&&<Huarong storageKey={`huarong:${sessionId}:${runtimeId??"solo"}:${aid}`} disabled={locked} progress={progress} onMove={execute}/>}
      {action.kind==='timed_volley'&&<TimedVolley sid={sessionId} runtimeId={runtimeId} disabled={locked} progress={progress} onHit={execute}/>}
      {action.kind==='search'&&<BeachSearch action={action} disabled={locked} progress={progress} onFind={execute}/>}
      {data.separate_dining&&action.venue&&<DiningPanel key={aid} action={action} data={data} disabled={locked} onExecute={execute} onEnjoy={()=>{const consume=object?.actions.find(a=>a.kind==='consume');if(consume)void execute({},consume);}}/>}
      {!data.separate_dining&&action.kind==='order'&&<>
        <div className="grid gap-3 sm:grid-cols-3">{action.items.map(i=><div key={i.id} className="flex flex-col items-center justify-between gap-3 rounded-xl border bg-[#faf6ec] p-3"><div className="text-center">{i.art_id?<HolidayIllustration id={i.art_id} compact staticDay/>:<ItemPicture kind={i.id}/>}<strong>{i.name}{i.price!==undefined&&` · ¥${i.price}`}</strong><p className="text-sm text-stone-600">{i.text}</p></div><div className="flex items-center gap-2"><button aria-label={`减少${i.name}`} className={btn} disabled={locked||!cart[i.id]} onClick={()=>setCart(c=>({...c,[i.id]:Math.max(0,(c[i.id]??0)-1)}))}>−</button><span>{cart[i.id]??0}</span><button aria-label={`添加${i.name}`} className={btn} disabled={locked||(cart[i.id]??0)>=9} onClick={()=>setCart(c=>({...c,[i.id]:(c[i.id]??0)+1}))}>＋</button></div></div>)}</div>
        <section aria-label="购物车" className="rounded-xl bg-teal-50 p-4"><h5 className="font-bold">本次点单</h5>{Object.entries(cart).filter(([,n])=>n>0).map(([k,n])=><p key={k}>{action.items.find(i=>i.id===k)?.name} × {n}</p>)}{!Object.values(cart).some(n=>n>0)&&<p>还没有选择餐点或饮品。</p>}<div className="my-3 flex flex-wrap rounded-xl bg-white p-2">{Object.entries(cart).filter(([,n])=>n>0).map(([k,n])=><div key={k} className="w-20"><ItemPicture kind={k}/><p className="text-center text-xs">× {n}</p></div>)}</div><p className="mt-2 text-sm">{data.world_version==='chaoxi-holiday-v6'?`合计 ¥${Object.entries(cart).reduce((sum,[id,n])=>sum+(action.items.find(i=>i.id===id)?.price??0)*n,0)}。无需管理余额；点单后直接用餐。`:"无需支付；确认后到所选桌位入座。"}</p></section>
        <div aria-label="选择桌位" className="grid grid-cols-3 gap-2 rounded-xl bg-[#e9eee5] p-3">{data.seats[action.venue!].map(s=><button key={s.id} aria-pressed={seat===s.id} className={`${btn} ${seat===s.id?'ring-2 ring-teal-700':''}`} disabled={locked} onClick={()=>setSeat(s.id)}><HolidayIllustration id={`view.${action.venue}.${s.id}`} compact/>{s.name}</button>)}</div>
        <label className="sr-only">用餐位置<select aria-label="用餐位置" className="ml-2 rounded border p-2" value={seat} onChange={e=>setSeat(e.target.value)} disabled={locked}><option value="">选择位置</option>{data.seats[action.venue!].map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        {seat&&<details className="rounded-xl border bg-white p-3"><summary className="cursor-pointer">放大看看这个桌位的风景</summary><HolidayIllustration id={`view.${action.venue}.${seat}`}/></details>}
        {confirm('确认点单',{command:'confirm',cart:Object.fromEntries(Object.entries(cart).filter(([,n])=>n>0)),seat},action.can_order===false||!seat||!Object.values(cart).some(n=>n>0))}{action.can_order===false&&<p role="status" className="rounded-xl bg-amber-50 p-4">{action.order_unavailable_reason}</p>}
      </>}
      {!data.separate_dining&&order&&<p role="status" className="rounded-xl bg-teal-50 p-3">订单：{({preparing:'准备中，请到桌位入座',served:'已送达，可以享用',finished:'已用餐完毕',left:'已离座'} as Record<string,string>)[order.status]} · {data.seats[action.venue!]?.find(s=>s.id===order.seat)?.name}<br/>{order.selections?.join('；')}</p>}
      {!data.separate_dining&&action.kind==='seat'&&<>{!order||['finished','left'].includes(order.status)?<select aria-label="休息座位" value={seat} className="rounded border p-2" onChange={e=>setSeat(e.target.value)}><option value="">选择空座</option>{data.seats[action.venue!].map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select>:null}{confirm('在这里坐下',{seat},(!order||['finished','left'].includes(order.status))&&!seat)}</>}
      {!data.separate_dining&&v6&&action.kind==='consume'&&<HolidayIllustration id={`view.${action.venue}.${order?.seat??'window'}`}/>}
      {(action.kind==='snack'||!data.separate_dining&&action.kind==='consume')&&<div className="rounded-2xl border bg-[#f2e7ce] p-6 text-center"><p className="mb-3 text-sm text-stone-600">{action.kind==='consume'?'点击桌上的餐饮开始享用。':'点选桌上的茶点。'}</p><button className="focus-ring mx-auto block w-48 rounded-full bg-white/50 p-8 shadow-sm disabled:opacity-40" aria-label={action.name} disabled={locked||action.kind==='consume'&&order?.status!=='served'} onClick={()=>void execute({})}><ItemPicture kind={action.venue==='cafe'||action.id==='tea'?'tea':'rice'}/>{action.name}</button>{order?.status==='finished'&&<p className="mt-3 text-sm">已经享用完了，可以继续逛逛。</p>}</div>}
      {!data.separate_dining&&action.kind==='leave'&&confirm(action.name,{})}
      {action.kind==='schedule'&&<div className="rounded-xl border bg-amber-50 p-4"><p className="text-3xl font-bold">10月{data.day}日</p><p className="my-3">{data.separate_dining?'今天可以自由安排，手机里可以查看已约好的事。':data.day===1?'18:30 · 欢迎派对':data.day===7?'18:30 · 海边篝火晚会':'今天可以自由安排，手机里可以查看已约好的事。'}</p>{confirm('记下今天的安排',{})}</div>}
      {action.kind==='rest'&&v6?<div className="space-y-3"><HolidayIllustration id={oid==='bench'?'view.bench':'view.common'}/><p className="text-base leading-8">放慢脚步，看看眼前的风景。</p>{!progress.seated?confirm('坐下看看周围',{}):confirm('起身离开',{command:'leave'})}</div>:action.kind==='rest'&&<div className="overflow-hidden rounded-xl bg-[#d5e5dc]"><svg viewBox="0 0 400 170" className="w-full" aria-hidden="true"><path d="M0 80 Q150 50 400 90 V170 H0Z" fill="#aacdd1"/><path d="M0 135 H400 V170 H0Z" fill="#dfceb0"/><g transform="translate(200 113) scale(2)"><Piece kind="seat"/></g>{Boolean(progress.seated)&&<g><circle cx="200" cy="60" r="11" fill="#a38266"/><path d="M189 74 H211 L216 113 H184Z" fill="#657e70"/></g>}</svg><div className="flex justify-center gap-2 p-3">{!progress.seated?confirm('坐下看看周围',{}):confirm('起身离开',{command:'leave'})}</div></div>}
      {workshop?(oid==='rope'&&data.world_version==='chaoxi-holiday-v6'?<RopeWorkshop sid={sessionId} runtimeId={runtimeId} disabled={locked} onSave={execute}/>:<Workshop key={aid} objectId={oid} action={action} progress={progress} sessionId={sessionId} runtimeId={runtimeId} recordTrace={isV5} disabled={locked} onSubmit={execute}/>):['steps','craft'].includes(action.kind)&&<>
        <ol className="list-inside list-decimal space-y-2">{action.steps?.map((s,i)=><li key={s} className={i<Number(progress.step??0)?'text-teal-700':'text-stone-600'}>{s}{i<Number(progress.step??0)?' ✓':''}</li>)}</ol>
        {progress.step===undefined||progress.done?confirm(progress.done?'再做一次':'开始',{command:'start',item},action.kind==='craft'&&!item):confirm(action.steps?.[Number(progress.step)]??'继续',{command:'step',step:progress.step})}
        {Boolean(progress.done)&&<p role="status" className="text-teal-800">已完成，过程和作品已记录。</p>}
      </>}
      {workshop&&resultPanel}
      {action.kind==='write'&&action.postcard_status&&<PostcardWriter action={action} disabled={locked} onSave={execute}/>}
      {action.kind==='write'&&!action.postcard_status&&<><textarea aria-label="写下文字" placeholder="在这里留下你的文字……" className="min-h-44 w-full rounded-xl border border-[#d5c7a5] bg-[#fff9e9] p-5 text-lg leading-9 shadow-inner" maxLength={500} value={text} onChange={e=>setText(e.target.value)} /><blockquote className="rounded-xl bg-amber-50 p-4 whitespace-pre-wrap">{text||'文字预览'}</blockquote>{['postcards','welcome_table'].includes(oid)&&<label className="flex gap-2"><input type="checkbox" checked={publish} onChange={e=>setPublish(e.target.checked)}/>将这段文字公开留在这里</label>}{confirm('确认保存',{command:'save',text,public:publish},!text.trim())}{typeof progress.text==='string'&&<p>上次保存：{progress.text}</p>}</>}
      {action.kind==='sketch'&&(v6?(chosen?<SketchCanvas key={item} sid={sessionId} runtimeId={runtimeId} item={item} disabled={locked} progress={progress} onSave={execute}/>:<p>选择一个题材，铺开画纸。</p>):<><p className="text-sm">用鼠标或触控笔画一张小速写。至少画两笔，再保存。</p><svg aria-label="速写画纸" viewBox="0 0 100 100" className="h-64 w-full touch-none rounded-xl border bg-amber-50" onPointerDown={e=>{pen.current=true;e.currentTarget.setPointerCapture(e.pointerId);const q=drawingPoint(e);setStrokes(s=>s.length<16?[...s,[q,q]]:s);}} onPointerMove={e=>{if(!pen.current)return;const q=drawingPoint(e);setStrokes(s=>s.map((l,i)=>i===s.length-1&&l.length<10?[...l,q]:l));}} onPointerUp={()=>{pen.current=false;}} onPointerCancel={()=>{pen.current=false;}}>{strokes.map((s,i)=><polyline key={i} points={s.map(p=>p.join(',')).join(' ')} stroke="#355f59" strokeWidth="1" fill="none"/>)}</svg><button className={btn} onClick={()=>setStrokes([])}>清空画纸</button>{confirm('保存速写',{command:'save',item,strokes},!item||strokes.length<2)}</>)}
      {action.kind==='book'&&chosen&&v6?<BookReader key={chosen.id} item={chosen} initialPage={Number(progress[chosen.id]??0)} disabled={locked} onFinish={page=>execute({item,page})}/>:action.kind==='book'&&chosen&&<>{chosen.text.split('\n\n').map((_,i)=><button key={i} className={btn} disabled={locked} onClick={()=>void execute({item,page:i})}>第{i+1}页</button>)}<article className="whitespace-pre-line rounded-xl bg-amber-50 p-5 leading-8">{chosen.text.split('\n\n')[Number(progress[chosen.id]??0)]}</article></>}
      {action.kind==='puzzle'&&<>{confirm('开始一局',{command:'start'})}{Array.isArray(progress.board)&&<div aria-label="数字拼图桌面" className="grid max-w-sm grid-cols-3 gap-2 rounded-2xl border-8 border-[#c9ad81] bg-[#e7d4b3] p-3 shadow-inner">{(progress.board as number[]).map((n,i)=><button className={`${btn} aspect-square border-[#b69a70] bg-[#faf1da] text-center text-2xl shadow-sm`} key={i} disabled={locked||!n||Boolean(progress.done)} onClick={()=>void execute({command:'move',tile:n})}>{n||'　'}</button>)}</div>}{Boolean(progress.done)&&<p role="status">拼图完成！共 {Number(progress.moves)} 步。</p>}</>}
      {action.kind==='volley'&&<><p>看清目标区域，选择击球方向。每轮五次。</p>{confirm('开始练习',{command:'start'})}{progress.round!==undefined&&!progress.done&&<><p role="status">第 {Number(progress.round)+1} 球 · 目标：{['左','中','右'][Number(progress.target)]}</p><Court target={Number(progress.target)} disabled={locked} onHit={zone=>void execute({command:'hit',zone})}/></>}{progress.round!==undefined&&<p>命中：{Number(progress.score)} / {Number(progress.round)}{progress.done?' · 本轮结束':''}</p>}</>}
    </div>}
    {isV5&&!inActivity&&object&&collective&&<aside className="rounded-xl bg-teal-50 p-4"><strong>{collective.title}</strong><p className="my-2 text-sm">{collective.detail}</p><button className={btn} disabled={locked} onClick={()=>window.dispatchEvent(new CustomEvent('v5-invite-object',{detail:collective.recipe}))}>邀请别人一起</button></aside>}
    </div>
  </section>;
}
