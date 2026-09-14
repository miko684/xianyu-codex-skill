import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xianyu_dispatch import (  # noqa: E402
    ROUTE_API,
    ROUTE_HYBRID,
    ROUTE_PHONECONTROL,
    DispatchError,
    XianyuDispatcher,
    classify_task,
)


class DispatchTests(unittest.TestCase):
    def test_structured_item_detail_prefers_api(self):
        decision = classify_task({"operation": "get_item_info", "item_id": "123"})
        self.assertEqual(decision.route, ROUTE_API)
        self.assertEqual(decision.api_operation, "get_item_info")

    def test_visual_confirmation_uses_hybrid_route(self):
        decision = classify_task(
            {"operation": "publish_listing", "requires_visual_confirmation": True}
        )
        self.assertEqual(decision.route, ROUTE_HYBRID)
        self.assertEqual(decision.api_operation, "public")
        self.assertEqual(decision.phone_tool, "android_get_screen_state")

    def test_ui_only_task_uses_phonecontrol(self):
        decision = classify_task(
            {"operation": "screen_verify", "requires_phonecontrol": True}
        )
        self.assertEqual(decision.route, ROUTE_PHONECONTROL)
        self.assertEqual(decision.phone_tool, "android_get_screen_state")

    def test_force_route_rejects_missing_api_capability(self):
        with self.assertRaises(DispatchError):
            classify_task({"operation": "screen_verify", "force_route": "api"})

    def test_decision_has_no_credentials(self):
        decision = classify_task(
            {"operation": "get_item_info", "item_id": "123", "token": "secret"}
        )
        self.assertNotIn("secret", json.dumps(decision.to_dict()))

    def test_group_touch_uses_p2p_capable_android_tool(self):
        decision = classify_task({"operation": "group_broadcast_touch"})
        self.assertEqual(decision.route, ROUTE_PHONECONTROL)
        self.assertEqual(decision.phone_tool, "android_group_broadcast_touch")

    def test_hybrid_executes_api_then_phone_stage(self):
        calls = []

        class FakeApi:
            def call(self, operation, task):
                calls.append(("api", operation))
                return {"item_id": "123"}

        class FakePhone:
            def call_tool(self, tool_name, arguments):
                calls.append(("phone", tool_name, dict(arguments)))
                return {"verified": True}

        result = XianyuDispatcher(FakeApi(), FakePhone()).execute(
            {
                "operation": "publish",
                "requires_visual_confirmation": True,
                "phone_stage": {
                    "tool": "android_get_screen_state",
                    "arguments": {"include_screenshot": True},
                },
            },
            confirm_write=True,
        )
        self.assertEqual(calls[0], ("api", "public"))
        self.assertEqual(calls[1], ("phone", "android_get_screen_state", {"include_screenshot": True}))
        self.assertEqual(result["route"], ROUTE_HYBRID)


if __name__ == "__main__":
    unittest.main()
