"""Trusted status update, pro version."""
import os
from admit import state_body
from github import GitHub

MESSAGES = {
    "creating": "Your pro video is being created with full throttle HyperFrames (network enabled, high quality, up to 4K/60fps). You can leave and come back later - check GitHub Actions for live logs.",
    "failed": "Pro render failed. Check composition uses valid HyperFrames syntax, even dimensions, and external assets are reachable. For long videos, check memory/timeout (15 min limit). Ask owner to check Actions logs.",
}

api = GitHub()
status = os.environ["PILOT_STATUS"]
comment = int(os.environ["PILOT_COMMENT"])
api.request(f"issues/comments/{comment}", "PATCH", {"body": state_body(
    status, MESSAGES[status], run_url=f"https://github.com/{api.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}")})
