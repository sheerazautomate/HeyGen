#!/usr/bin/env python3
"""Story mode CLI - the glue between repo analysis, script generation,
composition, music synthesis and the GitHub two-phase flow.

Subcommands (all stdlib-only, safe in Actions runners):
  analyze     clone + analyze repo, generate script+storyboard+packet (phase 1)
  prepare     decode ST1 packet, apply /render overrides, emit build/request (phase 2)
  regenerate  same generation as analyze but local-only (--brief file supported)
  compose     script.json -> composition index.html
  music       synthesize a mood track to WAV
  storyboard  render the storyboard markdown from script.json
  post        post a comment file to an issue (prints the comment id)
  find-story  print the ST1 packet from an issue's storyboard comment
"""
import argparse
import base64
import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # scripts/ -> `story` package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pilot"))  # github client

from story.analyze import analyze_repo, brief_for_prompt            # noqa: E402
from story.commands import parse_command, validate_scene_edits, has_script_changes, CommandError  # noqa: E402
from story.compose import compose_to_file, width_for                # noqa: E402
from story.fetch_repo import validate_repo_url, clone_repo, FetchError  # noqa: E402
from story.llm import resolve_provider, chat_json, LLMError         # noqa: E402
from story.music import render_wav, fetch_custom, metadata, describe  # noqa: E402
from story.offline import generate_offline                          # noqa: E402
from story.prompts import system_prompt, user_prompt                # noqa: E402
from story.schema import normalize_script, ScriptError, TEMPLATE_SLOTS  # noqa: E402

STORY_MARKER = "<!-- hyperframes-story:v1 -->"
PACKET_PREFIX = "ST1."
MAX_PACKET_CHARS = 60000  # stays inside GitHub's comment limit with room for the storyboard


# --------------------------------------------------------------------------- #
# packets                                                                      #
# --------------------------------------------------------------------------- #

def encode_packet(script, engine, repo_url, logo_url=None):
    packed = {"v": 1, "script": script, "engine": engine, "repo": repo_url,
              "logo_url": logo_url}
    blob = base64.urlsafe_b64encode(gzip.compress(
        json.dumps(packed, separators=(",", ":")).encode(), compresslevel=9)).decode()
    packet = PACKET_PREFIX + blob
    if len(packet) > MAX_PACKET_CHARS:
        raise ScriptError("Script packet too large for a GitHub comment - try a shorter video.")
    return packet


def decode_packet(packet):
    if not isinstance(packet, str) or not packet.startswith(PACKET_PREFIX):
        raise ScriptError("Not a story packet (expected ST1....).")
    try:
        raw = gzip.decompress(base64.urlsafe_b64decode(packet[len(PACKET_PREFIX):]))
        packed = json.loads(raw)
    except (ValueError, OSError) as exc:
        raise ScriptError("Story packet is damaged - ask for a fresh /story run.") from exc
    script = packed.get("script")
    if not isinstance(script, dict):
        raise ScriptError("Story packet has no script.")
    return packed


# --------------------------------------------------------------------------- #
# generation                                                                   #
# --------------------------------------------------------------------------- #

def generate_script(brief, controls, note=None):
    """Returns (script, meta). Falls back to the offline generator on any LLM issue."""
    prefs = controls.get("prefs", {})
    tone, pace = controls["tone"], controls["pace"]
    duration, aspect = controls["duration"], controls["aspect"]
    music_mood = controls.get("music_mood", "upbeat")

    provider, config = resolve_provider(controls.get("provider"))
    warnings = []
    raw = None
    engine = "offline"

    if provider != "offline":
        brief_prompt = brief_for_prompt(brief)
        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": user_prompt(brief_prompt, tone, pace, duration,
                                                    aspect, music_mood, prefs, note=note)},
        ]
        try:
            raw = chat_json(messages, config)
            engine = f"{provider} ({config['model']})"
        except LLMError as exc:
            warnings.append(f"LLM failed ({exc}); used offline generator instead.")

    if raw is None:
        raw, off_warnings = generate_offline(brief, tone, pace, duration, aspect, music_mood, prefs)
        warnings.extend(off_warnings)
        if provider == "offline":
            warnings.append(f"offline generator: {config.get('reason', 'no provider configured')}")

    # user-requested music always wins over model taste
    music_url = prefs.get("music_url")
    raw.setdefault("music", {})
    if music_url:
        raw["music"] = {"kind": "url", "url": music_url, "volume": raw["music"].get("volume", 0.35)}
    elif music_mood == "none":
        raw["music"] = {"kind": "none"}
    else:
        raw["music"]["kind"], raw["music"]["mood"] = "mood", music_mood
    raw.update({"tone": tone, "pace": pace, "duration": duration, "aspect": aspect,
                "render": {"quality": prefs.get("quality", "standard"),
                           "fps": prefs.get("fps", 30), "format": prefs.get("format", "mp4")}})

    try:
        script, norm_warnings = normalize_script(raw)
        warnings.extend(norm_warnings)
    except ScriptError as exc:
        if engine != "offline":
            warnings.append(f"LLM script invalid ({exc}); used offline generator instead.")
            raw, _ = generate_offline(brief, tone, pace, duration, aspect, music_mood, prefs)
            raw["music"] = raw.get("music") or {"kind": "mood", "mood": music_mood}
            script, norm_warnings = normalize_script(raw)
            warnings.extend(norm_warnings)
            engine = "offline"
        else:
            raise
    return script, {"engine": engine, "warnings": warnings}


def controls_from_args(args):
    return {
        "tone": args.tone, "pace": args.pace, "duration": args.length,
        "aspect": args.aspect, "music_mood": args.music_mood,
        "provider": getattr(args, "provider", None),
        "prefs": {"quality": args.quality, "fps": args.fps, "format": args.format,
                  "music_url": getattr(args, "music_url", None)},
    }


def add_control_args(p):
    p.add_argument("--tone", default="cinematic")
    p.add_argument("--pace", default="balanced")
    p.add_argument("--length", type=float, default=30)
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    p.add_argument("--music-mood", default="upbeat")
    p.add_argument("--music-url", default=None)
    p.add_argument("--quality", default="standard")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--format", default="mp4")
    p.add_argument("--provider", default=None)


# --------------------------------------------------------------------------- #
# storyboard                                                                   #
# --------------------------------------------------------------------------- #

def _scene_summary(scene):
    slots = scene["slots"]
    for key in ("headline", "heading", "statement"):
        if slots.get(key):
            return slots[key]
    if slots.get("features"):
        return slots["features"][0]["title"] + (" …" if len(slots["features"]) > 1 else "")
    if slots.get("stats"):
        return f"{slots['stats'][0]['value']} {slots['stats'][0]['label']}"
    if slots.get("items"):
        return ", ".join(slots["items"][:3]) + " …"
    if slots.get("code"):
        return "`" + slots["code"].splitlines()[0][:50] + "`"
    return "(custom scene)"


def scene_edit_help(scene):
    spec = TEMPLATE_SLOTS[scene["template"]]
    return ", ".join(n for n, (k, _, _) in spec.items() if k == "text") or "—"


def storyboard_md(script, meta, repo_url, packet):
    p = script["palette"]
    rows = []
    t = 0.0
    for i, s in enumerate(script["scenes"]):
        rows.append(f"| {i+1} | `{s['id']}` | {s['template']} | {t:g}s–{t + s['duration_s']:g}s "
                    f"| {_scene_summary(s)} | {scene_edit_help(s)} |")
        t += s["duration_s"]
    warnings = meta.get("warnings") or []
    warn_block = ""
    if warnings:
        warn_block = "\n> **Notes from the generator:** " + " · ".join(w[:160] for w in warnings[:5]) + "\n"
    return f"""{STORY_MARKER}
## 🎬 Storyboard — {script['project']['name']}

**Repo:** {repo_url} · **Engine:** {meta.get('engine', 'offline')} · **Tone:** {script['tone']} · **Pace:** {script['pace']} · **Length:** {script['duration']:g}s · **Aspect:** {script['aspect']}
**Render:** {script['render']['quality']} · {script['render']['fps']}fps · {script['render']['format']} · **Music:** {describe(script['music']['kind'], script['music'].get('mood'), script['music'].get('url'))}
{warn_block}
### Palette (from {p.get('source', 'defaults')})
| role | color |
|---|---|
| background | `{p['bg']}` |
| surface | `{p['surface']}` |
| text | `{p['text']}` |
| muted | `{p['muted']}` |
| accent | `{p['accent']}` |
| accent 2 | `{p['accent2']}` |

### Scenes
| # | id | template | window | content | editable slots |
|---|---|---|---|---|---|
{chr(10).join(rows)}

### Next step — pick one
- ✅ **`/render`** — render exactly this
- 🎛 **`/render quality:high fps:60 format:webm`** — change render settings only
- 🎨 **`/render tone:playful pace:snappy length:45`** — regenerate script with new tone/pace/length, then render
- 🎵 **`/render music:lofi`** or **`/render music_url:"https://…/track.mp3"`** — swap the music
- ✏️ **`/render s2.heading:"A better heading"`** — edit copy directly (slot names in the table)
- 💬 **`/render note:"make it punchier"`** — free-form revision for the writer
- 🔁 **`/story tone:corporate`** — regenerate the storyboard only (no render)

<details><summary>Full script (JSON)</summary>

```json
{json.dumps(script, indent=2)[:12000]}
```

</details>

<details><summary>Story packet (used by the renderer — keep this comment intact)</summary>

```
{packet}
```

</details>
"""


# --------------------------------------------------------------------------- #
# subcommands                                                                  #
# --------------------------------------------------------------------------- #

def cmd_analyze(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    canonical = validate_repo_url(args.repo)
    repo_root = clone_repo(canonical, out / "repo", max_mb=args.max_repo_mb)
    brief = analyze_repo(repo_root, canonical)
    brief["fonts"] = brief.get("fonts") or {}
    logo_rel = None
    try:
        from story.fetch_repo import find_logo, raw_url
        logo_rel = find_logo(repo_root)
    except OSError:
        pass
    logo_url = (raw_url(canonical, logo_rel) if logo_rel else None) if logo_rel else None

    controls = controls_from_args(args)
    script, meta = generate_script(brief, controls, note=args.note)
    packet = encode_packet(script, meta["engine"], canonical, logo_url=logo_url)
    compose_to_file(script, out / "composition", logo_url=logo_url)

    (out / "brief.json").write_text(json.dumps(brief, indent=2)[:40000])
    (out / "script.json").write_text(json.dumps(script, indent=2))
    (out / "meta.json").write_text(json.dumps({**meta, "logo_url": logo_url, "repo": canonical}, indent=2))
    (out / "packet.txt").write_text(packet)
    (out / "storyboard.md").write_text(storyboard_md(script, meta, canonical, packet))
    print(f"engine={meta['engine']}")
    print(f"scenes={len(script['scenes'])} duration={script['duration']}")
    print(f"storyboard: {out / 'storyboard.md'}")


def cmd_prepare(args):
    """Phase 2: packet + /render overrides -> build/request ready for run_sandbox.sh."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    packed = decode_packet(Path(args.packet).read_text().strip() if Path(args.packet).is_file()
                           else args.packet)
    script = packed["script"]
    engine = packed.get("engine", "unknown")

    cmd = parse_command(args.comment or "", script)
    applied_edits, regenerated = [], False
    if cmd:
        overrides = dict(cmd["script_overrides"])
        if has_script_changes(cmd):
            # regenerate from a fresh clone with merged controls
            canonical = validate_repo_url(packed["repo"])
            tmp = out.parent / "story-regen"
            repo_root = clone_repo(canonical, tmp / "repo")
            brief = analyze_repo(repo_root, canonical)
            controls = {
                "tone": overrides.get("tone", script["tone"]),
                "pace": overrides.get("pace", script["pace"]),
                "duration": float(overrides.get("duration", script["duration"])),
                "aspect": overrides.get("aspect", script["aspect"]),
                "music_mood": overrides.get("music_mood", script["music"].get("mood", "upbeat")),
                "provider": args.provider,
                "prefs": {"quality": script["render"]["quality"], "fps": script["render"]["fps"],
                          "format": script["render"]["format"],
                          "music_url": script["music"].get("url")},
            }
            script, meta = generate_script(brief, controls, note=cmd["note"])
            engine = meta["engine"]
            regenerated = True
        try:
            applied_edits = validate_scene_edits(cmd["scene_edits"], script)
        except CommandError:
            raise
        # render-level overrides
        ro = cmd["render_overrides"]
        script["render"].update({k: ro[k] for k in ("quality", "fps", "format") if k in ro})
        if ro.get("music_kind") == "none":
            script["music"] = {"kind": "none"}
        elif ro.get("music_kind") == "url" and ro.get("music_url"):
            script["music"] = {"kind": "url", "url": ro["music_url"],
                               "volume": script["music"].get("volume", 0.35)}
    if applied_edits or regenerated or cmd:
        script, w = normalize_script(script)

    logo_url = packed.get("logo_url")
    meta_path = Path(args.meta) if args.meta else None
    if meta_path and meta_path.is_file():
        logo_url = json.loads(meta_path.read_text()).get("logo_url") or logo_url
    compose_to_file(script, out, logo_url=logo_url)

    # music artifacts (render.sh picks these up inside the sandbox)
    music = script["music"]
    if music["kind"] == "mood":
        render_wav(music["mood"], script["duration"], out / "music.wav",
                   seed_text=script["project"]["name"])
        (out / "music.json").write_text(metadata("mood", music["mood"], None, music.get("volume", 0.35)))
    elif music["kind"] == "url":
        fetch_custom(music["url"], out)
        (out / "music.json").write_text(metadata("url", None, music["url"], music.get("volume", 0.35)))

    (out / "variables.json").write_text("{}")
    w_, h_ = width_for(script["aspect"])
    manifest = {
        "title": f"{script['project']['name']} — story video",
        "width": w_, "height": h_, "duration": script["duration"],
        "fps": script["render"]["fps"], "quality": script["render"]["quality"],
        "format": script["render"]["format"], "variables": {},
        "story": {"engine": engine, "regenerated": regenerated, "edits": applied_edits,
                  "tone": script["tone"], "pace": script["pace"],
                  "music": describe(script["music"]["kind"], script["music"].get("mood"),
                                    script["music"].get("url"))},
    }
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "script.json").write_text(json.dumps(script, indent=2))
    print(f"engine={engine} regenerated={regenerated} edits={len(applied_edits)}")
    print(f"prepared: {out}")


def cmd_regenerate(args):
    brief = json.loads(Path(args.brief).read_text()) if args.brief else None
    if brief is None:
        canonical = validate_repo_url(args.repo)
        repo_root = clone_repo(canonical, Path(args.out) / "repo")
        brief = analyze_repo(repo_root, canonical)
    controls = controls_from_args(args)
    script, meta = generate_script(brief, controls, note=args.note)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text(json.dumps(script, indent=2))
    compose_to_file(script, out / "composition")
    print(f"engine={meta['engine']}")
    for wrn in meta["warnings"]:
        print(f"warning: {wrn}")
    print(f"script: {out / 'script.json'}")


def cmd_compose(args):
    script = json.loads(Path(args.script).read_text())
    path = compose_to_file(script, args.out, logo_url=args.logo)
    print(path)


def cmd_music(args):
    path = render_wav(args.mood, args.seconds, args.out, seed_text=args.seed)
    print(path)


def cmd_storyboard(args):
    script = json.loads(Path(args.script).read_text())
    meta = json.loads(Path(args.meta).read_text()) if args.meta and Path(args.meta).is_file() else {"engine": "unknown", "warnings": []}
    packet = Path(args.packet).read_text().strip() if args.packet else "(packet omitted)"
    print(storyboard_md(script, meta, args.repo or script["project"]["url"], packet))


def cmd_parse_issue(args):
    from story.commands import parse_issue_form, merge_command_into_form
    body = args.body if args.body is not None else sys.stdin.read()
    form = parse_issue_form(body)
    note = None
    if args.comment:
        cmd = parse_command(args.comment)
        if cmd:
            form = merge_command_into_form(form, cmd)
            note = cmd.get("note")
    print(json.dumps({"form": form, "note": note}))


def _gh():
    from github import GitHub
    return GitHub()


def cmd_post(args):
    api = _gh()
    body = Path(args.body).read_text()
    comment = api.request(f"issues/{args.issue}/comments", "POST", {"body": body})
    print(comment["id"])


def _extract_packet(text):
    if not text:
        return None
    import re as _re
    m = _re.search(r"ST1\.[A-Za-z0-9_=-]+", text)
    return m.group(0) if m else None


def cmd_find_story(args):
    api = _gh()
    comments = api.pages(f"issues/{args.issue}/comments")
    for c in comments:
        body = c.get("body") or ""
        if body.startswith(STORY_MARKER):
            packet = _extract_packet(body)
            if packet:
                Path(args.out).write_text(packet)
                print(f"comment={c['id']}")
                return
    raise ScriptError("No storyboard comment with a story packet found on this issue. "
                      "Open the issue - the storyboard comment should be right after your request.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Story mode: repo link -> script -> video")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="phase 1: repo -> storyboard + packet")
    p.add_argument("--repo", required=True)
    p.add_argument("--out", default="build/story")
    p.add_argument("--max-repo-mb", type=int, default=150)
    p.add_argument("--note", default=None)
    add_control_args(p)
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("prepare", help="phase 2: packet + overrides -> build/request")
    p.add_argument("--packet", required=True, help="ST1.… or path to packet.txt")
    p.add_argument("--comment", default="", help="the /render comment body")
    p.add_argument("--meta", default=None, help="meta.json from analyze (logo_url)")
    p.add_argument("--out", default="build/request")
    p.add_argument("--provider", default=None)
    p.set_defaults(fn=cmd_prepare)

    p = sub.add_parser("regenerate", help="generate script only (local dev)")
    p.add_argument("--repo", default=None)
    p.add_argument("--brief", default=None)
    p.add_argument("--out", default="build/story")
    p.add_argument("--note", default=None)
    add_control_args(p)
    p.set_defaults(fn=cmd_regenerate)

    p = sub.add_parser("compose")
    p.add_argument("--script", required=True)
    p.add_argument("--out", default="build/composition")
    p.add_argument("--logo", default=None)
    p.set_defaults(fn=cmd_compose)

    p = sub.add_parser("music")
    p.add_argument("--mood", default="upbeat")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--out", default="build/story/music.wav")
    p.add_argument("--seed", default="story")
    p.set_defaults(fn=cmd_music)

    p = sub.add_parser("storyboard")
    p.add_argument("--script", required=True)
    p.add_argument("--meta", default=None)
    p.add_argument("--packet", default=None)
    p.add_argument("--repo", default=None)
    p.set_defaults(fn=cmd_storyboard)

    p = sub.add_parser("post", help="post comment file to an issue")
    p.add_argument("--issue", required=True, type=int)
    p.add_argument("--body", required=True)
    p.set_defaults(fn=cmd_post)

    p = sub.add_parser("find-story", help="extract story packet from issue comments")
    p.add_argument("--issue", required=True, type=int)
    p.add_argument("--out", default="build/story-packet.txt")
    p.set_defaults(fn=cmd_find_story)

    p = sub.add_parser("parse-issue", help="print story controls from an issue-form body as JSON")
    p.add_argument("--body", default=None, help="body text (else stdin)")
    p.add_argument("--comment", default=None, help="optional /story comment to merge")
    p.set_defaults(fn=cmd_parse_issue)

    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except (FetchError, ScriptError, CommandError, LLMError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
