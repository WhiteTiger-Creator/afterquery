#!/usr/bin/env bash
# Sealed verifier entry point.
#
# Harden the environment first: a submission that leaves a sitecustomize on the path, an
# LD_PRELOAD in place, or a watcher rewriting files under /app could otherwise influence
# the measurement after the fact.
set -uo pipefail

export REWARD_DIR="${REWARD_DIR:-/logs/verifier}"
mkdir -p "$REWARD_DIR"

unset PYTHONPATH PYTHONSTARTUP PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1

# Stop anything the submission may have left running that could still touch /app while
# the archive is being measured.
for name in watchmedo inotifywait entr fswatch; do
    pkill -f "$name" 2>/dev/null || true
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$HERE/compute_reward.py"
status=$?

# A verifier that produces no score is itself a failure; make that explicit rather than
# leaving the run without a reward file.
if [ ! -s "$REWARD_DIR/reward.txt" ]; then
    echo "compute_reward.py produced no reward — recording zero" >&2
    printf '0.000000\n' > "$REWARD_DIR/reward.txt"
    printf '{"reward": 0.0, "status": "failed", "reason": "verifier produced no report"}\n' \
        > "$REWARD_DIR/reward.json"
fi

echo "reward: $(cat "$REWARD_DIR/reward.txt")"
exit "$status"
