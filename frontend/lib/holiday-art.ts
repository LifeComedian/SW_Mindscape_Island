import assets from './holiday-art-assets.json';
import v6assets from './holiday-art-v6-assets.json';
import nextAssets from './holiday-art-next-assets.json';
import {resolveApiAssetUrl, type ActivityExperience} from './api';

export function holidayArt(id: string,night=false) {
  const all={...assets,...v6assets,...nextAssets} as Record<string,{url:string;width:number;height:number;title:string}>;
  // Printed postcard art never changes with the light in the room.
  const printed=id.startsWith('postcard.')||id.startsWith('next.card.');
  const asset=all[night&&!printed&&all[id+'.night']?id+'.night':id];
  return asset ? {...asset,url:resolveApiAssetUrl(asset.url)} : undefined;
}

export function activityArt(activity: ActivityExperience) {
  if(!['chaoxi-holiday-v5','chaoxi-holiday-v6'].includes(activity.world_version??''))return undefined;
  if(['welcome','bonfire'].includes(activity.kind)) {
    const last=activity.history.at(-1);
    const phase=last?.kind==='speech' ? 'speech' : activity.speech_done ? 'chat' : 'wide';
    return `activity.${activity.kind}-${activity.kind==='bonfire'&&phase==='speech'?'wide':phase}`;
  }
  const targets:Record<string,string>={seaside:'bench',beach_walk:'beach',beach_search:'beach',harbor_sketch:'sketch',rope_practice:'rope',flower_arranging:'flowers',woodcraft:'wood_work',browse_plants:'plants',shop_visit:'shelf',photo_visit:'photos',meal:'restaurant_menu',table_game:'games',volley_pass:'volleyball',volley_match:'volleyball',common_chat:'common_room',coffee:'cafe_menu',reading:'books',postcard:'postcards'};
  const object=targets[activity.kind]??activity.catalogue.find(c=>c.object_id)?.object_id;
  return object ? `object.${object}` : undefined;
}
