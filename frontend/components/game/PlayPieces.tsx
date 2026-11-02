"use client";


export function Piece({kind, colour = '#fffdf4'}:{kind:string;colour?:string}) {
  if(['sunflower','rose','tulip','hydrangea','lily'].includes(kind))return <g>
    <path d="M0 0Q-4 20 0 37" stroke="#62805a" strokeWidth="2" fill="none"/><ellipse cx="5" cy="23" rx="7" ry="3" transform="rotate(-30 5 23)" fill="#829b72"/>
    {kind==='tulip'?<path d="M-13 -17L-5 -9L0 -20L5 -9L13 -17Q15 9 0 10Q-15 9 -13 -17Z" fill="#f4dfac" stroke="#c6b475"/>:kind==='rose'?<>{[17,12,7].map((r,i)=><circle key={r} cx={i%2?2:0} r={r} fill={['#e6a5b9','#cd7c97','#ae607b'][i]}/>)}<path d="M-3 0Q7 -6 5 3Q0 7 -3 0" fill="#efb7c7"/></>:kind==='hydrangea'?<>{Array.from({length:9},(_,i)=><g key={i} transform={`translate(${Math.cos(i*2.4)*Math.sqrt(i)*6} ${Math.sin(i*2.4)*Math.sqrt(i)*6})`}>{[0,90,180,270].map(a=><ellipse key={a} cy="-3" rx="3" ry="5" transform={`rotate(${a})`} fill={i%2?'#91b5de':'#779dcf'}/>)}<circle r="1" fill="#e4e5ca"/></g>)}</>:<>{Array.from({length:kind==='lily'?6:14},(_,i)=><ellipse key={i} cy="-9" rx={kind==='lily'?5:3} ry="11" transform={`rotate(${i*360/(kind==='lily'?6:14)})`} fill={kind==='lily'?'#fffdf1':'#efc547'} stroke="#c9b67c" strokeWidth=".5"/>)}<circle r={kind==='lily'?3:8} fill={kind==='lily'?'#bdad63':'#725337'}/></>}
  </g>;
  if(['plank','square','circle','triangle'].includes(kind))return <g fill="#c89e65" stroke="#8e683d" strokeWidth="1.4">
    {kind==='plank'?<rect x="-28" y="-7" width="56" height="14" rx="3"/>:kind==='square'?<rect x="-17" y="-17" width="34" height="34" rx="2"/>:kind==='circle'?<circle r="18"/>:<path d="M0 -22L22 17H-22Z"/>}
    <path d="M-10 -3Q0 -7 10 -3M-10 5Q0 1 10 5" fill="none" stroke="#a57a45" strokeWidth=".8"/>
  </g>;
  if (['daisy','warm','leaf','fern','mint','rosemary','dandelion','jasmine','lavender','cosmos'].includes(kind)) return <g>
    <path d="M0 0 Q-4 20 0 37" stroke="#62805a" strokeWidth="2" fill="none"/>
    <ellipse cx="5" cy="23" rx="7" ry="3" transform="rotate(-30 5 23)" fill="#829b72"/>
    {['leaf','fern','mint','rosemary'].includes(kind) ? <>{[0,9,18].map(y=><g key={y}><ellipse cx="-5" cy={y} rx="7" ry={kind==='rosemary'?1.5:4} transform={`rotate(35 -5 ${y})`} fill={kind==='mint'?'#609249':'#8ba797'}/><ellipse cx="5" cy={y-4} rx="7" ry={kind==='rosemary'?1.5:4} transform={`rotate(-35 5 ${y-4})`} fill={kind==='mint'?'#78a456':'#769c88'}/></g>)}</> : kind==='lavender'?<>{[-17,-10,-3,4,11].map((y,i)=><g key={y}><ellipse cx={-3+i*.4} cy={y} rx="4" ry="5" fill="#9975af"/><ellipse cx="3" cy={y+3} rx="4" ry="5" fill="#79528f"/></g>)}</>:<>{Array.from({length:kind==='jasmine'?5:kind==='dandelion'?24:8},(_,i)=><ellipse key={i} cy="-8" rx={kind==='dandelion'?1.4:4} ry="8" transform={`rotate(${i*(kind==='jasmine'?72:kind==='dandelion'?15:45)})`} fill={kind==='warm'?'#e9a071':kind==='dandelion'?'#ebbd32':kind==='cosmos'?'#df90b1':colour} stroke="#d4c9ad" strokeWidth=".5"/>)}<circle r={kind==='jasmine'?2:4} fill="#d1a649"/></>}
  </g>;
  if(kind==='hull'||kind==='boat')return <g><path d="M-24 -5 L24 -5 L15 10 L-15 10 Z" fill="#c39c6c" stroke="#896b45"/><path d="M-17 1 H17 M-10 6 H10" stroke="#a47d51"/>{kind==='boat'&&<><path d="M0 -5 V-32" stroke="#896b45" strokeWidth="2"/><path d="M2 -30 L20 -9 H2Z" fill="#f6e9c9"/></>}</g>;
  if(kind==='mast')return <rect x="-2" y="-21" width="4" height="42" rx="1" fill="#b78c54"/>;
  if(kind==='sail')return <path d="M-10 -17 L13 15 H-10Z" fill="#ecdab4" stroke="#a78254"/>;
  if(kind.startsWith('slat')||kind==='coaster')return <g><rect x="-23" y="-5" width="46" height="10" rx="3" fill="#cba97b" stroke="#9b774f"/><path d="M-18 -1 Q0 -3 19 0 M-16 2 H13" stroke="#b08b5d"/></g>;
  if(kind==='biscuit')return <g><rect x="-25" y="-30" width="50" height="60" rx="6" fill="#e7bd73" stroke="#9a763e"/><path d="M-25 -20H25M-25 22H25" stroke="#c5a16c"/><circle r="17" fill="#f7df9d" stroke="#b99457"/>{[-7,0,7].map(x=><circle key={x} cx={x} cy={x===0?7:-4} r="2" fill="#af7f43"/>)}</g>;
  if(kind==='juice')return <g><path d="M-10 -28H10V-18L17 -9V27H-17V-9L-10 -18Z" fill="#efb64f" stroke="#bd8739"/><rect x="-10" y="-32" width="20" height="7" rx="2" fill="#7b9a5d"/><rect x="-17" y="-2" width="34" height="20" fill="#fff5dd"/><circle cy="8" r="8" fill="#eb9942" stroke="#fff"/></g>;
  if(kind==='nuts')return <g><path d="M-23 -28H23L27 28H-27Z" fill="#9b6d48" stroke="#785238"/><rect x="-22" y="-10" width="44" height="30" rx="5" fill="#f6e5bc"/>{[-12,0,12].map((x,i)=><ellipse key={x} cx={x} cy={i%2?10:2} rx="6" ry="9" transform={`rotate(${i*20-20} ${x} 2)`} fill={i===1?'#c48f56':'#99703e'}/>)}</g>;
  if(kind==='pencil')return <g transform="rotate(32)"><rect x="-5" y="-30" width="10" height="52" fill="#d4ad55" stroke="#957542"/><path d="M-5 22L0 35L5 22Z" fill="#d9bb8d"/><path d="M-2 30L0 35L2 30Z" fill="#3e4945"/><rect x="-5" y="-34" width="10" height="8" fill="#c28075"/></g>;
  if(kind==='sketchbook')return <g><rect x="-24" y="-29" width="48" height="58" rx="3" fill="#77958a" stroke="#526d61"/><rect x="-16" y="-17" width="32" height="26" fill="#f7f0da"/><path d="M-10 4L-1 -8L9 4" stroke="#8ca18b" fill="none"/>{[-20,-10,0,10,20].map(y=><path key={y} d={`M-28 ${y}H-19`} stroke="#ad956e" strokeWidth="3"/>)}</g>;
  if(kind==='tissue')return <g><rect x="-27" y="-12" width="54" height="37" rx="5" fill="#a8c7cb" stroke="#6d9b9f"/><ellipse cy="-11" rx="16" ry="5" fill="#659599"/><path d="M-12 -12L-15 -33Q-2 -24 10 -32L14 -12Z" fill="#fffcf3" stroke="#dce0d5"/><path d="M-20 15Q0 -1 20 15" fill="none" stroke="#d4e5dd" strokeWidth="3"/></g>;
  if(['coffee','tea','cocoa'].includes(kind))return <g><path d="M14 -8 Q31 -10 24 6 Q20 10 13 7" fill="none" stroke="#a58766" strokeWidth="3"/><path d="M-16 -14 H16 L12 17 Q0 23 -12 17Z" fill="#fffaf0" stroke="#bba98c"/><ellipse cy="-14" rx="16" ry="5" fill={kind==='tea'?'#c48e43':'#896348'}/><path d="M-5 -24 Q-10 -29 -4 -34 M5 -24 Q0 -29 6 -34" fill="none" stroke="#b9b1a3" strokeWidth="1.5"/></g>;
  if(['rice','noodles','soup','food','snack'].includes(kind))return <g><ellipse cy="10" rx="28" ry="12" fill="#e5d9bc"/><ellipse rx="24" ry="13" fill="#fffaf0" stroke="#c3b69c"/><ellipse cy="-1" rx="20" ry="9" fill={kind==='soup'?'#d5b779':'#e5d9ab'}/>{[-12,0,12].map(x=><g key={x}><ellipse cx={x} cy="-3" rx="5" ry="3" fill="#849b63"/><circle cx={x+3} cy="1" r="3" fill="#c87958"/></g>)}</g>;
  if(['clam','spiral'].includes(kind))return <g><path d="M-18 -3 Q-20 -25 0 -22 Q25 -24 18 -3 L5 15 H-5Z" fill="#e6c8af" stroke="#bd9780"/>{[-12,-6,0,6,12].map(x=><path key={x} d={`M0 12 Q${x} 0 ${x} -16`} stroke="#bc9479" fill="none"/>)}</g>;
  if(['shore','window','book','stationery'].includes(kind))return <g><path d="M-23 -21 Q-12 -25 0 -18 Q12 -25 23 -21 V17 Q10 13 0 20 Q-12 13 -23 17Z" fill="#fff7df" stroke="#b6a180"/><path d="M0 -18 V20 M-18 -10 H-5 M5 -10 H18 M-18 -3 H-5 M5 -3 H18 M-18 4 H-5 M5 4 H18" stroke="#b4aa92"/></g>;
  if(['harbor','street','morning','sea','square','house'].includes(kind))return <g><rect x="-28" y="-21" width="56" height="42" rx="1" fill="#fff" stroke="#b5a58b"/><path d="M-23 -16 H23 V15 H-23Z" fill="#b7d8db"/><circle cx="12" cy="-8" r="5" fill="#f6dfa5"/><path d="M-23 8 L-8 -9 L3 6 L12 0 L23 11 V15 H-23Z" fill="#91a688"/><path d="M-23 10 Q0 4 23 12 V15 H-23Z" fill="#76abb7"/></g>;
  if(kind==='seat')return <g><rect x="-20" y="-18" width="40" height="20" rx="5" fill="#cbac7e"/><path d="M-24 2 H24 V9 H-24Z M-18 9 V23 M18 9 V23" stroke="#9c7c55" strokeWidth="4" fill="#d6b993"/></g>;
  if(kind==='colour')return <g>{['#70999a','#e0ae75','#c27e68'].map((c,i)=><g key={c} transform={`translate(${i*9-9} 0) rotate(${i*12-12})`}><rect x="-14" y="-22" width="28" height="44" rx="4" fill={c} stroke="white" strokeWidth="2"/><text textAnchor="middle" y="6" fill="white" fontSize="20">{i+1}</text></g>)}</g>;
  if(kind==='puzzle')return <g>{[1,2,3,4,5,6,7,8].map((n,i)=><g key={n} transform={`translate(${i%3*16-16} ${Math.floor(i/3)*16-16})`}><rect x="-7" y="-7" width="14" height="14" rx="2" fill="#ceb28a"/><text y="4" textAnchor="middle" fontSize="9" fill="#624c32">{n}</text></g>)}</g>;
  if(kind==='court')return <g><circle r="24" fill="#f7edce" stroke="#b79965"/><path d="M-20 -13 Q5 -10 18 15 M-7 -23 Q-18 4 -5 23 M23 -4 Q0 -7 -18 15" stroke="#b79965" fill="none"/></g>;
  if(kind==='reef')return <g><path d="M-28 14 Q23 -24 10 -14 Q-12 14 -24 -15 Q0 -35 26 14 M-26 -14 Q0 20 26 -14" fill="none" stroke="#b99467" strokeWidth="5" strokeLinecap="round"/></g>;
  return <g><rect x="-23" y="-19" width="46" height="38" rx="5" fill="#ebddbe" stroke="#b49c75"/><path d="M-14 -7 H14 M-14 0 H8 M-14 7 H11" stroke="#a08867" strokeWidth="2"/></g>;
}

export function ItemPicture({kind}:{kind:string}) {return <svg viewBox="-42 -42 84 84" aria-hidden="true" className="h-20 w-full overflow-visible"><Piece kind={kind}/></svg>;}

export function Court({target,disabled,onHit}:{target:number;disabled:boolean;onHit:(zone:number)=>void}){
  return <div className="rounded-2xl border border-stone-300 bg-[#eee3ca] p-3"><p className="mb-2 text-sm text-stone-600">点击球场落点回球，金色圆圈是本球目标。</p><svg viewBox="0 0 360 210" role="group" aria-label="排球场" className="w-full">
    <path d="M15 15 H345 V195 H15Z M15 105 H345" fill="#a9b4a0" stroke="white" strokeWidth="3"/>
    {[0,1,2].map(i=><g key={i} role="button" aria-label={['左','中','右'][i]} aria-disabled={disabled} tabIndex={disabled?-1:0} className="cursor-pointer outline-none focus:opacity-70" onClick={()=>{if(!disabled)onHit(i);}} onKeyDown={e=>{if(!disabled&&(e.key==='Enter'||e.key===' ')){e.preventDefault();onHit(i);}}}>
      <rect x={18+i*108} y="18" width="106" height="174" fill="transparent" stroke="white" strokeDasharray="4 5"/>
      <circle cx={72+i*108} cy="63" r="23" fill={target===i?'#f3cb72':'#d8dccf'} stroke={target===i?'#996c2e':'white'} strokeWidth="2"/>
      <text x={72+i*108} y="69" textAnchor="middle" fontSize="15" fill="#4f563f">{['左','中','右'][i]}</text>
    </g>)}<g transform="translate(180 160) scale(.7)"><Piece kind="court"/></g>
  </svg></div>;
}

export function PlayingCard({card,disabled,onPlay}:{card:string;disabled:boolean;onPlay:()=>void}){return <button disabled={disabled} aria-label={card} onClick={onPlay} className="focus-ring h-24 w-16 rounded-xl border-4 border-white text-2xl font-bold text-white shadow-md transition-transform hover:-translate-y-2 disabled:translate-y-0 disabled:opacity-35" style={{background:card[0]==='红'?'#b87560':card[0]==='蓝'?'#6894a5':'#7c9371'}}>{card[1]}<span className="block text-xs">{card[0]}</span></button>;}
