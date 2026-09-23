"""Free-of-cost LLM client for story generation.

GitHub Models (the old zero-key option) was retired on 2026-07-30, so this
client targets OpenAI-compatible endpoints with genuinely free tiers. Pick a
provider via STORY_PROVIDER (default: auto) and put ONE matching key in repo
secrets - no billing involved for any of these:

  provider   base_url                                    key env            free tier (as of 2026)
  groq       https://api.groq.com/openai/v1              GROQ_API_KEY       ~1,000 req/day, no card
  gemini     https://generativelanguage.googleapis.com/  GEMINI_API_KEY     free tier, no card
                    v1beta/openai                        (or GOOGLE_API_KEY)
  cerebras   https://api.cerebras.ai/v1                  CEREBRAS_API_KEY   ~1M tokens/day
  openrouter https://openrouter.ai/api/v1                OPENROUTER_API_KEY 50 req/day on :free models
  ollama     http://localhost:11434/v1                   (none)             unlimited, local, offline
  offline    (no HTTP at all - rule-based generator)     (none)             unlimited, always works

auto = first provider in the list whose key is present, else ollama if
reachable, else offline. Resolution details are returned so the storyboard can
say exactly how the script was written.
"""
import json
import os
import urllib.error
import urllib.request

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_envs": ["GROQ_API_KEY"],
        "model": "llama-3.3-70b-versatile",
        "json_mode": True,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_envs": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "model": "gemini-2.0-flash",
        "json_mode": True,
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "key_envs": ["CEREBRAS_API_KEY"],
        "model": "llama-3.3-70b",
        "json_mode": True,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_envs": ["OPENROUTER_API_KEY"],
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "json_mode": True,
    },
    "ollama": {
        "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "key_envs": [],
        "model": "qwen2.5:7b",
        "json_mode": True,
    },
}

AUTO_ORDER = ["groq", "gemini", "cerebras", "openrouter", "ollama"]

MAX_SCRIPT_TOKENS = 4000
MAX_BRIEF_CHARS = 6000  # keeps us inside free-tier per-request token limits


class LLMError(RuntimeError):
    pass


def _key_for(preset):
    for env in preset["key_envs"]:
        val = os.environ.get(env, "").strip()
        if val:
            return val
    return None


def resolve_provider(explicit=None):
    """Return (provider_name, config) or ('offline', reason_dict)."""
    explicit = (explicit or os.environ.get("STORY_PROVIDER", "auto")).strip().lower()
    if explicit == "offline":
        return "offline", {"reason": "STORY_PROVIDER=offline"}
    if explicit and explicit != "auto":
        preset = PROVIDERS.get(explicit)
        if not preset:
            return "offline", {"reason": f"unknown provider {explicit!r}"}
        if explicit == "ollama":
            return "ollama", _config_for("ollama", preset, None)
        key = _key_for(preset)
        if not key:
            return "offline", {"reason": f"{explicit} selected but no key in env ({', '.join(preset['key_envs'])})"}
        return explicit, _config_for(explicit, preset, key)
    for name in AUTO_ORDER:
        preset = PROVIDERS[name]
        if name == "ollama":
            if _ollama_alive(preset):
                return "ollama", _config_for(name, preset, None)
            continue
        key = _key_for(preset)
        if key:
            return name, _config_for(name, preset, key)
    return "offline", {"reason": "no free provider key found (set e.g. GROQ_API_KEY); "
                                 "add one to repo secrets, or run locally with Ollama"}


def _config_for(name, preset, key):
    return {
        "provider": name,
        "base_url": preset["base_url"].rstrip("/"),
        "api_key": key,
        "model": os.environ.get("STORY_MODEL", preset["model"]),
        "json_mode": preset["json_mode"],
    }


def _ollama_alive(preset):
    try:
        url = preset["base_url"].rstrip("/").removesuffix("/v1") + "/api/tags"
        with urllib.request.urlopen(url, timeout=2):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def chat_json(messages, config, timeout=90, retries=3):
    """POST chat.completions; return parsed JSON object from the reply."""
    url = f"{config['base_url']}/chat/completions"
    body = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": MAX_SCRIPT_TOKENS,
    }
    if config.get("json_mode"):
        body["response_format"] = {"type": "json_object"}
    headers = {
        "Content-Type": "application/json",
        # Groq's Cloudflare edge rejects Python-urllib's default User-Agent
        # with HTTP 403 "error code: 1010" before the key is ever checked
        # (music.py already sends this header for the same reason).
        "User-Agent": "hyperframes-story/1.0",
    }
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.load(resp)
            content = payload["choices"][0]["message"]["content"]
            return _parse_json(content)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode(errors="replace")[:300]
            except OSError:
                pass
            last_err = LLMError(f"{config['provider']} HTTP {exc.code}: {detail}")
            if exc.code in (401, 403):
                break  # bad key - retrying won't help
            if exc.code == 429 or exc.code >= 500:
                import time
                time.sleep(2 ** attempt * 3)
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = LLMError(f"{config['provider']} unreachable: {exc}")
            import time
            time.sleep(2 ** attempt * 3)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            last_err = LLMError(f"{config['provider']} returned malformed JSON: {exc}")
            break
    raise last_err or LLMError(f"{config['provider']} failed without detail")


def _parse_json(content):
    text = content.strip()
    if text.startswith("```"):
        # strip ```json fences if the model added them anyway
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("model reply contained no JSON object")
    return json.loads(text[start:end + 1])
