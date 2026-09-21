FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium ffmpeg python3 ca-certificates fonts-liberation fonts-dejavu-core fonts-noto-color-emoji fonts-noto fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/renderer
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# Full throttle: allow network, larger shm, modern fonts, no telemetry
ENV HYPERFRAMES_BROWSER_PATH=/usr/bin/chromium \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    HYPERFRAMES_NO_TELEMETRY=1 CONTAINER=true HOME=/tmp/home \
    NODE_OPTIONS=--max-old-space-size=4096

COPY offline.py render.sh ./

# Make render.sh executable
RUN chmod +x render.sh

USER node
ENTRYPOINT ["/bin/sh", "/opt/renderer/render.sh"]
