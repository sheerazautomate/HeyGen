"""Work out what the PRODUCT is - not what the repository contains.

The analyzer used to describe repositories: lines of code, dependency lists,
"how to start the dev server". That produces videos about a codebase instead of
videos about a thing people use. For a scaffolded project it is actively wrong -
GeoProof's README is the stock React Native readme, so the script called it
"a React Native Boilerplate Powered by Metro" and never once mentioned that the
app stamps photos with GPS coordinates and a timestamp.

This module reads the evidence a product actually leaves in its source:

  * platform metadata   GitHub description/topics, app.json displayName, manifests
  * capabilities        OS permissions (camera, location, ...), native modules
  * surfaces            screen/route component names (CameraScreen -> "Camera")
  * vocabulary          user-visible UI strings: labels, placeholders, titles,
                        button text, i18n catalogs
  * audience            is this a developer tool (library/CLI) or an end-user app?

Everything returned is EVIDENCE-BACKED: each inferred capability carries the
files it was seen in, so the script writer may describe the product's purpose
but may not invent features. Boilerplate is detected and demoted rather than
being mistaken for the project's own words.
"""
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------- #
# boilerplate detection                                                        #
# --------------------------------------------------------------------------- #

# Phrases that mean "this README is a framework scaffold, not a product pitch".
BOILERPLATE_MARKERS = (
    "this is a new react native project, bootstrapped",
    "bootstrapped using @react-native-community/cli",
    "bootstrapped with [create react app]",
    "bootstrapped with create react app",
    "this project was bootstrapped",
    "getting started with create react app",
    "this is a [next.js](https://nextjs.org) project bootstrapped",
    "this is a next.js project bootstrapped",
    "first, you will need to run metro",
    "metro, the javascript build tool",
    "run the development server",
    "open [http://localhost:3000](http://localhost:3000)",
    "you can start editing the page by modifying",
    "to learn more about next.js",
    "npm run dev\n# or\nyarn dev",
    "available scripts",
    "in the project directory, you can run",
    "launches the test runner in the interactive watch mode",
    "builds the app for production to the `build` folder",
    "see the section about deployment for more information",
    "welcome to your new ionic app",
    "this template should help get you started developing with vue",
    "recommended ide setup",
    "customize configuration",
    "project setup",
    "compiles and hot-reloads for development",
    "the easiest way to deploy your next.js app",
    "congratulations! you've just created",
    "edit `app.tsx` to change this screen",
    "step 1: start metro",
    "step 2: build and run your app",
    "now that you have successfully run the app",
    "check out the react native website",
    "troubleshooting",
    "learn more",
)

# Sentences/bullets that are about the toolchain, never about the product.
TOOLCHAIN_LINE_RE = re.compile(
    r"\b(metro|webpack|vite|babel|eslint|prettier|cocoapods|gradle|xcode|"
    r"bundler|npm|yarn|pnpm|bun|nvm|node_modules|dev server|hot[- ]?reload|"
    r"fast refresh|watchman|emulator|simulator|scaffold|boilerplate|"
    r"create-react-app|tsconfig|jest|vitest|storybook|dependabot|"
    r"typescript config|linting|formatter)\b"
    # framework-docs chatter that scaffolded READMEs list as "features"
    r"|\b(learn more|learn the basics|check out the docs|official .*blog|"
    r"read the (latest|official)|guided tour|documentation site|"
    r"set up your environment|troubleshooting)\b"
    r"|^(react native|next\.?js|vue|nuxt|svelte|angular|flutter|expo)\b"
    r".{0,40}\b(website|docs|blog|documentation|community)\b",
    re.IGNORECASE)

# A title that is just the framework, not the product.
GENERIC_TITLE_RE = re.compile(
    r"(?i)^(getting started|introduction|overview|readme|installation|setup|"
    r"usage|about|documentation|docs|my app|hello world|untitled|project|repo|"
    r"react native|next\.?js|vue|nuxt|svelte|app|template|starter|boilerplate)$")


def readme_is_boilerplate(text):
    """True when a README is framework scaffolding rather than a product pitch."""
    if not text or len(text.strip()) < 40:
        return True
    low = re.sub(r"\s+", " ", text.lower())
    hits = sum(1 for m in BOILERPLATE_MARKERS if m.replace("\n", " ") in low)
    if hits >= 2:
        return True
    # A short readme that is mostly toolchain talk is boilerplate too.
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return True
    tool_lines = sum(1 for l in lines if TOOLCHAIN_LINE_RE.search(l))
    return hits >= 1 and tool_lines >= max(3, len(lines) * 0.25)


def is_toolchain_text(text):
    """True when a tagline/bullet is about build tooling rather than the product."""
    if not text:
        return True
    t = text.strip()
    if len(t) < 12:
        return True
    return bool(TOOLCHAIN_LINE_RE.search(t))


# --------------------------------------------------------------------------- #
# capability evidence                                                          #
# --------------------------------------------------------------------------- #

# permission / entitlement string -> (capability key, human phrase)
PERMISSION_CAPS = {
    "ACCESS_FINE_LOCATION": ("location", "pinpoint GPS location"),
    "ACCESS_COARSE_LOCATION": ("location", "device location"),
    "ACCESS_BACKGROUND_LOCATION": ("location_bg", "location in the background"),
    "CAMERA": ("camera", "camera capture"),
    "RECORD_AUDIO": ("audio", "audio recording"),
    "READ_CONTACTS": ("contacts", "contacts"),
    "POST_NOTIFICATIONS": ("notifications", "push notifications"),
    "BLUETOOTH": ("bluetooth", "Bluetooth devices"),
    "NFC": ("nfc", "NFC"),
    "USE_BIOMETRIC": ("biometric", "biometric unlock"),
    "USE_FINGERPRINT": ("biometric", "fingerprint unlock"),
    "READ_MEDIA_IMAGES": ("photos", "photo library"),
    "WRITE_EXTERNAL_STORAGE": ("storage", "on-device storage"),
    "READ_EXTERNAL_STORAGE": ("storage", "on-device storage"),
    "NSCameraUsageDescription": ("camera", "camera capture"),
    "NSLocationWhenInUseUsageDescription": ("location", "device location"),
    "NSLocationAlwaysAndWhenInUseUsageDescription": ("location_bg", "location in the background"),
    "NSPhotoLibraryUsageDescription": ("photos", "photo library"),
    "NSMicrophoneUsageDescription": ("audio", "microphone"),
    "NSFaceIDUsageDescription": ("biometric", "Face ID"),
}

# dependency name fragment -> (capability key, human phrase)
DEPENDENCY_CAPS = (
    ("vision-camera", ("camera", "camera capture")),
    ("react-native-camera", ("camera", "camera capture")),
    ("expo-camera", ("camera", "camera capture")),
    ("image-picker", ("photos", "photo library")),
    ("geolocation", ("location", "GPS location")),
    ("expo-location", ("location", "GPS location")),
    ("react-native-maps", ("maps", "maps")),
    ("mapbox", ("maps", "maps")),
    ("leaflet", ("maps", "maps")),
    ("quick-crypto", ("crypto", "cryptographic signing")),
    ("crypto-js", ("crypto", "cryptographic hashing")),
    ("jsonwebtoken", ("auth", "token-based auth")),
    ("bcrypt", ("auth", "password security")),
    ("firebase", ("cloud", "cloud sync")),
    ("supabase", ("cloud", "cloud sync")),
    ("amplify", ("cloud", "cloud sync")),
    ("async-storage", ("offline", "offline storage")),
    ("sqlite", ("offline", "local database")),
    ("realm", ("offline", "local database")),
    ("watermelondb", ("offline", "local database")),
    ("netinfo", ("offline", "offline awareness")),
    ("react-native-share", ("share", "native sharing")),
    ("react-native-fs", ("files", "file export")),
    ("blob-util", ("files", "file handling")),
    ("react-native-pdf", ("pdf", "PDF output")),
    ("pdfkit", ("pdf", "PDF output")),
    ("jspdf", ("pdf", "PDF output")),
    ("xlsx", ("export", "spreadsheet export")),
    ("papaparse", ("export", "CSV export")),
    ("skia", ("graphics", "GPU-accelerated graphics")),
    ("reanimated", ("motion", "fluid animation")),
    ("three", ("3d", "3D rendering")),
    ("tensorflow", ("ml", "on-device ML")),
    ("onnxruntime", ("ml", "on-device ML")),
    ("openai", ("ai", "AI features")),
    ("anthropic", ("ai", "AI features")),
    ("langchain", ("ai", "AI features")),
    ("stripe", ("payments", "payments")),
    ("device-info", ("device", "device identity")),
    ("permissions", None),  # too generic on its own
    ("i18n", ("i18n", "multiple languages")),
    ("socket.io", ("realtime", "realtime updates")),
    ("ws", None),
    ("push-notification", ("notifications", "push notifications")),
    ("notifee", ("notifications", "push notifications")),
)

# Screen/route stems that describe a product surface, with a friendly label.
SURFACE_LABELS = {
    "camera": "Camera", "gallery": "Gallery", "upload": "Upload", "settings": "Settings",
    "license": "Licensing", "login": "Sign in", "signup": "Sign up", "auth": "Auth",
    "home": "Home", "dashboard": "Dashboard", "profile": "Profile", "map": "Map",
    "history": "History", "report": "Reports", "reports": "Reports", "export": "Export",
    "scan": "Scanner", "scanner": "Scanner", "search": "Search", "chat": "Chat",
    "inbox": "Inbox", "feed": "Feed", "cart": "Cart", "checkout": "Checkout",
    "orders": "Orders", "admin": "Admin", "analytics": "Analytics", "billing": "Billing",
    "notifications": "Notifications", "onboarding": "Onboarding", "detail": "Details",
}

SCREEN_FILE_RE = re.compile(r"(?i)^(.*?)(screen|page|view|activity|fragment)\.(tsx?|jsx?|swift|kt|dart|vue|svelte)$")

# user-visible copy in source
UI_STRING_RES = (
    re.compile(r"""(?:title|label|placeholder|heading|header|subtitle|caption|
                    message|tooltip|alt|buttonText|cta|description)\s*[:=]\s*
                   ["'`]([^"'`\n]{4,64})["'`]""", re.VERBOSE),
    re.compile(r""">\s*([A-Z][A-Za-z0-9 ,'’!?.&:%/-]{5,56})\s*<"""),
    re.compile(r"""Alert\.alert\(\s*["'`]([^"'`\n]{4,64})["'`]"""),
    re.compile(r"""(?:t|i18n\.t|translate)\(\s*["'`][^"'`]+["'`]\s*,\s*["'`]([^"'`\n]{4,64})["'`]"""),
)

# strings that are code-ish / developer-facing, not product vocabulary
UI_STRING_REJECT_RE = re.compile(
    r"(?i)(^https?://|^[a-z]+://|^\W|console\.|error:|warn|debug|todo|fixme|"
    r"undefined|null|true|false|^[0-9.\s%]+$|px$|rgba?\(|#[0-9a-f]{3,8}$|"
    r"^[a-z]+([A-Z][a-z]+)+$|_|\{|\}|\$\{|</|/>|import |export |function |return )")

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "your", "you", "are", "was",
    "all", "can", "has", "have", "not", "but", "its", "it's", "our", "out", "get",
    "new", "now", "use", "used", "using", "app", "application", "when", "what", "why",
    "how", "who", "will", "into", "onto", "over", "under", "more", "most", "less",
    "add", "set", "see", "show", "here", "there", "then", "than", "them", "they",
    "each", "every", "also", "just", "only", "very", "make", "made", "does", "done",
    "back", "next", "prev", "yes", "no", "ok", "cancel", "close", "open", "save",
    "edit", "delete", "remove", "select", "choose", "enter", "please", "loading",
    "failed", "success", "error", "warning", "info", "none", "default", "custom",
    "test", "tests", "example", "sample", "demo", "data", "item", "items", "list",
    "page", "screen", "view", "button", "click", "tap", "press", "swipe", "scroll",
}


def _walk_files(root, want_exts=None, max_files=4000):
    """Yield (relpath, Path) for candidate files, skipping heavy/vendor dirs."""
    root = Path(root)
    skip = {"node_modules", ".git", "build", "dist", "out", "vendor", "__pycache__",
            ".venv", "venv", "target", "coverage", ".next", ".nuxt", ".gradle",
            "Pods", "DerivedData", ".idea", ".vscode"}
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".git")]
        for name in sorted(filenames):
            if want_exts and Path(name).suffix.lower() not in want_exts:
                continue
            rel = str(Path(dirpath).joinpath(name).relative_to(root)).replace(os.sep, "/")
            yield rel, Path(dirpath) / name
            n += 1
            if n >= max_files:
                return


def _read(path, cap=60_000):
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:cap]
    except (OSError, UnicodeError):
        return ""


# --------------------------------------------------------------------------- #
# GitHub metadata (description + topics) - the most product-shaped signal      #
# --------------------------------------------------------------------------- #

def github_metadata(canonical_url, timeout=15):
    """Fetch description/topics/homepage via gh CLI. Returns {} when unavailable.

    The repo description ("Coordinates TimeStamp App") is usually the single most
    product-describing sentence that exists, and it lives outside the clone.
    """
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)", canonical_url or "")
    if not m:
        return {}
    slug = f"{m.group(1)}/{m.group(2)}"
    env = dict(os.environ)
    if not (env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")):
        return {}
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}",
             "--jq", '{description: .description, topics: .topics, homepage: .homepage, '
                     'language: .language, stars: .stargazers_count, license: .license.spdx_id}'],
            capture_output=True, timeout=timeout, env=env, text=True)
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout.strip() or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, ValueError):
        return {}
    return {
        "description": (data.get("description") or "").strip(),
        "topics": [t for t in (data.get("topics") or []) if isinstance(t, str)][:12],
        "homepage": (data.get("homepage") or "").strip(),
        "language": data.get("language") or "",
        "stars": data.get("stars") or 0,
        "license": data.get("license") or "",
    }


# --------------------------------------------------------------------------- #
# evidence collectors                                                          #
# --------------------------------------------------------------------------- #

def collect_permissions(root):
    """Capabilities proven by OS permission declarations. -> {cap: {phrase, evidence}}"""
    found = {}
    for rel, path in _walk_files(root, {".xml", ".plist", ".json", ".entitlements"}):
        low = rel.lower()
        if not any(k in low for k in ("androidmanifest", "info.plist", "app.json",
                                      "entitlements", "expo.json", "manifest.json")):
            continue
        text = _read(path, 40_000)
        for token, mapped in PERMISSION_CAPS.items():
            if token in text:
                key, phrase = mapped
                entry = found.setdefault(key, {"phrase": phrase, "evidence": []})
                if rel not in entry["evidence"]:
                    entry["evidence"].append(rel)
    return found


def collect_dependency_caps(stack):
    """Capabilities implied by notable dependencies."""
    found = {}
    for dep in stack or []:
        d = dep.lower()
        for frag, mapped in DEPENDENCY_CAPS:
            if frag in d and mapped:
                key, phrase = mapped
                entry = found.setdefault(key, {"phrase": phrase, "evidence": []})
                if dep not in entry["evidence"]:
                    entry["evidence"].append(dep)
    return found


def collect_surfaces(root):
    """Product surfaces from screen/page component filenames -> ['Camera', 'Gallery']."""
    labels, seen = [], set()
    for rel, _path in _walk_files(root, {".tsx", ".ts", ".jsx", ".js", ".swift",
                                         ".kt", ".dart", ".vue", ".svelte"}):
        name = Path(rel).name
        parts = [p.lower() for p in Path(rel).parts]
        # native shells (MainActivity/MainApplication/AppDelegate) are platform
        # plumbing, never a product surface
        if parts and parts[0] in ("android", "ios", "macos", "windows", "linux"):
            continue
        if re.match(r"(?i)^(main(activity|application)|appdelegate|scenedelegate)\.",
                    name):
            continue
        in_screen_dir = any(p in ("screens", "pages", "views", "routes", "app") for p in parts)
        m = SCREEN_FILE_RE.match(name)
        stem = None
        if m and m.group(1):
            stem = m.group(1)
        elif in_screen_dir:
            raw = Path(name).stem
            if raw.lower() not in ("index", "_app", "_document", "layout", "loading",
                                   "error", "not-found", "template", "route", "page"):
                stem = raw
        if not stem:
            continue
        key = re.sub(r"[^a-z]", "", stem.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        label = SURFACE_LABELS.get(key)
        if not label:
            # CamelCase / kebab -> Title Case words
            words = re.sub(r"[-_]", " ", re.sub(r"(?<!^)(?=[A-Z])", " ", stem)).split()
            words = [w for w in words if w.lower() not in ("screen", "page", "view")]
            if not words:
                continue
            label = " ".join(w.capitalize() for w in words)[:22]
        if 2 <= len(label) <= 22:
            labels.append(label)
    return labels[:10]


def collect_ui_vocabulary(root, limit=60):
    """User-visible strings from source: the product's own words."""
    strings, counts = [], Counter()
    for rel, path in _walk_files(root, {".tsx", ".ts", ".jsx", ".js", ".swift", ".kt",
                                        ".dart", ".vue", ".svelte", ".html"}):
        parts = [p.lower() for p in Path(rel).parts]
        if any(p in ("test", "tests", "__tests__", "spec", "e2e", "stories") for p in parts):
            continue
        if re.search(r"(?i)\.(test|spec|stories|d)\.", Path(rel).name):
            continue
        text = _read(path, 40_000)
        if not text:
            continue
        for rx in UI_STRING_RES:
            for hit in rx.findall(text):
                s = re.sub(r"\s+", " ", hit).strip()
                if not (4 <= len(s) <= 64) or UI_STRING_REJECT_RE.search(s):
                    continue
                if not re.search(r"[A-Za-z]{3}", s):
                    continue
                counts[s] += 1
                if s not in strings:
                    strings.append(s)
        if len(strings) > limit * 4:
            break
    # i18n catalogs are pure product vocabulary
    for rel, path in _walk_files(root, {".json"}):
        low = rel.lower()
        if not re.search(r"(locales?|i18n|lang|translations?)/", low):
            continue
        try:
            data = json.loads(_read(path, 30_000) or "{}")
        except (json.JSONDecodeError, ValueError):
            continue

        def flat(obj, depth=0):
            if depth > 3:
                return
            if isinstance(obj, dict):
                for v in obj.values():
                    yield from flat(v, depth + 1)
            elif isinstance(obj, str):
                yield obj

        for s in flat(data):
            s = re.sub(r"\s+", " ", s).strip()
            if 4 <= len(s) <= 64 and not UI_STRING_REJECT_RE.search(s):
                counts[s] += 2
                if s not in strings:
                    strings.append(s)
    ranked = sorted(strings, key=lambda s: (-counts[s], len(s)))
    return ranked[:limit]


def domain_keywords(*text_blobs, limit=12):
    """Salient domain nouns across the product's own vocabulary."""
    counts = Counter()
    for blob in text_blobs:
        if not blob:
            continue
        if isinstance(blob, (list, tuple)):
            blob = " ".join(str(b) for b in blob)
        for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", str(blob)):
            lw = w.lower()
            if lw in STOPWORDS or len(lw) < 4:
                continue
            if TOOLCHAIN_LINE_RE.search(lw):
                continue
            counts[lw] += 1
    return [w for w, _ in counts.most_common(limit)]


# --------------------------------------------------------------------------- #
# audience                                                                     #
# --------------------------------------------------------------------------- #

DEV_TOOL_SIGNALS = re.compile(
    r"(?i)\b(library|framework|sdk|cli|command[- ]line|api client|toolkit|plugin|"
    r"middleware|compiler|linter|parser|package|task runner|build tool|"
    r"code generator|test runner|import \{|from ['\"])")

# "how do you obtain it?" - installing via a package manager means the user is
# a developer; downloading an app from a store means they are not.
INSTALL_SIGNALS = re.compile(
    r"(?i)\b(npm|pnpm|yarn|bun)\s+(install|add|i)\b|"
    r"\bnpx\s|\bpip(x|3)?\s+install\b|\buv\s+(pip\s+)?(add|install)\b|"
    r"\bcargo\s+(add|install)\b|\bgo\s+get\b|\bgem\s+install\b|"
    r"\bcomposer\s+require\b|\bbrew\s+install\b|\bdotnet\s+add\s+package\b")


def detect_audience(brief_bits, has_app_shell, surfaces, permissions, topics,
                    commands=None):
    """'end_user' (an app people use) vs 'developer' (a library/CLI devs install).

    Repo-metadata scenes (LOC, dependency chips) are legitimate proof for a
    developer tool and pure noise for an end-user product.
    """
    dev_score = end_score = 0
    text = " ".join(str(b) for b in brief_bits if b)
    if DEV_TOOL_SIGNALS.search(text):
        dev_score += 2
    cmd_text = " ".join(commands or [])
    if INSTALL_SIGNALS.search(cmd_text) or INSTALL_SIGNALS.search(text):
        dev_score += 3
    for t in topics or []:
        tl = t.lower()
        if tl in ("library", "sdk", "cli", "framework", "api", "npm-package",
                  "python-package", "developer-tools", "devtools", "plugin"):
            dev_score += 2
        if tl in ("android", "ios", "mobile", "app", "react-native", "flutter",
                  "webapp", "saas", "productivity"):
            end_score += 1
    if has_app_shell:
        end_score += 2
    if surfaces:
        end_score += min(3, len(surfaces))
    if permissions:
        end_score += 2
    return "developer" if dev_score > end_score else "end_user"


# --------------------------------------------------------------------------- #
# public entry point                                                           #
# --------------------------------------------------------------------------- #

def infer_product(root, canonical_url, readme_text, readme_parsed, stack, repo_name):
    """Return a product-shaped view of the project, with evidence attached."""
    root = Path(root)
    meta = github_metadata(canonical_url)
    boiler = readme_is_boilerplate(readme_text)

    perms = collect_permissions(root)
    dep_caps = collect_dependency_caps(stack)
    capabilities = {}
    for src in (perms, dep_caps):
        for key, val in src.items():
            entry = capabilities.setdefault(key, {"phrase": val["phrase"], "evidence": []})
            for ev in val["evidence"]:
                if ev not in entry["evidence"]:
                    entry["evidence"].append(ev)
    # background location implies location; don't claim both
    if "location" in capabilities and "location_bg" in capabilities:
        capabilities.pop("location_bg", None)

    surfaces = collect_surfaces(root)
    vocabulary = collect_ui_vocabulary(root)
    has_app_shell = any((root / f).exists() for f in
                        ("app.json", "App.tsx", "App.js", "app/build.gradle",
                         "android/app/build.gradle", "pubspec.yaml", "Info.plist"))

    display_name = ""
    for cand in ("app.json", "expo.json", "app.config.json"):
        p = root / cand
        if p.exists():
            try:
                data = json.loads(_read(p, 8000) or "{}")
                display_name = (data.get("displayName") or data.get("name")
                                or (data.get("expo") or {}).get("name") or "")
                if display_name:
                    break
            except (json.JSONDecodeError, ValueError, AttributeError):
                pass

    topics = meta.get("topics") or []
    audience = detect_audience(
        [meta.get("description"), readme_parsed.get("tagline") if not boiler else "",
         " ".join(stack or [])],
        has_app_shell, surfaces, perms, topics,
        commands=(readme_parsed.get("commands") or []) if not boiler else [])

    # --- the one-line "what is it" ----------------------------------------- #
    # Priority: GitHub description > non-boilerplate README tagline > topics.
    purpose, purpose_source = "", ""
    if meta.get("description"):
        purpose, purpose_source = meta["description"], "github:description"
    elif not boiler and readme_parsed.get("tagline") and not is_toolchain_text(readme_parsed["tagline"]):
        purpose, purpose_source = readme_parsed["tagline"], "readme:tagline"
    elif topics:
        purpose, purpose_source = ", ".join(topics[:5]), "github:topics"

    name = display_name or repo_name or ""
    if GENERIC_TITLE_RE.match((name or "").strip()):
        name = repo_name or name

    # product-y README features only (drop "run npm install" bullets)
    product_features = []
    if not boiler:
        for f in readme_parsed.get("features") or []:
            if not is_toolchain_text(f):
                product_features.append(f)

    keywords = domain_keywords(purpose, " ".join(topics), " ".join(surfaces),
                               " ".join(vocabulary[:30]), " ".join(product_features))

    # Rank capabilities by how much they say about the PRODUCT. "pinpoint GPS
    # location" defines what an app is for; "on-device storage" does not.
    cap_rank = {
        "location": 0, "camera": 1, "crypto": 2, "ml": 3, "ai": 3, "maps": 4,
        "scanner": 4, "payments": 5, "realtime": 5, "audio": 6, "biometric": 6,
        "nfc": 7, "bluetooth": 7, "photos": 8, "share": 9, "pdf": 9, "export": 9,
        "cloud": 10, "offline": 11, "notifications": 12, "auth": 13, "i18n": 14,
        "files": 15, "device": 16, "3d": 17, "motion": 18, "graphics": 19,
        "storage": 20, "contacts": 21,
    }
    ordered_caps = sorted(
        capabilities.items(),
        key=lambda kv: (cap_rank.get(kv[0], 12), kv[0]))

    return {
        "display_name": name,
        "purpose": purpose[:220],
        "purpose_source": purpose_source,
        "topics": topics,
        "homepage": meta.get("homepage", ""),
        "stars": meta.get("stars", 0),
        "license": meta.get("license", ""),
        "audience": audience,
        "readme_is_boilerplate": boiler,
        "capabilities": [
            {"key": k, "phrase": v["phrase"], "evidence": v["evidence"][:4]}
            for k, v in ordered_caps
        ],
        "surfaces": surfaces,
        "vocabulary": vocabulary[:40],
        "keywords": keywords,
        "product_features": product_features[:8],
        "platforms": _platforms(root),
    }


def _platforms(root):
    root = Path(root)
    out = []
    if (root / "android").is_dir():
        out.append("Android")
    if (root / "ios").is_dir():
        out.append("iOS")
    if (root / "pubspec.yaml").exists() and not out:
        out.append("Mobile")
    if any((root / f).exists() for f in ("next.config.js", "next.config.mjs", "next.config.ts",
                                         "vite.config.ts", "vite.config.js", "index.html")):
        out.append("Web")
    if (root / "Dockerfile").exists():
        out.append("Docker")
    return out[:4]
