"""Trusted status update, using only fixed status/message values."""
import os
from admit import state_body
from github import GitHub

MESSAGES = {
    "creating": "Your video is being created. You can leave this page and come back later.",
    "failed": "We could not finish this video. Check that it uses a supported self-contained HyperFrames composition. Ask the owner to check the run before submitting again.",
}
api = GitHub()
status = os.environ["PILOT_STATUS"]
comment = int(os.environ["PILOT_COMMENT"])
api.request(f"issues/comments/{comment}", "PATCH", {"body": state_body(
    status, MESSAGES[status], run_url=f"https://github.com/{api.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}")})
