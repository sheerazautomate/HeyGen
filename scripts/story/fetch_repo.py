"""Fetch and safely read a public GitHub repo for story analysis.

Security posture (mirrors and extends latent-spaces/brag's secret handling):
  - only https://github.com/<owner>/<repo> URLs are accepted
  - clone is shallow, prompted-less, timed out, size-capped, .git removed
  - a skip list keeps env files, credentials, keys, lockfiles, vendored and
    built artifacts OUT of analysis (and therefore out of any video/prompt)
  - everything we do read is additionally scanned for token-shaped strings and
    redacted before it can reach an LLM prompt, a storyboard, or a video
"""
import os
import re
import shutil
import subprocess
from pathlib import Path


class FetchError(RuntimeError):
    pass


REPO_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)/?(?:\.git)?(?:[?#].*)?$")

MAX_REPO_MB_DEFAULT = 150
CLONE_TIMEOUT_DEFAULT = 120
MAX_TOTAL_TEXT_BYTES = 280_000
MAX_FILE_BYTES = 24_000
MAX_FILES = 500

# never read these - no exceptions (secrets, blobs, noise)
SKIP_BASENAMES = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "out",
    ".next", ".nuxt", ".cache", "__pycache__", ".venv", "venv", "target",
    "coverage", ".idea", ".vscode", ".github/assets",
}
SKIP_FILE_RE = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa.*|.*\.keystore|"
    r"credentials?(\..*)?|secrets?(\..*)?|.*secret.*|.*credential.*|\.npmrc|\.netrc|"
    r"package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|cargo\.lock|"
    r"composer\.lock|gemfile\.lock|go\.sum|.*\.min\.(js|css)|.*\.map)$",
    re.IGNORECASE,
)
TEXT_EXTS = {
    ".md", ".mdx", ".rst", ".txt", ".json", ".toml", ".yaml", ".yml", ".cfg", ".ini",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".css", ".scss", ".sass", ".less", ".html", ".htm",
    ".vue", ".svelte", ".astro", ".cs", ".cpp", ".c", ".h", ".hpp", ".swift",
    ".sh", ".bash", ".zsh", ".ps1", ".sql", ".graphql", ".tf", ".mod",
}
LOGO_RE = re.compile(r"(^|/)(logo|icon|brand)(-logo)?\.(svg|png)$", re.IGNORECASE)

# token-shaped strings get nuked even from files we do read
SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"), re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"), re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[\w/+.-]{16,}"),
]


def redact(text):
    for pat in SECRET_PATTERNS:
        text = pat.sub("[redacted]", text)
    return text


def validate_repo_url(url):
    """Return canonical https://github.com/owner/repo or raise FetchError."""
    if not isinstance(url, str):
        raise FetchError("Repo URL must be text.")
    m = REPO_RE.match(url.strip())
    if not m:
        raise FetchError(
            "Only public https://github.com/<owner>/<repo> links are supported "
            "(private repos need tokens this private tool doesn't accept).")
    owner, repo = m.group(1), m.group(2)
    if owner.startswith(".") or repo in (".", ".."):
        raise FetchError("That GitHub link doesn't look right.")
    return f"https://github.com/{owner}/{repo}"


def clone_repo(url, dest, max_mb=MAX_REPO_MB_DEFAULT, timeout=CLONE_TIMEOUT_DEFAULT):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", "--quiet", url, str(dest)],
            check=True, timeout=timeout, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired as exc:
        raise FetchError(f"Cloning took longer than {timeout}s - repo too big or network slow.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip().splitlines()
        hint = detail[-1] if detail else "git clone failed"
        raise FetchError(f"Couldn't clone {url} ({hint}). Private or missing repo?") from exc
    except FileNotFoundError as exc:
        raise FetchError("git is not installed on this runner.") from exc

    shutil.rmtree(dest / ".git", ignore_errors=True)
    total = 0
    for p in dest.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
            if total > max_mb * 1024 * 1024:
                shutil.rmtree(dest, ignore_errors=True)
                raise FetchError(f"Repo exceeds {max_mb} MB - too big for story analysis.")
    return dest


def _skippable(rel):
    parts = [p.lower() for p in Path(rel).parts]
    if any(part in SKIP_BASENAMES for part in parts):
        return True
    return bool(SKIP_FILE_RE.search("/".join(parts)))


def read_project_files(root):
    """Yield (relpath, redacted_text) for safe, text files, within budgets."""
    root = Path(root)
    seen, budget = 0, MAX_TOTAL_TEXT_BYTES
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_BASENAMES and not d.startswith(".git")]
        rel_dir = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            rel = str((rel_dir / name)) if str(rel_dir) != "." else name
            if _skippable(rel):
                continue
            ext = Path(name).suffix.lower()
            if ext not in TEXT_EXTS:
                continue
            p = Path(dirpath) / name
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]
            except (OSError, UnicodeError):
                continue
            text = redact(raw)
            seen += 1
            budget -= len(text.encode("utf-8", errors="replace"))
            yield rel, text
            if seen >= MAX_FILES or budget <= 0:
                return


def find_logo(root):
    """Best-effort logo discovery -> raw.githubusercontent URL for the public repo."""
    root = Path(root)
    candidates = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_BASENAMES]
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > 3:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            rel = Path(dirpath).relative_to(root) / name
            if LOGO_RE.search(str(rel).replace(os.sep, "/")):
                candidates.append(str(rel).replace(os.sep, "/"))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c.lower().endswith(".png"), len(c)))
    return candidates[0]


def raw_url(canonical_repo_url, relpath):
    return f"{canonical_repo_url}/raw/HEAD/{relpath}"
