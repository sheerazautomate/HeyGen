#!/usr/bin/env python3
"""
Personal pro local renderer - bypass GitHub for instant local renders.

Usage:
  python3 scripts/personal_render.py examples/product-launch.html --quality high --fps 60 --format mp4
  python3 scripts/personal_render.py my-video.html --vars '{"product":"MY BRAND"}'

This uses the same Docker image as the GitHub Action but runs locally with network enabled.
Full throttle: external assets, 4K, 60fps, high quality, variables.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def build_image():
    print("Building pro renderer image (4 CPUs, 8GB, network enabled)...")
    subprocess.run(["docker", "build", "-t", "pilot-renderer", str(ROOT / "scripts/pilot")], check=True)

def render(html_path, quality, fps, fmt, variables, output_path):
    html_path = Path(html_path).resolve()
    if not html_path.exists():
        print(f"HTML file not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    build_dir = ROOT / "build" / "personal"
    request_dir = build_dir / "request"
    raw_dir = build_dir / "raw"
    media_dir = build_dir / "media"

    for d in [request_dir, raw_dir, media_dir]:
        d.mkdir(parents=True, exist_ok=True)
        # Clean previous
        for f in d.glob("*"):
            if f.is_file():
                f.unlink()

    # Copy HTML
    shutil.copy(html_path, request_dir / "index.html")

    # Parse dimensions/duration for logging
    content = html_path.read_text(encoding="utf-8")
    import re
    m = re.search(r'data-width="(\d+)".*data-height="(\d+)".*data-duration="([\d.]+)"', content, re.S)
    if m:
        print(f"Composition: {m.group(1)}x{m.group(2)}, {m.group(3)}s")

    # Write manifest
    manifest = {
        "width": int(m.group(1)) if m else 1920,
        "height": int(m.group(2)) if m else 1080,
        "duration": float(m.group(3)) if m else 5,
        "fps": fps,
        "quality": quality,
        "format": fmt,
        "variables": variables,
        "title": html_path.stem,
    }
    (request_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (request_dir / "variables.json").write_text(json.dumps(variables), encoding="utf-8")

    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.chmod(0o777)

    # Docker run with network enabled
    mounts = [
        f"type=bind,src={request_dir / 'index.html'},dst=/input/index.html,readonly",
        f"type=bind,src={request_dir / 'manifest.json'},dst=/input/manifest.json,readonly",
        f"type=bind,src={request_dir / 'variables.json'},dst=/input/variables.json,readonly",
        f"type=bind,src={raw_dir},dst=/output",
    ]
    mount_args = []
    for mnt in mounts:
        mount_args.extend(["--mount", mnt])

    cmd = [
        "docker", "run", "--rm",
        "--name", "pilot-sandbox-personal",
        "--log-driver", "none",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "1000:1000",
        "--cpus", "4", "--memory", "8g", "--memory-swap", "8g",
        "--pids-limit", "1024",
        "--ulimit", "fsize=2147483648:2147483648",
        "--shm-size", "512m",
        "--tmpfs", "/tmp:rw,nosuid,size=3072m,mode=1777",
        *mount_args,
        "pilot-renderer"
    ]

    print(f"Rendering locally: {quality} quality, {fps}fps, {fmt} format...")
    print(f"Variables: {variables}")
    try:
        subprocess.run(cmd, check=True, timeout=900)
    except subprocess.TimeoutExpired:
        print("Render timed out after 15 min", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Render failed: {e}", file=sys.stderr)
        # Try to get logs
        sys.exit(1)

    # Collect outputs
    sys.path.insert(0, str(ROOT / "scripts/pilot"))
    from check_outputs import collect
    collect(raw_dir, media_dir)

    # Copy to desired output
    src_video = media_dir / f"video.{fmt}"
    if not src_video.exists():
        src_video = media_dir / "video.mp4"

    if src_video.exists():
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_video, output_path)
        print(f"\n✅ Pro render complete: {output_path}")
        print(f"   Size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
        if (media_dir / "thumbnail.jpg").exists():
            thumb_out = output_path.with_suffix(".jpg")
            shutil.copy(media_dir / "thumbnail.jpg", thumb_out)
            print(f"   Thumbnail: {thumb_out}")

        # Also show all formats if rendered
        for f in media_dir.glob("video.*"):
            print(f"   Available: {f} ({f.stat().st_size / 1024 / 1024:.2f} MB)")
    else:
        print("No video output found", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Personal pro local renderer - full throttle HyperFrames")
    parser.add_argument("html", help="Path to composition HTML file")
    parser.add_argument("--quality", choices=["draft", "standard", "high"], default="high", help="Render quality")
    parser.add_argument("--fps", type=int, default=30, choices=[24, 30, 60], help="FPS")
    parser.add_argument("--format", choices=["mp4", "webm", "mov"], default="mp4", help="Output format")
    parser.add_argument("--vars", type=str, default="{}", help="JSON string of variables overrides, e.g. '{\"product\":\"NIMBUS\"}'")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path (default: build/personal/<name>-pro.<format>)")

    args = parser.parse_args()

    try:
        variables = json.loads(args.vars)
    except json.JSONDecodeError as e:
        print(f"Invalid --vars JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        out_path = args.output
    else:
        html_name = Path(args.html).stem
        out_path = ROOT / f"build/personal/{html_name}-pro-{args.quality}-{args.fps}fps.{args.format}"

    # Ensure docker image exists, build if not
    try:
        subprocess.run(["docker", "image", "inspect", "pilot-renderer"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        build_image()

    render(args.html, args.quality, args.fps, args.format, variables, out_path)

if __name__ == "__main__":
    main()
