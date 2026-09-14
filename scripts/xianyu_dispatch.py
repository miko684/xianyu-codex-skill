"""Route Xianyu work to the cheapest safe execution backend.

The skill is the orchestration layer.  XianYuApis and Android MCP remain
separate runtimes and are connected through small adapters.  Planning is
always available without credentials; execution requires an explicit flag.
"""

from __future__ import annotations

import argparse
import importlib
import itertools
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib import error as urlerror
from urllib import request as urlrequest


ROUTE_API = "api"
ROUTE_PHONECONTROL = "phonecontrol"
ROUTE_HYBRID = "hybrid"

API_OPERATIONS = {
    "get_item_info": "get_item_info",
    "item_detail": "get_item_info",
    "refresh_token": "refresh_token",
    "upload_media": "upload_media",
    "get_public_channel": "get_public_channel",
    "get_default_location": "get_default_location",
    "publish_listing": "public",
    "publish": "public",
}

PHONE_OPERATIONS = {
    "screen_state": "android_get_screen_state",
    "screen_verify": "android_get_screen_state",
    "find_node": "android_find_nodes",
    "tap": "android_tap",
    "type_text": "android_type_append_text",
    "open_app": "android_open_app",
    "batch_touch": "android_batch_touch",
    "group_touch": "android_group_broadcast_touch",
    "group_broadcast_touch": "android_group_broadcast_touch",
}

WRITE_OPERATIONS = {
    "upload_media",
    "publish_listing",
    "publish",
    "tap",
    "type_text",
    "batch_touch",
    "group_touch",
    "group_broadcast_touch",
}

DEFAULT_VISUAL_TOOL = "android_get_screen_state"


class DispatchError(RuntimeError):
    """Raised for a route or adapter error without exposing credentials."""


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    api_operation: Optional[str] = None
    phone_tool: Optional[str] = None
    requires_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def classify_task(task: Mapping[str, Any]) -> RouteDecision:
    """Choose a route from explicit task intent and capability requirements.

    API is preferred for structured operations.  UI is selected when the
    operation is inherently visual or the caller explicitly requests a
    phone action.  A task that has an API capability plus a required visual
    confirmation becomes hybrid.
    """

    operation = str(task.get("operation") or task.get("intent") or "").strip().lower()
    forced = str(task.get("force_route") or "").strip().lower()
    if forced not in {"", ROUTE_API, ROUTE_PHONECONTROL, ROUTE_HYBRID}:
        raise DispatchError("force_route must be api, phonecontrol, or hybrid")

    api_operation = API_OPERATIONS.get(operation)
    phone_stage = task.get("phone_stage")
    phone_stage_tool = phone_stage.get("tool") if isinstance(phone_stage, Mapping) else None
    phone_tool = str(
        task.get("phone_tool") or phone_stage_tool or PHONE_OPERATIONS.get(operation) or ""
    ).strip() or None
    ui_required = any(
        _truthy(task.get(key))
        for key in (
            "requires_phonecontrol",
            "requires_visual_confirmation",
            "captcha_or_manual_login",
            "ui_only",
        )
    )
    if forced == ROUTE_API:
        if api_operation is None:
            raise DispatchError("the requested operation has no configured XianYuApis capability")
        return RouteDecision(
            ROUTE_API,
            "explicit API route",
            api_operation=api_operation,
            requires_confirmation=operation in WRITE_OPERATIONS,
        )
    if forced == ROUTE_PHONECONTROL:
        if phone_tool is None:
            raise DispatchError("phonecontrol route requires phone_tool or a known UI operation")
        return RouteDecision(
            ROUTE_PHONECONTROL,
            "explicit phonecontrol route",
            phone_tool=phone_tool,
            requires_confirmation=operation in WRITE_OPERATIONS,
        )
    if forced == ROUTE_HYBRID:
        if api_operation is None or phone_tool is None:
            raise DispatchError("hybrid route requires both an API operation and a phone tool")
        return RouteDecision(
            ROUTE_HYBRID,
            "explicit hybrid route",
            api_operation=api_operation,
            phone_tool=phone_tool,
            requires_confirmation=operation in WRITE_OPERATIONS,
        )

    if api_operation and ui_required:
        if phone_tool is None:
            phone_tool = DEFAULT_VISUAL_TOOL
        return RouteDecision(
            ROUTE_HYBRID,
            "use the API for structured work, then phonecontrol for the required visual step",
            api_operation=api_operation,
            phone_tool=phone_tool,
            requires_confirmation=operation in WRITE_OPERATIONS,
        )
    if api_operation:
        return RouteDecision(
            ROUTE_API,
            "structured Xianyu operation is available through XianYuApis",
            api_operation=api_operation,
            requires_confirmation=operation in WRITE_OPERATIONS,
        )
    if phone_tool:
        return RouteDecision(
            ROUTE_PHONECONTROL,
            "operation requires Android UI or no API capability is configured",
            phone_tool=phone_tool,
            requires_confirmation=operation in WRITE_OPERATIONS,
        )
    raise DispatchError("cannot classify task; provide operation or force_route")


class XianyuApiAdapter:
    """Thin adapter over the existing XianYuApis Python project."""

    def __init__(self, project_root: Path, cookies: Mapping[str, str], device_id: str) -> None:
        self.project_root = project_root.expanduser().resolve()
        self.cookies = dict(cookies)
        self.device_id = device_id
        if not self.project_root.is_dir():
            raise DispatchError("XIANYU_APIS_ROOT is not a directory")
        root_text = str(self.project_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        try:
            module = importlib.import_module("goofish_apis")
            self.client = module.XianyuApis(self.cookies, self.device_id)
        except Exception as exc:  # pragma: no cover - dependency errors are environment-specific
            raise DispatchError("could not load XianYuApis runtime") from exc

    @classmethod
    def from_environment(cls) -> "XianyuApiAdapter":
        root = os.environ.get("XIANYU_APIS_ROOT", "").strip()
        cookies_file = os.environ.get("XIANYU_COOKIES_FILE", "").strip()
        device_id = os.environ.get("XIANYU_DEVICE_ID", "").strip()
        if not root or not cookies_file or not device_id:
            raise DispatchError("set XIANYU_APIS_ROOT, XIANYU_COOKIES_FILE, and XIANYU_DEVICE_ID")
        try:
            cookies = json.loads(Path(cookies_file).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DispatchError("could not read XIANYU_COOKIES_FILE") from exc
        if not isinstance(cookies, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in cookies.items()):
            raise DispatchError("XIANYU_COOKIES_FILE must contain a JSON object of string cookies")
        return cls(Path(root), cookies, device_id)

    def call(self, operation: str, task: Mapping[str, Any]) -> Any:
        if operation == "get_item_info":
            item_id = str(task.get("item_id") or "").strip()
            if not item_id:
                raise DispatchError("item_id is required")
            return self.client.get_item_info(item_id)
        if operation == "refresh_token":
            return self.client.refresh_token()
        if operation == "upload_media":
            media_path = str(task.get("media_path") or "").strip()
            if not media_path:
                raise DispatchError("media_path is required")
            return self.client.upload_media(media_path)
        if operation == "get_public_channel":
            return self.client.get_public_channel(str(task.get("title") or ""), task.get("images_info") or [])
        if operation == "get_default_location":
            return self.client.get_default_location()
        if operation == "public":
            return self.client.public(
                list(task.get("images") or []),
                str(task.get("description") or task.get("title") or ""),
                task.get("price"),
                task.get("delivery") or {"choice": "无需邮寄", "can_self_pickup": False},
            )
        raise DispatchError("unsupported XianYuApis operation")


class PhoneControlMcpAdapter:
    """Minimal JSON-RPC client for the Android Remote Control MCP server."""

    def __init__(self, endpoint: str, token: str, timeout: float = 20.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._ids = itertools.count(1)
        if not self.endpoint or not self.token:
            raise DispatchError("phonecontrol endpoint and token are required")

    @classmethod
    def from_environment(cls) -> "PhoneControlMcpAdapter":
        endpoint = os.environ.get("PHONECONTROL_MCP_ENDPOINT", "").strip()
        token = os.environ.get("PHONECONTROL_MCP_TOKEN", "").strip()
        if not endpoint or not token:
            raise DispatchError("set PHONECONTROL_MCP_ENDPOINT and PHONECONTROL_MCP_TOKEN")
        return cls(endpoint, token)

    def list_tools(self) -> List[str]:
        """Discover the tools exposed by the configured MCP endpoint.

        This is intentionally opt-in: route planning must remain fast and
        offline, while callers that need runtime verification can check the
        actual Android MCP build before executing a task.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/list",
            "params": {},
        }
        result = self._request(payload)
        tools = result.get("tools") if isinstance(result, Mapping) else None
        if not isinstance(tools, list):
            raise DispatchError("phonecontrol MCP returned an invalid tools/list response")
        names = []
        for item in tools:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                names.append(item["name"])
        return names

    def _request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urlrequest.Request(
            self.endpoint + "/mcp",
            data=body,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except (OSError, urlerror.URLError, urlerror.HTTPError) as exc:
            raise DispatchError("phonecontrol MCP request failed") from exc
        try:
            result = json.loads(raw)
        except ValueError:
            # Some MCP servers answer with a single SSE data frame even when
            # the client asked for JSON. Do not log the raw body because it
            # may contain tool output or sensitive device data.
            data_lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
            if len(data_lines) != 1:
                raise DispatchError("phonecontrol MCP returned a non-JSON response")
            try:
                result = json.loads(data_lines[0])
            except ValueError as exc:
                raise DispatchError("phonecontrol MCP returned an invalid response") from exc
        if not isinstance(result, Mapping):
            raise DispatchError("phonecontrol MCP returned an invalid response")
        if "error" in result:
            raise DispatchError("phonecontrol MCP returned an error")
        inner = result.get("result", result)
        if not isinstance(inner, Mapping):
            raise DispatchError("phonecontrol MCP returned an invalid result")
        return inner

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": dict(arguments)},
        }
        return self._request(payload)


class XianyuDispatcher:
    """Plan and optionally execute one task using configured adapters."""

    def __init__(self, api: Optional[XianyuApiAdapter] = None, phone: Optional[PhoneControlMcpAdapter] = None) -> None:
        self.api = api
        self.phone = phone

    def plan(self, task: Mapping[str, Any]) -> RouteDecision:
        decision = classify_task(task)
        if decision.route == ROUTE_API and self.api is None:
            return RouteDecision(
                decision.route,
                decision.reason + "; configure XianYuApis before execution",
                decision.api_operation,
                decision.phone_tool,
                decision.requires_confirmation,
            )
        if decision.route == ROUTE_PHONECONTROL and self.phone is None:
            return RouteDecision(
                decision.route,
                decision.reason + "; configure phonecontrol before execution",
                decision.api_operation,
                decision.phone_tool,
                decision.requires_confirmation,
            )
        return decision

    def execute(self, task: Mapping[str, Any], confirm_write: bool = False) -> Any:
        decision = self.plan(task)
        operation = str(task.get("operation") or task.get("intent") or "").strip().lower()
        if decision.requires_confirmation and not confirm_write:
            raise DispatchError("write operation requires --confirm-write")
        if decision.route == ROUTE_API:
            if self.api is None or decision.api_operation is None:
                raise DispatchError("XianYuApis adapter is not configured")
            return self.api.call(decision.api_operation, task)
        if decision.route == ROUTE_PHONECONTROL:
            if self.phone is None or decision.phone_tool is None:
                raise DispatchError("phonecontrol adapter is not configured")
            arguments = task.get("arguments") or {}
            if not isinstance(arguments, Mapping):
                raise DispatchError("phonecontrol arguments must be an object")
            return self.phone.call_tool(decision.phone_tool, arguments)
        if self.api is None or self.phone is None or decision.api_operation is None or decision.phone_tool is None:
            raise DispatchError("hybrid execution requires both configured adapters")
        api_result = self.api.call(decision.api_operation, task)
        phone_stage = task.get("phone_stage")
        phone_arguments: Any = task.get("phone_arguments") or {}
        if isinstance(phone_stage, Mapping):
            phone_arguments = phone_stage.get("arguments") or phone_arguments
        if not isinstance(phone_arguments, Mapping):
            raise DispatchError("phonecontrol arguments must be an object")
        phone_result = self.phone.call_tool(decision.phone_tool, phone_arguments)
        return {"route": ROUTE_HYBRID, "api": api_result, "phonecontrol": phone_result}


def _load_task(args: argparse.Namespace) -> Dict[str, Any]:
    if args.task_file:
        raw = Path(args.task_file).expanduser().read_text(encoding="utf-8")
    elif args.task_json:
        raw = args.task_json
    else:
        raise DispatchError("provide --task-file or --task-json")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise DispatchError("task must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute an Xianyu API/phonecontrol task")
    parser.add_argument("--task-file")
    parser.add_argument("--task-json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()
    try:
        task = _load_task(args)
        api = XianyuApiAdapter.from_environment() if os.environ.get("XIANYU_APIS_ROOT") else None
        phone = PhoneControlMcpAdapter.from_environment() if os.environ.get("PHONECONTROL_MCP_ENDPOINT") else None
        dispatcher = XianyuDispatcher(api, phone)
        if args.execute:
            output = dispatcher.execute(task, confirm_write=args.confirm_write)
        else:
            output = dispatcher.plan(task).to_dict()
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return 0
    except (DispatchError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
