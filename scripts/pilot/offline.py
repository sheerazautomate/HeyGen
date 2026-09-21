"""Localize the two supported runtime scripts; never fetch user-controlled URLs.

All execution happens without networking. Other external assets won't load.
"""
from pathlib import Path
import re


def localize(html):
    replacements = {
        "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js": "gsap.min.js",
        "https://cdn.jsdelivr.net/npm/@hyperframes/core/dist/hyperframe.runtime.iife.js": "hyperframe.runtime.iife.js",
        "https://cdn.jsdelivr.net/npm/@hyperframes/core@0.8.58/dist/hyperframe.runtime.iife.js": "hyperframe.runtime.iife.js",
    }
    # Only rewrite exact, quoted src attributes. Unknown URLs remain offline.
    def replace(match):
        url = match.group(2)
        return f'src={match.group(1)}{replacements.get(url, url)}{match.group(1)}'
    return re.sub(r'\bsrc\s*=\s*([\x22\x27])([^\x22\x27]+)\1', replace, html, flags=re.I)


if __name__ == "__main__":
    project = Path("/tmp/project")
    project.mkdir()
    project.joinpath("index.html").write_text(localize(Path("/input/index.html").read_text()), encoding="utf-8")
    for name, source in {
        "gsap.min.js": "/opt/renderer/node_modules/gsap/dist/gsap.min.js",
        "hyperframe.runtime.iife.js": "/opt/renderer/node_modules/hyperframes/dist/hyperframe.runtime.iife.js",
    }.items():
        project.joinpath(name).write_bytes(Path(source).read_bytes())
