"""Enterprise Demo — one-click E2E: create task → plan → policy → execute → Word."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.agent_core.orchestrator import Orchestrator
from packages.db.session import Base, SessionLocal, engine
from packages.executor.executor_service import ExecutorService
from packages.executor.tool_runner import ToolRunner
from packages.executor.tools.browser_tools import BrowserOpen
from packages.executor.tools.file_tools import FileWriteDocx, FileWriteMarkdown
from packages.llm_gateway.provider_router import ProviderRouter
from packages.planner.planner_service import PlannerService
from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.tool_registry import ToolRegistry


async def run_demo():
    print("=" * 60)
    print("  Enterprise Agent Demo — Web Scrape → Word Report")
    print("=" * 60)

    # Initialize DB
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    print("\n[1/5] Database initialized")

    # Setup services
    tool_registry = ToolRegistry()
    token_issuer = TokenIssuer(secret_key="demo-secret-key")
    policy_engine = PolicyEngine(tool_registry, token_issuer)
    provider_router = ProviderRouter()
    planner = PlannerService(provider_router, tool_registry)

    tool_runner = ToolRunner(token_issuer)
    tool_runner.register(FileWriteDocx())
    tool_runner.register(FileWriteMarkdown())

    executor = ExecutorService(tool_runner, policy_engine)
    orchestrator = Orchestrator(planner, executor)
    print("[2/5] Services initialized (LLM: mock mode)")

    # Create and run task
    goal = "Open example.com, extract text content, and write a Word report"
    print(f"[3/5] Creating task: {goal}")

    from packages.executor.tools.base import ExecutionContext
    ctx = ExecutionContext(
        task_id="demo",
        step_id="demo",
        edition="enterprise",
        workspace_root=str(Path(__file__).resolve().parent.parent / "workspace"),
    )

    result = await orchestrator.run(db=db, goal=goal, context=ctx)
    print(f"[4/5] Task completed: {result['status']}")
    print(f"       Task ID: {result['task_id']}")
    print(f"       Success: {result['success']}")

    if result.get("results"):
        print(f"\n[5/5] Step results:")
        for r in result["results"]:
            status = "OK" if r["status"] == "completed" else "FAIL"
            print(f"       Step {r['step']}: {r['tool']} — {status}")
            if r.get("output"):
                print(f"         Output: {str(r['output'])[:100]}")

    # Check output files
    outputs_dir = Path(__file__).resolve().parent.parent / "workspace" / "outputs"
    if outputs_dir.exists():
        files = list(outputs_dir.glob("*"))
        if files:
            print(f"\nGenerated files in {outputs_dir}:")
            for f in files:
                print(f"  - {f.name} ({f.stat().st_size} bytes)")

    db.close()
    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_demo())
