#!/usr/bin/env python3
"""Tianshu dispatch — safe reference implementation (P0.6 G-11 fix).

替代 agent_tianshu/scripts/ 里的 4 处 subprocess.run(shell=True) 调用：
  - server.py:84
  - auto_dispatch.py:107
  - tianshu_agent_worker.py:119
  - scheduler_scan.py:91

那些原实现把 user-controlled message 拼进 shell 字符串，构成命令注入风险
（spec v1.1 G-11）。本模块用 control-core REST API 提交子任务，完全不
调 shell，message 作为 JSON body 字段传输，天然无注入。

P3 阶段 LangGraph StateGraph 的 dispatch 节点应调用本模块。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

CONTROL_API_URL = os.environ.get(
    "CONTROL_API_URL", "http://127.0.0.1:8000/api/v1"
)
CONTROL_API_TOKEN = os.environ.get("CONTROL_API_TOKEN", "")


async def dispatch_to_agent(
    agent_id: str,
    message: str,
    *,
    timeout: int = 300,
    workflow_id: str = "tianshu-default",
) -> dict[str, Any]:
    """通过 control-core REST 提交子任务，替代 openclaw CLI subprocess。

    参数化：message 作为 JSON 字段传输，不经 shell 解释器。
    即使 message 含 ``; rm -rf /`` 或 ``$(evil)`` 也只被视为字面字符串。

    Args:
        agent_id: tianshu 角色名（receiver/planning/review/dispatch/doc/eng/qa/aggregation）
        message: 任务描述（用户输入，不可信）
        timeout: HTTP 超时秒数
        workflow_id: 关联的 WorkflowDefinition id

    Returns:
        control-core /tasks 的响应（含 task_id）

    Raises:
        httpx.HTTPStatusError: 非 2xx 响应
        httpx.TimeoutException: 超时
    """
    headers = {"Content-Type": "application/json"}
    if CONTROL_API_TOKEN:
        headers["Authorization"] = f"Bearer {CONTROL_API_TOKEN}"

    payload = {
        "goal": message,           # 字面字符串，无 shell 解释
        "agent_profile": agent_id,
        "workflow_id": workflow_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{CONTROL_API_URL}/tasks",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# 安全性自检（可被 CI 调用）
# ---------------------------------------------------------------------------

def _self_check_no_shell() -> bool:
    """断言本模块不使用任何 shell 解释器。CI 可调用此函数。"""
    import inspect
    src = inspect.getsource(dispatch_to_agent)
    forbidden = ("shell=True", "os.system", "subprocess.Popen", "os.popen")
    for pat in forbidden:
        if pat in src:
            return False
    return True


if __name__ == "__main__":
    print(f"_self_check_no_shell: {'PASS' if _self_check_no_shell() else 'FAIL'}")
