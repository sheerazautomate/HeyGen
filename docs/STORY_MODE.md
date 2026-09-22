# Story Mode — repo link in, launch video out

Story mode turns a **public GitHub repo link** into a scripted, scored, full-throttle
rendered video — with a human approval checkpoint in the middle.

```
[Story] issue (repo URL + tone/pace/length/music/quality/fps/format)
  → clone & analyze (README, manifests, routes, styles, examples)
  → script writer (free LLM, or offline generator) writes script.json
  → composer assembles a HyperFrames composition from the template library
  → storyboard posted as an issue comment
  ← YOU review it, then reply /render (optionally with overrides)
  → sandbox render (same full-throttle pipeline as [Video]) → private release
```

## The two-phase flow

**Phase 1 — storyboard.** Open a **story issue** (studio card "Generate from a repo",
or GitHub → New issue → *Generate a video from a repo link*). The analyzer
(`scripts/story/`) reads the project: tagline, features, install commands, tech
stack, routes/screens, color palette, fonts, logo. Secrets and credentials are
skipped and anything token-shaped is redacted before it ever leaves the runner.
A script writer then drafts the story: scene order, copy, palette, per-scene
timing, music. The storyboard (palette table, scene table, editable slot names)
is posted back on the issue within ~a minute.

**Phase 2 — render.** Reply to the issue:

| command | what it does |
|---|---|
| `/render` | renders exactly the posted storyboard |
| `/render quality:high fps:60 format:webm` | render-level overrides only (no re-generation) |
| `/render music:lofi` / `music_url:"https://…/t.mp3"` | swap the music |
| `/render tone:playful pace:snappy length:45` | regenerate the script with new tone/pace/length, then render |
| `/render s2.heading:"Better heading"` | direct copy edit to a scene slot, then render |
| `/render note:"make it punchier"` | free-form revision note for the writer, then render |
| `/story tone:corporate` | regenerate the storyboard only |

Only repo owners/members/collaborators can trigger renders. The video is
published as a private release, same as `[Video]` requests.

## Free-of-cost script writing (no paid LLM)

GitHub Models was retired on 2026-07-30, so story mode targets **free-tier,
OpenAI-compatible providers** — one repo secret, no billing:

| provider | secret | model default | free tier (2026) |
|---|---|---|---|
| **Groq** | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | ~1,000 req/day, no card |
| **Gemini** | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `gemini-2.0-flash` | free tier, no card |
| **Cerebras** | `CEREBRAS_API_KEY` | `llama-3.3-70b` | ~1M tokens/day |
| **OpenRouter** | `OPENROUTER_API_KEY` | `llama-3.3-70b-instruct:free` | 50 req/day |
| **Ollama** (local) | none | `qwen2.5:7b` | unlimited, runs on your machine |
| **offline** | none | — | rule-based generator, always works |

- Set the repo variable `STORY_PROVIDER` to force one (`groq` / `gemini` /
  `cerebras` / `openrouter` / `ollama` / `offline`). Default: `auto` — first
  provider whose key exists, else Ollama if reachable, else **offline**.
- **Offline mode never fails and never costs anything**: the script is built
  deterministically from the repo analysis using the same template library.
  An LLM improves phrasing and scene choices; it is never a hard dependency.
  The storyboard always tells you which engine wrote it.

## How the script guarantees a full screen (no dead space)

1. **Full-bleed doctrine in templates.** Every scene is painted background
   (mesh gradient + grid + drifting accent orbs + vignette + film grain) with a
   content frame that stretches to fill the canvas. Aspect-aware layout tokens
   (16:9 / 9:16 / 1:1) tune paddings, type scale, and grid columns per shape.
2. **Grid completeness rules.** `features_grid` uses exactly 3, 4 or 6 cards;
   `stats` 2–4 cells; `steps` exactly 3. The offline generator pads grids from
   real project facts (routes, stack) instead of leaving holes; the LLM prompt
   enforces the same contract.
3. **Character budgets per slot.** Headlines ≤ 64 chars, card titles ≤ 30,
   descriptions ≤ 90, statements ≤ 170 — clamped at the schema level, so copy
   can never overflow the frame.
4. **Palette from the project itself.** Analysis rakes CSS/Tailwind/theme files,
   ranks colors by frequency with theme-file boost, and picks bg/text/accent by
   luminance and chroma. Contrast is verified and repaired at the schema level.
   If a repo has no styles, a tone-appropriate palette is chosen and the
   storyboard says so.

## Music

- **Mood tracks are synthesized, not downloaded** (`scripts/story/music.py`):
  chord pads, bass, hats, plucks and a gentle delay are generated per
  (mood, seed) at render time. Deterministic, and royalty-free by construction.
- Moods: `upbeat`, `corporate`, `cinematic`, `lofi`, `playful`, `none`.
- **Custom URL**: any short `https://` audio link ≤ 40 MB — downloaded in the
  prepare job, transcoded and mixed under the video (`music_url:` override or
  the form field). Volume is adjustable in the script (`music.volume`, 0–1).

## Local one-command mode (no GitHub needed)

```bash
python3 scripts/personal_render.py --story https://github.com/owner/repo \
  --tone hype --pace snappy --length 30 --music-mood upbeat --quality high --fps 60
```

Prints the storyboard, asks for confirmation (`-y` to skip), then renders
locally through the same Docker sandbox. Script generation uses Ollama if
running, otherwise the offline engine.

## Security notes

- Only `https://github.com/<owner>/<repo>` URLs accepted; clone is shallow,
  size-capped (150 MB), timed out, `.git` removed immediately.
- The analyzer never reads `.env*`, `*.pem`, `*.key`, `credentials*`,
  `secrets*`, lockfiles, vendored or built artifacts; everything else is
  scanned for token shapes and redacted.
- Custom LLM scenes are sanitized: no `<script>`, no event handlers, no
  `javascript:` URLs, images/media only via absolute `https://`.
- The LLM never gets your whole repo — only the redacted analysis brief.
- Render stays in the same sandbox: no Docker socket, read-only root,
  uid 1000, pid/size limits. Releases are private to repo collaborators.

## Files

```
scripts/story/
  fetch_repo.py   safe clone + skip-list + redaction
  analyze.py      ProjectBrief: features, stack, routes, palette, fonts, logo, stats
  llm.py          free-provider client (auto/offline fallback)
  prompts.py      layout doctrine + schema contract for the LLM
  offline.py      rule-based generator (zero-cost default)
  schema.py       script.json validation, clamping, palette repair
  templates.py    scene template library (the hybrid backbone)
  compose.py      script.json -> HyperFrames composition HTML
  music.py        procedural mood tracks + custom URL fetch
  commands.py     /render & /story comment parsing, issue form parsing
  story.py        CLI orchestrator (analyze/prepare/compose/music/...)
.github/ISSUE_TEMPLATE/story-video.yml
.github/workflows/story-script.yml   # repo -> storyboard comment
.github/workflows/story-render.yml   # /render comment -> prepare -> render-core
.github/workflows/render-core.yml    # shared render+publish (also used by [Video])
```
