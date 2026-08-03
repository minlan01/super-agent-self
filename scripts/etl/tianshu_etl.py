#!/usr/bin/env python3
"""ETL: tianshu tasks.json -> control-core Task schema (P3.6/P3.12).

Transforms the 7 tianshu tasks from scripts/etl/tianshu-tasks-source.json
into control-core Task records, mapping the tianshu 7-state workflow to
the control-core TaskStatus enum.

Field mapping (spec §G-16):
  tianshu.id          -> Task.id (preserve original ID)
  tianshu.title       -> Task.goal
  tianshu.state       -> Task.status (mapped, see _STATE_MAP)
  tianshu.org         -> Task metadata (agent assignment)
  tianshu.output      -> Task result
  tianshu.flow_log    -> TaskStep records (one per flow entry)
  tianshu.createdAt   -> Task.created_at
  tianshu.updatedAt   -> Task.updated_at

Usage:
    python scripts/etl/tianshu_etl.py [--dry-run] [--output <path>]

Output: JSON file with Task records ready for import, or dry-run summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# tianshu 7-state -> control-core TaskStatus mapping.
_STATE_MAP: dict[str, str] = {
    "Todo": "pending",
    "InProgress": "in_progress",
    "Blocked": "pending",       # tianshu Blocked -> control-core pending (needs attention)
    "Review": "in_review",      # maps to a review-related status
    "Done": "completed",
    "Cancelled": "cancelled",
    "Failed": "failed",
}


def transform_task(tianshu_task: dict[str, Any]) -> dict[str, Any]:
    """Transform a single tianshu task to control-core Task schema."""
    # Map state (case-insensitive, handle variations).
    raw_state = str(tianshu_task.get("state", "Todo")).strip()
    status = _STATE_MAP.get(raw_state, "pending")

    # Transform flow_log entries into steps.
    flow_log = tianshu_task.get("flow_log", [])
    steps = []
    for i, entry in enumerate(flow_log):
        if isinstance(entry, dict):
            steps.append({
                "step_order": i + 1,
                "tool_name": entry.get("agent", entry.get("action", "unknown")),
                "args": entry.get("input", {}),
                "result": entry.get("output", ""),
                "status": "completed" if entry.get("status") == "ok" else "pending",
            })
        elif isinstance(entry, str):
            steps.append({
                "step_order": i + 1,
                "tool_name": "flow",
                "args": {"log": entry},
                "status": "completed",
            })

    # Build the control-core Task record.
    task = {
        "id": tianshu_task.get("id", str(uuid4())),
        "goal": tianshu_task.get("title", "Untitled"),
        "status": status,
        "edition": "enterprise",
        "user_id": "etl-migration",
        "tenant_id": "default",
        "created_at": tianshu_task.get("createdAt"),
        "updated_at": tianshu_task.get("updatedAt"),
        "metadata": {
            "source": "tianshu",
            "original_org": tianshu_task.get("org"),
            "original_priority": tianshu_task.get("priority"),
            "original_output": tianshu_task.get("output"),
            "original_now": tianshu_task.get("now"),
            "original_block": tianshu_task.get("block"),
            "scheduler": tianshu_task.get("_scheduler", {}),
        },
        "steps": steps,
    }
    return task


def run_etl(
    source_path: str = "scripts/etl/tianshu-tasks-source.json",
    output_path: str = "scripts/etl/tianshu-tasks-transformed.json",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the ETL transform. Returns summary dict."""
    source = Path(source_path)
    if not source.exists():
        print(f"ERROR: source file not found: {source}", file=sys.stderr)
        return {"error": "source not found", "path": str(source)}

    with open(source, encoding="utf-8") as f:
        tianshu_tasks = json.load(f)

    if not isinstance(tianshu_tasks, list):
        print("ERROR: expected a list of tasks", file=sys.stderr)
        return {"error": "invalid format"}

    transformed = []
    state_counts: dict[str, int] = {}
    total_steps = 0

    for tt in tianshu_tasks:
        task = transform_task(tt)
        transformed.append(task)
        state_counts[task["status"]] = state_counts.get(task["status"], 0) + 1
        total_steps += len(task["steps"])

    if dry_run:
        print(f"\n=== DRY RUN SUMMARY ===")
        print(f"Source: {source}")
        print(f"Tasks: {len(transformed)}")
        print(f"Total steps: {total_steps}")
        print(f"Status distribution: {state_counts}")
        print(f"\nSample task (first):")
        print(json.dumps(transformed[0], indent=2, ensure_ascii=False, default=str)[:1000])
        return {
            "tasks": len(transformed),
            "steps": total_steps,
            "states": state_counts,
            "dry_run": True,
        }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(transformed, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n=== ETL COMPLETE ===")
    print(f"Source: {source}")
    print(f"Output: {output}")
    print(f"Tasks transformed: {len(transformed)}")
    print(f"Total steps: {total_steps}")
    print(f"Status distribution: {state_counts}")
    return {
        "tasks": len(transformed),
        "steps": total_steps,
        "states": state_counts,
        "output": str(output),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="tianshu tasks.json ETL")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--source", default="scripts/etl/tianshu-tasks-source.json")
    parser.add_argument("--output", default="scripts/etl/tianshu-tasks-transformed.json")
    args = parser.parse_args()

    result = run_etl(args.source, args.output, args.dry_run)
    if "error" in result:
        sys.exit(1)
