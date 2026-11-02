import { readProtectedStudyResource } from '@/lib/study-workflow';

type ExitInfo={paragraphs:string[];research_id:string|null;exit_receipt:string;ended_at:string};
export default async function ExitInformation({revised}:{revised:boolean}) {
  if(!revised)return null;
  const info=await readProtectedStudyResource<ExitInfo>('exit-information');
  if(!info)return <p className="mt-5">结束说明暂时未能载入，请刷新或联系研究者。</p>;
  return <section className="mt-6 border-t pt-5" data-testid="exit-information">
    <p>研究编号：{info.research_id ?? '尚未报名'}</p><p className="break-all">退出凭证：{info.exit_receipt}</p>
    <p className="text-sm">请自行保存此凭证；无需提交对话、问卷或报告截图。</p>
    <details className="mt-5"><summary className="cursor-pointer font-semibold">研究结束说明、补偿和数据删除</summary>{info.paragraphs.map((text,i)=><p key={i} className="mt-4 text-sm leading-7">{text}</p>)}</details>
  </section>;
}
