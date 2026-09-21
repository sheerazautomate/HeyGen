# Personal Pro HyperFrames — AI / Developer Authoring Guide
### Same interface, full throttle, private

This guide is for **all AIs and developers** writing `script.html` for this personal pro tool (private GitHub repo, 10MB/10min/4K/60fps/high/WebM/MOV, network ON).

---

## 1. Can this tool generate audio?

**Short answer: It composes audio, it doesn't generate it.**

HyperFrames is a **composition layer**, not a media generator:

- ✅ **Composes** your audio: BGM, SFX, voiceover via `<audio>` tags, mixes them, does ducking/carving, EQ, compressor, limiter, reverb, etc.
- ✅ **Audio-reactive visuals**: beat sync, glow, pulse driven by audio analysis.
- ❌ **Does NOT generate** TTS / music by itself. You bring the audio file.

**In this personal pro tool (network enabled):**
- You can use **external audio URLs** (https://.../music.mp3) — works because Docker has network.
- You can use **data: URIs** for small SFX (`data:audio/mp3;base64,...`).
- You can generate voice externally (ElevenLabs, HeyGen API, OpenAI TTS, etc.) then paste the URL.

**If you need TTS, do this before writing HTML:**
1. Generate audio file externally.
2. Host it at a public URL (S3, GitHub release asset, CDN) or inline as base64 if <2MB.
3. Reference it in HTML as `<audio src="https://.../voice.mp3">`.

**Audio mixing pro features (already supported):**
- `<hf-audio-group>` for submix buses with shared effect chain
- Voice carving: auto-duck music bed where voice is
- Effect chain: EQ, compressor, limiter, gate, saturation, delay, reverb, chorus, phaser, bitcrush
- Automation envelopes on volume/effects

---

## 2. The Composition Contract (MANDATORY for all AIs)

Every `script.html` MUST follow this — otherwise render fails or is blank.

### 2.1 Single file, single composition
```html
<!doctype html>
<html lang="en" data-composition-variables='[{"id":"headline","label":"Headline","type":"string","default":"Hello"}]'>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1920, height=1080">
  <title>My video</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@hyperframes/core@0.8.58/dist/hyperframe.runtime.iife.js"></script>
  <style> /* all CSS inline */ </style>
</head>
<body>
  <div id="main" data-composition-id="main" data-width="1920" data-height="1080" data-start="0" data-duration="10">
    <!-- clips here -->
  </div>
  <script> /* GSAP timeline */ </script>
</body>
</html>
```

**Rules:**
- Exactly **one** element with `data-composition-id` (the root).
- Root MUST have `data-width` (even, <=4096), `data-height` (even, <=4096), `data-duration` (>0, <=600), `data-start="0"`.
- `width * height <= 16,777,216` (4K). For 4K use 3840x2160 or 2160x3840.
- File size <=10MB (including inline base64).
- No external HTML imports via relative paths — single file only.

### 2.2 Clips = timeline
Every animated element is a clip:
```html
<div class="scene clip" data-start="0" data-duration="3" data-track-index="0">...</div>
<div class="scene clip" data-start="3" data-duration="3" data-track-index="0" style="visibility:hidden">...</div>
```
- `data-start` and `data-duration` in **seconds** (float allowed).
- `data-track-index` is layer stack (0 = bottom).
- Use `class="clip"` always.
- Hide future scenes initially with `style="visibility:hidden"` or `autoAlpha:0` — engine handles visibility via data attributes.

### 2.3 GSAP timeline — seekable, deterministic
```js
window.__timelines = window.__timelines || {};
(function(){
  var tl = gsap.timeline({ paused: true });
  // Scene toggles (hard cuts)
  tl.set("#s1", { autoAlpha: 0 }, 4.0);
  tl.set("#s2", { autoAlpha: 1 }, 4.0);

  // Animations — all seek-safe
  tl.from("#title", { y: 50, autoAlpha: 0, duration: 0.8, ease: "power3.out" }, 0.2);
  tl.to("#orb", { x: 100, duration: 1.5, ease: "sine.inOut", yoyo:true, repeat:1 }, 0.5);

  window.__timelines["main"] = tl;
})();
```
**NEVER:**
- `Math.random()` → use seeded PRNG only if needed
- `Date.now()`, `performance.now()` → use `tl.time()` or hardcoded
- `setInterval`, `setTimeout`, `requestAnimationFrame` → use GSAP tweens
- `repeat: -1` → use `repeat: Math.floor(duration/cycle)-1`
- `stagger: { from: "random" }` → use `from: "start"|"center"|"end"`
- Async timeline construction → build synchronously at page load
- `video.play()` / `audio.play()` → framework owns playback
- Animating `display` / `visibility` → use `autoAlpha`

### 2.4 Variables — one bundle, many videos
```html
<html data-composition-variables='[
  {"id":"product","label":"Product","type":"string","default":"NIMBUS"},
  {"id":"headline","label":"Headline","type":"string","default":"Ship video at speed of thought"}
]'>
<script>
  var vars = { product: "NIMBUS", headline: "Ship video..." };
  try {
    if (window.__hyperframes?.getVariables) vars = Object.assign(vars, window.__hyperframes.getVariables());
  } catch(e){}
  document.getElementById("product").textContent = vars.product;
</script>
```
Personal pro studio auto-detects this JSON and shows an editor. You override at render time. Supported types: string, number, boolean. Keep values <5000 chars.

---

## 3. External Assets Guide — Full Throttle (Personal Pro Only)

**Pilot blocked external assets (offline). Personal pro allows network.**

### 3.1 Images / Logos
**Option A — Public URL (recommended for large images, works in pro):**
```html
<img src="https://cdn.example.com/logo.png" crossorigin="anonymous">
<div style="background-image: url('https://images.unsplash.com/photo-123?w=1920')"></div>
```
- Must be **publicly fetchable, CORS-friendly**. No auth, no expiring signed URLs.
- Use `crossorigin="anonymous"` for canvas safety.
- Preferred: host on S3, R2, GitHub Releases, or your CDN.

**Option B — Inline base64 (best for small logos, fully self-contained, no network needed):**
```html
<img src="data:image/png;base64,iVBORw0KGgoAAAANS...">
```
- Use for logos <500KB. Convert: `base64 -w 0 logo.png`
- Pro limit 10MB total, so 1MB photo inline is okay.

**NEVER:** Relative paths like `src="./logo.png"` or `src="assets/logo.png"` — they don't arrive (single file import, no file tree).

### 3.2 Fonts
**Option A — Google Fonts (works in pro, network ON):**
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;600;800&display=swap" rel="stylesheet">
<style> body { font-family: "Sora", sans-serif; } </style>
```

**Option B — Inline @font-face (most deterministic, no network dependency):**
```html
<style>
@font-face {
  font-family: "MyFont";
  src: url(data:font/woff2;base64,d09GRgABAAAA...) format("woff2");
  font-weight: 600;
}
</style>
```
- Convert: `base64 -w 0 MyFont.woff2`

### 3.3 Audio (BGM, SFX, Voiceover)
```html
<!-- Background music -->
<audio id="bgm" src="https://cdn.example.com/music.mp3" data-start="0" data-duration="10"></audio>

<!-- Voiceover -->
<audio id="vo" src="https://cdn.example.com/voice.mp3" data-start="0.5" data-duration="8"></audio>

<!-- SFX -->
<audio id="sfx" src="data:audio/mp3;base64,//uQxAAAA..." data-start="2.3" data-duration="0.5"></audio>
```
- Always provide `data-start` and `data-duration` on audio if you want framework-synced playback.
- Don't call `play()`. Framework owns it.
- For long BGM, host externally (10MB limit would be exceeded if inlined).
- For SFX <100KB, inline as base64.

**Audio mixing (optional pro):**
```html
<hf-audio-group id="mix" data-effect="compressor threshold=-20 ratio=4">
  <audio src=".../bgm.mp3"></audio>
  <audio src=".../vo.mp3"></audio>
</hf-audio-group>
```

### 3.4 Video (A-roll, B-roll, screen recordings)
```html
<video id="broll" src="https://cdn.example.com/broll.mp4" muted playsinline data-start="0" data-duration="5" style="width:1920px;height:1080px;object-fit:cover"></video>
```
- **Must be `muted playsinline`** always.
- Keep video separate from audio — put voice on `<audio>`, not in video.
- External URLs work in pro. For small clips, data URI possible but not recommended (large).

### 3.5 Scripts / Libraries
```html
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@hyperframes/core@0.8.58/dist/hyperframe.runtime.iife.js"></script>
<!-- Three.js, Lottie, etc. allowed in pro -->
<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js"></script>
```
- Don't inline GSAP/HyperFrames runtime — use CDN, our offline.py localizes it anyway.
- For other libs, CDN URLs work because network is ON.

### 3.6 Determinism & Performance Tips for External Assets
- **Preload**: Add `<link rel="preload" as="image" href="https://...">` for critical images.
- **CORS**: Ensure `Access-Control-Allow-Origin: *` on your asset host, or `crossorigin` may fail.
- **Size**: Optimize images to <1MB, videos to <50MB for fast render. 4K render already heavy (4 CPUs/8GB).
- **No expiring URLs**: Don't use S3 presigned URLs that expire in 5 min — render may start later.
- **No auth**: No `Authorization` headers. Public URL only.

---

## 4. Common AI Prompts — Copy/Paste for All AIs

### Prompt for any AI to write script.html for this tool:
```
Write a single self-contained HyperFrames composition HTML for personal pro tool.

Constraints (MANDATORY):
- One file, one composition: <div data-composition-id="main" data-width="1920" data-height="1080" data-start="0" data-duration="10">
- Clips: class="clip" with data-start, data-duration, data-track-index. Hide future scenes with visibility:hidden.
- GSAP timeline: var tl = gsap.timeline({paused:true}); ... window.__timelines["main"]=tl; Build synchronously.
- No Math.random(), Date.now(), setTimeout, requestAnimationFrame, repeat:-1, video.play(), audio.play().
- Use autoAlpha, not display/visibility animation.
- All CSS inline in <style>. No relative asset paths.
- For variables, use <html data-composition-variables='[{"id":"headline","type":"string","default":"Hello"}]'> and read via window.__hyperframes.getVariables().
- Width/height even, <=4096, duration <=600, file <=10MB.
- External assets allowed via https:// URLs (images, fonts, audio, video) because this is personal pro with network ON. Prefer public CORS-friendly URLs or inline base64 for small assets.

Output ONLY the HTML file, no explanation.
```

### Prompt for external assets version:
```
Write a HyperFrames composition that uses external assets (full throttle personal pro).

Use:
- Google Fonts via <link href="https://fonts.googleapis.com/...">
- Background image via https://images.unsplash.com/...
- Logo via data:image/png;base64,... (small) or https://...
- BGM via <audio src="https://cdn.example.com/music.mp3" data-start="0" data-duration="10">
- Voiceover via <audio src="https://cdn.example.com/voice.mp3" data-start="0.5" data-duration="8">

Follow composition contract: data-composition-id, data-width/height/duration, clip with data-start/duration/track-index, GSAP timeline paused:true registered on window.__timelines["main"].

Don't use relative paths. All external URLs must be public, CORS-friendly, non-expiring.

Output single HTML.
```

---

## 5. Examples — How Pilot Examples Use Assets

**Original pilot example (offline):**
- Fonts: Google Fonts link in <head> — in pilot, this would fallback to system font because network OFF. In pro, it loads correctly.
- Images: None (all CSS gradients/orbs) — because external images blocked in pilot. In pro, you can add <img src="https://...">.
- Audio: None — pilot had no audio. In pro, add <audio> tags.

**To convert pilot example to pro with external assets:**
1. Replace CSS orbs with `<img src="https://images.unsplash.com/...">`
2. Replace font fallback with working Google Fonts (already in example, now works)
3. Add BGM: `<audio src="https://cdn.pixabay.com/audio/...mp3" data-start="0" data-duration="16">`
4. Add variables for product name (already has data-composition-variables)

---

## 6. Local vs GitHub Rendering

**GitHub (private repo):**
- Upload HTML in studio → set quality/fps/format/variables → Prepare → Copy HF1. packet → Create Issue → Track
- Renderer: 4 CPUs, 8GB, network ON, 15 min timeout, outputs private release

**Local (instant, no GitHub):**
```bash
docker build -t pilot-renderer scripts/pilot
python3 scripts/personal_render.py my-video.html --quality high --fps 60 --format mp4 --vars '{"headline":"Hello Pro"}'
# Output: build/personal/my-video-pro-high-60fps.mp4
```

---

## 7. Checklist Before Submitting

- [ ] One `data-composition-id`, even width/height <=4096, duration <=600, file <=10MB
- [ ] All clips have `class="clip" data-start data-duration data-track-index`
- [ ] GSAP timeline paused:true, registered on `window.__timelines[compositionId]`, no random/time-based logic
- [ ] No `video.play()` / `audio.play()`, video has `muted playsinline`
- [ ] External assets are https:// public URLs or data: URIs, not relative paths
- [ ] Fonts: Google Fonts link or inline base64 @font-face
- [ ] Audio: <audio> with data-start/duration if synced, or external URL
- [ ] Variables: valid JSON in `data-composition-variables`, read via `window.__hyperframes.getVariables()`
- [ ] Tested locally with `npx hyperframes preview` or our `personal_render.py`

---

**For AIs:** If you follow this contract, your HTML will render first try in this personal pro tool. If you violate determinism rules, render will be blank or wrong.

Enjoy full throttle!

