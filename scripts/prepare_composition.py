#!/usr/bin/env python3
"""Resolve the HyperFrames composition for the render workflow.

Two trigger paths are supported:
  * repository_dispatch (from the GitHub Pages site):
      client_payload.blob_sha points at a git blob (created via
      POST /repos/{owner}/{repo}/git/blobs) holding the composition HTML.
  * workflow_dispatch (manual / CLI):
      inputs.composition_path points at an HTML file already in the repo.

The resolved HTML is written to <out-dir>/index.html and all render parameters
are emitted as workflow outputs (GITHUB_OUTPUT).
"""

import base64
import json
import os
import re
import sys
import urllib.request

MAX_HTML_BYTES = 4 * 1024 * 1024  # 4 MB is plenty for an HTML composition
VALID_ENGINES = {"auto", "heygen-cloud", "local"}
QUALITY_ALIASES = {"delivery": "high", "looks": "standard"}


def read_event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not os.path.isfile(path):
        raise SystemExit("GITHUB_EVENT_PATH is not set; cannot read the trigger event")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def api_base() -> str:
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def fetch_blob(repo: str, sha: str, token: str) -> str:
    url = f"{api_base()}/repos/{repo}/git/blobs/{sha}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return data.get("content", "")


def emit(path: str, values: dict) -> None:
    if not path:
        raise SystemExit("GITHUB_OUTPUT is not set")
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            text = "" if value is None else str(value)
            if "\n" in text or "\r" in text:
                fh.write(f"{key}<<HF_EOF\n{text}\nHF_EOF\n")
            else:
                fh.write(f"{key}={text}\n")


def clean_title(raw: str, fallback: str) -> str:
    title = re.sub(r"\s+", " ", (raw or "").strip())
    title = re.sub(r"[\x00-\x1f\x7f]", "", title)
    return (title[:180] or fallback)


def main() -> int:
    event = read_event()
    name = os.environ.get("GITHUB_EVENT_NAME", event.get("event_name", ""))
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ.get("GITHUB_TOKEN", "")
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "build/project"
    props = os.environ.get("GITHUB_OUTPUT", "")

    inputs = event.get("inputs") or {}
    payload = (event.get("client_payload") or {}) if name == "repository_dispatch" else {}

    def pick(field, default=""):
        value = payload.get(field, inputs.get(field, default))
        return "" if value is None else str(value).strip()

    # ---- Resolve the HTML ----------------------------------------------------
    if name == "repository_dispatch":
        sha = pick("blob_sha")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            print(f"❌ client_payload.blob_sha is missing or not a valid blob SHA: {sha!r}")
            return 1
        html = fetch_blob(repo, sha, token)
        source = f"git blob {sha[:10]}…"
    else:
        rel = pick("composition_path", "examples/product-launch.html") or "examples/product-launch.html"
        rel = rel.lstrip("/")
        root = os.environ.get("GITHUB_WORKSPACE", ".")
        full = os.path.normpath(os.path.join(root, rel))
        if not full.startswith(os.path.abspath(root) + os.sep):
            print(f"❌ composition_path escapes the workspace: {rel}")
            return 1
        if not os.path.isfile(full):
            print(f"❌ composition_path not found in repo: {rel}")
            return 1
        with open(full, encoding="utf-8") as fh:
            html = fh.read()
        source = f"repo file {rel}"

    raw_bytes = html.encode("utf-8")
    if not raw_bytes.strip():
        print("❌ The composition HTML is empty.")
        return 1
    if len(raw_bytes) > MAX_HTML_BYTES:
        print(f"❌ The composition HTML is {len(raw_bytes)} bytes (max {MAX_HTML_BYTES}).")
        return 1

    warnings = []
    if "data-composition-id" not in html:
        warnings.append("no data-composition-id attribute found — is this a HyperFrames composition?")
    if "__timelines" not in html and "__hf" not in html:
        warnings.append("no timeline registration (__timelines / __hf) found — the render may be static")

    os.makedirs(out_dir, exist_ok=True)
    entry = os.path.join(out_dir, "index.html")
    with open(entry, "w", encoding="utf-8") as fh:
        fh.write(html)

    # ---- Validate + normalise parameters --------------------------------------
    fps_raw = pick("fps", "30")
    try:
        fps = max(1, min(240, int(float(fps_raw))))
    except ValueError:
        fps = 30

    quality = pick("quality", "standard").lower()
    quality = QUALITY_ALIASES.get(quality, quality)
    if quality not in {"draft", "standard", "high"}:
        quality = "standard"

    fmt = pick("format", "mp4").lower()
    if fmt not in {"mp4", "webm", "mov"}:
        fmt = "mp4"

    resolution = pick("resolution", "1080p").lower()
    if resolution not in {"1080p", "4k"}:
        resolution = "1080p"

    aspect = pick("aspect_ratio", "16:9")
    if aspect not in {"16:9", "9:16", "1:1"}:
        aspect = "16:9"

    engine = pick("engine", "auto").lower()
    if engine in {"cloud", "heygen", "heygen_cloud"}:
        engine = "heygen-cloud"
    if engine not in VALID_ENGINES:
        engine = "auto"

    variables = pick("variables_json", "")
    if variables:
        try:
            parsed = json.loads(variables)
            if not isinstance(parsed, dict):
                raise ValueError("must be a JSON object")
            variables = json.dumps(parsed)
        except ValueError as exc:
            print(f"❌ variables_json is not a valid JSON object: {exc}")
            return 1

    lint = pick("lint", "true").lower() in {"1", "true", "yes", "on"}
    render_key = re.sub(r"[^A-Za-z0-9_-]", "", pick("render_key"))[:32] or "manual"
    title = clean_title(pick("title"), f"HyperFrames render #{os.environ.get('GITHUB_RUN_NUMBER', '?')}")

    for warning in warnings:
        print(f"⚠️ {warning}")

    emit(props, {
        "title": title,
        "fps": fps,
        "quality": quality,
        "format": fmt,
        "resolution": resolution,
        "aspect_ratio": aspect,
        "engine": engine,
        "variables_json": variables,
        "lint": "true" if lint else "false",
        "render_key": render_key,
        "source": source,
        "entry": entry,
        "html_bytes": len(raw_bytes),
    })
    print(f"📄 Composition ready: {entry} ({len(raw_bytes)} bytes from {source})")
    print(f"   engine={engine} fps={fps} quality={quality} format={fmt} resolution={resolution} aspect={aspect}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
