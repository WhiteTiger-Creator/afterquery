#!/usr/bin/env bash
# Sealed verifier entry point.
set -uo pipefail

export REWARD_DIR="${REWARD_DIR:-/logs/verifier}"
mkdir -p "$REWARD_DIR"

unset PYTHONPATH PYTHONSTARTUP PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1

# Nothing left running may compete for the processor while timings are taken.
for name in watchmedo inotifywait entr fswatch; do
    pkill -f "$name" 2>/dev/null || true
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$HERE/compute_reward.py"
status=$?

if [ ! -s "$REWARD_DIR/reward.txt" ]; then
    echo "compute_reward.py produced no reward — recording zero" >&2
    printf '0.000000\n' > "$REWARD_DIR/reward.txt"
    printf '{"reward": 0.0, "status": "failed", "reason": "verifier produced no report"}\n' \
        > "$REWARD_DIR/reward.json"
fi

echo "reward: $(cat "$REWARD_DIR/reward.txt")"
exit "$status"
