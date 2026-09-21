# HeyGen HyperFrames → GitHub Actions

A **self-serve video-rendering platform on top of GitHub**: a GitHub Pages site where anyone can paste a
[HeyGen HyperFrames](https://developers.heygen.com/hyperframes) composition (`script.html`), a GitHub Actions
workflow that renders it to video, and a gallery that plays every finished render — all without a server.

```
┌─────────────────────┐   git blob + repository_dispatch   ┌──────────────────────────┐
│  GitHub Pages site  │ ─────────────────────────────────▶ │  GitHub Actions          │
│  (composer +        │                                    │  “Render HyperFrames     │
│   video gallery)    │ ◀───────────────────────────────── │   video” workflow        │
└─────────────────────┘   Releases tagged video-*         └────────────┬─────────────┘
        │  watches runs + lists releases                               │
        │                                                    ┌─────────▼──────────┐
        └────────────────────────────────────────────────────│  Render engine     │
             videos play right on the Pages site             │  A) HeyGen cloud   │
                                                             │  B) runner (CLI)   │
                                                             └────────────────────┘
```

## How it works

1. **Compose** — paste or upload your HyperFrames composition (plain HTML/CSS/JS with `data-*` timing
   attributes and a GSAP timeline). Preview it live in the browser with the real `@hyperframes/player`.
2. **Dispatch** — the site uploads the HTML as a *git blob* (`POST /repos/{owner}/{repo}/git/blobs`) and fires
   a `repository_dispatch` (`type: render-video`) with the blob SHA + render settings. The token never leaves
   the browser except to talk to `api.github.com`.
3. **Render** — the `Render HyperFrames video` workflow fetches the blob and renders it:
   * **Engine A — HeyGen cloud** (default when the `HEYGEN_API_KEY` secret exists): zips the project, submits it
     inline to `POST /v3/hyperframes/renders`, polls, downloads the MP4/WebM/MOV + thumbnail.
   * **Engine B — runner render** (free fallback): renders inside the Actions runner with the open-source
     `hyperframes` CLI (headless Chrome + FFmpeg).
4. **Publish** — the workflow creates a GitHub Release tagged `video-<run>-<key>` with the video, a thumbnail,
   and the source `script.html`.
5. **Watch** — the site's **Videos** tab lists every `video-*` release and plays the videos inline. The
   progress card tracks your run live (matched via a unique render key in the run title).

## Quick start

> Requirements: this repository, a GitHub account, ~3 minutes of clicking. No server, no database.

1. **Enable Pages** — `Settings → Pages → Build and deployment → Source: GitHub Actions`.
2. **Deploy the site** — run *Actions → Deploy site to GitHub Pages → Run workflow*. The site lands at
   `https://<owner>.github.io/<repo>/` and auto-knows its repo.
3. **(Optional) HeyGen cloud rendering** — add your API key as the repository secret
   `Settings → Secrets and variables → Actions → HEYGEN_API_KEY`
   (get one at the [HeyGen API dashboard](https://app.heygen.com/developers/api)). Without a key, renders fall
   back to the runner engine automatically.
4. **Create a browser token** — a fine-grained PAT for *this repo only* with
   **Contents: Read and write** + **Actions: Read-only**
   ([create it here](https://github.com/settings/personal-access-tokens/new); the classic `repo` scope also works).
   Paste it into the site's Composer tab — it is stored only in your browser's local/session storage.
5. **Render something** — Composer → *Load example* → **Render video**. ~1–6 minutes later your video is a
   GitHub Release and plays in the Videos tab.

## Triggering renders without the site

Any `repository_dispatch` with `event_type: render-video` works, and compositions already in the repo can be
rendered straight from the Actions tab or CLI:

```bash
# Render a file that lives in the repo (uses the workflow_dispatch inputs)
gh workflow run render.yml \
  -f composition_path=examples/product-launch.html \
  -f title="Launch teaser" -f engine=local -f quality=high

# Fully programmatic: create a blob, then dispatch
SHA=$(curl -s -X POST -H "Authorization: Bearer $GH_PAT" \
  https://api.github.com/repos/OWNER/REPO/git/blobs \
  -d '{"content":"'"$(base64 -w0 script.html | base64 -d)"'","encoding":"utf-8"}' | jq -r .sha)
# … or build the JSON properly with jq:
jq -n --rawfile html script.html '{content:$html,encoding:"utf-8"}' |
  curl -s -X POST -H "Authorization: Bearer $GH_PAT" \
    https://api.github.com/repos/OWNER/REPO/git/blobs -d @- | jq -r .sha

curl -X POST -H "Authorization: Bearer $GH_PAT" \
  https://api.github.com/repos/OWNER/REPO/dispatches -d '{
    "event_type":"render-video",
    "client_payload":{
      "blob_sha":"'"$SHA"'","render_key":"demo0001","title":"My video",
      "engine":"auto","format":"mp4","quality":"standard","resolution":"1080p",
      "aspect_ratio":"16:9","fps":30,"variables_json":"","lint":"true"
    }}'
```

### `client_payload` reference

GitHub caps `client_payload` at **10 properties**, so the site packs all render settings into a single
`settings_json` string. Individual fields are still accepted for hand-rolled dispatches and
`workflow_dispatch` inputs:

| Field                        | Default     | Notes                                                        |
| ---------------------------- | ----------- | ------------------------------------------------------------ |
| `blob_sha`                   | *required*  | Git blob SHA of the composition HTML (`encoding: "utf-8"`)   |
| `render_key`                 | *required*  | Unique short key; used in the run title, tag, and release    |
| `title`                      | `HyperFrames render` | Release + render title (≤180 chars)                 |
| `settings_json`              | *(empty)*   | JSON string with the settings below (one payload property)   |

Settings (inside `settings_json`, or as individual `client_payload` / `workflow_dispatch` fields):

| Field            | Default     | Notes                                                        |
| ---------------- | ----------- | ------------------------------------------------------------ |
| `blob_sha`       | *required*  | Git blob SHA of the composition HTML (`encoding: "utf-8"`)   |
| `render_key`     | *required*  | Unique short key; used in the run title, tag, and release    |
| `title`          | `HyperFrames render` | Release + render title (≤180 chars)                 |
| `engine`         | `auto`      | `auto` \| `heygen-cloud` \| `local`                          |
| `format`         | `mp4`       | `mp4` \| `webm` \| `mov` (webm/mov carry alpha)              |
| `quality`        | `standard`  | `draft` \| `standard` \| `high`                              |
| `resolution`     | `1080p`     | `1080p` \| `4k`                                              |
| `aspect_ratio`   | `16:9`      | `16:9` \| `9:16` \| `1:1` (cloud engine)                     |
| `fps`            | `30`        | 1–240                                                        |
| `variables_json` | *(empty)*   | JSON object overriding `data-composition-variables`          |
| `lint`           | `true`      | Run `hyperframes lint` first (advisory, never blocks)        |

## Writing compositions

A composition is a **self-contained HTML page** — the whole point of HyperFrames. The essentials
(full docs: [developers.heygen.com/hyperframes](https://developers.heygen.com/hyperframes)):

```html
<div id="main"
     data-composition-id="main" data-width="1920" data-height="1080"
     data-start="0" data-duration="16">
  <div class="scene clip" id="s1" data-start="0"  data-duration="4" data-track-index="0">…</div>
  <div class="scene clip" id="s2" data-start="4"  data-duration="4" data-track-index="0"
       style="visibility:hidden">…</div>
</div>
<script>
  window.__timelines = window.__timelines || {};
  var tl = gsap.timeline({ paused: true });
  tl.set("#s1", { autoAlpha: 0 }, 4);
  tl.set("#s2", { autoAlpha: 1 }, 4);
  /* tl.from(...) entrance + mid-scene tweens */
  window.__timelines["main"] = tl;
</script>
```

* Load `gsap` and the `@hyperframes/core` runtime from a CDN (see [`examples/`](examples/)).
* Parameterize with `data-composition-variables` on `<html>` and read them via
  `window.__hyperframes.getVariables()` — override per render with `variables_json`.
* Keep animations deterministic: no `Date.now()`, no unseeded `Math.random()`, no `repeat: -1`.
* Validate locally: `npx hyperframes lint`, preview with `npx hyperframes preview`.

Two ready-to-render examples ship in [`examples/`](examples/) — a 16:9 product launch and a 9:16 vertical
teaser, both parameterized with variables.

## Repository layout

```
site/                     GitHub Pages app (composer, live preview, video gallery)
  index.html · app.js · style.css · config.js
examples/                 Sample compositions (bundled into the Pages site at deploy)
scripts/
  prepare_composition.py  Workflow step: resolve blob/file → project + validated params
  cloud_render.py         HeyGen cloud pipeline: zip → submit → poll → download (stdlib only)
.github/workflows/
  render.yml              repository_dispatch + workflow_dispatch renderer → GitHub Release
  deploy-pages.yml        Publishes site/ to GitHub Pages (injects repo coordinates)
```

## Configuration reference

| Setting            | Where                | Effect                                                        |
| ------------------ | -------------------- | ------------------------------------------------------------- |
| `HEYGEN_API_KEY`   | Actions secret       | Enables the HeyGen cloud engine; without it renders use the runner |
| Pages source       | Settings → Pages     | Must be **GitHub Actions** for `deploy-pages.yml` to publish  |
| Browser PAT        | site Composer tab    | Needs Contents RW (+ Actions RO for live run status)          |
| `site/config.js`   | generated at deploy  | Defaults for owner/repo on the Pages site (editable in the UI) |

## Security notes

* The browser token is fine-grained and stored **only** in your browser (choose session-only to skip
  persistent storage). It is sent exclusively to `api.github.com`.
* Compositions are stored as dangling git blobs (not attached to any branch) and only referenced by the
  workflow run — nothing is pushed to `main`.
* Anyone who can dispatch the workflow can spend your HeyGen credits / runner minutes — share the PAT and
  repository write access accordingly. For public "anyone can render" setups, put the site on a dedicated
  repository with spending caps in place.
* Rendered videos and releases are as public as the repository itself.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `engine=heygen-cloud requested but HEYGEN_API_KEY is not set` | Add the secret, or pick engine `auto`/`local` |
| Site can't read run status | Token lacks **Actions: Read** — renders still work, watch them on the Actions tab |
| `403 rate limit` | Add/use the PAT (60 → 5,000 req/h) |
| Blank preview | The player loads `@hyperframes/player` from a CDN; rendering in Actions is unaffected |
| Render failed | Open the linked run → `render` job → failing step shows the exact API/render error |
| Workflow never starts | The workflow file must exist on the **default branch**; check the Actions tab for disabled workflows |
