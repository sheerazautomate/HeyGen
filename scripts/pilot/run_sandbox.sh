#!/usr/bin/env bash
# Personal pro tool: full throttle HyperFrames rendering
# Input: build/request/index.html, manifest.json, variables.json
# Output: build/media/{video.mp4,video.webm,video.mov,thumbnail.jpg}
set -euo pipefail
mkdir -p build/raw
chmod 777 build/raw

cleanup() { docker rm -f pilot-sandbox >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Full throttle: allow network for external assets (fonts, images, audio, video)
# Increased resources: 4 CPUs, 8GB memory, 512MB shm, 2GB file size limit
# Timeout 15 minutes for up to 10 min videos at high quality

echo "Starting pro renderer with network access, 4 CPUs, 8GB RAM..."

# Prepare mounts
MOUNTS=(
  --mount type=bind,src="$PWD/build/request/index.html",dst=/input/index.html,readonly
  --mount type=bind,src="$PWD/build/raw",dst=/output
)

if [ -f "$PWD/build/request/manifest.json" ]; then
  MOUNTS+=(--mount type=bind,src="$PWD/build/request/manifest.json",dst=/input/manifest.json,readonly)
fi

if [ -f "$PWD/build/request/variables.json" ]; then
  MOUNTS+=(--mount type=bind,src="$PWD/build/request/variables.json",dst=/input/variables.json,readonly)
fi

# Story mode music: synthesized WAV or a downloaded custom track + mixing metadata
if [ -f "$PWD/build/request/music.wav" ]; then
  MOUNTS+=(--mount type=bind,src="$PWD/build/request/music.wav",dst=/input/music.wav,readonly)
fi
for f in "$PWD"/build/request/music_src.*; do
  if [ -f "$f" ]; then
    MOUNTS+=(--mount type=bind,src="$f",dst=/input/"$(basename "$f")",readonly)
  fi
done
if [ -f "$PWD/build/request/music.json" ]; then
  MOUNTS+=(--mount type=bind,src="$PWD/build/request/music.json",dst=/input/music.json,readonly)
fi

timeout --kill-after=30s 900s docker run --name pilot-sandbox \
  --log-driver none \
  --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user 1000:1000 \
  --cpus 4 --memory 8g --memory-swap 8g --pids-limit 1024 \
  --ulimit fsize=2147483648:2147483648 --shm-size 512m \
  --tmpfs /tmp:rw,nosuid,size=3072m,mode=1777 \
  "${MOUNTS[@]}" \
  pilot-renderer > /dev/null 2>&1 || {
    echo '::error::Pro render failed or exceeded time limit (15 min). Check composition for errors.'
    # Try to show last logs for debugging if available
    docker logs pilot-sandbox 2>&1 | tail -n 100 || true
    exit 1
  }

cleanup
python3 scripts/pilot/check_outputs.py
echo "Pro render completed successfully"
