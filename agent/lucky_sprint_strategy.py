"""
幸运冲刺 策略表模块
根据人物等级和当前距离，返回应执行的动作。
"""

# 动作类型
ACTION_RUN = "run"         # 普通奔跑
ACTION_PROTECT = "protect"  # 防护
ACTION_BOOST = "boost"     # 助跑
ACTION_LUCKY = "lucky"     # 超级幸运


def _build_table(*pairs):
    """
    将 [距离, 动作] 对展开为距离→动作的字典。
    每对可以是 (start, end, action) 或 (distance, action)。
    三段式：从 start 到 end（不含），每 10m 执行 action。
    两段式：仅 distance 这一个点执行 action。
    """
    table = {}
    for pair in pairs:
        if len(pair) == 3:
            start, end, action = pair
            for d in range(start, end, 10):
                table[d] = action
        else:
            dist, action = pair
            table[dist] = action
    return table


# ============================================================
# 策略表
# ============================================================

STRATEGY_LV0 = _build_table(
    (0, 50, ACTION_RUN),
    (50, 70, ACTION_PROTECT),
    (70, 80, ACTION_BOOST),
    (80, 270, ACTION_RUN),
    (270, 280, ACTION_BOOST),
    (280, 310, ACTION_PROTECT),
)

STRATEGY_LV1 = _build_table(
    (0, 30, ACTION_RUN),
    (30, 50, ACTION_PROTECT),
    (50, 60, ACTION_BOOST),
    (60, 70, ACTION_PROTECT),
    (70, 80, ACTION_LUCKY),
    (80, 140, ACTION_RUN),
    (140, 170, ACTION_PROTECT),
    (170, 180, ACTION_BOOST),
    (180, 220, ACTION_RUN),
    (220, 230, ACTION_BOOST),
    (230, 250, ACTION_RUN),
    (250, 260, ACTION_PROTECT),
    (260, 270, ACTION_LUCKY),
    (270, 280, ACTION_BOOST),
    (280, 310, ACTION_PROTECT),
)

STRATEGY_LV2_3 = _build_table(
    (0, 30, ACTION_RUN),
    (30, 40, ACTION_BOOST),
    (40, 60, ACTION_PROTECT),
    (60, 70, ACTION_PROTECT),
    (70, 80, ACTION_LUCKY),
    (80, 120, ACTION_RUN),
    (120, 130, ACTION_BOOST),
    (130, 160, ACTION_RUN),
    (160, 180, ACTION_PROTECT),
    (180, 190, ACTION_LUCKY),
    (190, 210, ACTION_RUN),
    (210, 220, ACTION_BOOST),
    (220, 250, ACTION_RUN),
    (250, 270, ACTION_PROTECT),
    (270, 280, ACTION_BOOST),
    (280, 310, ACTION_PROTECT),
)

STRATEGY_LV4 = _build_table(
    (0, 30, ACTION_RUN),
    (30, 40, ACTION_BOOST),
    (40, 60, ACTION_PROTECT),
    (60, 70, ACTION_PROTECT),
    (70, 80, ACTION_LUCKY),
    (80, 120, ACTION_RUN),
    (120, 130, ACTION_BOOST),
    (130, 160, ACTION_RUN),
    (160, 180, ACTION_PROTECT),
    (180, 190, ACTION_LUCKY),
    (190, 210, ACTION_RUN),
    (210, 220, ACTION_BOOST),
    (220, 250, ACTION_RUN),
    (250, 270, ACTION_PROTECT),
    (270, 280, ACTION_BOOST),
    (280, 310, ACTION_PROTECT),
)

STRATEGY_LV5_FIRST = _build_table(
    (0, 30, ACTION_RUN),
    (30, 40, ACTION_BOOST),
    (40, 50, ACTION_BOOST),
    (50, 70, ACTION_PROTECT),
    (70, 80, ACTION_LUCKY),
    (80, 120, ACTION_RUN),
    (120, 130, ACTION_BOOST),
    (130, 160, ACTION_RUN),
    (160, 170, ACTION_PROTECT),
    (170, 180, ACTION_LUCKY),
    (180, 200, ACTION_RUN),
    (200, 210, ACTION_PROTECT),
    (210, 220, ACTION_PROTECT),
    (220, 230, ACTION_BOOST),
    (230, 250, ACTION_RUN),
    (250, 270, ACTION_PROTECT),
    (270, 280, ACTION_LUCKY),
    (280, 310, ACTION_PROTECT),
)

STRATEGY_LV5_LOOP = _build_table(
    (0, 30, ACTION_RUN),
    (30, 40, ACTION_BOOST),
    (40, 60, ACTION_PROTECT),
    (60, 70, ACTION_PROTECT),
    (70, 80, ACTION_LUCKY),
    (80, 120, ACTION_RUN),
    (120, 130, ACTION_BOOST),
    (130, 150, ACTION_RUN),
    (150, 160, ACTION_PROTECT),
    (160, 180, ACTION_PROTECT),
    (180, 200, ACTION_RUN),
    (200, 210, ACTION_BOOST),
    (210, 230, ACTION_PROTECT),
    (230, 250, ACTION_RUN),
    (250, 270, ACTION_PROTECT),
    (270, 280, ACTION_PROTECT),
    (280, 310, ACTION_PROTECT),
)

# 等级 → 策略表映射
STRATEGIES = {
    0: STRATEGY_LV0,
    1: STRATEGY_LV1,
    2: STRATEGY_LV2_3,
    3: STRATEGY_LV2_3,
    4: STRATEGY_LV4,
}


def get_action(level: int, distance: int) -> str:
    """
    根据人物等级和当前距离，返回应执行的动作。
    返回 ACTION_RUN / ACTION_PROTECT / ACTION_BOOST / ACTION_LUCKY。
    如果距离超出策略表范围，默认返回普通奔跑。
    """
    table = STRATEGIES.get(level)
    if table is None:
        return ACTION_RUN
    # 对齐到 10m 步长
    step = (distance // 10) * 10
    return table.get(step, ACTION_RUN)


def get_lv5_action(distance: int, is_first_pass: bool) -> str:
    """Lv5 专属：根据是否首通选择不同策略表。"""
    table = STRATEGY_LV5_FIRST if is_first_pass else STRATEGY_LV5_LOOP
    step = (distance // 10) * 10
    return table.get(step, ACTION_RUN)
