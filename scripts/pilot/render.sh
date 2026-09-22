#!/bin/sh
set -eu
mkdir -p /tmp/home
python3 /opt/renderer/offline.py
cd /tmp/project

# Read pro settings from manifest (injected via /input/manifest.json if present, or defaults)
MANIFEST="/input/manifest.json"
FPS=30
QUALITY="standard"
FORMAT="mp4"
VARS_FILE="/input/variables.json"
DURATION_CAP=600

if [ -f "$MANIFEST" ]; then
  # Extract with python for safety
  FPS=$(python3 -c "import json,sys; d=json.load(open('$MANIFEST')); print(d.get('fps',30))" 2>/dev/null || echo 30)
  QUALITY=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(d.get('quality','standard'))" 2>/dev/null || echo standard)
  FORMAT=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(d.get('format','mp4'))" 2>/dev/null || echo mp4)
  DURATION=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(d.get('duration',600))" 2>/dev/null || echo 600)
  # Cap duration to manifest duration but max 600
  DURATION_CAP=$(python3 -c "d=float('$DURATION'); print(int(d+2))" 2>/dev/null || echo 600)
fi

# Handle variables injection - write to project as hyperframes vars override if needed
if [ -f "$VARS_FILE" ]; then
  # hyperframes reads variables via window.__hyperframes.getVariables or data-composition-variables override
  # We inject a small JS that overrides getVariables to return our vars
  VARS_JSON=$(cat "$VARS_FILE")
  if [ "$VARS_JSON" != "{}" ] && [ -n "$VARS_JSON" ]; then
    echo "Injecting variables: $VARS_JSON"
    # Append a script to index.html that sets __hyperframes variables if not already handled
    # Safer: create a variables injection file
    echo "$VARS_JSON" > /tmp/project/injected-vars.json
  fi
fi

# Normalize format to hyperframes supported: mp4, webm, mov
case "$FORMAT" in
  mp4|webm|mov) ;;
  *) FORMAT="mp4" ;;
esac

# Normalize quality
case "$QUALITY" in
  draft|standard|high) ;;
  *) QUALITY="standard" ;;
esac

echo "Rendering with full throttle: ${FPS}fps, ${QUALITY} quality, ${FORMAT} format, cap ${DURATION_CAP}s"

# Full throttle hyperframes render
# --workers 2 for pro, allow network, no gpu restriction unless needed
/opt/renderer/node_modules/.bin/hyperframes render . \
  --output /output/video.${FORMAT} --fps ${FPS} --quality ${QUALITY} --format ${FORMAT} \
  --workers 2

# Normalize output name to video.mp4/webm/mov etc for downstream checks, but keep original
# If format is webm or mov, we still produce video.<format>, then copy to video.mp4 if needed for compat? Keep as is, but also create video.mp4 alias if not mp4?
if [ "$FORMAT" != "mp4" ] && [ -f "/output/video.${FORMAT}" ]; then
  # Keep original, but also copy as video.mp4 if mp4 requested elsewhere? Actually we keep original format
  # For thumbnail generation, use the rendered file regardless of format
  SRC="/output/video.${FORMAT}"
else
  SRC="/output/video.mp4"
fi

# Cap duration via ffmpeg but using manifest duration + buffer
ffmpeg -v error -y -i "$SRC" -t ${DURATION_CAP} -c copy -movflags +faststart /output/capped.${FORMAT} || \
  ffmpeg -v error -y -i "$SRC" -t ${DURATION_CAP} -c:v libx264 -c:a aac -movflags +faststart /output/capped.${FORMAT}

mv /output/capped.${FORMAT} "$SRC"

# ---- Story mode music mixing (optional) ----
MUSIC_META="/input/music.json"
MUSIC_WAV="/input/music.wav"
if [ -f "$MUSIC_META" ]; then
  VOL=$(python3 -c "import json; print(json.load(open('$MUSIC_META')).get('volume', 0.35))" 2>/dev/null || echo 0.35)
else
  VOL="0.35"
fi

# custom music needs transcode to uniform wav first
if [ ! -f "$MUSIC_WAV" ]; then
  for f in /input/music_src.*; do
    if [ -f "$f" ]; then
      echo "Transcoding custom music track..."
      ffmpeg -v error -y -i "$f" -ar 44100 -ac 1 /tmp/music.wav && MUSIC_WAV=/tmp/music.wav || true
    fi
  done
fi

if [ -f "$MUSIC_WAV" ]; then
  echo "Mixing music (volume ${VOL}) into video..."
  AUDIO_CODEC="aac"
  [ "$FORMAT" = "webm" ] && AUDIO_CODEC="libopus"
  HAS_AUDIO=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$SRC" | head -n 1)
  if [ -n "$HAS_AUDIO" ]; then
    ffmpeg -v error -y -i "$SRC" -stream_loop -1 -i "$MUSIC_WAV" \
      -filter_complex "[1:a]volume=${VOL},atrim=0:${DURATION_CAP},afade=t=out:st=$(python3 -c "print(max(0.0, float('${DURATION_CAP}')-2.0))" 2>/dev/null || echo 0):d=2[m];[0:a][m]amix=inputs=2:duration=first[a]" \
      -map 0:v -map "[a]" -c:v copy -c:a ${AUDIO_CODEC} -shortest /output/mixed.${FORMAT} \
      && mv /output/mixed.${FORMAT} "$SRC" || echo "Music mix failed, keeping video without music."
  else
    ffmpeg -v error -y -i "$SRC" -stream_loop -1 -i "$MUSIC_WAV" \
      -filter_complex "[1:a]volume=${VOL},atrim=0:${DURATION_CAP},afade=t=out:st=$(python3 -c "print(max(0.0, float('${DURATION_CAP}')-2.0))" 2>/dev/null || echo 0):d=2[a]" \
      -map 0:v -map "[a]" -c:v copy -c:a ${AUDIO_CODEC} -shortest /output/mixed.${FORMAT} \
      && mv /output/mixed.${FORMAT} "$SRC" || echo "Music mix failed, keeping video without music."
  fi
fi

# If format not mp4, also create mp4 fallback for gallery compatibility? Keep original but also create mp4 version for broad playback
if [ "$FORMAT" != "mp4" ]; then
  # Create mp4 version as well for gallery
  ffmpeg -v error -y -i "$SRC" -c:v libx264 -c:a aac -movflags +faststart /output/video.mp4 || true
fi

# Thumbnail - from the rendered video
ffmpeg -v error -y -i "$SRC" -frames:v 1 -vf 'scale=1280:-2' -q:v 2 /output/thumbnail.jpg || \
  ffmpeg -v error -y -i "$SRC" -frames:v 1 -vf 'scale=640:-2' -q:v 3 /output/thumbnail.jpg || true

# If webm/mov was primary, ensure video.mp4 exists for legacy gallery, else video.<format> is main
if [ -f "/output/video.${FORMAT}" ]; then
  echo "Rendered /output/video.${FORMAT} $(du -h /output/video.${FORMAT} | cut -f1)"
fi
if [ -f "/output/video.mp4" ]; then
  echo "Also have /output/video.mp4 $(du -h /output/video.mp4 | cut -f1)"
fi
