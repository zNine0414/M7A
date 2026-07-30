import json
import time

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context


@AgentServer.custom_action("my_action_111")
class MyCustomAction(CustomAction):

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:

        print("my_action_111 is running!")

        return True


@AgentServer.custom_action("click_screen_center")
class ClickScreenCenter(CustomAction):
    """
    点击屏幕正中间位置的自定义动作。

    用于游戏登录流程中，在识别到"同意协议"勾选框后，
    点击屏幕中央的登录/进入按钮，完成登录。

    参数 (custom_action_param, JSON 字符串):
        - offset_x (int): X 轴偏移量，默认 0。正值向右偏移。
        - offset_y (int): Y 轴偏移量，默认 0。正值向下偏移。
        - post_delay (int): 点击后等待时间，单位毫秒，默认 1000。

    坐标基准:
        以 display_short_side = 1080 为基准分辨率，
        16:9 竖屏 (1080x1920) 的正中心为 (540, 960)。
        MaaFramework 会根据实际设备分辨率自动缩放。
    """

    # 基准分辨率下的默认中心坐标
    DEFAULT_CENTER_X = 540
    DEFAULT_CENTER_Y = 960

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        # 解析自定义参数
        param = self._parse_param(argv.custom_action_param)

        offset_x = param.get("offset_x", 0)
        offset_y = param.get("offset_y", 0)
        post_delay = param.get("post_delay", 1000)

        # 计算实际点击坐标
        target_x = self.DEFAULT_CENTER_X + offset_x
        target_y = self.DEFAULT_CENTER_Y + offset_y

        print(
            f"[ClickScreenCenter] 点击屏幕中心: ({target_x}, {target_y}), "
            f"偏移: ({offset_x}, {offset_y}), 点击后延迟: {post_delay}ms"
        )

        # 执行点击
        click_job = context.tasker.controller.post_click(target_x, target_y)
        click_result = click_job.wait()

        if not click_result:
            print("[ClickScreenCenter] 点击执行失败!")
            return False

        # 点击后等待，确保界面响应
        if post_delay > 0:
            time.sleep(post_delay / 1000.0)

        print("[ClickScreenCenter] 点击完成")
        return True

    @staticmethod
    def _parse_param(custom_action_param) -> dict:
        """解析 custom_action_param，兼容 str / dict / None 多种形式。"""
        if custom_action_param is None:
            return {}
        if isinstance(custom_action_param, str):
            try:
                return json.loads(custom_action_param)
            except json.JSONDecodeError:
                print(
                    f"[ClickScreenCenter] 参数解析失败，使用默认值: "
                    f"{custom_action_param}"
                )
                return {}
        if isinstance(custom_action_param, dict):
            return custom_action_param
        return {}
