#!/usr/bin/env python3
"""Render a HyperFrames composition with the HeyGen Cloud Rendering API.

Pipeline (all stdlib, no pip dependencies):
  1. Zip the project directory (must contain index.html at its root).
  2. Submit it inline as base64 to POST /v3/hyperframes/renders.
  3. Poll GET /v3/hyperframes/renders/{render_id} until completed.
  4. Download the finished video (and thumbnail when available).

API reference: https://developers.heygen.com/hyperframes
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

API_BASE = os.environ.get("HEYGEN_API_BASE", "https://api.heygen.com").rstrip("/")
TERMINAL_OK = {"completed", "success"}
TERMINAL_FAIL = {"failed", "error", "cancelled", "canceled", "rejected"}


def log(msg: str) -> None:
    print(msg, flush=True)


def api_call(method: str, path: str, api_key: str, payload=None, extra_headers=None, timeout=120):
    req = urllib.request.Request(API_BASE + path, method=method)
    req.add_header("x-api-key", api_key)
    req.add_header("Accept", "application/json")
    if extra_headers:
        for k, v in extra_headers.items():
            req.add_header(k, v)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw.strip() else {}), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"raw": raw[:2000]}
        return exc.code, parsed, dict(exc.headers)
    except urllib.error.URLError as exc:
        return 0, {"raw": str(exc)}, {}


def zip_project(project_dir: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(project_dir):
            for name in sorted(files):
                full = os.path.join(root, name)
                arc = os.path.relpath(full, project_dir)
                zf.write(full, arc)
    return buf.getvalue()


def download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "heygen-hyperframes-actions/1.0")
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)


def emit_outputs(path: str, values: dict) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            if value is None:
                continue
            value = str(value).replace("\n", " ").replace("\r", " ")
            fh.write(f"{key}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-dir", required=True, help="Directory containing the composition (index.html at root)")
    ap.add_argument("--output", required=True, help="Where to save the rendered video, e.g. out/video.mp4")
    ap.add_argument("--api-key-env", default="HEYGEN_API_KEY", help="Env var holding the HeyGen API key")
    ap.add_argument("--composition", default="index.html", help="Entry HTML path inside the zip")
    ap.add_argument("--title", default="", help="Display title for the render (<=500 chars)")
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--quality", default=None, choices=["draft", "standard", "high"])
    ap.add_argument("--format", default=None, choices=["mp4", "webm", "mov"])
    ap.add_argument("--resolution", default=None, choices=["1080p", "4k"])
    ap.add_argument("--aspect-ratio", default=None, choices=["16:9", "9:16", "1:1"])
    ap.add_argument("--variables", default="", help="JSON object of composition variable overrides")
    ap.add_argument("--timeout-seconds", type=int, default=1800)
    ap.add_argument("--poll-interval", type=float, default=5.0)
    ap.add_argument("--thumbnail-output", default="", help="Where to save the thumbnail, if the API returns one")
    ap.add_argument("--output-props", default=os.environ.get("GITHUB_OUTPUT", ""), help="File for key=value outputs")
    args = ap.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        log("❌ No HeyGen API key found (set the %s environment variable)." % args.api_key_env)
        return 1

    # ---- 1. Zip the project ------------------------------------------------
    entry = os.path.join(args.project_dir, args.composition)
    if not os.path.isfile(entry):
        log(f"❌ Composition entry not found: {entry}")
        return 1
    zipped = zip_project(args.project_dir)
    if len(zipped) > 25 * 1024 * 1024:
        log(f"❌ Project zip is {len(zipped)} bytes; inline base64 submission is capped around 25 MB. "
            "Trim assets or pre-upload the zip via POST /v3/assets instead.")
        return 1
    log(f"📦 Project zip: {len(zipped)} bytes")

    variables = None
    if args.variables.strip():
        try:
            variables = json.loads(args.variables)
            if not isinstance(variables, dict):
                raise ValueError("variables must be a JSON object")
        except ValueError as exc:
            log(f"❌ Invalid --variables JSON: {exc}")
            return 1

    # ---- 2. Submit the render ----------------------------------------------
    payload = {
        "project": {"type": "base64", "media_type": "application/zip", "data": base64.b64encode(zipped).decode("ascii")},
        "composition": args.composition,
    }
    for key, value in (
        ("fps", args.fps),
        ("quality", args.quality),
        ("format", args.format),
        ("resolution", args.resolution),
        ("aspect_ratio", args.aspect_ratio),
        ("title", (args.title or "")[:500]),
    ):
        if value not in (None, ""):
            payload[key] = value
    if variables:
        payload["variables"] = variables

    idem = str(uuid.uuid4())
    status, body, _ = api_call("POST", "/v3/hyperframes/renders", api_key, payload=payload,
                               extra_headers={"Idempotency-Key": idem})
    if status not in (200, 202):
        log(f"❌ Render submission failed (HTTP {status}): {json.dumps(body)[:1500]}")
        return 1
    render_id = (body.get("data") or {}).get("render_id")
    if not render_id:
        log(f"❌ No render_id in response: {json.dumps(body)[:1500]}")
        return 1
    log(f"🚀 Submitted render {render_id} (poll every {args.poll_interval:g}s, timeout {args.timeout_seconds}s)")

    emit_outputs(args.output_props, {"heygen_render_id": render_id})

    # ---- 3. Poll until finished --------------------------------------------
    deadline = time.monotonic() + args.timeout_seconds
    last_status = None
    detail = {}
    while True:
        if time.monotonic() > deadline:
            log(f"⏱️ Timed out after {args.timeout_seconds}s. The render may still finish — "
                f"check it later with render_id {render_id}.")
            return 2
        time.sleep(args.poll_interval)
        status, body, headers = api_call("GET", f"/v3/hyperframes/renders/{render_id}", api_key)
        if status == 429:
            retry_after = float(headers.get("Retry-After") or args.poll_interval * 4)
            log(f"⏳ Rate limited; retrying in {retry_after:g}s")
            time.sleep(retry_after)
            continue
        if status != 200:
            log(f"⚠️ Poll returned HTTP {status}; retrying… ({json.dumps(body)[:300]})")
            continue
        detail = body.get("data") or {}
        current = detail.get("status") or "unknown"
        if current != last_status:
            log(f"🎬 Status: {current}")
            last_status = current
        if current in TERMINAL_OK:
            break
        if current in TERMINAL_FAIL:
            fail = detail.get("failure_message") or json.dumps(detail)[:800]
            log(f"❌ Render failed: {fail}")
            return 1

    video_url = detail.get("video_url")
    if not video_url:
        log(f"❌ Render completed but no video_url: {json.dumps(detail)[:800]}")
        return 1

    # ---- 4. Download --------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    log("⬇️  Downloading video…")
    download(video_url, args.output)
    size = os.path.getsize(args.output)
    log(f"✅ Saved {args.output} ({size} bytes, {size / (1024 * 1024):.1f} MiB)")

    thumb = detail.get("thumbnail_url") or ""
    if args.thumbnail_output and thumb.startswith(("http://", "https://")):
        try:
            download(thumb, args.thumbnail_output)
            log(f"🖼️ Saved {args.thumbnail_output}")
        except Exception as exc:  # thumbnail is best-effort
            log(f"⚠️ Thumbnail download failed: {exc}")

    duration = detail.get("duration")
    emit_outputs(args.output_props, {
        "video_path": args.output,
        "thumbnail_path": args.thumbnail_output or "",
        "duration_seconds": duration if duration is not None else "",
        "video_size_bytes": size,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
