"""Versioned, deterministic content for the v0.3 island vertical slice."""

from typing import Any

from world.graph import validate_location_graph
from world.schedules import (
    ScheduleResolutionError,
    resolve_resident_schedule,
    validate_resident_schedules,
)
from world.specs import CalendarSpec, world_spec_from_legacy


WORLD_VERSION = "island-v0.3"
SCENARIO_PACK_VERSION = "island-scenarios-v0.3"
SEATING_SCENARIO_ID = "restaurant_seating_v03"
CONFLICT_SCENARIO_ID = "restaurant_order_conflict_v03"
SCENARIO_VERSION = "v0.3.0"


LOCATIONS: dict[str, dict[str, Any]] = {
    "harbor": {
        "location_id": "harbor",
        "name": {"en": "Ferry Harbor", "zh-CN": "渡口"},
        "description": {
            "en": "A small ferry landing with a notice board and a path toward the square.",
            "zh-CN": "一处小型渡船码头，旁边有公告栏和通往广场的小路。",
        },
        "scene_type": "arrival",
        "connected_location_ids": ["square"],
        "interaction_points": [
            {"object_id": "harbor_notice_board", "type": "notice_board"},
            {"object_id": "ferry_railing", "type": "scenery"},
        ],
        "version": WORLD_VERSION,
    },
    "square": {
        "location_id": "square",
        "name": {"en": "Community Square", "zh-CN": "社区广场"},
        "description": {
            "en": "The island's central meeting place, linking the harbor and restaurant.",
            "zh-CN": "岛上的中心会面地点，连接渡口和餐厅。",
        },
        "scene_type": "community",
        "connected_location_ids": ["harbor", "restaurant"],
        "interaction_points": [
            {"object_id": "square_bench", "type": "seat"},
            {"object_id": "community_board", "type": "feed_entry"},
        ],
        "version": WORLD_VERSION,
    },
    "restaurant": {
        "location_id": "restaurant",
        "name": {"en": "Harborlight Restaurant", "zh-CN": "港灯餐厅"},
        "description": {
            "en": "A quiet island restaurant with several distinct seating areas.",
            "zh-CN": "一家安静的岛屿餐厅，设有几个不同的用餐区域。",
        },
        "scene_type": "research_anchor",
        "connected_location_ids": ["square"],
        "interaction_points": [
            {"object_id": "window_table", "type": "research_seat"},
            {"object_id": "quiet_corner", "type": "research_seat"},
            {"object_id": "shared_table", "type": "research_seat"},
            {"object_id": "counter_seat", "type": "research_seat"},
        ],
        "version": WORLD_VERSION,
    },
}


RESIDENTS: dict[int, dict[str, Any]] = {
    1: {
        "agent_id": 1,
        "name": "Mira",
        "role": {"en": "Library assistant", "zh-CN": "图书室助理"},
        "background": {
            "en": "Mira helps newcomers find their footing and spends quiet hours organizing the community shelf.",
            "zh-CN": "Mira 会帮助新岛民熟悉环境，空闲时整理社区书架。",
        },
        "schedule": [
            (
                0,
                599,
                "harbor",
                {"en": "welcoming arrivals", "zh-CN": "迎接抵达的岛民"},
                {"en": "help the new islander settle in", "zh-CN": "帮助新岛民安顿下来"},
                "morning_harbor",
            ),
            (
                600,
                719,
                "square",
                {"en": "organizing the community shelf", "zh-CN": "整理社区书架"},
                {"en": "finish a small community task", "zh-CN": "完成一项社区小任务"},
                "late_morning_square",
            ),
            (
                720,
                1439,
                "restaurant",
                {"en": "taking a tea break", "zh-CN": "喝茶休息"},
                {"en": "have an ordinary conversation", "zh-CN": "进行一次日常交谈"},
                "afternoon_restaurant",
            ),
        ],
    },
    2: {
        "agent_id": 2,
        "name": "Leo",
        "role": {"en": "Cafe helper", "zh-CN": "咖啡馆帮工"},
        "background": {
            "en": "Leo helps at the restaurant and turns minor everyday mishaps into light jokes.",
            "zh-CN": "Leo 在餐厅帮忙，也常把日常的小麻烦说成轻松的玩笑。",
        },
        "schedule": [
            (
                0,
                569,
                "square",
                {"en": "checking the event board", "zh-CN": "查看活动公告板"},
                {"en": "decide what to do before the lunch shift", "zh-CN": "安排午间班次前的时间"},
                "morning_square",
            ),
            (
                570,
                779,
                "restaurant",
                {"en": "helping with the lunch setup", "zh-CN": "协助午餐前的准备"},
                {"en": "get the tables ready", "zh-CN": "把餐桌准备妥当"},
                "lunch_restaurant",
            ),
            (
                780,
                1439,
                "square",
                {"en": "taking a break", "zh-CN": "稍作休息"},
                {"en": "catch up with the community", "zh-CN": "了解社区近况"},
                "afternoon_square",
            ),
        ],
    },
    3: {
        "agent_id": 3,
        "name": "Chen",
        "role": {"en": "Community coordinator", "zh-CN": "社区协调员"},
        "background": {
            "en": "Chen keeps practical island schedules but is learning to leave room for interruptions.",
            "zh-CN": "Chen 负责安排岛上的日常事务，也在学习为突发情况留出空间。",
        },
        "schedule": [
            (
                0,
                629,
                "restaurant",
                {"en": "reviewing a booking list", "zh-CN": "核对预订清单"},
                {"en": "resolve the morning reservations", "zh-CN": "处理上午的预订安排"},
                "morning_restaurant",
            ),
            (
                630,
                839,
                "square",
                {"en": "checking community tasks", "zh-CN": "检查社区任务"},
                {"en": "coordinate the afternoon plan", "zh-CN": "协调下午的计划"},
                "midday_square",
            ),
            (
                840,
                1439,
                "harbor",
                {"en": "checking the ferry timetable", "zh-CN": "核对渡船时刻表"},
                {"en": "prepare for the evening arrival", "zh-CN": "准备迎接傍晚抵达的渡船"},
                "afternoon_harbor",
            ),
        ],
    },
}


SEATING_FORMS: dict[str, list[dict[str, Any]]] = {
    "layout_a": [
        {
            "option_id": "window_table",
            "label": {"en": "Window table", "zh-CN": "靠窗桌"},
            "attributes": ["bright", "some_outside_noise", "independent_table"],
            "display_order": 1,
        },
        {
            "option_id": "quiet_corner",
            "label": {"en": "Quiet corner", "zh-CN": "安静角落"},
            "attributes": ["quiet", "low_traffic", "independent_table"],
            "display_order": 2,
        },
        {
            "option_id": "shared_table",
            "label": {"en": "Shared long table", "zh-CN": "共享长桌"},
            "attributes": ["shared", "moderate_noise", "near_residents"],
            "display_order": 3,
        },
        {
            "option_id": "counter_seat",
            "label": {"en": "Counter seat", "zh-CN": "吧台座位"},
            "attributes": ["counter", "staff_nearby", "moderate_traffic"],
            "display_order": 4,
        },
    ],
    "layout_b": [
        {
            "option_id": "counter_seat",
            "label": {"en": "Counter seat", "zh-CN": "吧台座位"},
            "attributes": ["counter", "staff_nearby", "moderate_traffic"],
            "display_order": 1,
        },
        {
            "option_id": "shared_table",
            "label": {"en": "Shared long table", "zh-CN": "共享长桌"},
            "attributes": ["shared", "moderate_noise", "near_residents"],
            "display_order": 2,
        },
        {
            "option_id": "quiet_corner",
            "label": {"en": "Quiet corner", "zh-CN": "安静角落"},
            "attributes": ["quiet", "low_traffic", "independent_table"],
            "display_order": 3,
        },
        {
            "option_id": "window_table",
            "label": {"en": "Window table", "zh-CN": "靠窗桌"},
            "attributes": ["bright", "some_outside_noise", "independent_table"],
            "display_order": 4,
        },
    ],
}


CONFLICT_VARIANTS = ("user_supported", "ambiguous", "other_supported")


TEXT = {
    "seating_stimulus": {
        "en": "The host says you may choose any currently open seat.",
        "zh-CN": "店员表示，你可以从当前空着的座位中任选一个。",
    },
    "conflict_user_supported": {
        "en": "After you sit down, a booking mix-up appears. The written list supports your understanding.",
        "zh-CN": "你落座后出现了预订误会，书面记录支持你的理解。",
    },
    "conflict_ambiguous": {
        "en": "After you sit down, a booking mix-up appears. The available information is incomplete.",
        "zh-CN": "你落座后出现了预订误会，目前的信息并不完整。",
    },
    "conflict_other_supported": {
        "en": "After you sit down, a booking mix-up appears. The written list supports the other person's understanding.",
        "zh-CN": "你落座后出现了预订误会，书面记录支持对方的理解。",
    },
    "follow_up": {
        "en": "Later, the restaurant staff checks in calmly, confirms the mix-up has been settled, and leaves room for an ordinary conversation.",
        "zh-CN": "稍后，餐厅员工平静地来确认情况，说明误会已经处理好，并自然地留出继续交流的空间。",
    },
}


ISLAND_V03_SPEC = world_spec_from_legacy(
    world_version=WORLD_VERSION,
    scenario_pack_version=SCENARIO_PACK_VERSION,
    start_location_id="harbor",
    calendar=CalendarSpec(
        total_days=1,
        day_start_minute=9 * 60,
        day_end_minute=20 * 60,
        rollover="clamp",
    ),
    locations=LOCATIONS,
    residents=RESIDENTS,
    action_minutes={
        "move": 15,
        "observe": 5,
        "approach": 5,
        "seat_view": 2,
        "seat_select": 5,
        "seat_change": 5,
        "scenario_response": 10,
        "scenario_skip": 5,
        "conversation_message": 5,
        "end_conversation": 0,
    },
)
validate_location_graph(ISLAND_V03_SPEC)
validate_resident_schedules(ISLAND_V03_SPEC)


def localized(value: dict[str, str], language: str) -> str:
    return value.get(language) or value["en"]


def schedule_for(agent_id: int, minute: int) -> dict[str, Any]:
    # Preserve the legacy KeyError contract for unknown resident ids.
    RESIDENTS[agent_id]
    normalized = max(0, min(1439, minute))
    try:
        block = resolve_resident_schedule(
            ISLAND_V03_SPEC,
            agent_id,
            day=1,
            minute=normalized,
        )
    except ScheduleResolutionError as exc:
        raise RuntimeError(
            f"No schedule entry for agent {agent_id} at {minute}."
        ) from exc
    return {
        "location_id": block.location_id,
        "activity": localized(block.activity, "en"),
        "goal": localized(block.goal, "en"),
        "activity_translations": block.activity,
        "goal_translations": block.goal,
        "schedule_state": block.state_id,
    }
