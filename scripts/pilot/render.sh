#!/bin/sh
set -eu
mkdir -p /tmp/home
python3 /opt/renderer/offline.py
cd /tmp/project
/opt/renderer/node_modules/.bin/hyperframes render . \
  --output /output/video.mp4 --fps 30 --quality standard --format mp4 \
  --workers 1 --no-browser-gpu
# Cap the final video's duration even if JavaScript changes declared metadata.
ffmpeg -v error -y -i /output/video.mp4 -t 30 -c copy -movflags +faststart /output/capped.mp4
mv /output/capped.mp4 /output/video.mp4
ffmpeg -v error -y -i /output/video.mp4 -frames:v 1 -vf 'scale=640:-2' -q:v 3 /output/thumbnail.jpg
