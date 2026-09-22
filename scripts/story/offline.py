"""Deterministic, LLM-free script generator.

When no LLM provider is configured (truly zero cost, zero keys), this builds a
real script straight from the ProjectBrief - the same analysis the LLM would
get. Copy is assembled from the project's own words (tagline, README features,
install commands, stack), so videos stay specific instead of generic.
"""
import re

from .schema import scene_budget, clamp_text

KICKERS = {
    "cinematic": ("A project story", "Built with intent"),
    "corporate": ("Product overview", "Engineered for teams"),
    "playful": ("Say hello", "Look what we made"),
    "hype": ("Just shipped", "Zero to launch"),
    "minimal": ("Overview", "Simply put"),
    "documentary": ("Behind the repo", "The making of"),
}
TONE_CTA = {
    "cinematic": "See it in action",
    "corporate": "Get started",
    "playful": "Give it a spin",
    "hype": "Try it now",
    "minimal": "Read the docs",
    "documentary": "Explore the code",
}


def _num(value, suffix=""):
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _fill_features(features, stack, routes):
    """Guarantee the grid is FULL: exactly 3, 4 or 6 items, padded from real project facts."""
    items = []
    for f in features:
        if ":" in f and len(f.split(":", 1)[0]) <= 28:
            t, d = f.split(":", 1)
            items.append({"title": t.strip(), "desc": d.strip()[:90]})
        else:
            words = f.split()
            items.append({"title": " ".join(words[:3])[:30], "desc": " ".join(words[3:])[:90] or f[:90]})
    for r in routes:
        items.append({"title": r.title()[:30], "desc": f"Built-in {r} experience"[:90]})
    for s in stack:
        items.append({"title": s.split("/")[-1][:30], "desc": f"Powered by {s}"[:90]})
    if len(items) < 3:
        return None  # not enough material - caller picks feature_focus instead
    for want in (6, 4, 3):
        if len(items) >= want and (len(items) < want + 2 or want == 6):
            return items[:want]
    return items[:3]


def _stat_cells(stats, stack):
    cells = []
    if stats["loc"] > 50:
        cells.append({"value": _num(stats["loc"]), "label": "lines of code"})
    if stats["files"] > 3:
        cells.append({"value": str(stats["files"]), "label": "source files"})
    if stats["languages"]:
        cells.append({"value": str(len(stats["languages"])), "label": "languages"})
    if stack:
        cells.append({"value": str(len(stack)), "label": "dependencies"})
    if not cells:
        cells.append({"value": "100", "label": "% open source"})
    return cells[:4] if len(cells) >= 2 else cells + [{"value": "1", "label": "command to start"}]


def generate_offline(brief, tone, pace, duration, aspect, music_mood, prefs):
    warnings = []
    kicker_a, kicker_b = KICKERS.get(tone, KICKERS["cinematic"])
    name = brief["name"]
    tagline = clamp_text(brief["tagline"], 150, warnings, "tagline") or f"A closer look at {name}."
    url = brief["url"]

    features = _fill_features(brief["features"], brief["stack"], brief["routes"])
    n = scene_budget(duration, pace)

    plan = ["hero"]
    if features:
        plan.append("features_grid")
    else:
        plan.append("feature_focus")
    if brief["commands"]:
        plan.append("code_showcase")
    plan.append("stats")
    if brief["stack"]:
        plan.append("stack")
    if len(tagline) >= 90:
        plan.append("statement")
    plan.append("outro")
    # fit the scene budget (hero/outro are untouchable anchors)
    while len(plan) > n:
        for drop in ("statement", "stack", "stats", "code_showcase"):
            if drop in plan and len(plan) > n:
                plan.remove(drop)
    while len(plan) < max(3, n - 1) and "statement" not in plan and tagline:
        plan.insert(-1, "statement")

    scenes = []
    per = duration / len(plan)
    for i, tpl in enumerate(plan):
        sid = f"s{i+1}"
        if tpl == "hero":
            scenes.append({"id": sid, "template": "hero", "duration_s": per * 1.1, "slots": {
                "kicker": kicker_a.upper(),
                "headline": tagline[:64] if tagline else f"Meet {name}",
                "subline": f"{name} — {', '.join(brief['stats']['languages'][:3]) or 'open source'} project on GitHub."[:150]}})
        elif tpl == "features_grid":
            scenes.append({"id": sid, "template": "features_grid", "duration_s": per * 1.2, "slots": {
                "kicker": "WHAT'S INSIDE", "heading": f"Why {name}"[:64], "features": features}})
        elif tpl == "feature_focus":
            stat = {}
            if brief["stats"]["loc"]:
                stat = {"stat_value": _num(brief["stats"]["loc"]), "stat_label": "lines of code and counting"}
            scenes.append({"id": sid, "template": "feature_focus", "duration_s": per * 1.1, "slots": {
                "kicker": kicker_b.upper(), "heading": (brief["features"][0][:64] if brief["features"] else f"Why {name}"),
                "body": (brief["features"][1][:200] if len(brief["features"]) > 1 else tagline[:200]), **stat}})
        elif tpl == "code_showcase":
            scenes.append({"id": sid, "template": "code_showcase", "duration_s": per * 1.1, "slots": {
                "kicker": "QUICK START", "heading": "Up and running in seconds",
                "filename": "terminal", "code": "\n".join(brief["commands"])[:900],
                "caption": f"From zero to {name} in one terminal."[:110]}})
        elif tpl == "stats":
            scenes.append({"id": sid, "template": "stats", "duration_s": per, "slots": {
                "kicker": "BY THE NUMBERS", "heading": "The repo in digits", "stats": _stat_cells(brief["stats"], brief["stack"])}})
        elif tpl == "stack":
            scenes.append({"id": sid, "template": "stack", "duration_s": per, "slots": {
                "kicker": "UNDER THE HOOD", "heading": "Standing on strong shoulders",
                "items": [s.split("/")[-1] for s in brief["stack"][:8]]}})
        elif tpl == "statement":
            scenes.append({"id": sid, "template": "statement", "duration_s": per, "slots": {
                "kicker": "IN SHORT", "statement": tagline[:170], "attribution": f"{name} readme"}})
        elif tpl == "outro":
            scenes.append({"id": sid, "template": "outro", "duration_s": per * 1.1, "slots": {
                "headline": f"Try {name} today"[:56], "subline": tagline[:130],
                "cta_label": TONE_CTA.get(tone, "Get started"), "url": url.replace("https://", "")}})

    raw = {
        "tone": tone, "pace": pace, "aspect": aspect, "duration": duration,
        "project": {"name": name, "url": url, "tagline": tagline},
        "palette": brief.get("palette") or {},
        "fonts": {k: v for k, v in (brief.get("fonts") or {}).items() if v},
        "music": {"kind": "url" if prefs.get("music_url") else ("none" if music_mood == "none" else "mood"),
                  "mood": music_mood, "url": prefs.get("music_url"), "volume": 0.35},
        "scenes": scenes,
        "render": {"quality": prefs.get("quality", "standard"), "fps": prefs.get("fps", 30),
                   "format": prefs.get("format", "mp4")},
        "share_copy": {
            "tweet": f"{name} — {tagline[:180]}\n{url}",
            "linkedin": f"Check out {name}: {tagline[:400]}\n\n{url}"},
        "notes": "Generated offline (no LLM configured) from repo analysis.",
    }
    if brief.get("palette") and brief.get("palette_source"):
        raw["palette"]["source"] = brief["palette_source"]
    if brief["fonts"].get("display"):
        raw["fonts"]["display"] = brief["fonts"]["display"]
    if brief["fonts"].get("mono"):
        raw["fonts"]["mono"] = brief["fonts"]["mono"]
    return raw, warnings
