"""Copy only bounded regular media files from the sandbox's output volume.

Do not trust file names, links, workflow outputs, or metadata from the renderer.
"""
import os
from pathlib import Path
import stat


def collect(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name, limit in (("video.mp4", 256 * 1024 * 1024), ("thumbnail.jpg", 5 * 1024 * 1024)):
        path = source / name
        if name == "thumbnail.jpg" and not path.exists():
            continue
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError("Invalid renderer output")
            head = stream.read(16)
            if name.endswith("mp4") and head[4:8] != b"ftyp":
                raise ValueError("Expected MP4 output")
            if name.endswith("jpg") and not head.startswith(b"\xff\xd8\xff"):
                raise ValueError("Expected JPEG thumbnail")
            stream.seek(0)
            (destination / name).write_bytes(stream.read(limit + 1))


if __name__ == "__main__":
    collect(Path("build/raw"), Path("build/media"))
