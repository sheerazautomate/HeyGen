"""Story mode script schema - validation and normalization.

The script (script.json) is the single contract between:
  - repo analysis (analyze.py)      -> informs content
  - LLM / offline generator         -> produces it
  - composer (compose.py)           -> renders it into a HyperFrames composition
  - workflow packets (ST1.*)        -> carries it between the storyboard and render jobs

Normalization rules: make the best of every input - clamp over-long copy,
repair palettes, and re-time scenes so durations always sum to the target.
"""
import math
import re

SCHEMA_VERSION = 1

TONES = ["cinematic", "corporate", "playful", "hype", "minimal", "documentary"]
PACES = ["snappy", "balanced", "slow"]
MOODS = ["upbeat", "corporate", "cinematic", "lofi", "playful", "none"]
QUALITIES = ["draft", "standard", "high"]
FORMATS = ["mp4", "webm", "mov"]
FPS_CHOICES = [24, 30, 60]
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}

# Pace -> typical seconds per scene (drives scene count for a given length)
PACE_SCENE_SECONDS = {"snappy": 3.5, "balanced": 5.0, "slow": 7.5}

# Fallback palettes per tone, used only when the repo reveals no colors at all.
TONE_PALETTES = {
    "cinematic":   {"bg": "#0b0e14", "surface": "#131826", "text": "#f2f4f8", "muted": "#8b93a7", "accent": "#ff5c39", "accent2": "#ffb03a"},
    "corporate":   {"bg": "#0a1128", "surface": "#12204a", "text": "#f5f7fc", "muted": "#92a0c8", "accent": "#3a86ff", "accent2": "#8ecae6"},
    "playful":     {"bg": "#1d1145", "surface": "#2b1a63", "text": "#fdf7ff", "muted": "#b9a8e8", "accent": "#ff6bb3", "accent2": "#ffd166"},
    "hype":        {"bg": "#0d0d0d", "surface": "#1a1a1a", "text": "#fafafa", "muted": "#9a9a9a", "accent": "#c8ff2e", "accent2": "#2ee6ff"},
    "minimal":     {"bg": "#f7f5f2", "surface": "#ffffff", "text": "#16161a", "muted": "#6d6d78", "accent": "#2e5bff", "accent2": "#ff6b4a"},
    "minimal":     {"bg": "#f7f5f2", "surface": "#ffffff", "text": "#16161a", "muted": "#6d6d78", "accent": "#2e5bff", "accent2": "#ff6b4a"},
    "documentary": {"bg": "#10150f", "surface": "#1a221a", "text": "#eef2ea", "muted": "#95a393", "accent": "#7fb069", "accent2": "#e6c79c"},
}

# Template catalog: slot -> (kind, max_chars, required)
# kinds: text | list | pairs(title/desc) | stats(value/label) | steps(title/desc) | code | html
TEMPLATE_SLOTS = {
    "hero": {
        "kicker": ("text", 44, False),
        "headline": ("text", 64, True),
        "subline": ("text", 150, True),
    },
    "features_grid": {
        "kicker": ("text", 44, False),
        "heading": ("text", 64, True),
        "features": ("pairs", 6, True),   # 3, 4 or 6 items fill the grid
    },
    "feature_focus": {
        "kicker": ("text", 44, False),
        "heading": ("text", 64, True),
        "body": ("text", 200, True),
        "stat_value": ("text", 14, False),
        "stat_label": ("text", 44, False),
    },
    "code_showcase": {
        "kicker": ("text", 44, False),
        "heading": ("text", 56, True),
        "filename": ("text", 48, True),
        "code": ("code", 900, True),
        "caption": ("text", 110, False),
    },
    "stats": {
        "kicker": ("text", 44, False),
        "heading": ("text", 64, True),
        "stats": ("stats", 4, True),  # 2-4 items
    },
    "stack": {
        "kicker": ("text", 44, False),
        "heading": ("text", 64, True),
        "items": ("list", 10, True),  # 4-10 short chips
    },
    "steps": {
        "kicker": ("text", 44, False),
        "heading": ("text", 64, True),
        "steps": ("steps", 3, True),  # exactly 3
    },
    "statement": {
        "kicker": ("text", 44, False),
        "statement": ("text", 170, True),
        "attribution": ("text", 48, False),
    },
    "outro": {
        "headline": ("text", 56, True),
        "subline": ("text", 130, False),
        "cta_label": ("text", 36, True),
        "url": ("text", 70, True),
    },
    "custom": {
        "heading": ("text", 64, False),
        "html": ("html", 4000, True),
        "caption": ("text", 110, False),
    },
}

PAIR_TITLE_MAX = 30
PAIR_DESC_MAX = 90
STAT_VALUE_MAX = 14
STAT_LABEL_MAX = 40
ITEM_MAX = 26

MIN_SCENES = 3
MAX_SCENES = 10
MAX_TITLE = 100


class ScriptError(ValueError):
    pass


def clamp_text(value, cap, warnings, label):
    """Coerce to a single-line string of at most `cap` chars (hard cut at word boundary)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= cap:
        return value
    cut = value[:cap].rsplit(" ", 1)[0].rstrip(".,;:!?-— ") or value[:cap]
    warnings.append(f"{label}: truncated to {cap} chars")
    return cut


def valid_color(value):
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return v
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:])
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        try:
            parts = [float(x) for x in m.group(1).split(",")][:3]
            return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(p)))) for p in parts)
        except ValueError:
            return None
    return None


def _luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def normalize_palette(raw, tone, warnings):
    base = dict(TONE_PALETTES.get(tone, TONE_PALETTES["cinematic"]))
    source = "generated:tone-default"
    if isinstance(raw, dict):
        source = raw.get("source") if isinstance(raw.get("source"), str) else source
        for key in ("bg", "surface", "text", "muted", "accent", "accent2"):
            c = valid_color(raw.get(key))
            if c:
                base[key] = c
            elif raw.get(key):
                warnings.append(f"palette.{key}: dropped invalid color {raw.get(key)!r}")
    # Guarantee legibility: body text must stand out from the background.
    if contrast_ratio(base["bg"], base["text"]) < 4.5:
        warnings.append("palette: text/bg contrast too low, using dark-on-light or light-on-dark fallback")
        base["text"] = "#f7f7fa" if _luminance(base["bg"]) < 0.4 else "#141419"
    if contrast_ratio(base["bg"], base["accent"]) < 2.0:
        warnings.append("palette: accent too close to bg, lightened/darkened")
        base["accent"] = "#3a86ff" if _luminance(base["bg"]) < 0.4 else "#1d4ed8"
    if "source" not in base:
        base["source"] = source[:200]
    return base


def _norm_pairs(items, max_items, tmax, dmax, warnings, label):
    out = []
    if not isinstance(items, list):
        return out
    for it in items[:max_items]:
        if not isinstance(it, dict):
            continue
        title = clamp_text(it.get("title"), tmax, warnings, f"{label}.title")
        desc = clamp_text(it.get("desc"), dmax, warnings, f"{label}.desc")
        if title:
            out.append({"title": title, "desc": desc})
    return out


def normalize_slots(template, slots, warnings, sid):
    spec = TEMPLATE_SLOTS[template]
    out = {}
    slots = slots if isinstance(slots, dict) else {}
    for name, (kind, cap, required) in spec.items():
        raw = slots.get(name)
        label = f"{sid}.{name}"
        if kind == "text":
            out[name] = clamp_text(raw, cap, warnings, label)
        elif kind == "list":
            items = raw if isinstance(raw, list) else []
            vals = [clamp_text(v, ITEM_MAX, warnings, label) for v in items[:cap]]
            out[name] = [v for v in vals if v]
        elif kind == "pairs":
            out[name] = _norm_pairs(raw, cap, PAIR_TITLE_MAX, PAIR_DESC_MAX, warnings, label)
        elif kind == "stats":
            out[name] = _norm_pairs(raw, cap, STAT_VALUE_MAX, STAT_LABEL_MAX, warnings, label)
            for st in out[name]:
                st["value"], st["label"] = st.pop("title"), st.pop("desc")
        elif kind == "steps":
            out[name] = _norm_pairs(raw, cap, 34, 90, warnings, label)
        elif kind == "code":
            if isinstance(raw, str):
                code = raw.replace("\t", "    ").rstrip()
                lines = code.splitlines()[:14]
                code = "\n".join(lines)
                if len(code) > cap:
                    code = code[:cap].rsplit("\n", 1)[0]
                    warnings.append(f"{label}: code truncated")
                out[name] = code
            else:
                out[name] = ""
        elif kind == "html":
            out[name] = sanitize_custom_html(raw if isinstance(raw, str) else "", cap, warnings, label)
        if required and (out[name] in ("", [], None)):
            # Leave placeholder-free: caller (offline/llm) is expected to fill; composer adds fallbacks.
            pass
    return out


def sanitize_custom_html(html, cap, warnings, label):
    """Custom scenes come from the LLM: strip anything executable or external-scripted.
    Structure + inline styles are fine; scripts, event handlers and javascript: URLs are not."""
    html = html.strip()[:cap]
    html = re.sub(r"<\s*(script|iframe|object|embed|link|meta)[^>]*>.*?<\s*/\s*\1\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<\s*(script|iframe|object|embed|link|meta)[^>]*/?>", "", html, flags=re.I)
    html = re.sub(r"\son[a-zA-Z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html)
    html = re.sub(r"(href|src)\s*=\s*(['\"])\s*javascript:[^'\"]*\2", r"\1=\2#\2", html, flags=re.I)
    # Media/img sources must be https (network render, no mixed/local surprises)
    html = re.sub(r"(src)\s*=\s*(['\"])(?!https://)[^'\"]*\2", r"\1=\2\2", html, flags=re.I)
    return html


def scene_budget(duration, pace):
    per = PACE_SCENE_SECONDS.get(pace, 5.0)
    n = max(MIN_SCENES, min(MAX_SCENES, round(duration / per)))
    return n


def normalize_scenes(raw_scenes, duration, pace, warnings):
    scenes = []
    if not isinstance(raw_scenes, list):
        raise ScriptError("script.scenes must be a list")
    for i, raw in enumerate(raw_scenes[:MAX_SCENES]):
        if not isinstance(raw, dict):
            continue
        template = raw.get("template")
        if template not in TEMPLATE_SLOTS:
            warnings.append(f"scene {i+1}: unknown template {template!r}, using 'statement'")
            template = "statement"
        sid = re.sub(r"[^a-z0-9_-]", "", str(raw.get("id") or f"s{i+1}").lower()) or f"s{i+1}"
        try:
            d = float(raw.get("duration_s") or 0)
        except (TypeError, ValueError):
            d = 0
        scenes.append({
            "id": sid,
            "template": template,
            "duration_s": d if math.isfinite(d) and d > 0 else PACE_SCENE_SECONDS.get(pace, 5.0),
            "slots": normalize_slots(template, raw.get("slots"), warnings, sid),
        })
    if len(scenes) < MIN_SCENES:
        raise ScriptError(f"need at least {MIN_SCENES} scenes, got {len(scenes)}")
    # Re-time so scenes fill the target duration exactly within tolerance.
    total = sum(s["duration_s"] for s in scenes)
    if total <= 0:
        raise ScriptError("scenes have no duration")
    scale = duration / total
    for s in scenes:
        s["duration_s"] = round(max(1.5, s["duration_s"] * scale) * 4) / 4  # quarter-second grid
    drift = sum(s["duration_s"] for s in scenes) - duration
    last = scenes[-1]
    last["duration_s"] = round((last["duration_s"] - drift) * 4) / 4
    if last["duration_s"] < 1.25:
        # absorb with the second-to-last if the outro got starved
        scenes[-2]["duration_s"] = round((scenes[-2]["duration_s"] + last["duration_s"] - 2.5) * 4) / 4
        last["duration_s"] = 2.5
    total = sum(s["duration_s"] for s in scenes)
    if abs(total - duration) > 0.75:
        warnings.append(f"scene re-time left {total - duration:+.2f}s drift; composition duration follows scenes")
    return scenes, round(total, 2)


def normalize_music(raw, warnings):
    music = {"kind": "mood", "mood": "upbeat", "url": None, "volume": 0.35}
    if isinstance(raw, dict):
        kind = raw.get("kind")
        if kind not in ("mood", "url", "none"):
            kind = "mood"
        music["kind"] = kind
        mood = raw.get("mood")
        music["mood"] = mood if mood in MOODS and mood != "none" else "upbeat"
        url = raw.get("url")
        if isinstance(url, str) and re.match(r"^https://[^\s<>'\"]+$", url.strip()) and len(url) < 500:
            music["url"] = url.strip()
        elif url:
            warnings.append("music.url: dropped (must be a short https:// URL)")
        if kind == "url" and not music["url"]:
            warnings.append("music: kind=url without valid url, falling back to mood")
            music["kind"] = "mood"
        try:
            vol = float(raw.get("volume", 0.35))
            music["volume"] = round(max(0.0, min(1.0, vol)), 2)
        except (TypeError, ValueError):
            pass
    return music


def normalize_script(raw, git_keep_durations=False):
    """Validate + repair a script dict. Returns (script, warnings) or raises ScriptError."""
    warnings = []
    if not isinstance(raw, dict):
        raise ScriptError("script must be a JSON object")

    tone = raw.get("tone") if raw.get("tone") in TONES else "cinematic"
    pace = raw.get("pace") if raw.get("pace") in PACES else "balanced"
    aspect = raw.get("aspect") if raw.get("aspect") in ASPECTS else "16:9"
    try:
        duration = float(raw.get("duration") or 30)
    except (TypeError, ValueError):
        duration = 30.0
    duration = max(10.0, min(600.0, duration))

    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    name = clamp_text(project.get("name") or "Project", 60, warnings, "project.name") or "Project"
    url = clamp_text(project.get("url") or "", 200, warnings, "project.url")
    tagline = clamp_text(project.get("tagline") or "", 150, warnings, "project.tagline")

    meta = raw.get("render") if isinstance(raw.get("render"), dict) else {}
    quality = meta.get("quality") if meta.get("quality") in QUALITIES else "standard"
    fmt = meta.get("format") if meta.get("format") in FORMATS else "mp4"
    try:
        fps = int(meta.get("fps", 30))
    except (TypeError, ValueError):
        fps = 30
    if fps not in FPS_CHOICES:
        fps = min(FPS_CHOICES, key=lambda f: abs(f - fps))

    scenes, total = normalize_scenes(raw.get("scenes"), duration, pace, warnings)
    if not git_keep_durations:
        duration = round(total, 2)

    script = {
        "version": SCHEMA_VERSION,
        "tone": tone,
        "pace": pace,
        "aspect": aspect,
        "duration": duration,
        "project": {"name": name, "url": url, "tagline": tagline},
        "palette": normalize_palette(raw.get("palette"), tone, warnings),
        "fonts": _normalize_fonts(raw.get("fonts")),
        "music": normalize_music(raw.get("music"), warnings),
        "scenes": scenes,
        "render": {"quality": quality, "fps": fps, "format": fmt},
        "share_copy": _normalize_share(raw.get("share_copy"), warnings),
    }
    notes = raw.get("notes")
    if isinstance(notes, str) and notes.strip():
        script["notes"] = notes.strip()[:600]
    return script, warnings


def _normalize_fonts(raw):
    fonts = {"display": "Archivo", "mono": "Space Mono"}
    if isinstance(raw, dict):
        for k in fonts:
            v = raw.get(k)
            if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9 +&-]{2,40}", v.strip()):
                fonts[k] = v.strip()
    return fonts


def _normalize_share(raw, warnings):
    out = {"tweet": "", "linkedin": ""}
    if isinstance(raw, dict):
        out["tweet"] = clamp_text(raw.get("tweet"), 280, warnings, "share.tweet")
        out["linkedin"] = clamp_text(raw.get("linkedin"), 700, warnings, "share.linkedin")
    return out
