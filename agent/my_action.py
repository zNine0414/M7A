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
