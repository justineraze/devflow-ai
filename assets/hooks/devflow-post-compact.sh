#!/usr/bin/env bash
# devflow-post-compact.sh — re-inject devflow context after Claude Code compaction.
#
# Reads .devflow/state.json in the current working directory (the project root
# Claude Code is open on).  Outputs the active feature ID, current phase and a
# plan summary to stdout so Claude Code injects it back into context.
#
# Must NEVER break Claude Code:
#   • Any error → exit 0 with empty stdout.
#   • set -euo pipefail only wraps our own logic; python failure falls through.
set -euo pipefail

STATE_FILE=".devflow/state.json"

# Nothing to do if the project hasn't been initialised with devflow.
if [[ ! -f "$STATE_FILE" ]]; then
    exit 0
fi

python3 - "$STATE_FILE" <<'PYEOF' || exit 0
import json
import sys
from pathlib import Path

try:
    from datetime import datetime
    from dateutil.parser import isoparse
except ImportError:
    # dateutil not available; fall back to lexical comparison
    isoparse = None

state_path = Path(sys.argv[1])

try:
    state = json.loads(state_path.read_text())
except Exception:
    sys.exit(0)

features = state.get("features", {})
if not features:
    sys.exit(0)

TERMINAL = {"done", "blocked"}

# Pick the active (non-terminal) feature with the most recent updated_at.
active = [
    f for f in features.values()
    if f.get("status", "").lower() not in TERMINAL
]

if not active:
    sys.exit(0)

# Extract timestamps for comparison, using isoparse if available for robustness.
# Contract: updated_at is ISO 8601 UTC (e.g., "2026-04-15T12:34:56.123456+00:00").
def get_timestamp(feature_dict):
    ts_str = feature_dict.get("updated_at", "")
    if not ts_str:
        return datetime.min if isoparse else ""
    if isoparse:
        try:
            return isoparse(ts_str)
        except (ValueError, TypeError):
            return datetime.min
    return ts_str

feature = max(active, key=get_timestamp)

feat_id = feature.get("id", "?")
description = feature.get("description", "")
# current_phase_name is a Pydantic computed_field on Feature — present in any
# state.json written by devflow ≥ 0.1.1. Older states fall back to "?".
phase_name = feature.get("current_phase_name") or "?"
phase_status = feature.get("status", "?")

print("# devflow context (post-compact)")
print(f"Active feature: {feat_id} — {description}")
print(f"Current phase: {phase_name} ({phase_status})")

# Append first 40 lines of planning.md if it exists.
plan_file = state_path.parent / feat_id / "planning.md"
if plan_file.exists():
    lines = plan_file.read_text().splitlines()[:40]
    print("Plan summary:")
    for line in lines:
        print(f"  {line}")
PYEOF
