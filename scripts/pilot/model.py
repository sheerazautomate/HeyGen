"""Pure validation for the public pilot. Parsing is NOT an execution sandbox."""
import base64
import json
import math
import re
from html.parser import HTMLParser

MARKER = "<!-- hyperframes-pilot:v1 -->"
CONSENT = "- [X] I understand that my HTML and video will be public, and I have the rights to publish them."


class InvalidRequest(ValueError):
    pass


class Composition(HTMLParser):
    def __init__(self):
        super().__init__()
        self.roots = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "data-composition-id" in data:
            self.roots.append(data)


def validate_html(html, policy):
    if not isinstance(html, str) or not html.strip():
        raise InvalidRequest("Choose a non-empty HTML file.")
    if len(html.encode("utf-8")) > policy["max_html_bytes"]:
        raise InvalidRequest("This HTML file exceeds the pilot's file-size limit.")
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
        raise InvalidRequest("The composition exceeds the pilot's duration limit or has an invalid duration.")
    if not (0 < width <= policy["max_dimension"] and 0 < height <= policy["max_dimension"] and width * height <= policy["max_pixels"]):
        raise InvalidRequest("Use dimensions up to 1920 pixels per side and 1080p total pixels.")
    if width % 2 or height % 2:
        raise InvalidRequest("Use even-numbered width and height for MP4 output.")
    return {"width": width, "height": height, "duration": duration}


def parse_request(body, policy):
    if not isinstance(body, str) or len(body) > 65000:
        raise InvalidRequest("The render request is too large.")
    if CONSENT.lower() not in body.lower().splitlines():
        raise InvalidRequest("Please accept the public-sharing checkbox on the submission form.")
    packets = re.findall(r"^HF1\.([A-Za-z0-9+/=]+)$", body, re.M)
    if len(packets) != 1:
        raise InvalidRequest("Copy a fresh render request from the studio and paste it in full.")
    try:
        packet = json.loads(base64.b64decode(packets[0], validate=True).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise InvalidRequest("The render request is damaged. Copy a fresh request from the studio.") from None
    if not isinstance(packet, dict) or packet.get("version") != 1 or packet.get("public") is not True:
        raise InvalidRequest("Use a public render request created by the studio.")
    html = packet.get("html")
    props = validate_html(html, policy)
    title = packet.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise InvalidRequest("Give your video a name between 1 and 100 characters.")
    title = re.sub(r"[\x00-\x1f\x7f]", " ", title).strip()
    return {"title": title, "html": html, **props}


def enforce_quota(issue, issues, policy):
    """Count ALL earlier issues by approved users, including invalid/closed ones.

    Never key quota accounting off editable titles, bodies, labels, or states.
    Request creation reserves a slot even when validation/rendering fails.
    """
    users = {name.lower() for name in policy["approved_users"]}
    day = issue["created_at"][:10]
    eligible = [i for i in issues if not i.get("pull_request")
                and i["number"] <= issue["number"] and i["created_at"][:10] == day
                and i["user"]["login"].lower() in users]
    if not any(i["number"] == issue["number"] for i in eligible):
        raise InvalidRequest("The submission index is not ready. Please ask the owner to check this request.")
    own = sum(i["user"]["login"].lower() == issue["user"]["login"].lower() for i in eligible)
    if own > policy["per_user_daily"] or len(eligible) > policy["global_daily"]:
        raise InvalidRequest("Today's pilot limit has been reached. Please submit again tomorrow (limits reset at midnight UTC).")
