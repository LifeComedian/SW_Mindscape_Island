"""Text cards and tabletop exercise definitions."""
from copy import deepcopy


def enrich(systems):
    actions = systems["action_definitions"]
    by_id = {a["action_id"]: a for a in actions}
    texts = {
        "act_43": [
            "《把空白留给海》：我原想把七天写满，后来只在第一页画了一条线。那是窗外的海岸线，也是今天愿意走到的地方。路过的人问我明天去哪里，我说还没定。他指了指自己的空杯：先坐一会儿，明天可以明天再想。",
            "《多出来的椅子》：小店门口总比客人多一把椅子。有人问是不是在等谁，店主说，不是约好的人也可以坐。下午来了个抱着空花盆的人。他没买东西，只坐了片刻。离开时把椅子往阴影里挪了挪。",
            "《晚风》：杯底留着一点光，／窗框收住半片海。／今天还没说完的话，／可以带走，／也可以留在今天。",
        ],
        "act_37": ["曲目卡《沿着木栈道》：轻快的木吉他与轻敲节奏。当前展示文字卡，尚未接入音频。", "曲目卡《窗边的下午》：舒缓钢琴，句子之间留出停顿。当前展示文字卡，尚未接入音频。", "曲目卡《返航灯》：低声弦乐与海边意象。当前展示文字卡，尚未接入音频。"],
        "act_41": ["清爽：轻、明亮、余味短。醇厚：口感饱满、余味较长。这是词义比较，不代表你已经品尝。", "花香可联想到白花或干花；果香可联想到柑橘或熟果。这里描述感受，没有唯一正确偏好。", "风味卡：同一种饮品可以同时显得清爽又带果香。选词表达体验，不是对人的判断。"],
        "act_19": ["老广告卡（虚构岛史）：圆润手写字围着一条小船。包装师傅希望远处也能认出店名。", "老广告卡（虚构岛史）：深蓝底色配米白波纹，后来改成更浅的蓝，便于读清材料说明。", "故事卡（虚构岛史）：这张纸套原本装短途渡船上的烘烤薄饼。乘客常把背面空白拿来记返航时刻。"],
        "act_09": ["花材卡：白色小雏菊、淡紫补血草、绿色尤加利叶。颜色与层次可以自由组合。", "香草卡：薄荷是清凉的描述，迷迭香带木质与草本意象。这里仅阅读描述，不安排采食。", "揭晓卡：细小紫色花簇是补血草，常作干燥花材。猜错也可以直接看答案。"],
    }
    for source, choices in texts.items():
        for i, text in enumerate(choices, 1):
            by_id[f"{source}_choice_{i}"]["consequences"].append({"effect_type": "set_object_state", "state_key": "result", "value": text})

    template = deepcopy(actions[0])
    def step(aid, oid, lid, label, before, after, result, duration):
        definition = deepcopy(template)
        definition.update(action_id=aid, label={"en": label, "zh-CN": label}, actor_types=["participant"],
            min_participants=1, max_participants=20, duration_minutes=duration, inputs=[], text_record=None,
            preconditions={"object_state_equals": {"exercise_step": before}},
            consequences=[{"effect_type": "set_object_state", "state_key": "exercise_step", "value": after},
                {"effect_type": "set_object_state", "state_key": "result", "value": result}])
        actions.append(definition)
        systems["affordances"].append({"affordance_id": aid + "_here", "action_id": aid, "location_ids": [lid],
            "object_ids": [oid], "enabled": True, "conditions": {}, "permission_keys": [], "capability_keys": []})

    exercises = [
        ("act_03", "obj_02", "loc_01", "桌面上有一根绳子，两端分别标着左右。可以跟着卡片打一个平结，也可以随时放下。", [
            ("右端压过左端并绕到下方", "右端从左端下方绕过，桌上形成第一个交叉。接下来换一侧。"),
            ("左端压过右端并绕到下方", "左端绕了回来，两个交叉已经叠在一起。最后把两端整理平整。"),
            ("轻拉两端并整理平整", "你轻拉两端，一个平整的绳结留在桌上。这次练习完成了，可以松开再试。")]),
        ("act_35", "obj_23", "loc_05", "篮子里放着柔软的小球，地面上画着几道距离标记。试着用三种方式让它动起来，按自己的节奏就好。", [
            ("第一轮：近距离轻抛", "你把软球轻轻抛向近处，再捡回手中。下一轮可以试试低一些的弧线。"),
            ("第二轮：沿低弧线传出", "软球沿低低的弧线落下，弹了一小下。你拾起球，准备最后一次尝试。"),
            ("第三轮：缓缓滚向标记", "你把软球放低，让它沿地面慢慢滚出去。三轮结束，你收回球放进篮里。")]),
    ]
    # Resolve object ids from existing affordances, keeping accepted source IDs.
    for source, oid, lid, instruction, rounds in exercises:
        oid = next(a["object_ids"][0] for a in systems["affordances"] if a["action_id"] == source + "_choice_1")
        for aid, definition in by_id.items():
            if aid.startswith(source + "_choice_"):
                definition["duration_minutes"] = 0
                definition["consequences"] += [
                    {"effect_type": "set_object_state", "state_key": "exercise_step", "value": 1},
                    {"effect_type": "set_object_state", "state_key": "result", "value": instruction}]
        for i, (label, result) in enumerate(rounds, 1):
            step(source + f"_step_{i}", oid, lid, label, i, i+1, result, [3, 3, 4][i-1])
    oid = next(a["object_ids"][0] for a in systems["affordances"] if a["action_id"] == "act_33_choice_1")
    for i in range(1, 4):
        by_id[f"act_33_choice_{i}"]["duration_minutes"] = 0
        by_id[f"act_33_choice_{i}"]["consequences"] += [
            {"effect_type": "set_object_state", "state_key": "exercise_step", "value": 1},
            {"effect_type": "set_object_state", "state_key": "result", "value": "图形卡：○ △ □ ○ △ ？。空位上应该是哪一个图形？可以慢慢想，也可以翻开提示卡。"}]
    for i, shape in enumerate(("○", "△", "□"), 1):
        step(f"act_33_answer_{i}", oid, "loc_05", "选择 " + shape, 1, 2 if i == 3 else 1,
            "完成：每组三个图形重复，最后一个是 □。" if i == 3 else "这张卡按三个图形循环。可以再试一次，或直接看提示。", 1)
    step("act_33_hint", oid, "loc_05", "查看提示与答案", 1, 2, "翻开提示卡：○ △ □ 为一组，接下来再重复一次，所以答案是 □。", 1)
