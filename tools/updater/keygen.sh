#!/usr/bin/env bash
# Tauri updater key management (P4 blocker #5)
#
# The PRIVATE key never enters the repository — it lives only on the
# release-signing machine (and a backed-up offline copy).
#
# Usage:
#   ./tools/updater/keygen.sh                     # generate a new keypair
#   ./tools/updater/keygen.sh --verify <pubkey>   # sanity-check a pubkey string

set -euo pipefail

if [[ "${1:-}" == "--verify" && -n "${2:-}" ]]; then
  if [[ "$2" =~ ^dW50cnkg|^[A-Za-z0-9+/]{100,}=*$ ]]; then
    echo "pubkey looks like a valid minisign/Tauri public key"
    exit 0
  fi
  echo "ERROR: not a valid Tauri pubkey" >&2
  exit 1
fi

echo "Generating Tauri updater keypair..."
echo "PRIVATE key password (empty = none; REQUIRED to re-sign updates):"
npx @tauri-apps/cli signer generate -w ~/.tauri/zcode-updater.key

echo ""
echo "=========================== NEXT STEPS ==========================="
echo "1. The PUBLIC key was printed above (.pub). Put it in"
echo "   apps/desktop/src-tauri/tauri.conf.json -> plugins.updater.pubkey"
echo "2. Back up the PRIVATE key offline (password manager / USB)."
echo "   Lost private key = all future updates rejected = forced reinstall."
echo "3. On the release machine, export for builds:"
echo "   export TAURI_SIGNING_PRIVATE_KEY=\$(cat ~/.tauri/zcode-updater.key)"
echo "   export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='...'"
echo "4. Set plugins.updater.active=true and endpoints in tauri.conf.json."
echo "=================================================================="
