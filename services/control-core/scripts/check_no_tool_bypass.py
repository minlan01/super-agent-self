#!/usr/bin/env python3
"""检测 routes/personal_shell 中「直接 import 工具类」的旁路。

import-linter 的 forbidden 契约会把 dependencies→orchestrator→tools/base
这种合法的间接链也判违规（因为 _auto_import 把所有工具都 import 一遍
触发 @register）。本脚本用 AST 精确检测「函数内 import 具体工具类文件」
的直连旁路，规避传递依赖误报。

用法：
    python scripts/check_no_tool_bypass.py
退出码：0 = 通过（无新增旁路），1 = 发现违规

P0.4：已登记的 4 处历史旁路在 KNOWN_DEBT 里，作为豁免。
P0.5 修复后逐条从 KNOWN_DEBT 删除，最终本脚本零豁免。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 检查范围：routes 全部 + personal_shell/executor.py
SCAN_TARGETS = [
    REPO / "apps/api_server/routes",
    REPO / "apps/personal_shell/executor.py",
]

# 禁止直接 import 的模块前缀
FORBIDDEN_PREFIXES = (
    "packages.executor.tools.",
    "packages.executor.tools",
)

# P0.5 TODO: 已登记的历史旁路（文件:行号 → 原因）。修复后逐条删除。
# 格式："相对路径:lineno"
KNOWN_DEBT = {
    "apps/api_server/routes/desktop.py:103",   # WindowManagerTool() 直 new
    "apps/api_server/routes/desktop.py:122",   # DesktopScreenshot() 直 new
    "apps/api_server/routes/tasks.py:131",     # ExecutionContext 直接 import
    "apps/personal_shell/executor.py:31",      # CLI 简化路径
}


def _forbidden_modules_in_node(node: ast.AST) -> list[tuple[int, str]]:
    """从 AST 节点提取所有 import 语句里指向禁止模块的 (lineno, module)。"""
    hits: list[tuple[int, str]] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            for alias in sub.names:
                if alias.name.startswith(FORBIDDEN_PREFIXES):
                    hits.append((sub.lineno, alias.name))
        elif isinstance(sub, ast.ImportFrom):
            mod = sub.module or ""
            if mod.startswith(FORBIDDEN_PREFIXES):
                hits.append((sub.lineno, mod))
    return hits


def check_file(path: Path, repo_root: Path) -> list[tuple[int, str, str]]:
    """返回 [(lineno, module, rel_path), ...] 的违规清单。"""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree = ast.parse(src, filename=str(path))
    rel = str(path.relative_to(repo_root))
    violations: list[tuple[int, str, str]] = []
    for lineno, mod in _forbidden_modules_in_node(tree):
        debt_key = f"{rel}:{lineno}"
        if debt_key in KNOWN_DEBT:
            continue   # 已登记债务，P0.5 修复
        violations.append((lineno, mod, rel))
    return violations


def main() -> int:
    all_violations: list[tuple[int, str, str]] = []
    for target in SCAN_TARGETS:
        if target.is_file():
            all_violations.extend(check_file(target, REPO))
        elif target.is_dir():
            for py in target.rglob("*.py"):
                all_violations.extend(check_file(py, REPO))

    if not all_violations:
        print("✅ check_no_tool_bypass: PASS — 无新增 routes/shell 直连工具类旁路")
        print(f"   （已登记历史债务 {len(KNOWN_DEBT)} 处，待 P0.5 修复）")
        return 0

    print("❌ check_no_tool_bypass: FAIL — 发现未登记的旁路：\n")
    for lineno, mod, rel in all_violations:
        print(f"  {rel}:{lineno}  imports {mod}")
    print(
        "\n这是新增的旁路。修复方式：改走 ToolRunner / ToolGateway（P0.5），"
        "或在 setup.cfg / KNOWN_DEBT 登记为已知债务。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
