"""Turn a cloned repo into a ProjectBrief: what the project is, what it does,
which colors/fonts it wears, and which details make it *this* project.

Pure heuristics (no LLM here) - the brief feeds both the LLM prompt and the
offline fallback generator, so even a zero-key run produces a real, specific
script instead of generic filler.
"""
import colorsys
import json
import re
from collections import Counter
from pathlib import Path

from .fetch_repo import read_project_files, redact
from .product import infer_product, is_toolchain_text

STYLE_EXTS = {".css", ".scss", ".sass", ".less"}
ROUTE_DIRS = {"pages", "app", "routes", "views", "screens", "src/pages", "src/routes", "src/app"}
GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "cursive", "fantasy",
                 "inherit", "initial", "unset", "-apple-system", "arial", "helvetica",
                 "helvetica neue", "roboto", "inter", "sans"}

COLOR_RE = re.compile(
    r"#(?:[0-9a-fA-F]{3,4}\b|[0-9a-fA-F]{6}\b|[0-9a-fA-F]{8}\b)|"
    r"rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}(?:\s*,\s*[\d.]+)?\s*\)")
FONT_RE = re.compile(r"font-family\s*:\s*([^;}]+)", re.IGNORECASE)
GOOGLE_FONT_RE = re.compile(r"family=([A-Za-z0-9 +]+)(?::|&|$)")

FEATURE_HEAD_RE = re.compile(r"^#{1,4}\s*(.*\b(feature|highlight|why|capabilit|what it does|what's inside)\b.*)$",
                             re.IGNORECASE | re.MULTILINE)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(\S.{4,120}?)\s*$", re.MULTILINE)
CODEBLOCK_RE = re.compile(r"```(?:bash|sh|shell|console|zsh)?\s*\n(.*?)```", re.DOTALL)
INSTALL_RE = re.compile(r"\b(npm|npx|pnpm|yarn|bun|pip|pipx|uv|cargo|go|docker|brew|curl|make)\b")


def _hex6(value):
    value = value.strip().lower()
    if value.startswith("#"):
        h = value[1:]
        if len(h) in (3, 4):
            return "#" + "".join(c * 2 for c in h[:3])
        if len(h) >= 6:
            return "#" + h[:6]
        return None
    m = re.match(r"rgba?\(([^)]+)\)", value)
    if m:
        try:
            parts = [float(x) for x in m.group(1).split(",")][:3]
        except ValueError:
            return None
        return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(p)))) for p in parts)
    return None


def _hsv(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def extract_palette(files):
    """Rank repo colors. Returns (palette_dict, source_label) or (None, None)."""
    counts = Counter()
    var_boost_files = re.compile(r"(tailwind\.config|theme|variables|tokens|colors)", re.IGNORECASE)
    for rel, text in files:
        ext = Path(rel).suffix.lower()
        base = Path(rel).name.lower()
        if ext not in STYLE_EXTS and not base.startswith("tailwind.config") and \
           base not in ("theme.json", "colors.json", "tokens.json") and "config" not in base:
            continue
        boost = 2 if var_boost_files.search(rel) else 1
        var_names = set(re.findall(r"(--[\w-]+)\s*:", text))
        named_var_hits = sum(len(v) for v in var_names)  # cheap weight for "themed" files
        for raw in COLOR_RE.findall(text):
            c = _hex6(raw)
            if c:
                counts[c] += boost + (1 if named_var_hits > 10 else 0)
    if not counts:
        return None, None

    def hue_dist(a, b):
        h1, h2 = _hsv(a)[0], _hsv(b)[0]
        return min(abs(h1 - h2), 1 - abs(h1 - h2))

    top = [c for c, _ in counts.most_common(40)]
    darks = [c for c in top if _lum(c) < 0.10]
    lights = [c for c in top if _lum(c) > 0.90]
    chroma = sorted([c for c in top if _hsv(c)[1] > 0.40 and 0.25 < _lum(c) < 0.80],
                    key=lambda c: -counts[c])

    palette = {}
    if darks:
        palette["bg"] = darks[0]
        palette["text"] = lights[0] if lights else "#f5f6fa"
    elif lights:
        palette["bg"] = lights[0]
        palette["text"] = darks[0] if darks else "#16161c"
    if chroma:
        palette["accent"] = chroma[0]
        for c in chroma[1:]:
            if hue_dist(c, chroma[0]) > 0.08:
                palette["accent2"] = c
                break
    src = "repo:styles"
    return palette or None, src if palette else None


def extract_fonts(files):
    counts = Counter()
    for rel, text in files:
        ext = Path(rel).suffix.lower()
        if ext in STYLE_EXTS or ext in (".html", ".htm", ".css"):
            for group in FONT_RE.findall(text):
                for fam in group.split(","):
                    fam = fam.strip().strip("'\"").lower()
                    if fam and fam not in GENERIC_FONTS and len(fam) < 40:
                        counts[fam] += 1
            for fam in GOOGLE_FONT_RE.findall(text):
                fam = fam.replace("+", " ").strip().lower()
                if fam and fam not in GENERIC_FONTS:
                    counts[fam] += 2
    display = mono = None
    for fam, _ in counts.most_common(10):
        if display is None and "mono" not in fam and "code" not in fam:
            display = fam.title()
        if mono is None and ("mono" in fam or "code" in fam):
            mono = fam.title()
    return display, mono


def _readme(files):
    for rel, text in files:
        if Path(rel).name.lower().startswith("readme"):
            return text
    return ""


def _manifest(files, name):
    for rel, text in files:
        if Path(rel).name.lower() == name:
            return text
    return ""


def parse_readme(text):
    out = {"title": "", "tagline": "", "features": [], "commands": []}
    if not text:
        return out
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # drop badges/images
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        out["title"] = re.sub(r"[*_`]", "", m.group(1)).strip()[:80]
    # first meaningful paragraph after the title
    paras = re.split(r"\n\s*\n", body)
    for p in paras[1:] if m else paras:
        p = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", p).strip()
        p = re.sub(r"^[#>\s]+", "", p)
        if len(p) > 24 and not p.startswith(("-", "*", "```", "<")):
            out["tagline"] = re.sub(r"\s+", " ", p)[:220]
            break
    # features: bullets under a features-ish heading, else first bullets anywhere
    feats = []
    fmatch = FEATURE_HEAD_RE.search(body)
    zone = body[fmatch.end():fmatch.end() + 2200] if fmatch else body[:4000]
    for b in BULLET_RE.findall(zone):
        b = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", b)
        b = re.sub(r"[*_`]", "", b).strip()
        if 6 < len(b) <= 120 and not b.lower().startswith(("http", "license")):
            if re.search(
                r"(?i)password|passwd|secret|api[_-]?key|credential|token\s*[:=]|"
                r"\b[A-Z0-9_]{3,}(EMAIL|PASSWORD|SECRET|TOKEN|KEY)\b",
                b,
            ):
                continue
            feats.append(b)
        if len(feats) >= 8:
            break
    out["features"] = feats
    for block in CODEBLOCK_RE.findall(body):
        lines = [ln for ln in block.strip().splitlines() if ln.strip() and not ln.strip().startswith("#")]
        joined = "\n".join(lines[:10])
        if INSTALL_RE.search(joined) and len(joined) < 600:
            out["commands"] = lines[:10]
            break
    return out


def parse_manifest(files):
    stack, name, desc = [], "", ""
    pkg = _manifest(files, "package.json")
    if pkg:
        try:
            data = json.loads(pkg)
            name = data.get("name") or ""
            desc = data.get("description") or ""
            deps = list((data.get("dependencies") or {}).keys()) + list((data.get("devDependencies") or {}).keys())
            notable = [d for d in deps if not d.startswith(("@types/", "eslint", "prettier", "@babel"))]
            stack.extend(notable[:10])
        except (json.JSONDecodeError, AttributeError):
            pass
    for fname, marker in (("requirements.txt", None), ("pyproject.toml", "name"),
                          ("cargo.toml", None), ("go.mod", None), ("gemfile", None)):
        text = _manifest(files, fname)
        if not text:
            continue
        if fname == "requirements.txt":
            stack.extend(re.findall(r"^([A-Za-z0-9_.-]+)", text, re.MULTILINE)[:8])
        elif fname == "pyproject.toml":
            nm = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if nm and not name:
                name = nm.group(1)
            ds = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
            if ds:
                stack.extend(re.findall(r'"([A-Za-z0-9_.-]+)', ds.group(1))[:8])
        elif fname == "cargo.toml":
            nm = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if nm and not name:
                name = nm.group(1)
            ds = re.search(r"\[dependencies\](.*?)(?:\n\[|\Z)", text, re.DOTALL)
            if ds:
                stack.extend(re.findall(r"^([A-Za-z0-9_-]+)\s*=", ds.group(1), re.MULTILINE)[:8])
        elif fname == "go.mod":
            stack.extend(re.findall(r"^\s*([a-z0-9.-]+\.[a-z]+/[\w./-]+)\s+v", text, re.MULTILINE)[:6])
        elif fname == "gemfile":
            stack.extend(re.findall(r"gem\s+['\"]([\w-]+)['\"]", text)[:8])
    seen, dedup = set(), []
    for s in stack:
        base = s.split("/")[-1].lower()
        if base not in seen and len(dedup) < 12:
            seen.add(base)
            dedup.append(s)
    return dedup, name, desc


def extract_routes(files):
    names = []
    for rel, _ in files:
        parts = Path(rel).parts
        if len(parts) < 2:
            continue
        for i, part in enumerate(parts):
            if part.lower() in ROUTE_DIRS and i < len(parts) - 1:
                stem = Path(parts[-1]).stem
                if stem.lower() not in ("index", "_app", "_document", "layout", "loading", "error"):
                    names.append(stem.replace("-", " ").replace("_", " "))
                break
    out, seen = [], set()
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:8]


def repo_stats(files):
    exts = Counter(Path(rel).suffix.lower() for rel, _ in files)
    loc = sum(text.count("\n") + 1 for _, text in files)
    langs = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
             ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
             ".kt": "Kotlin", ".swift": "Swift", ".cpp": "C++", ".c": "C", ".cs": "C#",
             ".php": "PHP", ".vue": "Vue", ".svelte": "Svelte"}
    lang_counts = Counter()
    for ext, n in exts.items():
        if ext in langs:
            lang_counts[langs[ext]] += n
    has_tests = any("test" in rel.lower() or "spec" in rel.lower() for rel, _ in files)
    has_license = any(Path(rel).name.lower().startswith("license") for rel, _ in files)
    return {
        "files": len(files),
        "loc": loc,
        "languages": [l for l, _ in lang_counts.most_common(4)],
        "has_tests": has_tests,
        "has_license": has_license,
    }


def analyze_repo(root, canonical_url, repo_name=None):
    files = list(read_project_files(root))
    readme_text = _readme(files)
    readme = parse_readme(readme_text)
    stack, man_name, man_desc = parse_manifest(files)
    palette, psource = extract_palette(files)
    display_font, mono_font = extract_fonts(files)
    routes = extract_routes(files)
    stats = repo_stats(files)

    if repo_name is None and canonical_url:
        m = re.match(r"https://github\.com/[^/]+/([^/]+)", canonical_url)
        if m:
            repo_name = m.group(1)

    # What is this product? (source-level inference; see product.py)
    product = infer_product(root, canonical_url, readme_text, readme, stack, repo_name)

    name = (product.get("display_name") or man_name or readme["title"]
            or repo_name or Path(root).name)
    name = re.sub(r"^@[\w.-]+/", "", name)  # npm scope
    name = re.sub(r"^[/\\`:]+", "", name).strip() or repo_name or Path(root).name

    # The tagline must describe the PRODUCT. A scaffolded README's first
    # paragraph is build-tool instructions ("First, you will need to run
    # Metro..."), so it is only used when it survives the toolchain filter.
    tagline = ""
    for cand in (product.get("purpose"), man_desc, readme["tagline"]):
        if cand and not is_toolchain_text(cand):
            tagline = cand
            break

    # README bullets are only "features" when they describe the product.
    # A boilerplate README contributes nothing: its bullets are scaffold docs
    # links ("Learn the Basics", "read the official Blog"), not product value.
    features = [redact(f) for f in (product.get("product_features") or [])]
    if not features and not product.get("readme_is_boilerplate"):
        features = [redact(f) for f in readme["features"][:8] if not is_toolchain_text(f)]

    brief = {
        "name": name[:60],
        "url": canonical_url,
        "tagline": tagline[:220],
        "features": features[:8],
        "commands": readme["commands"][:8],
        "stack": stack[:12],
        "routes": routes,
        "palette": palette,
        "palette_source": psource,
        "fonts": {"display": display_font, "mono": mono_font},
        "stats": stats,
        "product": product,
    }
    # compact, redacted excerpt for the LLM (never the whole repo).
    # Boilerplate READMEs are withheld: feeding "run Metro" to the writer is
    # exactly how videos end up being about the toolchain.
    if product.get("readme_is_boilerplate"):
        brief["readme_excerpt"] = ""
    else:
        brief["readme_excerpt"] = redact(readme_text[:1400])
    return brief


def brief_for_prompt(brief):
    """Slim dict the prompt builder serializes - keeps tokens predictable.

    Deliberately PRODUCT-FIRST. Repo metadata (LOC, file counts, dependency
    lists) is only included for developer-audience projects, where devs are the
    viewers and the stack is genuine proof. For an end-user app it is omitted
    entirely so the writer cannot reach for "1.2k lines of code" as a selling
    point to someone who just wants to know what the app does.
    """
    product = brief.get("product") or {}
    audience = product.get("audience", "end_user")

    out = {
        "name": brief["name"],
        "what_it_is": brief["tagline"] or product.get("purpose", ""),
        "audience": ("developers who will install it" if audience == "developer"
                     else "the people who use this product"),
        "platforms": product.get("platforms") or [],
        "topics": product.get("topics") or [],
        "capabilities_with_evidence": [
            {"does": c["phrase"], "proven_by": c["evidence"][:2]}
            for c in (product.get("capabilities") or [])[:10]
        ],
        "product_surfaces": product.get("surfaces") or brief["routes"][:6],
        "ui_vocabulary": product.get("vocabulary") or [],
        "domain_keywords": product.get("keywords") or [],
        "features": brief["features"][:6],
        "palette_hint": brief["palette"],
    }
    if audience == "developer":
        out["install_commands"] = brief["commands"][:6]
        out["stack"] = brief["stack"][:10]
        out["repo_stats"] = {
            "languages": brief["stats"]["languages"],
            **{k: v for k, v in brief["stats"].items() if k != "languages"},
        }
    if brief.get("readme_excerpt"):
        out["readme_excerpt"] = brief["readme_excerpt"][:1200]
    else:
        out["readme_note"] = ("README is framework boilerplate (scaffold instructions), "
                              "NOT a product description - it was withheld on purpose. "
                              "Describe the product from the evidence above.")
    return out
