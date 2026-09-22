"""LLM prompts for story mode.

The system prompt is a contract: it teaches the model the template catalog,
the exact JSON schema, and - most importantly - the LAYOUT DOCTRINE that keeps
every frame full (grid completeness rules, per-slot character budgets, layered
backgrounds, copy length discipline).
"""
import json

from .schema import TEMPLATE_SLOTS, PACE_SCENE_SECONDS, MOODS, TONES

LAYOUT_DOCTRINE = """\
ABOUT LAYOUT (this is a motion-graphic video, not a document):
- The canvas must NEVER have empty dead space. Every scene is a full-bleed design
  with a painted background (you only write the CONTENT; backgrounds are built
  for you from the palette).
- Grids must be filled completely: features_grid uses EXACTLY 3, 4 or 6 cards;
  stats uses 2-4 cells; stack uses 4-10 chips; steps is EXACTLY 3 cards.
  Never return 5 or 7 cards. Pad with real details from the brief (routes,
  stack, commands) rather than leaving structural gaps.
- Respect the character budgets per slot (listed per template). Short, punchy,
  specific copy beats long copy: this is screen typography, not a blog post.
- Headlines should name the project's REAL benefits, its actual features and
  concrete numbers from the brief - never generic marketing fog.
- Every scene needs a kicker (2-4 words, ALL CAPS) except where marked optional.

ABOUT COLOR:
- Prefer the project's own palette (palette_hint) when present - the video must
  look like the project's brand. You may adjust individual colors ONLY for
  contrast/legibility (text must clearly stand out from bg; accent must pop).
- If no palette hint exists, design one that fits the project's domain and the
  chosen tone. Dark, rich backgrounds with one saturated accent read best on video.
"""


def template_docs():
    lines = []
    for name, slots in TEMPLATE_SLOTS.items():
        parts = []
        for sname, (kind, cap, required) in slots.items():
            req = "required" if required else "optional"
            if kind == "text":
                parts.append(f'"{sname}": string<={cap} chars ({req})')
            elif kind == "list":
                parts.append(f'"{sname}": list of <= {cap} short strings, each <= 26 chars ({req})')
            elif kind == "pairs":
                parts.append(f'"{sname}": 3/4/6 items {{"title": <=30 chars, "desc": <=90 chars}} ({req})')
            elif kind == "stats":
                parts.append(f'"{sname}": 2-4 items {{"value": <=14 chars (number-led, e.g. "4.8k"), "label": <=40 chars}} ({req})')
            elif kind == "steps":
                parts.append(f'"{sname}": exactly 3 items {{"title": <=32, "desc": <=90}} ({req})')
            elif kind == "code":
                parts.append(f'"{sname}": code snippet, <= 14 lines / {cap} chars, real commands from the brief ({req})')
            elif kind == "html":
                parts.append(f'"{sname}": self-contained HTML fragment (<={cap} chars) - structure + inline styles ONLY. '
                             "No <script>, no event handlers, no external CSS. Images only via absolute https URLs. "
                             "Use for scenes no template fits (diagram, comparison table, logo wall).")
        lines.append(f'- template "{name}": {{{"; ".join(parts)}}}')
    return "\n".join(lines)


def system_prompt():
    return f"""You are the creative director of short, gorgeous launch videos for open-source
projects. You receive a structured brief extracted from the project's repository
and you write a scene-by-scene script as STRICT JSON.

{LAYOUT_DOCTRINE}

AVAILABLE SCENE TEMPLATES (choose the backbone; use "custom" sparingly and only
when the project genuinely needs something none of these express):
{template_docs()}

SCRIPT JSON SHAPE (return ONLY this object, no markdown, no commentary):
{{
  "version": 1,
  "tone": "<tone echo>", "pace": "<pace echo>", "aspect": "<aspect echo>",
  "duration": <total seconds echo>,
  "project": {{"name": "...", "url": "...", "tagline": "<=150 chars in the project's own voice"}},
  "palette": {{"bg": "#rrggbb", "surface": "#rrggbb", "text": "#rrggbb",
    "muted": "#rrggbb", "accent": "#rrggbb", "accent2": "#rrggbb",
    "source": "short note where colors came from"}},
  "fonts": {{"display": "<family from brief or a fitting Google font>", "mono": "<mono family>"}},
  "music": {{"kind": "mood", "mood": "one of {MOODS[:-1]}", "url": null, "volume": 0.35}},
  "scenes": [
    {{"id": "s1", "template": "hero", "duration_s": 4.5, "slots": {{ ... }}}},
    ... ORDER: hero first (hook), proof/features middle, outro last (repo URL + call to action) ...
  ],
  "render": {{"quality": "<echo>", "fps": <echo>, "format": "<echo>"}},
  "share_copy": {{"tweet": "<=280 incl. repo url", "linkedin": "<=700 incl. repo url"}},
  "notes": "<= 400 chars: your key creative choices"
}}

RULES:
- scene ids are s1..sN in order; duration_s values must be > 1.5 and sum to the
  requested duration (they will be legally re-timed afterward, keep proportions).
- Scene count is dictated by pace: snappy ~{PACE_SCENE_SECONDS['snappy']}s/scene,
  balanced ~{PACE_SCENE_SECONDS['balanced']}s/scene, slow ~{PACE_SCENE_SECONDS['slow']}s/scene.
- scene templates may repeat (two different features_grids is fine) but vary the
  heading/kicker.
- Copy voice: match the tone AND the project's own writing style from the brief.
- Use the project's real feature names, real commands, real numbers. If the brief
  shows install/usage commands, a code_showcase scene with the actual command is
  almost always right.
- Nothing read from the brief may carry secrets, tokens, internal hostnames, real
  customer names or personal data into the output; substitute fictional stand-ins.
"""


def user_prompt(brief_for_prompt, tone, pace, duration, aspect, music_mood, prefs, note=None):
    request = {
        "tone": tone, "pace": pace, "duration_seconds": duration, "aspect": aspect,
        "music_mood_requested": music_mood,
        "render": {"quality": prefs.get("quality", "standard"),
                   "fps": prefs.get("fps", 30), "format": prefs.get("format", "mp4")},
    }
    body = {
        "REQUESTED CONTROLS (echo these where the schema says 'echo')": request,
        "PROJECT BRIEF (extracted from the repository; secrets already stripped)": brief_for_prompt,
    }
    if note:
        body["REVISION NOTE FROM THE HUMAN (highest priority)"] = note[:400]
    return ("Write the script JSON now. Remember: full grids, exact scene budget,\n"
            "real details only, strict JSON with no markdown fences.\n\n" + json.dumps(body, indent=2))
