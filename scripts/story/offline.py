"""Deterministic, LLM-free script generator.

When no LLM provider is configured (truly zero cost, zero keys), this builds a
real script straight from the ProjectBrief - the same analysis the LLM would
get. Copy is assembled from the PRODUCT's own words (what it does, its
capabilities, the literal strings in its interface), so videos are about the
thing people use, not about the repository that holds it.

Repo metrics (lines of code, dependency chips) only appear when the audience is
developers - for an end-user app they are noise and are omitted entirely.
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

# capability key -> (card title, user-benefit description)
CAP_COPY = {
    "location": ("Pinpoint location", "Every capture carries exact GPS coordinates."),
    "location_bg": ("Always accurate", "Keeps location current, even in the background."),
    "camera": ("Built-in camera", "Capture in the app — no switching required."),
    "photos": ("Your photo library", "Bring in shots you already have."),
    "maps": ("See it on a map", "Place every entry visually."),
    "crypto": ("Tamper-evident", "Records are cryptographically sealed."),
    "auth": ("Secure access", "Your data stays behind your login."),
    "cloud": ("Synced everywhere", "Your work follows you across devices."),
    "offline": ("Works offline", "No signal? Everything keeps working."),
    "share": ("Share anywhere", "Send results straight to any app."),
    "files": ("Export freely", "Save and hand off your files."),
    "pdf": ("PDF ready", "Export clean, shareable documents."),
    "export": ("Export your data", "Take everything with you."),
    "graphics": ("Buttery smooth", "GPU-accelerated rendering throughout."),
    "motion": ("Fluid by design", "Every interaction feels instant."),
    "notifications": ("Never miss it", "Timely alerts when it matters."),
    "biometric": ("Locked down", "Unlock with fingerprint or face."),
    "device": ("Device-bound", "Tied securely to your device."),
    "audio": ("Record audio", "Capture sound alongside everything else."),
    "ml": ("On-device smarts", "Runs locally — nothing leaves the device."),
    "ai": ("AI assisted", "Intelligence built into the flow."),
    "payments": ("Get paid", "Payments handled end to end."),
    "realtime": ("Live updates", "Changes appear the moment they happen."),
    "i18n": ("Speaks your language", "Localized for every user."),
    "nfc": ("Tap to connect", "NFC built in."),
    "bluetooth": ("Connects to devices", "Pairs with nearby hardware."),
    "storage": ("Stored on device", "Your records stay with you."),
    "3d": ("3D rendering", "Rich three-dimensional visuals."),
    "scanner": ("Scan instantly", "Point, scan, done."),
    "contacts": ("Your contacts", "Works with the people you know."),
}


def _num(value, suffix=""):
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _titlecase(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if any(c.islower() for c in s) else s.title()


def _is_dev(brief):
    return (brief.get("product") or {}).get("audience") == "developer"


def _cap_cards(product):
    """Feature cards from evidenced product capabilities."""
    cards = []
    for cap in product.get("capabilities") or []:
        copy = CAP_COPY.get(cap["key"])
        if copy:
            cards.append({"title": copy[0][:30], "desc": copy[1][:90]})
        else:
            cards.append({"title": _titlecase(cap["phrase"])[:30],
                          "desc": f"Built for {cap['phrase']}."[:90]})
    return cards


def _vocab_cards(product, limit=6):
    """Feature cards mined from the product's own interface strings."""
    cards, seen = [], set()
    noisy = re.compile(r"(?i)(failed|error|required|loading|^no |yet$|^[A-Z]{2,3}$|"
                       r"^(top|bot|bottom|left|right) ?[lr]?$|^\W|yyyy|dd/mm|mm/dd)")
    for s in product.get("vocabulary") or []:
        if noisy.search(s) or len(s) < 5:
            continue
        key = re.sub(r"[^a-z]", "", s.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        label = _titlecase(s)
        cards.append({"title": label[:30], "desc": f"{label} — right where you need it."[:90]})
        if len(cards) >= limit:
            break
    return cards


def _surface_cards(product):
    out = []
    for s in product.get("surfaces") or []:
        out.append({"title": s[:30], "desc": f"A dedicated {s.lower()} experience."[:90]})
    return out


def _fill_features(brief):
    """Guarantee a FULL grid: exactly 3, 4 or 6 product-value cards."""
    product = brief.get("product") or {}
    items, seen = [], set()

    def add(card):
        key = re.sub(r"[^a-z]", "", card["title"].lower())
        if key and key not in seen:
            seen.add(key)
            items.append(card)

    # 1. explicit product features from a real (non-boilerplate) README
    for f in brief.get("features") or []:
        if ":" in f and len(f.split(":", 1)[0]) <= 28:
            t, d = f.split(":", 1)
            add({"title": t.strip()[:30], "desc": d.strip()[:90]})
        else:
            words = f.split()
            add({"title": " ".join(words[:3])[:30],
                 "desc": (" ".join(words[3:])[:90] or f[:90])})
    # 2. evidenced capabilities  3. interface vocabulary  4. product surfaces
    for card in _cap_cards(product):
        add(card)
    for card in _vocab_cards(product):
        add(card)
    for card in _surface_cards(product):
        add(card)
    # 5. developer projects may legitimately fall back to the stack
    if _is_dev(brief):
        for s in brief.get("stack") or []:
            add({"title": s.split("/")[-1][:30], "desc": f"Powered by {s}"[:90]})

    if len(items) < 3:
        return None
    for want in (6, 4, 3):
        if len(items) >= want and (len(items) < want + 2 or want == 6):
            return items[:want]
    return items[:3]


def _stat_cells(brief):
    """PRODUCT stats. Returns None for end-user apps with no real product numbers.

    Repo metrics are proof for developers and noise for everyone else, so we
    never tell an app's user how many source files it has.
    """
    if not _is_dev(brief):
        return None
    stats, stack = brief["stats"], brief.get("stack") or []
    cells = []
    if stats["loc"] > 50:
        cells.append({"value": _num(stats["loc"]), "label": "lines of code"})
    if stats["files"] > 3:
        cells.append({"value": str(stats["files"]), "label": "source files"})
    if stats["languages"]:
        cells.append({"value": str(len(stats["languages"])), "label": "languages"})
    if stack:
        cells.append({"value": str(len(stack)), "label": "dependencies"})
    if len(cells) < 2:
        return None
    return cells[:4]


def _product_summary(brief):
    """One honest sentence about what the product is."""
    product = brief.get("product") or {}
    name = brief["name"]
    if brief.get("tagline"):
        return brief["tagline"]
    caps = [c["phrase"] for c in (product.get("capabilities") or [])[:2]]
    if caps:
        return (f"{name}: {caps[0]} and {caps[1]}, in one app." if len(caps) > 1
                else f"{name} is built around {caps[0]}.")
    if product.get("surfaces"):
        return f"{name}: {', '.join(product['surfaces'][:3])} in one place."
    return f"A closer look at {name}."


def _headline(brief, cap=64):
    """A hero headline that FITS - built short, never chopped mid-word."""
    product = brief.get("product") or {}
    name = brief["name"]
    tagline = (brief.get("tagline") or "").strip()
    if tagline and len(tagline) <= cap:
        return tagline
    caps = [c["phrase"] for c in (product.get("capabilities") or [])]
    for cand in ([f"{name}: {caps[0]}" if caps else "",
                  f"{name} — {caps[0]}" if caps else "",
                  tagline, f"Meet {name}"]):
        cand = (cand or "").strip()
        if cand and len(cand) <= cap:
            return cand
    return f"Meet {name}"[:cap]


def _hero_subline(brief):
    """Say what it IS and where it runs - never which framework built it."""
    product = brief.get("product") or {}
    name = brief["name"]
    platforms = product.get("platforms") or []
    if _is_dev(brief):
        langs = brief["stats"]["languages"][:2]
        base = f"{name} — open source" + (f" · {', '.join(langs)}" if langs else "")
        return base[:150]
    bits = []
    if platforms and platforms != ["Docker"]:
        bits.append(" · ".join(p for p in platforms if p != "Docker"))
    caps = [c["phrase"] for c in (product.get("capabilities") or [])[:2]]
    if caps:
        bits.append(" and ".join(caps))
    return (f"{name} — {'. '.join(bits)}." if bits else _product_summary(brief))[:150]


def generate_offline(brief, tone, pace, duration, aspect, music_mood, prefs):
    warnings = []
    product = brief.get("product") or {}
    kicker_a, kicker_b = KICKERS.get(tone, KICKERS["cinematic"])
    name = brief["name"]
    summary = _product_summary(brief)
    tagline = clamp_text(summary, 150, warnings, "tagline")
    url = brief["url"]
    is_dev = _is_dev(brief)

    features = _fill_features(brief)
    stat_cells = _stat_cells(brief)
    surfaces = product.get("surfaces") or []
    n = scene_budget(duration, pace)

    plan = ["hero"]
    if features:
        plan.append("features_grid")
    else:
        plan.append("feature_focus")
    # A terminal on screen only makes sense when developers are the audience.
    if is_dev and brief.get("commands"):
        plan.append("code_showcase")
    if stat_cells:
        plan.append("stats")
    if not is_dev and len(surfaces) >= 3:
        plan.append("steps")
    if is_dev and brief.get("stack"):
        plan.append("stack")
    if len(tagline) >= 90:
        plan.append("statement")
    plan.append("outro")
    # fit the scene budget (hero/outro are untouchable anchors)
    while len(plan) > n:
        for drop in ("statement", "stack", "stats", "steps", "code_showcase"):
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
                "headline": _headline(brief),
                "subline": _hero_subline(brief)}})
        elif tpl == "features_grid":
            scenes.append({"id": sid, "template": "features_grid", "duration_s": per * 1.2, "slots": {
                "kicker": "WHAT IT DOES", "heading": f"Why {name}"[:64], "features": features}})
        elif tpl == "feature_focus":
            caps = product.get("capabilities") or []
            heading = (_titlecase(CAP_COPY.get(caps[0]["key"], (caps[0]["phrase"],))[0])
                       if caps else f"Why {name}")
            body = (brief["features"][0] if brief.get("features")
                    else (CAP_COPY.get(caps[0]["key"], ("", tagline))[1] if caps else tagline))
            slots = {"kicker": kicker_b.upper(), "heading": heading[:64], "body": body[:200]}
            if is_dev and brief["stats"]["loc"]:
                slots.update({"stat_value": _num(brief["stats"]["loc"]),
                              "stat_label": "lines of code and counting"})
            scenes.append({"id": sid, "template": "feature_focus", "duration_s": per * 1.1,
                           "slots": slots})
        elif tpl == "code_showcase":
            scenes.append({"id": sid, "template": "code_showcase", "duration_s": per * 1.1, "slots": {
                "kicker": "QUICK START", "heading": "Up and running in seconds",
                "filename": "terminal", "code": "\n".join(brief["commands"])[:900],
                "caption": f"From zero to {name} in one terminal."[:110]}})
        elif tpl == "stats":
            scenes.append({"id": sid, "template": "stats", "duration_s": per, "slots": {
                "kicker": "BY THE NUMBERS", "heading": "Built to scale", "stats": stat_cells}})
        elif tpl == "steps":
            steps = [{"title": s[:32], "desc": f"{s} — built in."[:90]} for s in surfaces[:3]]
            scenes.append({"id": sid, "template": "steps", "duration_s": per, "slots": {
                "kicker": "HOW IT WORKS", "heading": f"{name} in three moves"[:64], "steps": steps}})
        elif tpl == "stack":
            scenes.append({"id": sid, "template": "stack", "duration_s": per, "slots": {
                "kicker": "UNDER THE HOOD", "heading": "Standing on strong shoulders",
                "items": [s.split("/")[-1] for s in brief["stack"][:8]]}})
        elif tpl == "statement":
            scenes.append({"id": sid, "template": "statement", "duration_s": per, "slots": {
                "kicker": "IN SHORT", "statement": tagline[:170], "attribution": name}})
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
        "notes": "Generated offline (no LLM configured) from product analysis.",
    }
    if brief.get("palette") and brief.get("palette_source"):
        raw["palette"]["source"] = brief["palette_source"]
    if brief["fonts"].get("display"):
        raw["fonts"]["display"] = brief["fonts"]["display"]
    if brief["fonts"].get("mono"):
        raw["fonts"]["mono"] = brief["fonts"]["mono"]
    return raw, warnings
