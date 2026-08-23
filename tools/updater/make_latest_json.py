#!/usr/bin/env python3
"""Generate the signed Tauri updater manifest (latest.json) — P4 blocker #5.

Signs the built installer with the Tauri updater private key (minisign)
and emits the `latest.json` consumed by the app's updater plugin.

Usage (release machine only):
    export TAURI_SIGNING_PRIVATE_KEY=$(cat ~/.tauri/zcode-updater.key)
    export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='...'

    python tools/updater/make_latest_json.py \
        --version 1.0.0 \
        --notes "First stable release" \
        --platforms windows-x86_64 \
        --url-base https://cdn.example.com/zcode \
        --installer "apps/desktop/src-tauri/target/release/bundle/nsis/Zcode Desktop Agent_1.0.0_x64-setup.exe"

The updater .sig for the *updater bundle* is produced automatically by
`tauri build` when TAURI_SIGNING_PRIVATE_KEY is set; this tool signs the
standalone installer for the manual-download path and emits latest.json.
Both artifacts are uploaded to the CDN together.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def minisign_sign(filepath: Path) -> str:
    """Sign with the Tauri CLI; returns base64 signature string."""
    result = subprocess.run(
        ["npx", "@tauri-apps/cli", "signer", "sign", "-f", str(filepath)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"signer failed:\n{result.stdout}\n{result.stderr}")
    # tauri signer sign prints the signature to stdout
    sig_line = next(
        (ln for ln in result.stdout.splitlines() if ln and not ln.startswith(" ")),
        "",
    )
    return base64.b64encode(sig_line.encode()).decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="e.g. 1.0.0")
    parser.add_argument("--notes", default="")
    parser.add_argument("--pub-date", default=None, help="ISO8601; default now")
    parser.add_argument("--url-base", required=True, help="CDN base URL, no trailing slash")
    parser.add_argument("--platforms", default="windows-x86_64",
                        help="comma-separated: windows-x86_64,linux-x86_64,darwin-x86_64,darwin-aarch64")
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("latest.json"))
    args = parser.parse_args()

    if not os.environ.get("TAURI_SIGNING_PRIVATE_KEY"):
        sys.exit("TAURI_SIGNING_PRIVATE_KEY not set — refusing to emit unsigned manifest (fail closed)")

    if not args.installer.exists():
        sys.exit(f"installer not found: {args.installer}")

    from datetime import datetime, timezone
    pub_date = args.pub_date or datetime.now(timezone.utc).isoformat()

    platforms = {}
    for plat in args.platforms.split(","):
        plat = plat.strip()
        signature = minisign_sign(args.installer)
        url_name = args.installer.name.replace(" ", "%20")
        platforms[plat] = {
            "signature": signature,
            "url": f"{args.url_base}/{url_name}",
        }

    manifest = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": pub_date,
        "platforms": platforms,
    }

    args.out.write_text(json.dumps(manifest, indent=2))
    print(f"wrote {args.out}")
    print(f"  installer sha256: {sha256(args.installer)}")
    print("  channels: publish to CDN, then update docs/releases gate record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
