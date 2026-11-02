"""Image anchors in uncropped coordinates: map 1000x700, scenes 800x450."""
import json
from functools import lru_cache
from pathlib import Path

MAP_ANCHORS = {'guest_room':(155,91),'loc_02':(284,188),'loc_03':(238,323),
               'loc_04':(710,311),'loc_05':(497,232),'loc_06':(496,435),
               'loc_01':(727,173),'residential':(794,474)}
OBJECT_ANCHORS = {
    'rope':(195,217), 'sketch':(404,239), 'bench':(644,322), 'beach':(700,217),
    'bonfire_table':(715,275),
    'plants':(95,245), 'flowers':(493,191), 'wood_display':(738,159), 'wood_work':(711,276),
    'shelf':(480,229), 'photos':(608,111),
    'restaurant_menu':(280,103), 'restaurant_table':(366,211),
    'games':(315,184), 'volleyball':(492,174), 'common_room':(691,188), 'welcome_table':(641,184),
    'cafe_menu':(705,119), 'books':(500,173), 'postcards':(577,151), 'cafe_table':(385,227),
    'guidebook':(729,270),
}
# Place resident portraits in clear floor areas.
FLOOR_ANCHORS = {
    'loc_01':[(200,340),(270,354),(340,374),(410,365),(480,389),(540,410),(160,390),(340,430)],
    'loc_02':[(270,301),(332,321),(403,323),(469,338),(530,360),(257,386),(390,396),(497,417)],
    'loc_03':[(242,314),(315,330),(380,350),(450,371),(510,400),(216,404),(316,416),(422,427)],
    'loc_04':[(470,288),(524,312),(569,340),(603,386),(526,407),(455,377),(414,310),(625,303)],
    'loc_05':[(245,290),(310,310),(377,295),(441,322),(510,304),(570,331),(335,382),(472,394)],
    'loc_06':[(276,305),(340,319),(409,333),(472,351),(535,365),(267,390),(383,405),(512,420)],
    'guest_room':[(245,355),(300,370),(354,399),(207,411),(284,425),(140,373),(123,309),(192,291)],
    'residential':[(433,299),(477,329),(400,340),(441,376),(486,408),(390,420),(539,353),(566,405)],
}

def apply_layout(world_map):
    for node in world_map['location_nodes']:
        node['x'],node['y']=MAP_ANCHORS[node['location_id']]
        node['click_radius']=22
        node['label_offset']=[0,41]
    for path in world_map['paths']:
        path['points']=[list(MAP_ANCHORS[path['from_location_id']]),list(MAP_ANCHORS[path['to_location_id']])]
    for scene in world_map['scene_layouts']:
        scene['interaction_point_positions']={oid:list(OBJECT_ANCHORS[oid]) for oid in scene['interaction_point_positions']}
        scene['resident_slots']=[list(p) for p in FLOOR_ANCHORS[scene['location_id']]]
        from content.experience_next import enabled
        if enabled():
            # Give visitors distinct positions from permanent residents.
            scene['resident_slots'] += [[610,425],[680,405],[735,430]]
        scene['participant_spawn']=[78,414] if scene['location_id']!='residential' else [336,416]

@lru_cache(maxsize=1)
def art_assets():
    path=Path(__file__).resolve().parents[1]/'assets/holiday-v5/manifest.json'
    return json.loads(path.read_text(encoding='utf-8'))['assets'] if path.is_file() else {}

def apply_visuals(slots,world=None):
    assets=art_assets()
    if world and world.world_version=='chaoxi-holiday-v6':
        path=Path(__file__).resolve().parents[1]/'assets/holiday-v6/manifest.json'
        additional=json.loads(path.read_text(encoding='utf-8'))['assets'] if path.is_file() else {}
        assets={**assets,**additional}
    from content.experience_next import enabled
    if enabled():
        path=Path(__file__).resolve().parents[1]/'assets/holiday-next/manifest.json'
        if path.is_file():assets={**assets,**json.loads(path.read_text(encoding='utf-8'))['assets']}
    for slot_id,slot in slots.items():
        if slot_id=='map.image':key='map.island'
        elif slot_id.startswith('locations.'):key='location.'+slot['target_id']
        elif slot['target_id'].startswith('resident:'):key='resident.'+slot['target_id'].split(':')[1]+'.closeup'
        else:continue
        if world and world.world_version=='chaoxi-holiday-v6' and world.current_time_minutes>=1080 and key+'.night' in assets:
            key+='.night'
        if key in assets:
            slot['asset_key']=key
            slot['asset']={k:assets[key][k] for k in ('asset_key','url','mime_type','width','height','sha256','source','license')}
