#!/usr/bin/env python3
"""Build the same static bundle for Pages and local preview (no npm required)."""
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "build/site"
DEST.mkdir(parents=True, exist_ok=True)
shutil.copytree(ROOT / "site", DEST, dirs_exist_ok=True)
shutil.copytree(ROOT / "examples", DEST / "examples", dirs_exist_ok=True)
policy = json.loads((ROOT / ".github/pilot.json").read_text())
policy.pop("approved_users")
owner, repo = os.environ.get("GITHUB_REPOSITORY", "sheerazautomate/HeyGen").split("/", 1)
config = {"owner": owner, "repo": repo, "pilot": policy}
(DEST / "config.js").write_text("window.SITE_CONFIG = " + json.dumps(config) + ";\n")
print(f"Built {DEST}")
