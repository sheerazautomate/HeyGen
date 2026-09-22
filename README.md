# HyperFrames Studio — Personal Pro (Full Throttle)

Private, unlimited version of the HyperFrames pilot — same interface, pro power. Built for personal projects with full HyperFrames capabilities.

**Original pilot was:** public, 24KB, 30s max, 1920px, 2/day, offline only, standard quality.
**Personal pro is:** private, 10MB, 10min, 4096px (4K), unlimited (1000/day soft), network enabled, high quality, 60fps, MP4/WebM/MOV, external assets, variables.

> **✦ NEW — Story mode:** paste a **repo link**, get a script written for you → [docs/STORY_MODE.md](docs/STORY_MODE.md)

## Story mode — repo link in, launch video out

Don't want to author HTML? **Story mode** writes the script for you:

1. **Open a story issue** from the studio ("Generate from a repo") or GitHub → *Generate a video from a repo link*. Paste any **public** repo URL. Pick tone, pace, length, aspect, music, quality, fps, format.
2. **Review the storyboard** posted back on the issue: scene-by-scene copy, palette extracted from your project's own styles, music choice, real commands/stats/features from your repo.
3. **Approve it**: reply `/render` (or steer: `/render tone:playful length:45 music:lofi`, `/render s2.heading:"New headline"`). Full-throttle render → private release with the same quality/fps/format knobs.

- **Free-of-cost writing**: works with free-tier LLM providers (Groq/Gemini/Cerebras/OpenRouter — one secret, no billing), local Ollama, or the built-in **offline generator** (zero keys, never fails). GitHub Models was retired 2026-07-30; no provider is hardcoded.
- **No dead space**: full-bleed layered backgrounds, grid completeness rules (3/4/6 cards), per-slot character budgets, palette + contrast from the repo's own CSS.
- **Music**: synthesized per mood (royalty-free by construction) or your own `https://` track.
- **Local one-shot**: `python3 scripts/personal_render.py --story https://github.com/owner/repo --tone hype --fps 60`

Full guide: [docs/STORY_MODE.md](docs/STORY_MODE.md)

## What changed? (Pilot → Personal Pro)

| Feature | Pilot | Personal Pro |
|---------|-------|--------------|
| Visibility | Public releases | Private releases (repo private) |
| HTML limit | 24 KiB | 10 MiB |
| Duration | 30s | 600s (10 min) |
| Dimensions | 1920 per side, 2M pixels | 4096 per side, 16.7M pixels (4K) |
| FPS | 30 | 24/30/60 |
| Quality | standard | draft/standard/high |
| Format | MP4 only | MP4/WebM/MOV |
| Output size | 256 MiB | 2 GiB |
| Renderer | 2 CPUs, 4GB, no network, offline | 4 CPUs, 8GB, network ON, 15min timeout |
| External assets | Blocked | Allowed (images, fonts, audio, video, fetch) |
| Variables | Ignored | Full support via data-composition-variables + editor |
| Approval | approved_users list | private_mode: true (any user in private repo) |
| Quota | 2/day per user, 10/day global | 1000/day (effectively unlimited) |
| UI | Simple | Pro controls + live preview + variables editor |

## Quick start — Private GitHub mode (selected)

You chose **private GitHub repo** mode: keep Issue → Actions flow, but private and unlimited.

1. **Make repo private**: GitHub → Settings → Danger Zone → Change visibility → Private.
2. **Update `.github/pilot.json`**: Ensure `private_mode: true` and `approved_users` includes your username (or leave empty since private_mode skips check).
3. **Push to main**: Workflows must be on default branch.
4. **Enable Pages** (optional, private Pages needs Pro): Settings → Pages → GitHub Actions. Or run locally:
   ```bash
   npm run dev
   # Open http://localhost:4173
   ```
5. **Render**: Choose HTML → set quality/fps/format → edit variables → Prepare → Copy → Open GitHub form → Create Issue → Track.

Videos become private releases: `video-pilot-<issue>` with MP4/WebM/MOV + thumbnail. Only visible to repo collaborators.

## Local direct rendering (bonus)

Bypass GitHub for instant local renders:

```bash
# Build docker image (first time)
docker build -t pilot-renderer scripts/pilot

# High quality 60fps MP4
python3 scripts/personal_render.py examples/product-launch.html --quality high --fps 60 --format mp4

# With variable overrides
python3 scripts/personal_render.py examples/product-launch.html --vars '{"product":"MY BRAND","headline":"Full throttle"}' --quality high

# WebM with alpha
python3 scripts/personal_render.py examples/vertical-teaser.html --format webm --quality high --output ~/Videos/teaser-pro.webm
```

Or via npm:
```bash
npm run render:local -- examples/product-launch.html --quality high --fps 60
```

Outputs to `build/personal/` by default.

## Architecture — Pro

```
Local browser (private studio with preview + variables editor)
  → clipboard packet (now includes fps/quality/format/variables, version 2)
  → GitHub Issue form (private repo, private_mode skips approval)
  → admit job: validate 10MB/600s/4K/60fps/high/WebM/MOV + variables
  → render job: Docker with NETWORK, 4 CPUs, 8GB, 15min, offline.py injects variables
      → hyperframes render . --fps 60 --quality high --format webm --workers 2
      → ffmpeg cap to manifest duration
      → thumbnail 1280px
  → publish job: private release with all formats
  → Pages: track via API (needs auth for private repo) + download
```

Local mode skips GitHub entirely: same Docker, direct output.

## Files changed for personal pro

- `.github/pilot.json`: pro limits, private_mode, allow_external_assets, allow_network
- `site/core.mjs`: validate 4K/10min/10MB, encodePacket v2 with fps/quality/format/variables, extractVariables helper
- `site/app.js`: pro controls (quality/fps/format/resolution), live preview iframe, variables editor, private gallery handling
- `site/index.html`: pro hero, workflow strip, preview, variables card, private notices, enhanced FAQ
- `site/style.css`: pro-controls, preview-wrap, variables-card styles
- `site/config.js`: pro defaults
- `scripts/build_site.py`: preserve private_mode
- `scripts/pilot/model.py`: pro validation, version 2, private consent, no quota in private_mode, variables sanitization
- `scripts/pilot/admit.py`: skip approval in private_mode, store variables.json
- `scripts/pilot/offline.py`: allow external URLs (keep them), inject variables via window.__hyperframes.getVariables
- `scripts/pilot/render.sh`: read manifest for fps/quality/format, inject variables, network allowed, 600s cap, support webm/mov, high quality
- `scripts/pilot/Dockerfile`: fonts-noto, larger Node memory, pro labels
- `scripts/pilot/package.json`: renamed to personal-renderer, gsap 3.15.0
- `scripts/pilot/check_outputs.py`: allow webm/mov, 2GB, permissive validation
- `scripts/pilot/run_sandbox.sh`: 4 CPUs, 8GB, network enabled, 15min timeout, mount manifest/variables
- `scripts/pilot/publish.py`: private release notes with pro settings + variables
- `scripts/pilot/status.py`: pro messages
- `.github/workflows/pilot-render.yml`: renamed to personal pro, 30min timeout, 7 day artifacts
- `.github/ISSUE_TEMPLATE/render-video.yml`: private consent
- `tests/`: updated for pro limits
- `scripts/personal_render.py`: new local CLI

## Using HyperFrames full throttle

**External assets now work** (pilot blocked them):
```html
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@800&display=swap" rel="stylesheet">
<img src="https://example.com/image.jpg">
<audio src="https://example.com/music.mp3">
<video src="https://example.com/clip.mp4">
<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"></script>
```

**Variables** (one bundle, many videos):
```html
<html data-composition-variables='[{"id":"headline","label":"Headline","type":"string","default":"Hello"}]'>
<script>
  const vars = window.__hyperframes?.getVariables?.() || {};
  document.getElementById("title").textContent = vars.headline;
</script>
```

Studio auto-detects `data-composition-variables` and shows editor. Overrides injected at render time.

**Quality/FPS/Format**:
- Quality: draft (fast), standard (balanced), high (pro)
- FPS: 24 cinematic, 30 standard, 60 smooth
- Format: MP4 (widely supported), WebM (alpha transparent), MOV (ProRes for editing)
- Resolution: original (from composition), or override via composition width/height

## Security notes (private tool)

- Private repo = private releases, but still GitHub-hosted. Don't commit secrets in HTML.
- Renderer now has network access (required for external assets). Container still has no Docker socket, no credentials, read-only root, user 1000, pids-limit, fsize limit.
- For maximum isolation, run local renders on your own machine, not shared runner.
- No token in Pages — still uses GitHub Issue flow with `GITHUB_TOKEN` in trusted jobs only.

## Local dev

```bash
python3 scripts/build_site.py
python3 -m http.server 4173 --bind 0.0.0.0 --directory build/site
# Open http://localhost:4173

npm ci
npm test
npx playwright install --with-deps chromium
npm run test:browser
```

Docker smoke test (pro):
```bash
docker build -t pilot-renderer scripts/pilot
mkdir -p build/request
cp examples/product-launch.html build/request/index.html
echo '{"fps":60,"quality":"high","format":"mp4","duration":16,"width":1920,"height":1080,"variables":{}}' > build/request/manifest.json
echo '{}' > build/request/variables.json
bash scripts/pilot/run_sandbox.sh
# Outputs: build/media/video.mp4 + thumbnail.jpg (or webm/mov)
```

## Make repo private checklist

- [ ] Settings → General → Danger Zone → Change visibility → Private
- [ ] Settings → Actions → General → Workflow permissions → Read and write
- [ ] Settings → Pages → Source → GitHub Actions (requires Pro for private Pages, or use local dev)
- [ ] `.github/pilot.json` has `private_mode: true`
- [ ] Push to main
- [ ] Test with `examples/product-launch.html` at high/60fps/webm
- [ ] Verify release is private and only visible to you

For HeyGen Cloud Rendering API (optional future): set `HEYGEN_API_KEY` secret and add a job that uses `hyperframes cloud render` — not included in this private GitHub mode, but CLI supports it.

Enjoy full throttle!
