"""Compose a validated story script into a HyperFrames composition (index.html).

Deterministic: same script.json in -> byte-identical HTML out. The output mirrors
the conventions in examples/*.html: a <main data-composition-*> root, .scene.clip
sections with data-start/data-duration, GSAP timeline registered at
window.__timelines["main"], grains/vignettes/orbs on every frame.
"""
import json
import re

from .templates import BASE_CSS, TEMPLATE_CSS, RENDERERS, esc

GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
HF_CDN = "https://cdn.jsdelivr.net/npm/@hyperframes/core/dist/hyperframe.runtime.iife.js"

# Aspect-aware layout tokens. The "no dead space" doctrine is enforced here:
# font sizes, paddings, gaps and grid columns are tuned per canvas so every
# scene fills the frame regardless of shape.
ASPECT_PARAMS = {
    "16:9": dict(PADX=150, PADY=110, PADY_INNER=110, FS_HERO=118, FS_H2=74, FS_BODY=32,
                 FS_SMALL=21, FS_XS=16, FS_CARD_T=30, FS_CARD_B=21, FS_STAT=120, FS_CODE=23,
                 FS_CTA=30, CTA_PADY=24, CTA_PADX=48, FS_STM=64, FS_QUOTE=190, FS_STEP_N=58,
                 RAD=26, RAD_LG=999, GAP=34, GAP_S=26, GAP_BIG=64, CARD_GAP=28, CARD_GAP_S=16,
                 CARD_PADY=40, CARD_PADX=38, CARD_PADX_S=22, CHIP_PADY=18, CHIP_PADX=32,
                 GRID_SIZE=64, GRID_OPACITY=0.10, ORB1=620, ORB2=520, ORB_BLUR=80,
                 SUB_W=1150, BADGE=34, BADGE_R=10, BADGE_FS=18, BADGE_HERO=84, BADGE_HERO_FS=44,
                 KICK_GAP=14, KICK_DASH=46, ARROW=34, DOT=14, CODE_HEAD_PAD=16, CODE_LINE_GAP=6,
                 SHADOW_Y=26, SHADOW_BLUR=70, VIN_STRENGTH=0.42),
    "9:16": dict(PADX=64, PADY=96, PADY_INNER=96, FS_HERO=82, FS_H2=56, FS_BODY=27,
                 FS_SMALL=18, FS_XS=14, FS_CARD_T=26, FS_CARD_B=19, FS_STAT=96, FS_CODE=20,
                 FS_CTA=26, CTA_PADY=20, CTA_PADX=40, FS_STM=48, FS_QUOTE=150, FS_STEP_N=48,
                 RAD=22, RAD_LG=999, GAP=26, GAP_S=22, GAP_BIG=40, CARD_GAP=20, CARD_GAP_S=13,
                 CARD_PADY=30, CARD_PADX=26, CARD_PADX_S=18, CHIP_PADY=14, CHIP_PADX=24,
                 GRID_SIZE=56, GRID_OPACITY=0.10, ORB1=520, ORB2=460, ORB_BLUR=70,
                 SUB_W=900, BADGE=30, BADGE_R=9, BADGE_FS=16, BADGE_HERO=72, BADGE_HERO_FS=38,
                 KICK_GAP=12, KICK_DASH=40, ARROW=28, DOT=12, CODE_HEAD_PAD=14, CODE_LINE_GAP=5,
                 SHADOW_Y=22, SHADOW_BLUR=60, VIN_STRENGTH=0.42),
    "1:1": dict(PADX=88, PADY=88, PADY_INNER=88, FS_HERO=86, FS_H2=60, FS_BODY=28,
                FS_SMALL=19, FS_XS=15, FS_CARD_T=27, FS_CARD_B=19, FS_STAT=100, FS_CODE=20,
                FS_CTA=27, CTA_PADY=21, CTA_PADX=42, FS_STM=52, FS_QUOTE=160, FS_STEP_N=52,
                RAD=22, RAD_LG=999, GAP=28, GAP_S=22, GAP_BIG=48, CARD_GAP=22, CARD_GAP_S=14,
                CARD_PADY=34, CARD_PADX=30, CARD_PADX_S=18, CHIP_PADY=15, CHIP_PADX=26,
                GRID_SIZE=58, GRID_OPACITY=0.10, ORB1=540, ORB2=480, ORB_BLUR=70,
                SUB_W=880, BADGE=30, BADGE_R=9, BADGE_FS=16, BADGE_HERO=76, BADGE_HERO_FS=40,
                KICK_GAP=12, KICK_DASH=40, ARROW=28, DOT=12, CODE_HEAD_PAD=14, CODE_LINE_GAP=5,
                SHADOW_Y=22, SHADOW_BLUR=60, VIN_STRENGTH=0.42),
}

GRID_COLS = {
    "16:9": {2: 2, 3: 3, 4: 2, 5: 3, 6: 3},
    "9:16": {2: 1, 3: 1, 4: 2, 5: 2, 6: 2},
    "1:1":  {2: 2, 3: 3, 4: 2, 5: 2, 6: 2},
}


# --------------------------------------------------------------------------- #
# color helpers                                                                #
# --------------------------------------------------------------------------- #

def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a, b, t):
    """t=0 -> a, t=1 -> b"""
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t), round(ag + (bg - ag) * t), round(ab + (bb - ab) * t))


def alpha(hex_color, a):
    r, g, b = _rgb(hex_color)
    return f"rgba({r},{g},{b},{a})"


def luminance(hex_color):
    r, g, b = (c / 255 for c in _rgb(hex_color))
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def is_dark(hex_color):
    return luminance(hex_color) < 0.35


def tokens_for(script):
    p = script["palette"]
    aspect = script.get("aspect", "16:9")
    params = dict(ASPECT_PARAMS.get(aspect, ASPECT_PARAMS["16:9"]))
    dark = is_dark(p["bg"])
    on_accent = "#0c0e14" if luminance(p["accent"]) > 0.45 else "#ffffff"
    card = p["surface"]
    line = mix(p["bg"], p["text"], 0.14 if dark else 0.10)
    fonts = script.get("fonts", {})
    disp = fonts.get("display", "Archivo")
    mono = fonts.get("mono", "Space Mono")
    tokens = dict(
        W=width_for(aspect)[0], H=width_for(aspect)[1],
        BG=p["bg"], TEXT=p["text"], MUTED=p["muted"], ACCENT=p["accent"], ACCENT2=p["accent2"],
        CARD=card, LINE=line,
        MESH_A=alpha(p["accent"], 0.16 if dark else 0.12),
        MESH_B=alpha(p["accent2"], 0.13 if dark else 0.10),
        MESH_C=alpha(p["accent"], 0.08),
        ORB_A_C=alpha(p["accent"], 0.55), ORB_B_C=alpha(p["accent2"], 0.5),
        GLOW=alpha(p["accent"], 0.35),
        ON_ACCENT=on_accent,
        EDITOR_BG=mix(p["bg"], "#000000", 0.35) if dark else mix(p["bg"], "#0d1220", 0.92),
        CODE_FG=mix(p["text"], p["bg"], 0.08) if dark else "#e8ecf6",
        LINE_HI=alpha(p["text"], 0.28),
        FONT_DISPLAY=f"'{disp}', 'Segoe UI', sans-serif",
        FONT_MONO=f"'{mono}', 'Courier New', monospace",
        COLS=3,  # overridden inline per scene
        HOST=host_for(script), VIDEO_KIND=f"project story · {int(round(script['duration']))}s",
    )
    tokens.update(params)
    return tokens


def width_for(aspect):
    from .schema import ASPECTS
    return ASPECTS.get(aspect, ASPECTS["16:9"])


def host_for(script):
    url = script.get("project", {}).get("url", "")
    m = re.match(r"https?://([^/]+)/([^/]+)/([^/#?]+)", url.strip())
    if not m:
        return "github.com"
    repo = m.group(3)[:-4] if m.group(3).endswith(".git") else m.group(3)
    return f"{m.group(1)}/{m.group(2)}/{repo}"


def fonts_link(script):
    fonts = script.get("fonts", {})
    disp = fonts.get("display", "Archivo").replace(" ", "+")
    mono = fonts.get("mono", "Space Mono").replace(" ", "+")
    return ("https://fonts.googleapis.com/css2?"
            f"family={disp}:wght@300;500;700;800;900&family={mono}:wght@400;700&display=swap")


def build_css(script):
    tokens = tokens_for(script)
    used = {s["template"] for s in script["scenes"]}
    css = BASE_CSS + "".join(TEMPLATE_CSS[t] for t in sorted(used) if t in TEMPLATE_CSS)
    return css.format(**{k: v for k, v in tokens.items()})


def cols_for(aspect, n):
    table = GRID_COLS.get(aspect, GRID_COLS["16:9"])
    return table.get(n, 3 if n >= 3 else n)


def _ctx(script, tokens, logo_url):
    aspect = script.get("aspect", "16:9")
    return {
        "project_name": script["project"]["name"],
        "logo_url": logo_url,
        "HOST": tokens["HOST"],
        "VIDEO_KIND": tokens["VIDEO_KIND"],
        "SUB_W": tokens["SUB_W"],
        "cols_for": lambda n: cols_for(aspect, n),
        "show_wordmark": True,
    }


# --------------------------------------------------------------------------- #
# timeline                                                                     #
# --------------------------------------------------------------------------- #

def _sel(sid, suffix):
    return f"#{sid} .{suffix}"


def timeline_js(scenes_timing):
    """scenes_timing: list of (sid, start, dur, anims). One deterministic GSAP timeline."""
    lines = ["(function () {",
             "  var tl = gsap.timeline({ defaults: { ease: 'power2.out' } });",
             "  function q(s) { return document.querySelectorAll(s); }"]
    for sid, start, dur, anims in scenes_timing:
        T = round(start, 3)
        stagger = 0.0
        seen_type = False
        for entry in anims:
            if len(entry) == 2:
                suffix, kind = entry
                extra = {}
            else:
                suffix, kind, extra = entry
            s = _sel(sid, suffix)
            if kind in ("rise", "big", "pop", "fade"):
                stagger += 0.16
                at = round(T + 0.12 + stagger, 3)
                if kind == "rise":
                    lines.append(f"  tl.from('{s}', {{ y: 30, autoAlpha: 0, duration: 0.55, ease: 'power2.out' }}, {at});")
                elif kind == "big":
                    lines.append(f"  tl.from('{s}', {{ y: 58, autoAlpha: 0, duration: 0.72, ease: 'power3.out' }}, {at});")
                elif kind == "pop":
                    lines.append(f"  tl.from('{s}', {{ y: 42, scale: 0.94, autoAlpha: 0, duration: 0.55, ease: 'back.out(1.5)' }}, {at});")
                else:
                    lines.append(f"  tl.from('{s}', {{ autoAlpha: 0, duration: 0.6, ease: 'power1.out' }}, {at});")
            elif kind == "num" and not seen_type:
                at = round(T + 0.55, 3)
                lines.append(
                    f"  q('#{sid} .num').forEach(function (el) {{"
                    f" var raw = String(el.getAttribute('data-end') || '');"
                    f" var end = parseFloat(raw); if (isNaN(end)) return;"
                    f" var suffix = raw.replace(/^[\\d.]+/, '');"
                    f" var st = {{ v: 0 }};"
                    f" tl.to(st, {{ v: end, duration: 1.2, ease: 'power1.out', onUpdate: function () {{"
                    f" el.textContent = (end % 1 ? st.v.toFixed(1) : Math.round(st.v)) + suffix; }} }}, {at});"
                    f" }});")
            elif kind == "bars":
                at = round(T + 0.6, 3)
                lines.append(f"  tl.to('{s}', {{ scaleX: 1, duration: 1.1, ease: 'power2.out', stagger: 0.12 }}, {at});")
            elif kind == "barx":
                at = round(T + 0.4, 3)
                lines.append(f"  tl.to('{s}', {{ scaleX: 1, duration: {max(0.5, dur - 1.0):.2f}, ease: 'none' }}, {at});")
            elif kind == "type" and not seen_type:
                seen_type = True
                at = round(T + 0.7, 3)
                lines.append(
                    f"  tl.fromTo('#{sid} .cs-body .cs-line', {{ autoAlpha: 0, x: -16 }},"
                    f" {{ autoAlpha: 1, x: 0, duration: 0.28, ease: 'power1.out', stagger: 0.08 }}, {at});")
            elif kind == "orbs":
                at = round(T + 0.3, 3)
                lines.append(f"  tl.to('#{sid} .orb-a', {{ x: -56, y: 38, scale: 1.08, duration: 1.7, ease: 'sine.inOut', yoyo: true, repeat: 1 }}, {at});")
                lines.append(f"  tl.to('#{sid} .orb-b', {{ x: 48, y: -30, duration: 1.5, ease: 'sine.inOut', yoyo: true, repeat: 1 }}, {round(at + 0.2, 3)});")
            elif kind == "pulse":
                at = round(T + max(1.2, dur - 1.9), 3)
                lines.append(f"  tl.to('{s}', {{ scale: 1.045, duration: 0.5, ease: 'sine.inOut', yoyo: true, repeat: 3, transformOrigin: 'center center' }}, {at});")
    return "\n".join(lines)


def outro_exit_js(sid, start, dur):
    return f"  tl.to('#{sid} .frame', {{ autoAlpha: 0, y: -30, duration: 0.55, ease: 'power2.in' }}, {round(start + dur - 0.62, 3)});"


# --------------------------------------------------------------------------- #
# assembly                                                                     #
# --------------------------------------------------------------------------- #

def bg_layers():
    return ('<div class="bg"><i class="mesh"></i><i class="grid"></i>'
            '<i class="orb orb-a"></i><i class="orb orb-b"></i><i class="vin"></i></div>')


def compose_html(script, logo_url=None):
    tokens = tokens_for(script)
    css = build_css(script)
    ctx = _ctx(script, tokens, logo_url)
    w, h = width_for(script.get("aspect", "16:9"))
    total = script["duration"]

    scene_divs = []
    timing = []
    t = 0.0
    aspect = script.get("aspect", "16:9")
    for i, s in enumerate(script["scenes"]):
        sid = s["id"]
        renderer = RENDERERS[s["template"]]
        inner, anims = renderer(ctx, sid, s)
        # inline per-scene grid columns (aspect-aware fill)
        if s["template"] in ("features_grid", "stats"):
            n = len(s["slots"].get("features") or s["slots"].get("stats") or [])
            inner = inner.replace('class="fg-grid"',
                                  f'class="fg-grid" style="grid-template-columns:repeat({cols_for(aspect, n)},1fr)"')
            inner = inner.replace('class="st-grid"',
                                  f'class="st-grid" style="grid-template-columns:repeat({cols_for(aspect, n)},1fr)"')
        hidden = ' style="visibility: hidden"' if i > 0 else ""
        scene_divs.append(
            f'<div class="scene clip" id="{esc(sid)}" data-start="{t:g}" data-duration="{s["duration_s"]:g}" '
            f'data-track-index="0"{hidden}>{bg_layers()}{inner}</div>')
        timing.append((sid, t, s["duration_s"], anims))
        t += s["duration_s"]

    last = timing[-1]
    tl = timeline_js(timing)
    tl += "\n" + outro_exit_js(last[0], last[1], last[2])
    tl += '\n  window.__timelines["main"] = tl;\n})();'

    duration_attr = f"{total:g}"
    title = esc(f"{script['project']['name']} — story")
    scenes_block = "\n      ".join(scene_divs)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={w}, height={h}" />
    <title>{title}</title>
    <!-- generated by story mode · {esc(script['tone'])}/{esc(script['pace'])} · palette: {esc(script['palette'].get('source', 'default'))} -->
    <script src="{GSAP_CDN}"></script>
    <script src="{HF_CDN}"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="{fonts_link(script)}" rel="stylesheet" />
    <style>
{css}
    </style>
  </head>
  <body>
    <main
      data-composition-id="main"
      data-width="{w}"
      data-height="{h}"
      data-duration="{duration_attr}"
    >
      {scenes_block}
      <div class="grain"></div>
    </main>
    <script>
{tl}
    </script>
  </body>
</html>
"""


def compose_to_file(script, out_dir, logo_url=None):
    """Write composition index.html into out_dir. Returns path."""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(compose_html(script, logo_url=logo_url), encoding="utf-8")
    return path
