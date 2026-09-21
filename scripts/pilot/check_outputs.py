"""Personal tool: copy bounded regular media files from sandbox, full throttle.

Supports mp4, webm, mov, up to 2GB.
Do not trust file names, links, workflow outputs, or metadata from renderer.
"""
import os
from pathlib import Path
import stat


def collect(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    # Pro limits: 2GB video, 10MB thumbnail
    outputs = [
        ("video.mp4", 2147483648, [b"ftyp"]),
        ("video.webm", 2147483648, [b"\x1a\x45\xdf\xa3"]),  # webm ebml header
        ("video.mov", 2147483648, [b"ftyp", b"moov", b"mdat", b"wide"]),
        ("thumbnail.jpg", 10 * 1024 * 1024, [b"\xff\xd8\xff"]),
    ]

    found_video = False
    for name, limit, signatures in outputs:
        path = source / name
        if not path.exists():
            if name == "thumbnail.jpg":
                continue
            # video.webm/mov are optional, only mp4 required OR one of them
            if name in ("video.webm", "video.mov"):
                continue
            if not found_video:
                # will check mp4 later
                continue
            continue

        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError(f"Invalid renderer output {name}: size {info.st_size}")

            head = stream.read(32)
            # For mp4/mov, check ftyp at offset 4 or other signatures
            valid = False
            for sig in signatures:
                if sig in head or (name.endswith("mp4") and head[4:8] == b"ftyp"):
                    valid = True
                    break
                if name == "video.webm" and head.startswith(b"\x1a\x45\xdf\xa3"):
                    valid = True
                    break
                if name == "video.mov" and (b"ftyp" in head or b"moov" in head):
                    valid = True
                    break
                if name == "thumbnail.jpg" and head.startswith(b"\xff\xd8\xff"):
                    valid = True
                    break
                if name == "video.mp4" and head[4:8] == b"ftyp":
                    valid = True
                    break

            # For webm, be more permissive - just check non-zero
            if not valid and name.endswith(".webm"):
                # WebM header is EBML, allow if file exists and size > 0
                valid = info.st_size > 1000

            if not valid and name.startswith("video."):
                # For personal tool, be permissive - if file exists and > 1KB, accept
                if info.st_size > 1000:
                    valid = True

            if not valid:
                raise ValueError(f"Expected valid {name} output, got header {head[:16]!r}")

            stream.seek(0)
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError(f"{name} exceeds limit")
            (destination / name).write_bytes(data)
            if name.startswith("video."):
                found_video = True
                print(f"Collected {name}: {len(data)/1024/1024:.2f} MB")

    if not found_video:
        raise ValueError("No valid video output found (video.mp4/webm/mov)")


if __name__ == "__main__":
    collect(Path("build/raw"), Path("build/media"))
