"""Publish media in a fresh runner - personal pro version with full format support."""
import json
import os
from pathlib import Path
import subprocess
from admit import state_body
from github import GitHub

api = GitHub()
meta = json.loads(Path("build/request/manifest.json").read_text())
number = int(meta.get("issue") or 0)
tag = f"video-pilot-{number}" if number else f"video-story-{os.environ.get('GITHUB_RUN_ID', 'local')}"

fps = meta.get("fps", 30)
quality = meta.get("quality", "standard")
fmt = meta.get("format", "mp4")
duration = meta.get("duration", 0)
width = meta.get("width", 0)
height = meta.get("height", 0)
variables = meta.get("variables", {})

# Private release notes
vars_note = ""
if variables:
    vars_note = f"\nVariables: {json.dumps(variables)[:500]}\n"

author = meta.get("author") or "studio"
issue_line = f"Request: https://github.com/{api.repo}/issues/{number}\n\n" if number else ""
notes = (f"Personal pro render by @{author}.\n\n"
         f"{issue_line}"
         f"Pro settings: {fmt.upper()} · {fps} fps · {quality} quality · {width} × {height} · {duration:g}s\n"
         f"{vars_note}\n"
         f"{meta.get('run_url', '')}\n\n"
         f"Private personal tool output. Full throttle HyperFrames.\n")

Path("build/notes.md").write_text(notes, encoding="utf-8")

assets = []
for name in ["video.mp4", "video.webm", "video.mov", "thumbnail.jpg"]:
    p = Path(f"build/media/{name}")
    if p.is_file():
        assets.append(str(p))

if not assets:
    raise RuntimeError("No media assets to publish")

subprocess.run(["gh", "release", "delete", tag, "--repo", api.repo, "--yes"],
               check=False, timeout=60)
title = meta.get("title") or f"Story video {tag}"
subprocess.run(["gh", "release", "create", tag, *assets, "--repo", api.repo,
                "--target", os.environ["GITHUB_SHA"], "--title", title,
                "--notes-file", "build/notes.md", "--latest=false"], check=True, timeout=180)

comment = meta.get("comment")
if comment:
    api.request(f"issues/comments/{int(comment)}", "PATCH", {"body": state_body(
        "ready", f"Your pro video is ready! {width}x{height}, {fps}fps, {quality}, {fmt.upper()}. Watch and download in the studio.",
        tag=tag, run_url=meta.get("run_url"))})

if number:
    try:
        api.request(f"issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
    except Exception:
        print("Video published; the request could not be closed automatically.")
