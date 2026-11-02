import {postV5} from './holiday-v5';

export type TraceEvent={seq:number;operation:'add'|'move'|'remove'|'clear'|'style'|'polish'|'visit'|'restart'|'submit'|'rotate'|'copy'|'layer'|'undo';method:'pointer'|'keyboard'|'button';piece_index?:number;material?:string;x?:number;y?:number;choice?:string};
type Batch={idempotency_key:string;draft_id:string;object_id:string;action_id:string;runtime_id:number|null;events:TraceEvent[];dropped_count:number};
type Journal={draft_id:string;next:number;events:TraceEvent[];dropped_count:number;batch?:Batch};
const flights=new Map<string,Promise<boolean>>();

// Store low-frequency semantic operations, never pointermove streams or text.
// Read storage at every mutation so an old mounted component cannot erase new events.
export function workshopTrace(sid:number,oid:string,aid:string,runtimeId:number|null){
  const key=`workshop-trace:${sid}:${runtimeId??'solo'}:${aid}`;
  let fallback:Journal={draft_id:crypto.randomUUID(),next:1,events:[],dropped_count:0};
  function read():Journal{try{const j=JSON.parse(sessionStorage.getItem(key)??'null');return j&&typeof j.draft_id==='string'&&Number.isInteger(j.next)&&Array.isArray(j.events)&&Number.isInteger(j.dropped_count)?j:fallback;}catch{return fallback;}}
  function write(j:Journal){fallback=j;try{sessionStorage.setItem(key,JSON.stringify(j));}catch{/* Still bounded in memory; not proof of a complete trace. */}}
  function record(event:Omit<TraceEvent,'seq'>){
    const j=read();j.events.push({...event,seq:j.next++});
    if(j.events.length>200){j.events.shift();j.dropped_count++;}
    write(j);
  }
  function flush():Promise<boolean>{
    const existing=flights.get(key);if(existing)return existing;
    const work=(async()=>{
      for(let n=0;n<8;n++){
        const j=read();
        if(!j.batch&&!j.events.length)return true;
        j.batch??={idempotency_key:crypto.randomUUID(),draft_id:j.draft_id,object_id:oid,action_id:aid,runtime_id:runtimeId,events:j.events.slice(0,32),dropped_count:j.dropped_count};
        write(j);
        const sent=j.batch;
        try{await postV5(sid,'workshop-traces',sent);}catch{return false;}
        const latest=read();
        if(latest.batch?.idempotency_key===sent.idempotency_key){
          const last=sent.events.at(-1)!.seq;
          latest.events=latest.events.filter(e=>e.seq>last);delete latest.batch;write(latest);
        }
      }
      return false;
    })();
    flights.set(key,work);void work.finally(()=>flights.delete(key));return work;
  }
  return {record,flush,draftId:()=>read().draft_id};
}
