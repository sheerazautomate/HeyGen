"""Personal tool admission - private mode, unlimited, full throttle.

Only this job needs issue-write; it never executes HTML or invokes a browser.
"""
import json
import os
from pathlib import Path

from github import GitHub
from model import MARKER, InvalidRequest, enforce_quota, parse_request


def state_body(status, message, **extra):
    state = {"status": status, "message": message, **extra}
    return f"{MARKER}\n```json\n{json.dumps(state, ensure_ascii=True)}\n```\n\n{message}\n"


def admit(api, event, policy, destination):
    issue = event["issue"]
    number = int(issue["number"])
    # Unrelated issues incur only this cheap gate, never an image build/render.
    if not (issue.get("title", "").startswith("[Video]") or "HF1." in (issue.get("body") or "")):
        return None
    comments = api.pages(f"issues/{number}/comments")
    prior = [c for c in comments if c["user"]["login"] == "github-actions[bot]"
             and c["user"]["type"] == "Bot" and c.get("body", "").startswith(MARKER)]
    if prior:
        return None
    try:
        if not policy["enabled"]:
            raise InvalidRequest("Rendering is paused. Re-enable in pilot.json.")

        # Private mode: skip approval check, allow owner or any if private_mode
        if not policy.get("private_mode"):
            # Legacy approval check for public pilot, but in personal tool we allow all
            approved = {u.lower() for u in policy.get("approved_users", [])}
            if approved and issue["user"]["login"].lower() not in approved:
                raise InvalidRequest("This account is not approved. In private mode, add your username to approved_users or enable private_mode.")

        current = api.request(f"issues/{number}")
        if current["state"] != "open" or current.get("body") != issue.get("body"):
            raise InvalidRequest("This request was closed or edited before processing. Please submit a new request from the studio.")

        # Quota - skipped in private_mode inside enforce_quota
        if not policy.get("private_mode"):
            from urllib.parse import quote
            since = quote(issue["created_at"][:10] + "T00:00:00Z")
            issues = api.pages(f"issues?state=all&since={since}&sort=created&direction=asc")
            enforce_quota(issue, issues, policy)
        else:
            # Still call enforce_quota but it will no-op in private_mode
            enforce_quota(issue, [], policy)

        packet = parse_request(issue.get("body") or "", policy)
    except InvalidRequest as exc:
        api.request(f"issues/{number}/comments", "POST", {"body": state_body("rejected", str(exc))})
        return None
    run_id = os.environ["GITHUB_RUN_ID"]
    run_url = f"https://github.com/{api.repo}/actions/runs/{run_id}"
    comment = api.request(f"issues/{number}/comments", "POST", {"body": state_body(
        "queued", f"Accepted: {packet['width']}x{packet['height']}, {packet['duration']}s, {packet['fps']}fps, {packet['quality']} quality, {packet['format']}. Preparing pro renderer.", run_url=run_url)})
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(packet.pop("html"), encoding="utf-8")
    # Write variables as separate file for renderer
    variables = packet.get("variables", {})
    (destination / "variables.json").write_text(json.dumps(variables), encoding="utf-8")
    meta = {**packet, "issue": number, "author": issue["user"]["login"],
            "comment": int(comment["id"]), "run_id": run_id, "run_url": run_url}
    (destination / "manifest.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def main():
    policy = json.loads(Path(".github/pilot.json").read_text())
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    result = admit(GitHub(), event, policy, Path("build/request"))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"accepted={'true' if result else 'false'}\n")
        if result:
            output.write(f"issue={result['issue']}\ncomment={result['comment']}\n")


if __name__ == "__main__":
    main()
