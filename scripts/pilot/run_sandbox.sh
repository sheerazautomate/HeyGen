#!/usr/bin/env bash
# Input: build/request/index.html. Output: build/media/{video.mp4,thumbnail.jpg}.
# The image must be built from trusted tooling BEFORE calling this script.
set -euo pipefail
mkdir -p build/raw
chmod 777 build/raw
cleanup() { docker rm -f pilot-sandbox >/dev/null 2>&1 || true; }
trap cleanup EXIT
# No token/runner environment, socket, home, or repository is mounted/passed.
# Discard hostile stdout: it can contain Actions workflow commands or a log flood.
timeout --kill-after=10s 720s docker run --name pilot-sandbox \
  --log-driver none --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user 1000:1000 \
  --cpus 2 --memory 4g --memory-swap 4g --pids-limit 512 \
  --ulimit fsize=268435456:268435456 --shm-size 256m \
  --tmpfs /tmp:rw,nosuid,size=1536m,mode=1777 \
  --mount type=bind,src="$PWD/build/request/index.html",dst=/input/index.html,readonly \
  --mount type=bind,src="$PWD/build/raw",dst=/output \
  pilot-renderer > /dev/null 2>&1 || {
    echo '::error::The isolated render failed or exceeded its time limit.'
    exit 1
  }
cleanup
python3 scripts/pilot/check_outputs.py
