"""Publish media in a fresh runner that has never executed the composition."""
import json
import os
from pathlib import Path
import subprocess
from admit import state_body
from github import GitHub

api = GitHub()
meta = json.loads(Path("build/request/manifest.json").read_text())
number = int(meta["issue"])
tag = f"video-pilot-{number}"
notes = (f"Public pilot video submitted by @{meta['author']}.\n\n"
         f"Request: https://github.com/{api.repo}/issues/{number}\n\n"
         f"MP4 · 30 fps · {meta['width']} × {meta['height']} · {meta['duration']:g} seconds\n\n"
         f"{meta['run_url']}\n\nSource HTML is public in the original request. Treat it as untrusted code.")
Path("build/notes.md").write_text(notes, encoding="utf-8")
assets = ["build/media/video.mp4"]
if Path("build/media/thumbnail.jpg").is_file():
    assets.append("build/media/thumbnail.jpg")
# No source HTML served from the site's origin; no commands built from user text.
subprocess.run(["gh", "release", "create", tag, *assets, "--repo", api.repo,
                "--target", os.environ["GITHUB_SHA"], "--title", meta["title"],
                "--notes-file", "build/notes.md", "--latest=false"], check=True, timeout=180)
api.request(f"issues/comments/{int(meta['comment'])}", "PATCH", {"body": state_body(
    "ready", "Your video is ready to watch and download in the studio.",
    tag=tag, run_url=meta["run_url"])})
# Publishing and the ready status succeeded. Closing is convenience, not a
# reason to mark a successfully published video as failed.
try:
    api.request(f"issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
except Exception:
    print("Video published; the request could not be closed automatically.")
