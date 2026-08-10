"""m7 任务配置面板（读写 m7 config.yaml，ruamel 保留注释）。

范围（合理取舍）：每任务的关键标量配置（开关/数字/下拉/文本）；
列表型复杂配置（power_plan/队伍/兑换码）提示改 yaml——322 键全做 UI
不现实且易错。写回前备份 .bak。
"""

from pathlib import Path

M7_CONFIG = (Path(__file__).resolve().parent.parent.parent.parent
             / "March7thAssistant" / "config.yaml")


def load_config():
    """ruamel 加载 m7 config.yaml（保注释）；失败返回 None。"""
    import ruamel.yaml
    yaml = ruamel.yaml.YAML()
    with open(M7_CONFIG, "r", encoding="utf-8") as f:
        return yaml.load(f)


def save_config(updates: dict):
    """更新键值并写回（保注释）；写前备份 .bak。返回 (ok, 错误或None)。"""
    import shutil
    import ruamel.yaml
    if not M7_CONFIG.exists():
        return False, f"config.yaml 不存在: {M7_CONFIG}"
    try:
        yaml = ruamel.yaml.YAML()
        with open(M7_CONFIG, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        for k, v in updates.items():
            data[k] = v
        shutil.copy2(M7_CONFIG, str(M7_CONFIG) + ".bak")
        with open(M7_CONFIG, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# 配置 schema：每键 (类型, 标签, 选项/默认)
# 类型: bool/int/text/choice
SCHEMA = {
    "通用": {
        "game_path": ("text", "游戏可执行文件路径"),
        "use_background_screenshot": ("bool", "使用后台截图"),
        "hotkey_stop_task": ("text", "停止任务热键"),
    },
    "日常/奖励": {
        "daily_enable": ("bool", "每日实训"),
        "activity_enable": ("bool", "活动任务"),
        "reward_enable": ("bool", "奖励领取总开关"),
        "reward_mail_enable": ("bool", "邮件奖励"),
        "reward_assist_enable": ("bool", "支援奖励"),
        "reward_dispatch_enable": ("bool", "委托派遣奖励"),
        "reward_quest_enable": ("bool", "每日实训奖励"),
        "reward_srpass_enable": ("bool", "无名勋礼"),
        "reward_redemption_code_enable": ("bool", "兑换码"),
    },
    "体力": {
        "power_enable": ("bool", "清体力"),
        "instance_type": ("choice", "副本类型", [
            "拟造花萼（金）", "拟造花萼（赤）", "凝滞虚影",
            "侵蚀隧洞", "饰品提取", "历战余响"]),
        "instance_team_enable": ("bool", "自动切换队伍"),
        "instance_team_number": ("int", "副本队伍编号", 1, 8),
        "use_fuel": ("bool", "使用燃料"),
        "use_reserved_trailblaze_power": ("bool", "使用后备开拓力"),
        "echo_of_war_enable": ("bool", "历战余响"),
        "echo_of_war_start_day_of_week": ("int", "历战余响开始星期", 1, 7),
        "tp_before_instance": ("bool", "副本前传送治疗"),
    },
    "锄大地": {
        "fight_enable": ("bool", "锄大地"),
        "fight_team_enable": ("bool", "锄大地自动切队"),
        "fight_team_number": ("int", "锄大地队伍编号", 1, 10),
        "fight_timeout": ("int", "锄大地超时（小时）", 1, 24),
        "fight_operation_mode": ("choice", "运行方式", ["exe", "source"]),
        "fight_main_map": ("int", "主地图", 0, 10),
    },
    "模拟宇宙": {
        "universe_enable": ("bool", "模拟宇宙"),
        "universe_category": ("choice", "类别", [
            "universe", "divergent", "divergent_weekly"]),
        "universe_count": ("int", "次数", 1, 50),
        "universe_frequency": ("choice", "频率", ["weekly", "daily"]),
        "universe_operation_mode": ("choice", "运行方式", ["exe", "source"]),
        "universe_bonus_enable": ("bool", "双倍奖励"),
        "universe_timeout": ("int", "超时（小时）", 1, 48),
    },
    "差分宇宙": {
        "weekly_divergent_enable": ("bool", "差分宇宙"),
        "weekly_divergent_type": ("choice", "类型", ["cycle", "level"]),
        "weekly_divergent_level": ("int", "难度", 1, 8),
        "weekly_divergent_bonus_enable": ("bool", "双倍奖励"),
        "divergent_station_priority_enable": ("bool", "站点优先级"),
    },
    "货币战争": {
        "currencywars_enable": ("bool", "货币战争"),
        "currencywars_type": ("choice", "类型", ["overclock", "deep_abyss"]),
        "currencywars_rank_difficulty": ("choice", "难度", [
            "lowest", "low", "medium", "high", "highest"]),
        "currencywars_strategy": ("choice", "策略", [
            "default", "mem_meta", "erudition_meta"]),
        "currencywars_fast_mode": ("bool", "快速模式"),
        "currencywars_bonus_enable": ("bool", "双倍奖励"),
    },
    "挑战": {
        "forgottenhall_enable": ("bool", "混沌回忆"),
        "forgottenhall_level": ("text", "混沌回忆层数（如 9,12）"),
        "purefiction_enable": ("bool", "虚构叙事"),
        "purefiction_level": ("text", "虚构叙事层数（如 3,4）"),
        "apocalyptic_enable": ("bool", "末日幻影"),
        "apocalyptic_level": ("text", "末日幻影层数（如 3,4）"),
    },
}

# 任务 → 配置分组映射
TASK_GROUPS_MAP = {
    "routine": "日常/奖励", "daily": "日常/奖励", "redemption": "日常/奖励",
    "power": "体力",
    "fight": "锄大地",
    "universe": "模拟宇宙",
    "divergent": "差分宇宙", "divergentloop": "差分宇宙",
    "currencywars": "货币战争", "currencywarsloop": "货币战争",
    "forgottenhall": "挑战", "purefiction": "挑战", "apocalyptic": "挑战",
}


def schema_for_task(task_id):
    """任务 → (分组名, 键列表) 或 None（无配置）。"""
    group = TASK_GROUPS_MAP.get(task_id)
    if group is None or group not in SCHEMA:
        return None
    return group, list(SCHEMA[group].items())
