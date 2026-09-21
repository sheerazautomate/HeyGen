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
import shutil
import subprocess
import sys
import time
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


def preflight_browser(engine: str) -> None:
    """Pre-fetch chrome-headless-shell for the local render engine.

    `hyperframes render` exits immediately with code 1 when its inline browser
    download fails, so download it up front (in this step) with one forced
    retry. Non-fatal: if this fails, the render step will surface the real
    error. Skipped for the HeyGen cloud engine, which needs no local browser.
    """
    if engine == "heygen-cloud":
        return
    ensure_ffmpeg()
    for attempt, flags in enumerate(([], ["--force"]), start=1):
        label = f"hyperframes browser ensure {' '.join(flags)}".strip()
        print(f"🌐 Prefetching render browser (attempt {attempt}/2: {label})…", flush=True)
        try:
            proc = subprocess.run(
                ["npx", "-y", "hyperframes", "browser", "ensure", *flags],
                timeout=300,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            print("⚠️ browser ensure timed out after 300s — continuing.", flush=True)
            return
        if proc.returncode == 0:
            print("✅ Render browser ready.", flush=True)
            return
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        tail = [line for line in combined.strip().splitlines() if line.strip()][-6:]
        print("⚠️ browser ensure failed:\n" + "\n".join(tail), flush=True)
    print("⚠️ Continuing without a pre-fetched browser — the render step will retry.", flush=True)


def ensure_ffmpeg() -> None:
    """Install FFmpeg/FFprobe when missing.

    GitHub's ubuntu-latest runner images no longer ship ffmpeg, and
    `hyperframes render` exits immediately when it cannot find an encoder.
    Runners have passwordless sudo and open apt access, so install it here
    (before the render step). Non-fatal if installation fails.
    """
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        print("✅ FFmpeg already present.", flush=True)
        return
    print("📦 Installing FFmpeg (apt-get)…", flush=True)
    try:
        subprocess.run(["sudo", "apt-get", "update", "-qq"], timeout=300, capture_output=True)
        proc = subprocess.run(
            ["sudo", "apt-get", "install", "-y", "-qq", "ffmpeg"],
            timeout=600,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ FFmpeg install error: {exc}", flush=True)
        return
    if proc.returncode == 0 and shutil.which("ffmpeg"):
        version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        print(f"✅ FFmpeg installed: {version}", flush=True)
    else:
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        print("⚠️ FFmpeg install failed:\n" + "\n".join(tail), flush=True)


def debug_rehearsal(engine: str, fmt: str, fps: int, quality: str, resolution: str, variables: str) -> None:
    """Run the render step's exact command, capture everything, push to a branch.

    Enabled with settings {"debug": "true"}. GitHub's log-storage hosts are not
    reachable from some sandboxes, so the combined output (plus doctor output
    and tool versions) is committed to the `render-debug` branch where it can
    be read through the regular contents API. Non-fatal throughout.
    """
    ws = os.environ.get("GITHUB_WORKSPACE", ".")
    out_path = os.path.join(ws, "out", f"video.{fmt}")
    cmd = ["npx", "-y", "hyperframes", "render", "build/project", "--output", out_path,
           "--fps", str(fps), "--quality", quality, "--format", fmt]
    if resolution == "4k":
        cmd += ["--resolution", "4k"]
    if variables:
        cmd += ["--variables", variables]

    def run(label, command, timeout=120):
        try:
            proc = subprocess.run(command, cwd=ws, timeout=timeout, capture_output=True, text=True)
            return f"$ {label}\nexit={proc.returncode}\n{proc.stdout}\n{proc.stderr}".strip()
        except subprocess.TimeoutExpired as exc:
            return f"$ {label}\nTIMEOUT after {timeout}s\n{(exc.stdout or b'').decode(errors='replace')[-3000:]}"
        except Exception as exc:  # noqa: BLE001
            return f"$ {label}\nERROR: {exc}"

    sections = [f"# render-debug for run {os.environ.get('GITHUB_RUN_ID', '?')} ({time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())})"]
    sections.append(run("node --version && npm --version", ["bash", "-lc", "node --version && npm --version"]))
    sections.append(run("npx -y hyperframes --version", ["npx", "-y", "hyperframes", "--version"], timeout=180))
    sections.append(run("npx -y hyperframes doctor", ["npx", "-y", "hyperframes", "doctor"], timeout=240))
    sections.append(run("npx -y hyperframes browser path", ["npx", "-y", "hyperframes", "browser", "path"], timeout=120))
    sections.append(run("ffmpeg/ffprobe", ["bash", "-lc", "which ffmpeg ffprobe; ffmpeg -version 2>&1 | head -2; ffprobe -version 2>&1 | head -1"]))
    sections.append(run("chrome candidates", ["bash", "-lc", "for b in google-chrome google-chrome-stable chromium chromium-browser chrome-headless-shell; do printf '%s: ' $b; command -v $b || echo missing; done; ls -la $HOME/.cache/puppeteer 2>/dev/null || true; ls -la $HOME/.cache/hyperframes 2>/dev/null || true"]))
    sections.append(run("RENDER (exact command)", cmd, timeout=1500))

    report = "\n\n---\n\n".join(sections)[-180000:]
    tmp = f"render-debug-{os.environ.get('GITHUB_RUN_ID', 'x')}.txt"
    os.makedirs("debug", exist_ok=True)
    with open(os.path.join("debug", tmp), "w", encoding="utf-8") as fh:
        fh.write(report)

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("⚠️ debug: no GITHUB_TOKEN — report kept in debug/ only.", flush=True)
        return
    env = dict(os.environ, GIT_AUTHOR_NAME="render-debug-bot", GIT_AUTHOR_EMAIL="debug@arena.ai",
               GIT_COMMITTER_NAME="render-debug-bot", GIT_COMMITTER_EMAIL="debug@arena.ai")
    url = f"https://x-access-token:{token}@github.com/{repo}.git"

    def sh(command, timeout=120):
        try:
            return subprocess.run(command, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            class R:
                returncode = -1
                stderr = str(exc)
            return R()

    fetch = sh(["git", "fetch", url, "render-debug", "--depth", "1"])
    if fetch.returncode == 0:
        sh(["git", "checkout", "-B", "render-debug", "FETCH_HEAD"])
    else:
        sh(["git", "checkout", "-B", "render-debug"])
    sh(["git", "add", "-A", "debug"])
    sh(["git", "commit", "-m", f"render debug log {tmp}"])
    push = sh(["git", "push", url, "render-debug"])
    if push.returncode != 0:
        print(f"⚠️ debug push failed: {(push.stderr or '')[-400:]}", flush=True)
        return
    print("🧪 Debug report pushed to the render-debug branch: debug/" + tmp, flush=True)


def main() -> int:
    event = read_event()
    name = os.environ.get("GITHUB_EVENT_NAME", event.get("event_name", ""))
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ.get("GITHUB_TOKEN", "")
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "build/project"
    props = os.environ.get("GITHUB_OUTPUT", "")

    inputs = event.get("inputs") or {}
    payload = (event.get("client_payload") or {}) if name == "repository_dispatch" else {}

    # client_payload is capped at 10 properties by GitHub, so the site packs all
    # render settings into one `settings_json` string. Individual fields are
    # still accepted (workflow_dispatch inputs, hand-rolled dispatches).
    settings = {}
    if isinstance(payload.get("settings_json"), str) and payload["settings_json"].strip():
        try:
            settings = json.loads(payload["settings_json"])
            if not isinstance(settings, dict):
                raise ValueError("must be a JSON object")
        except ValueError as exc:
            print(f"❌ client_payload.settings_json is invalid: {exc}")
            return 1

    def pick(field, default=""):
        value = settings.get(field, payload.get(field, inputs.get(field, default)))
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

    # Download the local-render browser now (with retry) so the render step
    # never dies on an inline download failure. No-op for the cloud engine.
    preflight_browser(engine)

    # Optional render rehearsal: runs the render step's exact command, captures
    # everything (doctor, versions, chrome candidates, full stderr) and pushes
    # it to the `render-debug` branch. Enable with settings {"debug":"true"}.
    debug = str(settings.get("debug", "")).lower() in {"1", "true", "yes", "on"} or os.environ.get("HF_RENDER_DEBUG") == "1"
    if debug:
        debug_rehearsal(engine, fmt, fps, quality, resolution, variables)

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
