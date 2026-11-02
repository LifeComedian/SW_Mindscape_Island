"""Three-day island content for the v0.4 world."""

from __future__ import annotations

from typing import Any

from world.graph import validate_location_graph
from world.schedules import validate_resident_schedules
from world.specs import (
    CalendarSpec,
    LocationSpec,
    ResidentSpec,
    ScheduleBlock,
    WorldSpec,
)


WORLD_VERSION = "island-v0.4"
SCENARIO_PACK_VERSION = "island-neutral-v0.4"
DAY_START = 9 * 60
DAY_END = 20 * 60


def text(en: str, zh_cn: str) -> dict[str, str]:
    return {"en": en, "zh-CN": zh_cn}


def location(
    location_id: str,
    *,
    name_en: str,
    name_zh_cn: str,
    description_en: str,
    description_zh_cn: str,
    scene_type: str,
    connected_location_ids: tuple[str, ...],
    interaction_points: tuple[dict[str, Any], ...],
) -> LocationSpec:
    return LocationSpec(
        location_id=location_id,
        name=text(name_en, name_zh_cn),
        description=text(description_en, description_zh_cn),
        scene_type=scene_type,
        connected_location_ids=connected_location_ids,
        interaction_points=interaction_points,
        version=WORLD_VERSION,
    )


def block(
    state_id: str,
    start_minute: int,
    end_minute: int,
    location_id: str,
    activity_en: str,
    activity_zh_cn: str,
    goal_en: str,
    goal_zh_cn: str,
    *,
    days: frozenset[int] | None = None,
) -> ScheduleBlock:
    return ScheduleBlock(
        state_id=state_id,
        start_minute=start_minute,
        end_minute=end_minute,
        location_id=location_id,
        activity=text(activity_en, activity_zh_cn),
        goal=text(goal_en, goal_zh_cn),
        days=days,
    )


def resident(
    agent_id: int,
    name: str,
    role_en: str,
    role_zh_cn: str,
    background_en: str,
    background_zh_cn: str,
    schedule: tuple[ScheduleBlock, ...],
) -> ResidentSpec:
    return ResidentSpec(
        agent_id=agent_id,
        name=name,
        role=text(role_en, role_zh_cn),
        background=text(background_en, background_zh_cn),
        schedule=schedule,
    )


LOCATIONS = {
    "participant_home": location(
        "participant_home",
        name_en="Guest Cottage",
        name_zh_cn="访客小屋",
        description_en=(
            "A small cottage set aside for visiting islanders, with a desk, "
            "a kettle, and a path to the residential lane."
        ),
        description_zh_cn="为来访岛民准备的小屋，有书桌、热水壶和通往住宅巷的小路。",
        scene_type="home",
        connected_location_ids=("residential_lane",),
        interaction_points=(
            {"object_id": "cottage_desk", "type": "writing_spot"},
            {"object_id": "day_planner", "type": "schedule_note"},
        ),
    ),
    "residential_lane": location(
        "residential_lane",
        name_en="Residential Lane",
        name_zh_cn="住宅巷",
        description_en=(
            "A quiet lane of small homes and shared planters where residents "
            "start and end ordinary days."
        ),
        description_zh_cn="一条安静的小巷，两侧是小屋和共享花箱，居民在这里开始和结束日常。",
        scene_type="residential",
        connected_location_ids=("participant_home", "square", "beach_lighthouse"),
        interaction_points=(
            {"object_id": "shared_planters", "type": "garden"},
            {"object_id": "courtyard_table", "type": "rest_spot"},
        ),
    ),
    "square": location(
        "square",
        name_en="Community Square",
        name_zh_cn="社区广场",
        description_en=(
            "The island's central meeting place, with paths to the harbor, "
            "restaurant, shop, homes, and lighthouse trail."
        ),
        description_zh_cn="岛上的中心会面地点，通往渡口、餐厅、商店、住处和灯塔小径。",
        scene_type="community",
        connected_location_ids=("harbor", "restaurant", "shop", "residential_lane"),
        interaction_points=(
            {"object_id": "community_board", "type": "notice_board"},
            {"object_id": "book_shelf", "type": "shared_library"},
            {"object_id": "square_bench", "type": "seat"},
        ),
    ),
    "harbor": location(
        "harbor",
        name_en="Ferry Harbor",
        name_zh_cn="渡口",
        description_en=(
            "A modest ferry landing with a tide chart, railings, and a broad "
            "view back toward the square."
        ),
        description_zh_cn="朴素的渡船停靠点，有潮汐表、栏杆，也能望见通往广场的路。",
        scene_type="arrival",
        connected_location_ids=("square",),
        interaction_points=(
            {"object_id": "tide_chart", "type": "notice"},
            {"object_id": "ferry_railing", "type": "scenery"},
        ),
    ),
    "restaurant": location(
        "restaurant",
        name_en="Harborlight Restaurant",
        name_zh_cn="港灯餐厅",
        description_en=(
            "A calm restaurant used by residents for meals, tea breaks, and "
            "ordinary conversation."
        ),
        description_zh_cn="居民用餐、喝茶和日常聊天的安静餐厅。",
        scene_type="restaurant",
        connected_location_ids=("square",),
        interaction_points=(
            {"object_id": "tea_counter", "type": "counter"},
            {"object_id": "community_table", "type": "table"},
        ),
    ),
    "shop": location(
        "shop",
        name_en="Corner Shop",
        name_zh_cn="街角小店",
        description_en=(
            "A practical shop with supplies, postcards, and a small shelf for "
            "borrowed tools."
        ),
        description_zh_cn="一间实用的小店，放着补给、明信片和可借用工具的小架子。",
        scene_type="shop",
        connected_location_ids=("square",),
        interaction_points=(
            {"object_id": "supply_shelf", "type": "shelf"},
            {"object_id": "postcard_rack", "type": "display"},
        ),
    ),
    "beach_lighthouse": location(
        "beach_lighthouse",
        name_en="Beach And Lighthouse",
        name_zh_cn="海滩与灯塔",
        description_en=(
            "A quiet stretch of beach below the lighthouse, often used for "
            "walks, maintenance checks, and unhurried talks."
        ),
        description_zh_cn="灯塔下方安静的海滩，常有人散步、做维护检查或慢慢聊天。",
        scene_type="shore",
        connected_location_ids=("residential_lane",),
        interaction_points=(
            {"object_id": "lighthouse_steps", "type": "landmark"},
            {"object_id": "driftwood_log", "type": "seat"},
        ),
    ),
}


RESIDENTS = {
    1: resident(
        1,
        "Mira",
        "Adult library assistant",
        "成年图书室助理",
        "Mira helps newcomers settle in and keeps the shared shelf orderly.",
        "Mira 会帮助新来的岛民安顿下来，也照看共享书架。",
        (
            block("mira_start_lane", 540, 569, "residential_lane", "checking the shared planters", "查看共享花箱", "start the day calmly", "平静地开始一天"),
            block("mira_square_shelf", 570, 659, "square", "organizing the community shelf", "整理社区书架", "keep books easy to find", "让书更容易找到"),
            block("mira_harbor_welcome", 660, 719, "harbor", "welcoming ferry arrivals", "迎接渡船抵达", "help visitors find their way", "帮助访客找到方向"),
            block("mira_square_notes", 720, 779, "square", "updating notice-board notes", "更新公告栏便签", "share practical information", "分享实用信息"),
            block("mira_restaurant_break", 780, 839, "restaurant", "taking a tea break", "喝茶休息", "make time for ordinary conversation", "留出日常交谈的时间"),
            block("mira_square_return", 840, 959, "square", "sorting returned books", "整理归还的书", "finish the shelf routine", "完成书架日常"),
            block("mira_lane_evening", 960, 1200, "residential_lane", "resting near home", "在住处附近休息", "wind down after community tasks", "在社区事务后慢慢收尾"),
            block("mira_day2_lighthouse", 1020, 1079, "beach_lighthouse", "walking by the lighthouse", "沿灯塔散步", "take a quiet day-two pause", "在第二天安静停顿片刻", days=frozenset({2})),
        ),
    ),
    2: resident(
        2,
        "Leo",
        "Adult cafe helper",
        "成年咖啡馆帮手",
        "Leo helps prepare meals and keeps ordinary mishaps light.",
        "Leo 帮忙准备餐点，也常把日常小插曲变得轻松。",
        (
            block("leo_start_lane", 540, 569, "residential_lane", "checking the morning route", "查看早晨路线", "arrive on time for setup", "准时开始准备"),
            block("leo_square_board", 570, 629, "square", "reading the event board", "阅读活动板", "plan the lunch shift", "安排午间班次"),
            block("leo_restaurant_setup", 630, 779, "restaurant", "preparing tables", "准备餐桌", "make lunch service smooth", "让午餐时段顺利"),
            block("leo_square_errand", 780, 839, "square", "carrying a small errand", "处理小差事", "coordinate with nearby residents", "和附近居民协调"),
            block("leo_shop_supplies", 840, 929, "shop", "picking up cafe supplies", "领取餐厅补给", "restock the counter", "补充柜台用品"),
            block("leo_square_break", 930, 1019, "square", "taking a short break", "短暂休息", "catch up with the community", "了解社区近况"),
            block("leo_lane_evening", 1020, 1200, "residential_lane", "heading home after the shift", "班后回到住处附近", "finish the day without rushing", "不匆忙地结束一天"),
            block("leo_day3_late_shop", 930, 989, "shop", "counting spare cups", "清点备用杯子", "prepare for the last afternoon", "为最后一个下午做准备", days=frozenset({3})),
        ),
    ),
    3: resident(
        3,
        "Chen",
        "Adult community coordinator",
        "成年社区协调员",
        "Chen keeps practical schedules and leaves room for interruptions.",
        "Chen 负责日常安排，也会给临时情况留出余地。",
        (
            block("chen_start_lane", 540, 569, "residential_lane", "reviewing the day plan", "查看当天安排", "set a workable rhythm", "安排可执行的节奏"),
            block("chen_square_tasks", 570, 719, "square", "checking community tasks", "检查社区任务", "coordinate shared chores", "协调共同事务"),
            block("chen_shop_inventory", 720, 809, "shop", "reviewing shop inventory", "核对小店库存", "note what needs restocking", "记录需要补充的物品"),
            block("chen_square_followup", 810, 899, "square", "following up on notices", "跟进公告事项", "close small loops", "处理小收尾"),
            block("chen_harbor_timetable", 900, 959, "harbor", "checking the ferry timetable", "核对渡船时刻", "prepare for later arrivals", "为稍后的抵达做准备"),
            block("chen_square_wrap", 960, 1019, "square", "summarizing community notes", "整理社区记录", "make tomorrow easier", "让明天更顺利"),
            block("chen_lane_evening", 1020, 1200, "residential_lane", "returning home with notes", "带着记录回到住处附近", "put the day in order", "把一天整理清楚"),
            block("chen_day2_beach_check", 1080, 1139, "beach_lighthouse", "checking the lighthouse path", "检查灯塔小径", "confirm the path is clear", "确认道路畅通", days=frozenset({2})),
        ),
    ),
    4: resident(
        4,
        "Nova",
        "Adult shopkeeper",
        "成年店主",
        "Nova runs the corner shop and notices what residents tend to need.",
        "Nova 经营街角小店，也会留意居民常需要什么。",
        (
            block("nova_start_lane", 540, 569, "residential_lane", "opening the shutters at home", "在住处附近打开窗板", "begin the shop day", "开始小店的一天"),
            block("nova_square_walk", 570, 629, "square", "walking through the square", "穿过广场", "see what the morning needs", "看看上午需要什么"),
            block("nova_shop_open", 630, 839, "shop", "restocking the shop", "给小店补货", "keep everyday items available", "保持日用品充足"),
            block("nova_square_delivery", 840, 929, "square", "dropping off shared supplies", "送出共享用品", "help the community board stay useful", "让社区公告板保持有用"),
            block("nova_restaurant_dropoff", 930, 989, "restaurant", "delivering a small order", "送一份小订单", "support the lunch crowd", "支持午餐时段"),
            block("nova_square_return", 990, 1049, "square", "checking the square again", "再次查看广场", "notice late-day needs", "留意傍晚需求"),
            block("nova_lane_evening", 1050, 1200, "residential_lane", "closing up near home", "在住处附近收尾", "end the shop day", "结束小店的一天"),
            block("nova_day2_lighthouse_supplies", 1110, 1169, "beach_lighthouse", "bringing spare batteries", "带来备用电池", "support a lighthouse check", "支持灯塔检查", days=frozenset({2})),
        ),
    ),
    5: resident(
        5,
        "Kai",
        "Adult maintenance worker",
        "成年维护员",
        "Kai handles small repairs and prefers practical, direct conversation.",
        "Kai 负责小修小补，也偏好实际直接的交流。",
        (
            block("kai_start_lane", 540, 569, "residential_lane", "checking the tool bag", "检查工具包", "start prepared", "准备充分地开始"),
            block("kai_square_scan", 570, 629, "square", "scanning the square for repairs", "查看广场维修点", "find small maintenance tasks", "找到小型维护任务"),
            block("kai_harbor_fix", 630, 749, "harbor", "tightening harbor railings", "加固渡口栏杆", "keep the landing tidy", "保持停靠点整洁"),
            block("kai_square_tools", 750, 809, "square", "checking shared tools", "检查共享工具", "return tools to the right place", "把工具放回合适的位置"),
            block("kai_restaurant_repair", 810, 899, "restaurant", "fixing a loose chair", "修理松动的椅子", "handle a small repair", "处理小修理"),
            block("kai_square_report", 900, 959, "square", "leaving a maintenance note", "留下维护记录", "make the work visible", "让工作有记录"),
            block("kai_lane_evening", 960, 1200, "residential_lane", "cleaning tools near home", "在住处附近清理工具", "put everything away", "把东西收好"),
            block("kai_day3_lighthouse_check", 1020, 1079, "beach_lighthouse", "checking lighthouse steps", "检查灯塔台阶", "keep the shore path safe", "保持海边小径安全", days=frozenset({3})),
        ),
    ),
}


ISLAND_V04_SPEC = WorldSpec(
    world_version=WORLD_VERSION,
    scenario_pack_version=SCENARIO_PACK_VERSION,
    start_location_id="participant_home",
    calendar=CalendarSpec(
        total_days=3,
        day_start_minute=DAY_START,
        day_end_minute=DAY_END,
        rollover="next_day",
    ),
    locations=LOCATIONS,
    residents=RESIDENTS,
    action_minutes={
        "move": 15,
        "observe": 5,
        "approach": 5,
        "wait": 15,
        "conversation_message": 5,
        "end_conversation": 0,
        "end_day": 0,
    },
)
validate_location_graph(ISLAND_V04_SPEC)
validate_resident_schedules(ISLAND_V04_SPEC)
