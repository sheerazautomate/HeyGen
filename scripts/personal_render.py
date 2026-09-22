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

def render(html_path, quality, fps, fmt, variables, output_path, music_files=None):
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

    # Story mode music (synthesized wav or downloaded custom track + mixing metadata)
    for f in (music_files or []):
        if f and Path(f).exists():
            shutil.copy(f, request_dir / Path(f).name)

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
    if (request_dir / "music.wav").exists():
        mounts.append(f"type=bind,src={request_dir / 'music.wav'},dst=/input/music.wav,readonly")
    for f in sorted(request_dir.glob("music_src.*")):
        mounts.append(f"type=bind,src={f},dst=/input/{f.name},readonly")
    if (request_dir / "music.json").exists():
        mounts.append(f"type=bind,src={request_dir / 'music.json'},dst=/input/music.json,readonly")
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

def story_flow(args, variables, out_path_hint):
    """Local story mode: repo link -> analysis -> script -> (review) -> composition -> render."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from story.story import main as story_main

    story_dir = ROOT / "build" / "story-local"
    story_dir.mkdir(parents=True, exist_ok=True)

    analyze_argv = ["analyze", "--repo", args.story,
                    "--tone", args.tone, "--pace", args.pace, "--length", str(args.length),
                    "--aspect", args.aspect, "--music-mood", args.music_mood,
                    "--quality", args.quality, "--fps", str(args.fps), "--format", args.format,
                    "--out", str(story_dir)]
    if args.music_url:
        analyze_argv += ["--music-url", args.music_url]
    try:
        story_main(analyze_argv)
    except SystemExit as exc:  # story.py exits(2) with a friendly ::error::
        sys.exit(exc.code)

    board = (story_dir / "storyboard.md").read_text(encoding="utf-8")
    # storyboard minus the giant details blocks, for terminal review
    preview = board.split("### Next step")[0]
    print("\n" + preview)
    if not args.yes:
        reply = input("Render this storyboard? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print(f"Aborted. Storyboard + script kept in {story_dir}")
            sys.exit(0)

    script = json.loads((story_dir / "script.json").read_text(encoding="utf-8"))

    prep_argv = ["prepare", "--packet", str(story_dir / "packet.txt"),
                 "--comment", "", "--out", str(ROOT / "build" / "personal" / "story-request")]
    try:
        story_main(prep_argv)
    except SystemExit as exc:
        sys.exit(exc.code)

    req = ROOT / "build" / "personal" / "story-request"
    music_files = [p for p in req.glob("music*") if p.is_file()]
    html_path = req / "index.html"
    render_fmt = script["render"]["format"]
    render_quality = script["render"]["quality"]
    render_fps = script["render"]["fps"]
    out = args.output or ROOT / f"build/personal/{script['project']['name']}-story-{render_fps}fps.{render_fmt}"
    return html_path, render_quality, render_fps, render_fmt, out, music_files


def main():
    parser = argparse.ArgumentParser(description="Personal pro local renderer - full throttle HyperFrames")
    parser.add_argument("html", nargs="?", default=None, help="Path to composition HTML file (omit when using --story)")
    parser.add_argument("--story", metavar="REPO_URL", default=None,
                        help="Story mode: analyze a public repo, write the script for you, then render it")
    parser.add_argument("--tone", choices=["cinematic", "corporate", "playful", "hype", "minimal", "documentary"], default="cinematic")
    parser.add_argument("--pace", choices=["snappy", "balanced", "slow"], default="balanced")
    parser.add_argument("--length", type=float, default=30, help="Story mode video length in seconds")
    parser.add_argument("--aspect", choices=["16:9", "9:16", "1:1"], default="16:9")
    parser.add_argument("--music-mood", choices=["upbeat", "corporate", "cinematic", "lofi", "playful", "none"], default="upbeat")
    parser.add_argument("--music-url", default=None, help="Custom https:// audio track (story mode)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the storyboard review prompt")
    parser.add_argument("--quality", choices=["draft", "standard", "high"], default="high", help="Render quality")
    parser.add_argument("--fps", type=int, default=30, choices=[24, 30, 60], help="FPS")
    parser.add_argument("--format", choices=["mp4", "webm", "mov"], default="mp4", help="Output format")
    parser.add_argument("--vars", type=str, default="{}", help="JSON string of variables overrides, e.g. '{\"product\":\"NIMBUS\"}'")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path (default: build/personal/<name>-pro.<format>)")

    args = parser.parse_args()

    if not args.story and not args.html:
        parser.error("give a composition HTML file, or --story <repo-url> (see --help)")

    try:
        variables = json.loads(args.vars)
    except json.JSONDecodeError as e:
        print(f"Invalid --vars JSON: {e}", file=sys.stderr)
        sys.exit(1)

    music_files = []
    if args.story:
        html, args.quality, args.fps, args.format, out, music_files = story_flow(args, variables, args.output)
        args.html = str(html)
        args.output = str(out)

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

    render(args.html, args.quality, args.fps, args.format, variables, out_path, music_files=music_files)

if __name__ == "__main__":
    main()
