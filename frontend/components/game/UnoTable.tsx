"use client";
import {useEffect,useRef,useState} from "react";
import type {ActivityExperience} from "@/lib/api";
const colors:Record<string,string>={红:"#ba5448",黄:"#b58322",绿:"#417b60",蓝:"#477aa0"};
const button="focus-ring min-h-11 rounded-xl border bg-white px-4 py-2 disabled:opacity-40";
function Card({card,disabled,onClick}:{card:string;disabled:boolean;onClick:()=>void}){
  const face=card.split("#")[0],colored=Boolean(colors[face[0]]),symbol=colored?face.slice(1):face;
  return <button className="focus-ring flex h-28 w-16 flex-col items-center justify-between rounded-xl border-4 border-white p-2 text-white shadow-md transition-transform hover:-translate-y-2 disabled:translate-y-0 disabled:opacity-45" aria-label={face} disabled={disabled} onClick={onClick}
    style={{background:colored?colors[face[0]]:"conic-gradient(#ba5448,#b58322,#417b60,#477aa0,#ba5448)"}}>
    <span className="self-start text-xs">{colored?face[0]:"万能"}</span><span className="rounded-full bg-white/90 px-2 py-3 text-xl font-bold text-stone-900">{symbol}</span><span className="self-end text-xs">{colored?face[0]:"万能"}</span>
  </button>;
}
export function UnoTable({activity,busy,onCommand}:{activity:ActivityExperience;busy:boolean;onCommand:(choice:string,partners?:number[])=>void}){
  const [color,setColor]=useState("红"),[partners,setPartners]=useState<number[]>([]);
  const game=activity.game,started=game?.mode==="uno",finished=Boolean(game?.finished);
  const easy=!started||game?.rules_version==='uno-easy-v1';
  const resumed=useRef(-1);
  useEffect(()=>{if(started&&!finished&&!busy&&!game?.your_turn&&resumed.current!==game?.turn){resumed.current=game?.turn??-1;onCommand("continue");}},[started,finished,busy,game?.your_turn,game?.turn,onCommand]);
  return <section className="space-y-4 rounded-2xl border border-amber-300 bg-[#f5efdf] p-4" aria-label="UNO桌游">
    <h2 className="text-xl font-bold">UNO · {easy?"轻松规则":"原局规则"}</h2>
    <details className="rounded-xl bg-white/80 p-3"><summary className="cursor-pointer font-semibold">查看本桌规则</summary><p className="mt-3 text-sm leading-7">{easy?"每人5张，只需同色或同数字出牌，也可以使用变色牌。摸一张后自动出牌或轮到下家，没有罚牌，也不用手动喊UNO。先出完牌就结束这一局。":"每人7张，数字牌开局。颜色、数字或符号相同即可出牌，也可以摸一张；摸牌后只可出刚摸到的牌。跳过、反转、+2和万能变色牌生效。+4仅允许没有同色牌时使用，由游戏自动检查，不需争议判定；罚牌不能叠加。两人局反转等同跳过。出倒数第二张前点击UNO，忘记会被同桌提醒并补摸两张。先出完牌者赢下这一局，不累计积分。"}</p></details>
    {(!started||finished)&&<>
      {activity.kind==="welcome"&&<fieldset className="flex flex-wrap gap-3"><legend className="mb-2">选择一至三位到场的伙伴</legend>{activity.people.map(p=><label key={p.id}><input type="checkbox" checked={partners.includes(p.id)} disabled={busy||!partners.includes(p.id)&&partners.length>=3} onChange={e=>setPartners(v=>e.target.checked?[...v,p.id]:v.filter(i=>i!==p.id))}/>{p.name}</label>)}</fieldset>}
      {finished&&<p role="status">{game?.winner??"同桌"}先出完了牌。</p>}
      <button className={button} disabled={busy} onClick={()=>onCommand("start",activity.kind==="welcome"?(partners.length?partners:activity.people.slice(0,1).map(p=>p.id)):undefined)}>{finished?"再玩一局":"开一局UNO"}</button>
    </>}
    {started&&!finished&&<>
      <div className="flex flex-wrap justify-center gap-3">{game?.others?.map(p=><div key={p.name} className="rounded-xl bg-white px-4 py-3"><strong>{p.name}</strong><p>▧ {p.count} 张{p.count===1?" · UNO!":""}</p></div>)}</div>
      <div className="flex items-center justify-center gap-5 rounded-3xl border-8 border-[#b08c5c] bg-[#527963] p-6 text-white"><div><p>{game?.direction===1?"顺时针 ↻":"逆时针 ↺"}</p><p className="mt-2">当前颜色：{game?.color}</p></div><Card card={game!.top} disabled onClick={()=>{}}/><p>轮到{game?.current_name}</p></div>
      <label className="block">万能牌换成<select aria-label="UNO换色" className="ml-3 rounded-xl border p-3" value={color} onChange={e=>setColor(e.target.value)}>{Object.keys(colors).map(c=><option key={c} value={c}>{c}色</option>)}</select></label>
      <div className="flex flex-wrap gap-3 p-2" aria-label="你的UNO手牌">{game!.hand.map(c=><Card key={c} card={c} disabled={busy||!game?.your_turn||!game?.playable?.includes(c)} onClick={()=>onCommand(`play:${c}|${color}`)}/>)}</div>
      <div className="flex flex-wrap gap-3">{game?.your_turn?<><button className={button} disabled={busy||Boolean(game.drawn)} onClick={()=>onCommand("draw")}>摸一张</button>{game.drawn&&<button className={button} disabled={busy} onClick={()=>onCommand("pass")}>保留刚摸到的牌</button>}{!easy&&<button className={`${button} bg-amber-100 font-bold`} disabled={busy||game.hand.length!==2||game.uno_declared} onClick={()=>onCommand("uno")}>{game.uno_declared?"已喊 UNO!":"喊 UNO!"}</button>}</>:<span role="status">同桌正在出牌…</span>}</div>
    </>}
  </section>;
}
