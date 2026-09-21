"""Personal tool validation - pro limits, full HyperFrames throttle."""
import base64
import json
import math
import re
from html.parser import HTMLParser

MARKER = "<!-- hyperframes-pilot:v1 -->"
# For private personal tool, accept both old public consent and new private consent
CONSENT_PUBLIC = "- [X] I understand that my HTML and video will be public, and I have the rights to publish them."
CONSENT_PRIVATE = "- [X] I understand this is a private render for my own projects and I have the rights to use the content."
CONSENT_ALT = "- [X] I understand my video will be stored as a private release and I have the rights to publish it."

class InvalidRequest(ValueError):
    pass


class Composition(HTMLParser):
    def __init__(self):
        super().__init__()
        self.roots = []
        self.composition_vars = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "data-composition-id" in data:
            self.roots.append(data)
            # Try to parse composition variables
            if "data-composition-variables" in data:
                try:
                    vars_raw = data["data-composition-variables"]
                    self.composition_vars = json.loads(vars_raw)
                except:
                    pass


def validate_html(html, policy):
    if not isinstance(html, str) or not html.strip():
        raise InvalidRequest("Choose a non-empty HTML file.")
    if len(html.encode("utf-8")) > policy["max_html_bytes"]:
        raise InvalidRequest(f"This HTML file exceeds the personal tool limit of {policy['max_html_bytes'] // (1024*1024)} MB.")
    parser = Composition()
    parser.feed(html)
    if len(parser.roots) != 1:
        raise InvalidRequest("Use a single HyperFrames composition with data-composition-id, data-width, data-height, and data-duration.")
    root = parser.roots[0]
    try:
        width, height = int(root["data-width"]), int(root["data-height"])
        duration = float(root["data-duration"])
    except (KeyError, ValueError, TypeError):
        raise InvalidRequest("The composition must declare its width, height, and duration.") from None
    if not math.isfinite(duration) or not 0 < duration <= policy["max_duration_seconds"]:
        raise InvalidRequest(f"The composition exceeds duration limit of {policy['max_duration_seconds']}s or has invalid duration.")
    if not (0 < width <= policy["max_dimension"] and 0 < height <= policy["max_dimension"] and width * height <= policy["max_pixels"]):
        raise InvalidRequest(f"Use dimensions up to {policy['max_dimension']} per side and {policy['max_pixels']//1000000}MP total (4K ready).")
    if width % 2 or height % 2:
        raise InvalidRequest("Use even-numbered width and height for MP4/WebM/MOV output.")
    return {"width": width, "height": height, "duration": duration, "variables_schema": parser.composition_vars}


def parse_request(body, policy):
    if not isinstance(body, str) or len(body) > 600000:
        raise InvalidRequest("The render request is too large for GitHub (max 500k). Use smaller HTML or external asset URLs.")
    body_lower = body.lower()
    has_consent = (
        CONSENT_PUBLIC.lower() in body_lower.splitlines() or
        CONSENT_PRIVATE.lower() in body_lower.splitlines() or
        CONSENT_ALT.lower() in body_lower.splitlines() or
        "i understand" in body_lower  # more permissive for personal
    )
    if not has_consent:
        raise InvalidRequest("Please accept the sharing checkbox on the submission form.")

    packets = re.findall(r"^HF1\.([A-Za-z0-9+/=]+)$", body, re.M)
    if len(packets) != 1:
        raise InvalidRequest("Copy a fresh render request from the studio and paste it in full.")
    try:
        packet = json.loads(base64.b64decode(packets[0], validate=True).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise InvalidRequest("The render request is damaged. Copy a fresh request from the studio.") from None

    if not isinstance(packet, dict):
        raise InvalidRequest("Invalid request packet.")

    version = packet.get("version")
    if version not in (1, 2):
        raise InvalidRequest("Use a request created by the personal studio (v1 or v2).")

    # v1 was public, v2 is private pro - accept both for backwards compat
    html = packet.get("html")
    props = validate_html(html, policy)
    title = packet.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise InvalidRequest("Give your video a name between 1 and 100 characters.")
    title = re.sub(r"[\x00-\x1f\x7f]", " ", title).strip()

    # Pro options - with sensible defaults and validation
    fps = packet.get("fps", 30)
    try:
        fps = int(fps)
        if fps not in [24, 30, 60] and not (1 <= fps <= 60):
            fps = 30
        if fps > policy.get("max_fps", 60):
            fps = policy.get("max_fps", 60)
    except:
        fps = 30

    quality = packet.get("quality", "standard")
    if quality not in policy.get("allowed_qualities", ["draft", "standard", "high"]):
        quality = "standard"

    fmt = packet.get("format", "mp4")
    if fmt not in policy.get("allowed_formats", ["mp4", "webm", "mov"]):
        fmt = "mp4"

    resolution = packet.get("resolution", "original")
    variables = packet.get("variables", {})
    if not isinstance(variables, dict):
        variables = {}

    # Sanitize variables - ensure simple types
    clean_vars = {}
    for k, v in variables.items():
        if isinstance(k, str) and len(k) <= 100:
            if isinstance(v, (str, int, float, bool)) and (not isinstance(v, str) or len(v) <= 5000):
                clean_vars[k] = v

    return {
        "title": title,
        "html": html,
        "fps": fps,
        "quality": quality,
        "format": fmt,
        "resolution": resolution,
        "variables": clean_vars,
        **props
    }


def enforce_quota(issue, issues, policy):
    """For personal private mode, quotas are effectively unlimited.
    If private_mode is true, skip all quota checks.
    Otherwise count only for backward compat but with high limits.
    """
    if policy.get("private_mode"):
        # Private personal tool: no quota enforcement, only check issue exists
        return

    users = {name.lower() for name in policy.get("approved_users", [])}
    if not users:
        return

    day = issue["created_at"][:10]
    eligible = [i for i in issues if not i.get("pull_request")
                and i["number"] <= issue["number"] and i["created_at"][:10] == day
                and i["user"]["login"].lower() in users]
    if not any(i["number"] == issue["number"] for i in eligible):
        # In private mode, don't fail on index check - just log
        if not policy.get("private_mode"):
            raise InvalidRequest("The submission index is not ready. Please ask the owner to check this request.")
    own = sum(i["user"]["login"].lower() == issue["user"]["login"].lower() for i in eligible)
    if own > policy["per_user_daily"] or len(eligible) > policy["global_daily"]:
        raise InvalidRequest("Today's limit has been reached. Limits are 1000/day in personal mode.")
