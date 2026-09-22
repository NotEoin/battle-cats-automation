#!/usr/bin/env bash
# Wait for the iPhone to come back, then roll the goal out.
# The run itself only ever presses "Use all" on the storage screen; nothing
# else there is touched, so no unit can be exchanged away by accident.
set -u
cd "$(dirname "$0")/.."
echo "waiting for the device..."
for _ in $(seq 1 720); do
    if lsusb | grep -qi apple; then
        echo "device seen at $(date +%H:%M:%S), settling"
        sleep 4
        if .venv/bin/python -m bcgacha.cli probe >/dev/null 2>&1; then
            echo "probe ok, starting the goal run"
            exec .venv/bin/python -u -m bcgacha.cli goal \
                --platinum 7 --prefer 2026-09-21_979 --speed 0.85
        fi
        echo "device present but not ready yet"
    fi
    sleep 5
done
echo "device never appeared"
