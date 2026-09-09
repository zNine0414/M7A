import json
import re
import time

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from lucky_sprint_strategy import (
    ACTION_RUN,
    ACTION_PROTECT,
    ACTION_BOOST,
    ACTION_LUCKY,
    get_action,
    get_lv5_action,
)


# ============================================================
# 通用工具
# ============================================================

def _parse_param(custom_action_param) -> dict:
    if custom_action_param is None:
        return {}
    if isinstance(custom_action_param, str):
        try:
            return json.loads(custom_action_param)
        except json.JSONDecodeError:
            return {}
    if isinstance(custom_action_param, dict):
        return custom_action_param
    return {}


def _screencap(context: Context):
    job = context.tasker.controller.post_screencap()
    return job.wait().get()


def _find_and_click(context: Context, node_name: str, image) -> bool:
    """模板匹配并点击中心。"""
    result = context.run_recognition(node_name, image)
    if result and result.hit and result.box is not None:
        box = result.box
        cx = box[0] + box[2] // 2
        cy = box[1] + box[3] // 2
        context.tasker.controller.post_click(cx, cy).wait()
        return True
    return False


def _ocr_int(context: Context, node_name: str, image) -> int | None:
    """运行 OCR 节点，提取首个整数。"""
    result = context.run_recognition(node_name, image)
    if result and result.hit and result.best_result:
        text = getattr(result.best_result, "text", "")
        nums = re.findall(r'\d+', str(text))
        if nums:
            return int(nums[0])
    return None


def _ocr_text(context: Context, node_name: str, image) -> str:
    """运行 OCR 节点，返回文本。"""
    result = context.run_recognition(node_name, image)
    if result and result.hit and result.best_result:
        return str(getattr(result.best_result, "text", "")).strip()
    return ""


def _check_visible(context: Context, node_name: str, image) -> bool:
    """检查模板是否可见。"""
    result = context.run_recognition(node_name, image)
    return result is not None and result.hit


# ============================================================
# click_screen_center
# ============================================================

@AgentServer.custom_action("click_screen_center")
class ClickScreenCenter(CustomAction):
    """点击屏幕正中间位置。"""

    DEFAULT_CENTER_X = 540
    DEFAULT_CENTER_Y = 960

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        param = _parse_param(argv.custom_action_param)
        offset_x = param.get("offset_x", 0)
        offset_y = param.get("offset_y", 0)
        post_delay = param.get("post_delay", 1000)

        tx = self.DEFAULT_CENTER_X + offset_x
        ty = self.DEFAULT_CENTER_Y + offset_y
        print(f"[ClickScreenCenter] 点击 ({tx}, {ty})")

        context.tasker.controller.post_click(tx, ty).wait()
        if post_delay > 0:
            time.sleep(post_delay / 1000.0)
        return True


# ============================================================
# lucky_sprint_core — 幸运冲刺核心循环
# ============================================================

ITEM_NODES = {
    ACTION_PROTECT: ("Find_ProtectBtn", "Find_ProtectUse"),
    ACTION_BOOST:   ("Find_BoostBtn",   "Find_BoostUse"),
    ACTION_LUCKY:   ("Find_LuckyBtn",   "Find_LuckyUse"),
}


@AgentServer.custom_action("lucky_sprint_core")
class LuckySprintCore(CustomAction):
    """
    幸运冲刺核心循环。

    Pipeline 参数 (custom_action_param):
        max_rounds   (int): 最大轮次，默认 100
        min_drinks   (int): 饮料低于此值停止，默认 1
        loop_forever (bool): 无视饮料数量一直循环，默认 false
    """

    def __init__(self):
        super().__init__()
        self._first_pass_checked = False
        self._is_first_pass = False
        self._round = 0
        self._distance = 0
        self._low_drink_count = 0  # 连续低饮料计数

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        param = _parse_param(argv.custom_action_param)
        max_rounds = param.get("max_rounds", 100)
        min_drinks = param.get("min_drinks", 1)
        loop_forever = param.get("loop_forever", False)

        # 等待活动页面加载完成
        time.sleep(2.0)

        # 进入活动后先领一次饮料
        print("[LuckySprint] 首次检测饮料...")
        img = _screencap(context)
        self._claim_drink(context, img)

        for self._round in range(max_rounds):
            # 检查停止信号
            if context.tasker.stopping:
                print("[LuckySprint] 收到停止信号，退出")
                break

            print(f"\n[LuckySprint] === 第 {self._round + 1} 轮 ===")

            # ── OCR ──
            img = _screencap(context)
            ocr_dist = _ocr_int(context, "OCR_Distance", img)

            # 首通已判过 → 不再 OCR 等级，节省时间
            if not self._first_pass_checked:
                level = _ocr_int(context, "OCR_Level", img) or 0
            else:
                level = 5  # 已确认过，固定走 Lv5 分支

            drinks = self._read_drinks(context, img)

            if ocr_dist is not None:
                self._distance = ocr_dist
            distance = self._distance

            print(f"[LuckySprint] 距离={distance}m  等级={level}  饮料={drinks}")

            # ── 终止检查 ──
            if not loop_forever and drinks is not None and drinks < min_drinks:
                self._low_drink_count += 1
                if self._low_drink_count >= 2:
                    print(f"[LuckySprint] 饮料不足({drinks}<{min_drinks})，结束")
                    break
            else:
                self._low_drink_count = 0

            # ── Lv5 首通检测 ──
            if level >= 5 and not self._first_pass_checked:
                self._is_first_pass = self._check_first_pass(context)
                self._first_pass_checked = True
                print(f"[LuckySprint] 首通={'未领' if self._is_first_pass else '已领'}")

            # ── 策略 ──
            if level >= 5:
                action = get_lv5_action(distance, self._is_first_pass)
            else:
                action = get_action(level, distance)
            print(f"[LuckySprint] 策略 → {action}")

            # ── 执行 ──
            img = _screencap(context)
            self._execute_action(context, img, action)

            # ── 等结果 ──
            self._handle_result(context)

            # ── 领饮料 ──
            img = _screencap(context)
            self._claim_drink(context, img)

        print(f"[LuckySprint] 完成，共 {self._round + 1} 轮")
        return True

    # ── 动作执行 ──

    def _execute_action(self, context: Context, image, action: str):
        if action == ACTION_RUN:
            _find_and_click(context, "Find_RunBtn", image)
            return

        find_btn, use_btn = ITEM_NODES[action]

        # 点道具
        if not _find_and_click(context, find_btn, image):
            print(f"[LuckySprint] 未找到道具按钮，改普通奔跑")
            _find_and_click(context, "Find_RunBtn", image)
            return

        time.sleep(0.3)
        img2 = _screencap(context)

        if _check_visible(context, use_btn, img2):
            print(f"[LuckySprint] 道具已激活 → 奔跑")
        else:
            print(f"[LuckySprint] 道具未激活(已耗尽) → 普通奔跑")

        _find_and_click(context, "Find_RunBtn", img2)

    # ── 结果处理 ──

    def _handle_result(self, context: Context):
        """等待前进结果（奖励弹窗 / 摔倒结算），最多等 3 秒。"""
        for _ in range(10):
            if context.tasker.stopping:
                return
            time.sleep(0.3)
            img = _screencap(context)

            if _check_visible(context, "Find_RewardResult", img):
                print("[LuckySprint] 奖励弹窗 → 关闭")
                _find_and_click(context, "Find_RewardClose", img)
                return

            if _check_visible(context, "Find_Settlement", img):
                print("[LuckySprint] 摔倒结算 → 重置 0m")
                _find_and_click(context, "Find_SettlementOK", img)
                self._distance = 0
                return

    # ── 饮料 ──

    def _claim_drink(self, context: Context, image):
        text = _ocr_text(context, "OCR_DrinkAvailable", image)
        if not re.search(r'\d', text):
            return

        print("[LuckySprint] 领取饮料")
        if _find_and_click(context, "Find_DrinkClaim", image):
            time.sleep(0.5)
            img2 = _screencap(context)
            if _check_visible(context, "Find_RewardResult", img2):
                _find_and_click(context, "Find_RewardClose", img2)

    def _read_drinks(self, context: Context, image) -> int | None:
        """读取剩余饮料数。格式: 1/xxx → 返回 xxx。OCR 失败返回 None。"""
        text = _ocr_text(context, "OCR_DrinkCount", image)
        print(f"[LuckySprint] OCR_DrinkCount 原始文本: '{text}'")
        # 期望格式: "1/99"
        if "/" in text:
            parts = text.split("/")
            if len(parts) >= 2:
                nums = re.findall(r'\d+', parts[1])
                if nums:
                    return int(nums[0])
        # 兜底: 至少要有两位数才采信（避免把单个"0"当作结果）
        nums = re.findall(r'\d+', text)
        if len(nums) >= 2:
            return int(nums[-1])  # 取最后一个数字（剩余数）
        # OCR 不可靠，返回 None 跳过本轮终止检查
        return None

    # ── Lv5 首通 ──

    def _check_first_pass(self, context: Context) -> bool:
        """Lv5 首通检测：True = 未领(需首通模式)  False = 已领。只执行一次。"""
        print("[LuckySprint] Lv5 首通检测...")
        img = _screencap(context)

        if not _find_and_click(context, "Find_InfoBtn", img):
            return True  # 保守：没找到按钮就当需要首通

        time.sleep(0.5)
        img2 = _screencap(context)
        if not _find_and_click(context, "Find_FirstRewardDetail", img2):
            self._close_detail_popup(context)
            return True

        time.sleep(0.5)
        img3 = _screencap(context)
        is_done = _check_visible(context, "Find_300mFirstPassDone", img3)
        self._close_detail_popup(context)
        return not is_done

    def _close_detail_popup(self, context: Context):
        """点击 ROI 区域关闭弹窗，然后等待按钮消失确认退出。"""
        # 在 ROI 内随机点击关闭
        roi = [31, 919, 283, 131]
        cx = roi[0] + roi[2] // 2
        cy = roi[1] + roi[3] // 2
        context.tasker.controller.post_click(cx, cy).wait()

        # 等待按钮消失
        for _ in range(6):
            time.sleep(0.3)
            img = _screencap(context)
            if not _check_visible(context, "Find_FirstRewardDetail", img):
                print("[LuckySprint] 详情弹窗已关闭")
                return
        # 兜底再点一次
        context.tasker.controller.post_click(cx, cy).wait()
        time.sleep(0.3)


# ============================================================
# arena_core — 竞技场(NPC 对战)核心循环
# ============================================================

# NPC 列表页固定选位（ROI [459,265,461,141] 的中心），不识别直接点
ARENA_NPC_SLOT_X = 690
ARENA_NPC_SLOT_Y = 336
KEY_BACK = 4  # Android 返回键 keyevent


@AgentServer.custom_action("arena_core")
class ArenaCore(CustomAction):
    """
    竞技场 NPC 对战主循环。

    前提：已在 NPC 对战列表页（由 arena.json 导航到达）。
    流程（每轮）：
      等 NPC 对战页就绪(npc 切换按钮 + 挑战按钮双信号) →
      固定点选 NPC → 点确定挑战 → 处理弹窗（购买旗帜/装备提示）→
      走战斗分支：
        有扫荡次数 → 主按钮是"扫荡键" → 点击秒结算；
        扫荡次数用尽(每日 10 次) → 主按钮变成"战斗开始键" →
          点击进入真实战斗 → 局内图标确认在战场 →
          点一次"开始自动战斗"(AI 托管,相当于扫荡) → 等战斗结束结算。
      分支内各阶段异常(挑战未生效/超时) → 快速重试,每场最多 3 次。
    终止：再次弹出购买窗（已购买过）→ 结束，系统返回键逐级回主页。

    Pipeline 参数 (custom_action_param):
        max_rounds (int): 轮次上限，默认 20（免费 5 + 购买 5 后留余量）
    """

    def __init__(self):
        super().__init__()
        self._bought = False   # 是否已用友情点购买过额外次数
        self._stop_flag = False  # 正常终止标记（第二次弹购买窗时置位）

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        param = _parse_param(argv.custom_action_param)
        max_rounds = param.get("max_rounds", 20)
        self._stop_flag = False
        self._bought = False
        done = 0  # 实际完成的场数

        for self._round in range(max_rounds):
            if context.tasker.stopping:
                print("[Arena] 收到停止信号，退出")
                break

            print(f"\n[Arena] === 第 {self._round + 1} 场 ===")

            # 每场最多尝试 3 次：点挑战后没进入战斗 → 快速回到列表页重试。
            # 判定信号是 npc 切换按钮(页面标志)+ 挑战按钮,避免"点快了"：
            # 列表未真正就绪时挑战无效,_one_fight 会在 ~1s 内发现
            # 还停在列表页并快速失败,不用等满 8s 超时。
            started = False
            for attempt in range(1, 4):
                if context.tasker.stopping:
                    break

                print(f"[Arena] 本场尝试 {attempt}/3：等待回到 NPC 对战页...")
                if not self._wait_list_ready(context, 8):
                    if self._stop_flag:
                        break  # 第二次购买窗 → 正常终止
                    print("[Arena] 未检测到 NPC 对战页（加载/过渡中），稍候重试")
                    time.sleep(0.5)
                    continue

                if not self._challenge(context):
                    print("[Arena] 发起挑战失败，重试本场")
                    continue

                # 点完挑战 → 完整战斗流程（扫荡 或 真实战斗+自动战斗）
                result = self._one_fight(context)
                if result == "ok":
                    started = True
                    done += 1
                    break
                if result == "stop" or context.tasker.stopping:
                    break  # 第二次购买窗/停止信号 → 正常终止
                # 'retry'：画面仍停在列表页（或已回列表）→ 直接下一尝试

            if not started:
                break  # 尝试耗尽或正常终止

        # 循环结束 → 返回主页
        self._back_to_home(context)
        print(f"[Arena] 完成，共进行 {done} 场")
        return True

    # ── 列表页就绪 / 发起挑战 ──

    def _wait_list_ready(self, context: Context, timeout_s: float) -> bool:
        """等 NPC 对战列表页就绪。
        单看挑战按钮不可靠——按钮随页面先渲染,列表数据还在刷新时点它会无效。
        改用页面强标志 npc 切换按钮(只有 NPC 对战页有它)+ 挑战按钮双信号,
        连续 2 帧稳定 + 缓冲后才放行,保证点下去的时机不会太早。"""
        ok = 0
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if context.tasker.stopping:
                return False
            img = _screencap(context)
            # 上限弹窗兜底:列表页被挡无法就绪时 → 点取消直接结束
            if self._handle_limit_popup(context, img):
                return False
            if _check_visible(context, "Find_NpcSwitch", img) and \
                    _check_visible(context, "Find_ArenaConfirm", img):
                ok += 1
                if ok >= 2:  # 连续 2 帧 ≈ 1s,画面稳定不是动画瞬闪
                    time.sleep(0.5)  # 列表卡片就位缓冲
                    return True
            else:
                ok = 0
            time.sleep(0.5)
        return False

    def _challenge(self, context: Context) -> bool:
        """固定点选 NPC 槽位，再点确定挑战。返回 False 表示本场无法开始。"""
        img = _screencap(context)
        if not _check_visible(context, "Find_ArenaConfirm", img):
            return False

        print(f"[Arena] 固定点击 NPC 槽位 ({ARENA_NPC_SLOT_X}, {ARENA_NPC_SLOT_Y})")
        context.tasker.controller.post_click(ARENA_NPC_SLOT_X, ARENA_NPC_SLOT_Y).wait()
        time.sleep(0.5)

        # 点确定挑战（点击后可能触发购买窗/装备提示,由 _one_fight 处理）
        img = _screencap(context)
        if _find_and_click(context, "Find_ArenaConfirm", img):
            return True

        # 选中动画/列表仍在加载 → 等待重试
        for _ in range(6):  # ~3 秒
            if context.tasker.stopping:
                return False
            time.sleep(0.5)
            img = _screencap(context)
            if _find_and_click(context, "Find_ArenaConfirm", img):
                return True
        print("[Arena] 挑战按钮迟迟不可用，本场结束")
        return False

    # ── 弹窗处理 + 进入战斗页 ──

    def _handle_limit_popup(self, context: Context, img) -> bool:
        """购买次数上限弹窗处理（样式与可购买弹窗不同,需独立识别）。
        命中 → 点取消键回到 NPC 列表页 → 置终止标记。返回 True = 已处理并应结束。"""
        if not _check_visible(context, "Find_BuyLimitFlag", img):
            return False
        print("[Arena] 购买次数已达上限 → 点取消,结束挑战")
        _find_and_click(context, "Find_BuyCancelBtn", img)
        self._stop_flag = True
        time.sleep(0.8)
        return True

    def _handle_buy_popup(self, context: Context) -> bool:
        """处理购买旗帜弹窗。返回 False = 应结束任务。
        弹窗有两种状态,以"购买次数上限"提示图判断还能不能买：
          - 上限提示可见 → 友情点购买次数已用完 → 点取消键回到
            NPC 列表页 → 结束（挑战次数 + 购买次数都耗尽,任务完成）
          - 无上限提示 → 点购买键用友情点买一次额外次数（+5）
        """
        img = _screencap(context)

        # 购买次数已达上限 → 点取消,回列表页后结束任务
        if self._handle_limit_popup(context, img):
            return False

        # 兜底保险：没显示上限提示但本会话已买过（理论上不会同时出现）
        if self._bought:
            print("[Arena] 额外次数已购买过,再次弹购买窗 → 点取消结束")
            _find_and_click(context, "Find_BuyCancelBtn", img)
            self._stop_flag = True
            time.sleep(0.8)
            return False

        clicked = _find_and_click(context, "Find_BuyFlagBtn", img)
        if not clicked:
            # 兜底：尝试通用确认按钮
            _find_and_click(context, "Find_EquipTipConfirm", img)
        self._bought = True
        print("[Arena] 友情点购买额外挑战次数 → 进入战斗")
        time.sleep(0.8)
        return True

    def _one_fight(self, context: Context) -> str:
        """点完确定挑战后的完整战斗流程。返回：
          'ok'    本场完成（扫荡结算 或 真实战斗自动打完）
          'retry' 挑战未生效/画面异常,应回到列表页重新点（主循环接手）
          'stop'  第二次购买窗/停止信号 → 终止全部

        点挑战后可能出现的画面：
          - 弹窗：购买旗帜（挑战次数用尽）/ 装备提示（每日首次）
          - 准备页主按钮：有扫荡次数 → 扫荡键(点后秒结算)；
            无扫荡次数(每日 10 次用尽) → "战斗开始"键 → 进真实战斗
        弹窗全排除仍能看到 npc 切换按钮 = 挑战点击没生效、
        画面还停在 NPC 列表页 → 连续 3 帧确认后快速返回 'retry',
        主循环重新点 NPC,不等满超时——"点快了"时的快速自救路径。
        """
        on_list = 0  # 连续观测到"停在列表页"的帧数
        for _ in range(32):  # 32 × 0.25s ≈ 8s
            if context.tasker.stopping:
                return "stop"
            img = _screencap(context)

            # 购买次数上限弹窗（样式不同需独立识别,优先级最高）
            if self._handle_limit_popup(context, img):
                return "stop"

            # 购买旗帜弹窗（扫荡/真实战斗前都可能弹）
            if _check_visible(context, "Find_BuyFlagPopup", img):
                if not self._handle_buy_popup(context):
                    return "stop"
                on_list = 0
                continue

            # 装备提示弹窗（每日首次）
            if _check_visible(context, "Find_EquipTipPopup", img):
                print("[Arena] 装备提示弹窗 → 确认")
                _find_and_click(context, "Find_EquipTipConfirm", img)
                on_list = 0
                time.sleep(0.5)
                continue

            # 扫荡键在 → 扫荡路径（秒结算）
            if _check_visible(context, "Find_SweepBtn", img):
                return self._fight_sweep(context)

            # 战斗开始键在（扫荡次数用尽）→ 真实战斗路径
            if _check_visible(context, "Find_BattleStartBtn", img):
                print("[Arena] 扫荡次数用尽 → 点战斗开始,进真实战斗")
                if not _find_and_click(context, "Find_BattleStartBtn", img):
                    continue  # 按钮动画帧没点上 → 下一帧再试
                return self._fight_real(context)

            # 无弹窗无主按钮仍见切换钮 → 挑战未生效,还停在列表页
            if _check_visible(context, "Find_NpcSwitch", img):
                on_list += 1
                if on_list >= 3:  # 连续 ~0.75s,过滤弹窗关闭等动画帧
                    print("[Arena] 挑战未生效仍停在列表页,快速重试")
                    return "retry"
            else:
                on_list = 0

            time.sleep(0.25)
        print("[Arena] 点挑战后 ~8s 未出现主按钮/弹窗,重试本场")
        return "retry"

    # ── 扫荡路径 / 真实战斗路径 ──

    def _fight_sweep(self, context: Context) -> str:
        """扫荡路径：点扫荡键 → 等结算弹窗 → 关闭（回列表由下一轮把关）。"""
        print("[Arena] 扫荡作战")
        img = _screencap(context)
        if not _find_and_click(context, "Find_SweepBtn", img):
            for _ in range(20):  # ~10s 等待按钮可点
                if context.tasker.stopping:
                    return "stop"
                time.sleep(0.5)
                img = _screencap(context)
                if _find_and_click(context, "Find_SweepBtn", img):
                    break
            else:
                print("[Arena] 找不到扫荡按钮,重试本场")
                return "retry"

        # 等扫荡结算弹窗并关闭
        for _ in range(60):  # 60 × 0.3s ≈ 30s（扫荡通常瞬时完成）
            if context.tasker.stopping:
                return "stop"
            time.sleep(0.3)
            img = _screencap(context)
            if _check_visible(context, "Find_SweepResult", img):
                time.sleep(0.3)
                _find_and_click(context, "Find_SweepConfirm", img)
                print("[Arena] 扫荡结算关闭")
                time.sleep(1.5)  # 列表刷新缓冲（下一场仍由 _wait_list_ready 把关）
                return "ok"
        print("[Arena] 等待扫荡结算超时,重试本场")
        return "retry"

    def _fight_real(self, context: Context) -> str:
        """真实战斗路径（战斗开始键已点击,扫荡次数用尽时）：
        等战场加载（局内图标） → 点一次"开始自动战斗"(AI 托管≈扫荡)
        → 战斗进行中等结束信号 → 处理结算 → 回列表。"""
        # ── 阶段1: 等战场(局内图标),途中弹窗一并处理 ≤25s ──
        in_field = False
        for _ in range(50):  # 50 × 0.5s = 25s
            if context.tasker.stopping:
                return "stop"
            img = _screencap(context)

            # 上限弹窗独立识别(优先级最高,样式与可购买弹窗不同)
            if self._handle_limit_popup(context, img):
                return "stop"

            if _check_visible(context, "Find_BuyFlagPopup", img):
                if not self._handle_buy_popup(context):
                    return "stop"
                continue
            if _check_visible(context, "Find_EquipTipPopup", img):
                print("[Arena] 装备提示弹窗 → 确认")
                _find_and_click(context, "Find_EquipTipConfirm", img)
                time.sleep(0.5)
                continue
            if self._on_list_page(context, img):
                print("[Arena] 未进战场已回列表页")
                return "ok"
            if _check_visible(context, "Find_InBattleIcon", img):
                in_field = True
                break
            time.sleep(0.5)
        if not in_field:
            print("[Arena] 点战斗开始后 25s 未进入战场,重试本场")
            return "retry"

        # ── 阶段2: 点"开始自动战斗"(AI 托管),按钮动画中可重试 ~6s ──
        for _ in range(6):
            if context.tasker.stopping:
                return "stop"
            img = _screencap(context)
            if _find_and_click(context, "Find_AutoBattleBtn", img):
                print("[Arena] 已点击开始自动战斗")
                break
            time.sleep(1.0)
        else:
            print("[Arena] 未找到开始自动战斗按钮,仍按战斗流程继续等待")

        # ── 阶段3: 战斗进行中(慢轮询),等结束信号 ≤240s ──
        # 结束信号：自动战斗完成确认图标 / 局内图标消失 / 直接回列表
        icon_lost = 0
        fight_deadline = time.time() + 240
        while time.time() < fight_deadline:
            if context.tasker.stopping:
                return "stop"
            time.sleep(1.5)
            img = _screencap(context)

            # 上限弹窗独立识别(战斗结束后若挑战额度也尽可能再弹)
            if self._handle_limit_popup(context, img):
                return "stop"

            if _check_visible(context, "Find_BuyFlagPopup", img):
                if not self._handle_buy_popup(context):
                    return "stop"
                continue
            if self._on_list_page(context, img):
                print("[Arena] 战斗结束,已回列表页")
                return "ok"
            if _check_visible(context, "Find_AutoDoneConfirm", img):
                print("[Arena] 自动战斗完成,出现确认图标")
                break
            if _check_visible(context, "Find_InBattleIcon", img):
                icon_lost = 0
            else:
                icon_lost += 1
                if icon_lost >= 2:  # 局内图标消失 ~3s → 战斗结束流程启动
                    print("[Arena] 局内图标消失,等待结算")
                    break
        else:
            print("[Arena] 等待战斗结束超时(240s),重试本场")
            return "retry"

        # ── 阶段4: 结算段(高频轮询):点确认图标/结算弹窗 → 等回列表 ≤60s ──
        settle_deadline = time.time() + 60
        while time.time() < settle_deadline:
            if context.tasker.stopping:
                return "stop"
            time.sleep(0.5)
            img = _screencap(context)

            if self._on_list_page(context, img):
                print("[Arena] 结算完毕,已回列表页")
                return "ok"
            # 上限弹窗独立识别
            if self._handle_limit_popup(context, img):
                return "stop"
            if _check_visible(context, "Find_BuyFlagPopup", img):
                if not self._handle_buy_popup(context):
                    return "stop"
                continue
            if _check_visible(context, "Find_EquipTipPopup", img):
                print("[Arena] 装备提示弹窗 → 确认")
                _find_and_click(context, "Find_EquipTipConfirm", img)
                continue
            # 自动战斗完成确认:真实战斗结算(与扫荡弹窗二选一,优先级更高)
            if _check_visible(context, "Find_AutoDoneConfirm", img):
                time.sleep(0.3)
                _find_and_click(context, "Find_AutoDoneConfirm", img)
                print("[Arena] 自动战斗确认已点击,返回列表页")
                time.sleep(1.5)
                continue
            # 扫荡同款结算弹窗(兜底兼容)
            if _check_visible(context, "Find_SweepResult", img):
                time.sleep(0.3)
                _find_and_click(context, "Find_SweepConfirm", img)
                print("[Arena] 战斗结算关闭")
                time.sleep(1.5)
        print("[Arena] 结算 60s 未见回列表,重试本场")
        return "retry"

    def _on_list_page(self, context: Context, img) -> bool:
        """NPC 对战列表页判定:切换按钮 + 挑战按钮双信号（见 _wait_list_ready）。"""
        return _check_visible(context, "Find_NpcSwitch", img) and \
            _check_visible(context, "Find_ArenaConfirm", img)

    # ── 返回主页 ──

    def _back_to_home(self, context: Context):
        """按一次返回键 → 轮询检测主页最多 ~2.5s，确认已回主页才停；
        未回主页才按下一次，避免在主页多按弹出"退出游戏"确认框。"""
        print("[Arena] 逐级返回主页...")
        img = _screencap(context)
        if _check_visible(context, "HomeFlag", img):
            return

        for i in range(6):
            if context.tasker.stopping:
                return
            context.tasker.controller.post_press_key(KEY_BACK).wait()
            # 按键后轮询：页面动画/加载需要时间，多截几次确认是否已回主页
            back_home = False
            for _ in range(6):  # 6 × 0.4s ≈ 2.5s
                if context.tasker.stopping:
                    return
                time.sleep(0.4)
                img = _screencap(context)
                if _check_visible(context, "HomeFlag", img):
                    back_home = True
                    break
            if back_home:
                print("[Arena] 已回到主页")
                return
            print(f"[Arena] 第 {i + 1} 次返回未到主页，继续")
        print("[Arena] 返回键按完仍未检测到主页，可能已停在游戏内某层界面")
