"""Parse issue-comment commands for the two-phase story flow.

Supported on a [Story] issue, from a repo owner/member/collaborator:

  /render                              render the storyboard as-is
  /render quality:high fps:60          render overrides (no re-generation)
  /render format:webm music:lofi
  /render music:"https://.../song.mp3" custom music URL
  /render tone:playful pace:snappy length:45
                                       script-changing overrides -> regenerate
                                       the script (LLM/offline) then render
  /render s2.headline:"New headline"   direct scene copy edit, then render
  /render note:"make it shorter and punchier"
                                       free-form revision note for the LLM
  /story tone:corporate                regenerate storyboard only (no render)

Values may be quoted with "..." to include spaces. Scene edits use the ids from
the storyboard table (s1, s2, ...) and any text slot of that scene's template.
"""
import re

from .schema import (TONES, PACES, MOODS, QUALITIES, FORMATS, ASPECTS, TEMPLATE_SLOTS)

SCRIPT_KEYS = {"tone": TONES, "pace": PACES, "music": MOODS, "mood": MOODS}
RENDER_KEYS = {"quality": QUALITIES, "format": FORMATS}
NUM_KEYS = {"fps", "length"}

TOKEN_RE = re.compile(r"(\S+?:\"[^\"]*\")|(\S+?:\S+)")


class CommandError(ValueError):
    pass


def parse_command(body, script=None):
    """Returns dict(handle, script_overrides, render_overrides, scene_edits, note)
    or None if the comment isn't a command we handle."""
    if not isinstance(body, str):
        return None
    text = body.strip()
    handle = None
    for h in ("/render", "/story"):
        if text.lower().startswith(h):
            handle = h
            text = text[len(h):].strip()
            break
    if handle is None:
        return None

    result = {"handle": handle, "script_overrides": {}, "render_overrides": {},
              "scene_edits": {}, "note": None, "explicit_none": False}
    for m in TOKEN_RE.finditer(text):
        token = m.group(0)
        key, _, value = token.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        if key in ("note", "notes"):
            result["note"] = value[:400] or None
        elif key in NUM_KEYS:
            try:
                num = int(float(value))
            except ValueError:
                raise CommandError(f"`{key}:` expects a number, got `{value}`.")
            if key == "fps":
                if num not in (24, 30, 60):
                    raise CommandError("`fps:` must be 24, 30 or 60.")
                result["render_overrides"]["fps"] = num
            else:
                if not 10 <= num <= 600:
                    raise CommandError("`length:` must be between 10 and 600 seconds.")
                result["script_overrides"]["duration"] = float(num)
        elif key == "aspect":
            if value not in ASPECTS:
                raise CommandError(f"`aspect:` must be one of {', '.join(ASPECTS)}.")
            result["script_overrides"]["aspect"] = value
        elif key in SCRIPT_KEYS:
            allowed = SCRIPT_KEYS[key]
            if key in ("music", "mood") and value.startswith("https://"):
                # music:"https://..." shorthand for a custom track
                result["render_overrides"]["music_kind"] = "url"
                result["render_overrides"]["music_url"] = value
                continue
            if value not in allowed:
                raise CommandError(f"`{key}:` must be one of {', '.join(allowed)}.")
            if key in ("music", "mood"):
                if value == "none":
                    result["render_overrides"]["music_kind"] = "none"
                else:
                    result["script_overrides"]["music_mood"] = value
            else:
                result["script_overrides"][key] = value
        elif key in RENDER_KEYS:
            allowed = RENDER_KEYS[key]
            if value not in allowed:
                raise CommandError(f"`{key}:` must be one of {', '.join(allowed)}.")
            result["render_overrides"][key] = value
        elif key in ("music_url", "song"):
            if not value.startswith("https://"):
                raise CommandError("`music_url:` must be an https:// link.")
            result["render_overrides"]["music_kind"] = "url"
            result["render_overrides"]["music_url"] = value
        elif key.startswith("music"):
            # music:"https://..." shorthand
            if value.startswith("https://"):
                result["render_overrides"]["music_kind"] = "url"
                result["render_overrides"]["music_url"] = value
        elif re.fullmatch(r"s\d+\.[a-z_]+", key):
            sid, slot = key.split(".", 1)
            result["scene_edits"].setdefault(sid, {})[slot] = value
        # unknown tokens are ignored on purpose (human chatter in the same comment)
    return result


def validate_scene_edits(edits, script):
    """Apply scene copy edits in place; returns list of applied descriptions.
    Raises CommandError on bad references - typos shouldn't silently render."""
    applied = []
    for sid, slots in edits.items():
        scene = next((s for s in script["scenes"] if s["id"] == sid), None)
        if scene is None:
            raise CommandError(f"No scene `{sid}` in the storyboard "
                               f"(ids: {', '.join(s['id'] for s in script['scenes'])}).")
        spec = TEMPLATE_SLOTS[scene["template"]]
        for slot, value in slots.items():
            if slot not in spec or spec[slot][0] != "text":
                raise CommandError(f"Scene `{sid}` (template `{scene['template']}`) has no editable "
                                   f"text slot `{slot}`. Slots: {', '.join(s for s, (k, _, _) in spec.items() if k == 'text')}.")
            scene["slots"][slot] = value
            applied.append(f'{sid} {slot} → "{value[:60]}"')
    return applied


def has_script_changes(cmd):
    return bool(cmd["script_overrides"]) or bool(cmd["note"])


# --------------------------------------------------------------------------- #
# issue form parsing - fields come back as "### Label\n\nvalue" markdown       #
# --------------------------------------------------------------------------- #

FIELD_MARKS = {
    "repo_url": re.compile(r"###\s*Public repo URL\s*\n+\s*(\S[^\n]*)", re.IGNORECASE),
    "tone": re.compile(r"###\s*Tone\s*\n+\s*(\w+)", re.IGNORECASE),
    "pace": re.compile(r"###\s*Pace\s*\n+\s*(\w+)", re.IGNORECASE),
    "length": re.compile(r"###\s*Length \(seconds\)\s*\n+\s*([\d.]+)", re.IGNORECASE),
    "aspect": re.compile(r"###\s*Aspect\s*\n+\s*([\d]+:[\d]+)", re.IGNORECASE),
    "music_mood": re.compile(r"###\s*Music\s*\n+\s*([^\n]+)", re.IGNORECASE),
    "music_url": re.compile(r"###\s*Custom music URL[^\n]*\n+\s*(https?://\S+)", re.IGNORECASE),
    "quality": re.compile(r"###\s*Quality\s*\n+\s*(\w+)", re.IGNORECASE),
    "fps": re.compile(r"###\s*FPS\s*\n+\s*(\d+)", re.IGNORECASE),
    "format": re.compile(r"###\s*Format\s*\n+\s*(\w+)", re.IGNORECASE),
}


def parse_issue_form(body):
    """Extract story fields from a rendered issue-form body.
    Missing fields fall back to sensible defaults - the form validates anyway."""
    body = body or ""
    out = {"music_url": None}
    for key, pat in FIELD_MARKS.items():
        m = pat.search(body)
        if m:
            out[key] = m.group(1).strip()
    if out.get("length"):
        try:
            out["length"] = float(out["length"])
        except ValueError:
            out["length"] = 30.0
    else:
        out["length"] = 30.0
    if out.get("fps"):
        out["fps"] = int(out["fps"])
    else:
        out["fps"] = 30
    from .schema import TONES, PACES, ASPECTS, MOODS, QUALITIES, FORMATS
    out["tone"] = out.get("tone") if out.get("tone") in TONES else "cinematic"
    out["pace"] = out.get("pace") if out.get("pace") in PACES else "balanced"
    out["aspect"] = out.get("aspect") if out.get("aspect") in ASPECTS else "16:9"
    music_mood = (out.get("music_mood") or "").strip().lower()
    # GitHub reserves the exact option "none" in issue-form dropdowns, so the
    # public form uses "no music" while the story pipeline keeps its canonical
    # internal value.
    if music_mood == "no music":
        music_mood = "none"
    out["music_mood"] = music_mood if music_mood in MOODS else "upbeat"
    out["quality"] = out.get("quality") if out.get("quality") in QUALITIES else "standard"
    out["format"] = out.get("format") if out.get("format") in FORMATS else "mp4"
    if not out.get("repo_url"):
        raise CommandError("Couldn't find the repo URL field in this issue.")
    return out


def merge_command_into_form(form, cmd):
    """A /story comment regenerates from form defaults + command overrides."""
    merged = dict(form)
    so = cmd["script_overrides"]
    ro = cmd["render_overrides"]
    for key in ("tone", "pace", "aspect"):
        if key in so:
            merged[key] = so[key]
    if "duration" in so:
        merged["length"] = so["duration"]
    if "music_mood" in so:
        merged["music_mood"] = so["music_mood"]
    for key in ("quality", "format", "fps"):
        if key in ro:
            merged[key] = ro[key]
    return merged
