import {requestJson} from './api';
export type Proposal={source_action_id:number;agent_id:number;reply:string;decision:string;recipe_id:string;reason:string;start_day:number;start_minute:number;channel:string};
export type V5Snapshot={version:string;next_local?:boolean;closed?:boolean;profile:{gender:'male'|'female';portrait_url:string}|null;proposals:Proposal[];notifications:{id:string;text:string}[];residents:{id:number;name:string}[];messages:{id:number;agent_id:number;message:string;reply:string;day:number;minute:number;generation_mode:string}[]};
export const getV5=(sid:number)=>requestJson<V5Snapshot>(`/sessions/${sid}/world/v5`);
export const postV5=<T=Record<string,unknown>>(sid:number,path:string,data:Record<string,unknown>)=>requestJson<T>(`/sessions/${sid}/world/v5/${path}`,{method:'POST',body:JSON.stringify(data)});
export type GuidanceSource='unknown'|'direct'|'guidebook'|'activity_default'|'npc_suggestion';
export function seenV5(sid:number,kind:string,target:string,guided=false,displayed_action_ids:string[]=[],guidance_source:GuidanceSource=guided?'guidebook':'direct'){return postV5(sid,'opportunities',{kind,target,guided,eligible:true,displayed_action_ids,guidance_source,idempotency_key:crypto.randomUUID()});}
export const GROUP_PLAY:Record<string,{title:string;detail:string;recipe:string}>={
  bench:{title:'一起观海 · 2–4人',detail:'可以独自坐一会儿，也可以约邻居一起看海。',recipe:'seaside'},
  beach:{title:'一起散步 · 2–4人',detail:'独自散步或写字，也可以邀人沿沙滩走走。',recipe:'beach_walk'},
  sketch:{title:'一起速写 · 2–4人',detail:'每个人画自己的作品，可以一起观察和交流。',recipe:'harbor_sketch'},
  rope:{title:'一起练习 · 2–4人',detail:'可以自己照示范试，也可以请邻居一起练习。',recipe:'rope_practice'},
  flowers:{title:'合作插花 · 2–4人',detail:'单人制作之外，可以一起商量配色与摆放。',recipe:'flower_arranging'},
  wood_work:{title:'一起做木作 · 2–4人',detail:'可以独自拼装，也可以现场问问邻居愿不愿意一起做。',recipe:'woodcraft'},
  plants:{title:'一起看花草 · 2–4人',detail:'邀请邻居一起浏览和交流。',recipe:'browse_plants'},
  shelf:{title:'一起逛店 · 2–4人',detail:'邀请邻居一起看看货架。',recipe:'shop_visit'},
  photos:{title:'一起看摄影 · 2–4人',detail:'照片可以独自欣赏，也可以一起聊聊。',recipe:'photo_visit'},
  restaurant_menu:{title:'一起用餐 · 2–4人',detail:'每位到场者都能选择自己的餐点。',recipe:'meal'},
  games:{title:'颜色接龙 · 2–4人',detail:'独自可玩数字拼图；颜色接龙需要你和1–3位居民。人数包含你。',recipe:'table_game'},
  volleyball:{title:'传接球2–4人／小场对打4人',detail:'自己可以垫球和发球练习；多人玩法需先约齐人数。',recipe:'volley_pass'},
  common_room:{title:'活动室小聚 · 2–4人',detail:'约邻居聊聊，或参与已开始的活动。',recipe:'common_chat'},
  cafe_menu:{title:'一起喝咖啡 · 2–4人',detail:'每个人可以点不同的饮品。',recipe:'coffee'},
  books:{title:'一起读书 · 2–4人',detail:'各自阅读，也可以分享读到的片段。',recipe:'reading'},
  postcards:{title:'一起写明信片 · 2–4人',detail:'每人写自己的卡片，是否公开由本人决定。',recipe:'postcard'},
};
