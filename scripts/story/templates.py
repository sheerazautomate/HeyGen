"""Scene template library - the hybrid backbone of story mode.

Every scene is built with a strict full-bleed doctrine ("no dead space"):
  layer 0  painted background: base color + mesh gradient + fine grid + drifting
           accent orbs + vignette (no empty pixels, ever)
  layer 1  .frame - a flex/grid region with aspect-aware padding that STRETCHES
           content to fill the canvas (grids use flex:1, editors fill remaining
           height, big display type is sized from aspect tokens)
  extras   a global film grain overlay across the whole composition

Templates declare their animatable elements; compose.py turns those into one
deterministic GSAP timeline (mirroring examples/*.html conventions), and the
@hyperframes runtime swaps scenes by data-start/data-duration.
"""
import html as _html
import json
import re


def esc(value):
    return _html.escape(str(value), quote=True)


# --------------------------------------------------------------------------- #
# Base CSS - placeholders {TOKENS} filled by compose.py (aspect + palette).    #
# --------------------------------------------------------------------------- #
BASE_CSS = """
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{
  width: {W}px; height: {H}px; overflow: hidden;
  background: {BG}; color: {TEXT};
  font-family: {FONT_DISPLAY}; font-weight: 500;
}}
main {{ position: relative; width: {W}px; height: {H}px; overflow: hidden; }}
.scene {{ position: absolute; top: 0; left: 0; width: {W}px; height: {H}px; overflow: hidden; }}
/* --- layer 0: always-painted background --- */
.bg {{ position: absolute; inset: 0; z-index: 0; background: {BG}; }}
.bg .mesh {{ position: absolute; inset: -10%;
  background:
    radial-gradient(ellipse 60% 50% at 18% 12%, {MESH_A}, transparent 62%),
    radial-gradient(ellipse 55% 55% at 85% 80%, {MESH_B}, transparent 60%),
    radial-gradient(ellipse 40% 40% at 70% 15%, {MESH_C}, transparent 65%);
}}
.bg .grid {{ position: absolute; inset: 0; opacity: {GRID_OPACITY};
  background-image:
    linear-gradient({LINE} 1px, transparent 1px),
    linear-gradient(90deg, {LINE} 1px, transparent 1px);
  background-size: {GRID_SIZE}px {GRID_SIZE}px;
  mask-image: radial-gradient(ellipse 90% 85% at 50% 45%, black 30%, transparent 78%);
  -webkit-mask-image: radial-gradient(ellipse 90% 85% at 50% 45%, black 30%, transparent 78%);
}}
.orb {{ position: absolute; border-radius: 50%; filter: blur({ORB_BLUR}px); z-index: 0; }}
.orb-a {{ width: {ORB1}px; height: {ORB1}px; top: -18%; right: -10%;
  background: radial-gradient(circle, {ORB_A_C}, transparent 70%); }}
.orb-b {{ width: {ORB2}px; height: {ORB2}px; bottom: -22%; left: -12%;
  background: radial-gradient(circle, {ORB_B_C}, transparent 70%); opacity: .75; }}
.bg .vin {{ position: absolute; inset: 0;
  background: radial-gradient(ellipse at center, transparent 52%, rgba(0,0,0,{VIN_STRENGTH}) 100%); }}
/* --- layer 1: content frame stretches to fill --- */
.frame {{ position: relative; z-index: 2; width: 100%; height: 100%;
  padding: {PADY}px {PADX}px; display: flex; flex-direction: column; }}
.frame.center {{ justify-content: center; }}
.grow {{ flex: 1; min-height: 0; display: flex; flex-direction: column; }}
/* --- global grain, like examples --- */
.grain {{ position: absolute; inset: 0; pointer-events: none; z-index: 50; opacity: 0.15;
  background-image:
    radial-gradient(rgba(255,255,255,0.09) 1px, transparent 1.2px),
    radial-gradient(rgba(0,0,0,0.2) 1px, transparent 1.2px);
  background-size: 3px 3px, 5px 5px; background-position: 0 0, 1px 2px;
  mix-blend-mode: overlay; }}
/* --- shared type & ui parts --- */
.kicker {{ display: inline-flex; align-items: center; gap: {KICK_GAP}px;
  font-family: {FONT_MONO}; font-size: {FS_SMALL}px; letter-spacing: 0.22em;
  color: {ACCENT}; text-transform: uppercase; }}
.kicker::before {{ content: ""; width: {KICK_DASH}px; height: 3px; background: {ACCENT}; }}
.h-hero {{ font-weight: 900; font-size: {FS_HERO}px; line-height: 1.02; letter-spacing: -0.022em; }}
.h-hero em, .h2 em {{ font-style: normal; color: {ACCENT}; }}
.h2 {{ font-weight: 900; font-size: {FS_H2}px; line-height: 1.06; letter-spacing: -0.02em; }}
.sub {{ font-weight: 300; font-size: {FS_BODY}px; color: {MUTED}; line-height: 1.45; }}
.mono {{ font-family: {FONT_MONO}; }}
.chip {{ display: inline-flex; align-items: center; gap: 12px;
  font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED}; }}
.chip b {{ color: {TEXT}; font-weight: 700; }}
.mini-badge {{ width: {BADGE}px; height: {BADGE}px; border-radius: {BADGE_R}px; flex: 0 0 auto;
  background: linear-gradient(135deg, {ACCENT}, {ACCENT2});
  display: inline-flex; align-items: center; justify-content: center;
  color: {ON_ACCENT}; font-weight: 900; font-size: {BADGE_FS}px; overflow: hidden; }}
.mini-badge img {{ width: 100%; height: 100%; object-fit: contain; }}
.cta {{ display: inline-flex; align-items: center; gap: 18px; width: max-content;
  background: linear-gradient(135deg, {ACCENT}, {ACCENT2}); color: {ON_ACCENT};
  font-weight: 800; font-size: {FS_CTA}px; padding: {CTA_PADY}px {CTA_PADX}px;
  border-radius: {RAD_LG}px; box-shadow: 0 {SHADOW_Y}px {SHADOW_BLUR}px {GLOW}; }}
"""

TEMPLATE_CSS = {
    "hero": """
.hero-wrap {{ gap: {GAP}px; justify-content: center; }}
.hero-mark {{ display: flex; align-items: center; gap: 22px; }}
.hero-mark .mini-badge {{ width: {BADGE_HERO}px; height: {BADGE_HERO}px; font-size: {BADGE_HERO_FS}px; }}
.hero-word {{ font-family: {FONT_MONO}; font-size: {FS_BODY}px; letter-spacing: .14em;
  text-transform: uppercase; color: {TEXT}; font-weight: 700; }}
.hero-foot {{ display: flex; align-items: center; justify-content: space-between;
  font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED}; margin-top: auto; padding-top: 30px; }}
.hero-foot .bar {{ flex: 1; height: 2px; background: {LINE}; margin: 0 26px; position: relative; overflow: hidden; }}
.hero-foot .bar i {{ position: absolute; inset: 0; background: linear-gradient(90deg, {ACCENT}, {ACCENT2});
  transform: scaleX(0); transform-origin: left; display: block; }}
""",
    "features_grid": """
.fg-grid {{ display: grid; grid-template-columns: repeat({COLS}, 1fr); gap: {CARD_GAP}px;
  flex: 1; min-height: 0; margin-top: {GAP_S}px; }}
.fg-card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: {RAD}px;
  padding: {CARD_PADY}px {CARD_PADX}px; display: flex; flex-direction: column; gap: {CARD_GAP_S}px;
  min-height: 0; position: relative; overflow: hidden; }}
.fg-card::before {{ content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
  background: linear-gradient(90deg, {ACCENT}, {ACCENT2}); opacity: .9; }}
.fg-num {{ font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {ACCENT}; letter-spacing: .12em; }}
.fg-title {{ font-weight: 800; font-size: {FS_CARD_T}px; line-height: 1.12; }}
.fg-desc {{ font-size: {FS_CARD_B}px; color: {MUTED}; line-height: 1.4; font-weight: 400; }}
""",
    "feature_focus": """
.ff-wrap {{ display: grid; grid-template-columns: 1.25fr 1fr; gap: {GAP_BIG}px; flex: 1;
  min-height: 0; align-items: stretch; margin-top: {GAP_S}px; }}
.ff-copy {{ display: flex; flex-direction: column; justify-content: center; gap: {GAP_S}px; }}
.ff-body {{ font-size: {FS_BODY}px; line-height: 1.5; color: {MUTED}; font-weight: 300; }}
.ff-stat {{ background: {CARD}; border: 1px solid {LINE}; border-radius: {RAD}px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: {GAP_S}px; position: relative; overflow: hidden; padding: {CARD_PADY}px; }}
.ff-stat::after {{ content: ""; position: absolute; inset: auto 0 0 0; height: 42%;
  background: linear-gradient(0deg, {MESH_A}, transparent); }}
.ff-value {{ font-weight: 900; font-size: {FS_STAT}px; line-height: 1; letter-spacing: -0.03em;
  background: linear-gradient(135deg, {ACCENT}, {ACCENT2});
  -webkit-background-clip: text; background-clip: text; color: transparent; }}
.ff-label {{ font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED};
  text-transform: uppercase; letter-spacing: .16em; text-align: center; }}
""",
    "code_showcase": """
.cs-editor {{ flex: 1; min-height: 0; margin-top: {GAP_S}px; background: {EDITOR_BG};
  border: 1px solid {LINE}; border-radius: {RAD}px; overflow: hidden;
  display: flex; flex-direction: column;
  box-shadow: 0 {SHADOW_Y}px {SHADOW_BLUR}px rgba(0,0,0,.35); }}
.cs-head {{ display: flex; align-items: center; gap: 10px; padding: {CODE_HEAD_PAD}px {CARD_PADX}px;
  border-bottom: 1px solid {LINE}; background: rgba(255,255,255,0.02); }}
.cs-dot {{ width: {DOT}px; height: {DOT}px; border-radius: 50%; }}
.cs-file {{ margin-left: auto; font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED}; }}
.cs-body {{ flex: 1; min-height: 0; padding: {CARD_PADY}px {CARD_PADX}px; overflow: hidden;
  display: flex; flex-direction: column; justify-content: center; gap: {CODE_LINE_GAP}px; }}
.cs-line {{ display: flex; gap: {CARD_PADX_S}px; font-family: {FONT_MONO};
  font-size: {FS_CODE}px; line-height: 1.5; white-space: pre; }}
.cs-ln {{ color: {LINE_HI}; user-select: none; text-align: right; min-width: 2ch; }}
.cs-line .cd {{ color: {CODE_FG}; }}
.cs-cap {{ margin-top: {GAP_S}px; font-size: {FS_SMALL}px; color: {MUTED};
  font-family: {FONT_MONO}; letter-spacing: .06em; }}
.tk-s {{ color: {ACCENT2}; }} .tk-k {{ color: {ACCENT}; }}
.tk-c {{ color: {MUTED}; font-style: italic; }} .tk-n {{ color: {ACCENT2}; }}
""",
    "stats": """
.st-grid {{ display: grid; grid-template-columns: repeat({COLS}, 1fr); gap: {CARD_GAP}px;
  flex: 1; min-height: 0; margin-top: {GAP_S}px; align-items: stretch; }}
.st-cell {{ background: {CARD}; border: 1px solid {LINE}; border-radius: {RAD}px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: {GAP_S}px; padding: {CARD_PADY}px {CARD_PADX_S}px; text-align: center; }}
.st-val {{ font-weight: 900; font-size: {FS_STAT}px; line-height: 1; letter-spacing: -0.03em; }}
.st-lab {{ font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED};
  text-transform: uppercase; letter-spacing: .15em; }}
.st-bar {{ width: 62%; height: 5px; border-radius: 99px; background: {LINE}; overflow: hidden; }}
.st-bar i {{ display: block; height: 100%; border-radius: 99px;
  background: linear-gradient(90deg, {ACCENT}, {ACCENT2});
  transform: scaleX(0); transform-origin: left; }}
""",
    "stack": """
.sk-cloud {{ flex: 1; min-height: 0; margin-top: {GAP_S}px; display: flex; flex-wrap: wrap;
  gap: {CARD_GAP}px; align-content: center; justify-content: center; }}
.sk-chip {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 999px;
  padding: {CHIP_PADY}px {CHIP_PADX}px; font-family: {FONT_MONO}; font-size: {FS_BODY}px;
  display: inline-flex; align-items: center; gap: 14px; }}
.sk-chip::before {{ content: ""; width: 12px; height: 12px; border-radius: 50%;
  background: linear-gradient(135deg, {ACCENT}, {ACCENT2}); }}
""",
    "steps": """
.stp-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: {CARD_GAP}px;
  flex: 1; min-height: 0; margin-top: {GAP_S}px; align-items: stretch; }}
.stp-card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: {RAD}px;
  padding: {CARD_PADY}px {CARD_PADX}px; display: flex; flex-direction: column; gap: {CARD_GAP_S}px;
  position: relative; }}
.stp-num {{ font-family: {FONT_MONO}; font-weight: 700; font-size: {FS_STEP_N}px;
  background: linear-gradient(135deg, {ACCENT}, {ACCENT2});
  -webkit-background-clip: text; background-clip: text; color: transparent; }}
.stp-title {{ font-weight: 800; font-size: {FS_CARD_T}px; }}
.stp-desc {{ font-size: {FS_CARD_B}px; color: {MUTED}; line-height: 1.45; font-weight: 400; }}
.stp-arrow {{ position: absolute; top: 50%; right: -{ARROW}px; transform: translateY(-50%);
  color: {ACCENT}; font-size: {FS_BODY}px; z-index: 3; }}
""",
    "statement": """
.stm-wrap {{ justify-content: center; gap: {GAP}px; }}
.stm-text {{ font-weight: 800; font-size: {FS_STM}px; line-height: 1.18; letter-spacing: -0.015em; }}
.stm-text em {{ font-style: normal; color: {ACCENT}; }}
.stm-attr {{ font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED};
  letter-spacing: .14em; text-transform: uppercase; }}
.stm-mark {{ font-size: {FS_QUOTE}px; line-height: 0.4; color: {ACCENT}; opacity: .8;
  font-family: Georgia, serif; }}
""",
    "outro": """
.ou-wrap {{ justify-content: center; align-items: center; text-align: center; gap: {GAP_S}px; }}
.ou-url {{ font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED}; letter-spacing: .1em; }}
.ou-mark {{ display: flex; align-items: center; gap: 18px; }}
.ou-foot {{ position: absolute; bottom: {PADY_INNER}px; left: {PADX}px; right: {PADX}px;
  display: flex; justify-content: space-between; font-family: {FONT_MONO};
  font-size: {FS_XS}px; color: {MUTED}; }}
""",
    "custom": """
.cu-wrap {{ gap: {GAP_S}px; }}
.cu-stage {{ flex: 1; min-height: 0; position: relative; display: flex;
  flex-direction: column; }}
.cu-cap {{ margin-top: {GAP_S}px; font-family: {FONT_MONO}; font-size: {FS_SMALL}px; color: {MUTED}; }}
""",
}

# dot colors for the code editor chrome
DOT_CSS = ("#ff5f57", "#febc2e", "#28c840")


def _badge(ctx, big=False):
    """Project badge: real logo when analysis found one, else gradient initial."""
    url = ctx.get("logo_url")
    name = ctx.get("project_name") or "P"
    m = re.search(r"[A-Za-z0-9]", name)
    initial = (m.group(0) if m else "P").upper()
    cls = "mini-badge"
    if url:
        return (f'<span class="{cls}"><img src="{esc(url)}" alt="" '
                f'onerror="this.parentNode.innerHTML=\'{initial}\'" /></span>')
    return f'<span class="{cls}">{initial}</span>'


def hl(code):
    """Tiny language-agnostic highlighter: comments, strings, numbers, common keywords."""
    kw = re.compile(r"\b(import|from|export|const|let|var|function|return|def|class|if|else|"
                    r"for|while|async|await|new|use|fn|pub|package|func|type|struct|interface)\b")
    out_lines = []
    for line in code.splitlines():
        e = esc(line)
        e = re.sub(r"(//.*|#.*)$", r'<span class="tk-c">\1</span>', e)
        e = re.sub(r'(&quot;.*?&quot;|&#x27;.*?&#x27;)', r'<span class="tk-s">\1</span>', e)
        e = re.sub(r"\b(\d+(?:\.\d+)?)\b", r'<span class="tk-n">\1</span>', e)
        e = kw.sub(r'<span class="tk-k">\1</span>', e)
        # never nest spans inside the comment span cleanly - acceptable: regex operates on text nodes mostly
        out_lines.append(e)
    return out_lines


# --------------------------------------------------------------------------- #
# Scene renderers - each returns (html, anims).                                #
# anims entries: (suffix, kind)  kinds: rise | big | pop | fade | num | bars   #
#                | type | orbs | pulse                                         #
# --------------------------------------------------------------------------- #

def scene_hero(ctx, sid, s):
    k = s["slots"]
    word = ctx["project_name"]
    logo_row = ""
    if ctx.get("logo_url") or ctx.get("show_wordmark", True):
        logo_row = (f'<div class="hero-mark an a-fade">{_badge(ctx, big=True)}'
                    f'<span class="hero-word">{esc(word)}</span></div>')
    html_ = f"""
<div class="frame hero-wrap">
  {logo_row}
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <h1 class="h-hero an a-big">{esc(k["headline"])}</h1>
  <p class="sub an a-rise" style="max-width:{ctx['SUB_W']}px">{esc(k.get("subline", ""))}</p>
  <div class="hero-foot an a-fade">
    <span class="mono">{esc(ctx['HOST'])}</span>
    <span class="bar"><i></i></span>
    <span class="mono">{esc(ctx['VIDEO_KIND'])}</span>
  </div>
</div>"""
    return html_, [("hero-mark", "fade"), ("kicker", "rise"), ("h-hero", "big"),
                   ("sub", "rise"), ("hero-foot .bar i", "barx"), ("hero-foot", "fade"), ("bg", "orbs")]


def scene_features_grid(ctx, sid, s):
    k = s["slots"]
    feats = k["features"]
    cards = []
    anims = [("kicker", "rise"), ("h2", "big")]
    for i, f in enumerate(feats):
        cards.append(f"""
<div class="fg-card an a-pop">
  <span class="fg-num">{i+1:02d}</span>
  <span class="fg-title">{esc(f['title'])}</span>
  <span class="fg-desc">{esc(f.get('desc', ''))}</span>
</div>""")
        anims.append((f"fg-card:nth-child({i+1})", "pop"))
    anims.append(("bg", "orbs"))
    html_ = f"""
<div class="frame">
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <h2 class="h2 an a-big" style="margin-top:18px">{esc(k["heading"])}</h2>
  <div class="fg-grid">{''.join(cards)}</div>
</div>"""
    return html_, anims


def scene_feature_focus(ctx, sid, s):
    k = s["slots"]
    stat = ""
    if k.get("stat_value"):
        stat = f"""
<div class="ff-stat an a-pop">
  <span class="ff-value num" data-end="{esc(k['stat_value'])}">{esc(k['stat_value'])}</span>
  <span class="ff-label">{esc(k.get('stat_label', ''))}</span>
</div>"""
    html_ = f"""
<div class="frame">
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <div class="ff-wrap">
    <div class="ff-copy">
      <h2 class="h2 an a-big">{esc(k["heading"])}</h2>
      <p class="ff-body an a-rise">{esc(k.get("body", ""))}</p>
    </div>
    {stat}
  </div>
</div>"""
    anims = [("kicker", "rise"), ("h2", "big"), ("ff-body", "rise")]
    if stat:
        anims += [("ff-stat", "pop"), ("ff-value", "num")]
    anims.append(("bg", "orbs"))
    return html_, anims


def scene_code_showcase(ctx, sid, s):
    k = s["slots"]
    lines = hl(k.get("code", ""))[:14]
    rows = "".join(
        f'<div class="cs-line"><span class="cs-ln">{i+1}</span><span class="cd">{ln or " "}</span></div>'
        for i, ln in enumerate(lines))
    dots = "".join(f'<span class="cs-dot" style="background:{c}"></span>' for c in DOT_CSS)
    html_ = f"""
<div class="frame">
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <h2 class="h2 an a-big" style="margin-top:18px">{esc(k["heading"])}</h2>
  <div class="cs-editor an a-rise">
    <div class="cs-head">{dots}<span class="cs-file">{esc(k.get("filename", ""))}</span></div>
    <div class="cs-body">{rows}</div>
  </div>
  {f'<div class="cs-cap an a-fade">{esc(k["caption"])}</div>' if k.get("caption") else ""}
</div>"""
    return html_, [("kicker", "rise"), ("h2", "big"), ("cs-editor", "rise"),
                   ("cs-body", "type"), ("cs-cap", "fade"), ("bg", "orbs")]


def scene_stats(ctx, sid, s):
    k = s["slots"]
    stats = k["stats"]
    cells = []
    for st_ in stats:
        cells.append(f"""
<div class="st-cell an a-pop">
  <span class="st-val num" data-end="{esc(st_['value'])}">{esc(st_['value'])}</span>
  <span class="st-bar"><i></i></span>
  <span class="st-lab">{esc(st_.get('label', ''))}</span>
</div>""")
    html_ = f"""
<div class="frame">
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <h2 class="h2 an a-big" style="margin-top:18px">{esc(k["heading"])}</h2>
  <div class="st-grid">{''.join(cells)}</div>
</div>"""
    anims = [("kicker", "rise"), ("h2", "big")]
    anims += [(f"st-cell:nth-child({i+1})", "pop") for i in range(len(stats))]
    anims += [("st-val", "num"), ("st-bar i", "bars"), ("bg", "orbs")]
    return html_, anims


def scene_stack(ctx, sid, s):
    k = s["slots"]
    chips = "".join(f'<span class="sk-chip an a-pop">{esc(it)}</span>' for it in k["items"])
    html_ = f"""
<div class="frame">
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <h2 class="h2 an a-big" style="margin-top:18px">{esc(k["heading"])}</h2>
  <div class="sk-cloud">{chips}</div>
</div>"""
    anims = [("kicker", "rise"), ("h2", "big")]
    anims += [(f"sk-chip:nth-child({i+1})", "pop") for i in range(len(k["items"]))]
    anims.append(("bg", "orbs"))
    return html_, anims


def scene_steps(ctx, sid, s):
    k = s["slots"]
    steps = k["steps"][:3]
    cards = []
    for i, st_ in enumerate(steps):
        arrow = '<span class="stp-arrow">⟶</span>' if i < len(steps) - 1 else ""
        cards.append(f"""
<div class="stp-card an a-rise">
  <span class="stp-num">{i+1:02d}</span>
  <span class="stp-title">{esc(st_['title'])}</span>
  <span class="stp-desc">{esc(st_.get('desc', ''))}</span>
  {arrow}
</div>""")
    html_ = f"""
<div class="frame">
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <h2 class="h2 an a-big" style="margin-top:18px">{esc(k["heading"])}</h2>
  <div class="stp-row">{''.join(cards)}</div>
</div>"""
    anims = [("kicker", "rise"), ("h2", "big")]
    anims += [(f"stp-card:nth-child({i+1})", "rise") for i in range(len(steps))]
    anims.append(("bg", "orbs"))
    return html_, anims


def scene_statement(ctx, sid, s):
    k = s["slots"]
    html_ = f"""
<div class="frame stm-wrap">
  <div class="stm-mark an a-fade">“</div>
  {f'<div class="kicker an a-rise">{esc(k["kicker"])}</div>' if k.get("kicker") else ""}
  <p class="stm-text an a-big">{esc(k.get("statement", ""))}</p>
  {f'<div class="stm-attr an a-fade">{esc(k["attribution"])}</div>' if k.get("attribution") else ""}
</div>"""
    return html_, [("stm-mark", "fade"), ("kicker", "rise"), ("stm-text", "big"),
                   ("stm-attr", "fade"), ("bg", "orbs")]


def scene_outro(ctx, sid, s):
    k = s["slots"]
    html_ = f"""
<div class="frame ou-wrap">
  <div class="ou-mark an a-fade">{_badge(ctx, big=True)}</div>
  <h2 class="h-hero an a-big" style="text-align:center">{esc(k["headline"])}</h2>
  {f'<p class="sub an a-rise" style="text-align:center">{esc(k["subline"])}</p>' if k.get("subline") else ""}
  <div class="cta an a-pop">{esc(k.get("cta_label", "Learn more"))}<span aria-hidden="true">→</span></div>
  <div class="ou-url an a-fade">{esc(k.get("url", ""))}</div>
  <div class="ou-foot"><span>{esc(ctx['project_name'])}</span><span>made with hyperframes</span></div>
</div>"""
    return html_, [("ou-mark", "fade"), ("h-hero", "big"), ("sub", "rise"),
                   ("cta", "pop"), ("cta", "pulse"), ("ou-url", "fade"), ("bg", "orbs")]


def scene_custom(ctx, sid, s):
    k = s["slots"]
    html_ = f"""
<div class="frame cu-wrap">
  {f'<div class="kicker an a-rise">{esc(k.get("heading", ""))}</div>' if k.get("heading") else ""}
  <div class="cu-stage an a-rise">{k.get("html", "")}</div>
  {f'<div class="cu-cap an a-fade">{esc(k["caption"])}</div>' if k.get("caption") else ""}
</div>"""
    return html_, [("kicker", "rise"), ("cu-stage", "rise"), ("cu-cap", "fade"), ("bg", "orbs")]


RENDERERS = {
    "hero": scene_hero,
    "features_grid": scene_features_grid,
    "feature_focus": scene_feature_focus,
    "code_showcase": scene_code_showcase,
    "stats": scene_stats,
    "stack": scene_stack,
    "steps": scene_steps,
    "statement": scene_statement,
    "outro": scene_outro,
    "custom": scene_custom,
}
