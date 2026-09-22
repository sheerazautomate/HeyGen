"""Mood music, generated - not downloaded.

Each track is procedurally synthesized with only the stdlib (wave + math), so
it's deterministic per (mood, length, seed) and 100% royalty-free by
construction - no licensing concerns, nothing binary committed to git.
Custom user URLs are handled separately by fetch_custom().

A track = chord pad (detuned sines, slow attack) + soft bass + filtered-noise
hats + a mood-appropriate pluck/arp pattern + gentle delay. Mixed, soft-clipped,
fade in/out, written as 16-bit mono WAV (render.sh loops/levels it against the
video with ffmpeg).
"""
import hashlib
import json
import math
import os
import random
import struct
import urllib.request
import wave
from pathlib import Path

SR = 22050

# scale degrees (semitones from root A2=110Hz) per mood: (progression of chords, bpm,
# pad level, bass level, hat level, arp pattern, brightness 0-1, swing)
MOODS = {
    "upbeat":    dict(chords=[[0, 4, 7, 12], [5, 9, 12, 16], [7, 11, 14, 17], [0, 4, 7, 12]],
                      bpm=118, pad=0.16, bass=0.20, hat=0.10, arp=[0, 1, 2, 3, 2, 1], bright=0.7, swing=0.0),
    "corporate": dict(chords=[[0, 4, 7, 11], [3, 7, 10, 14], [5, 9, 12, 16], [7, 11, 14, 17]],
                      bpm=100, pad=0.22, bass=0.16, hat=0.05, arp=[0, 2, 1, 3], bright=0.45, swing=0.0),
    "cinematic": dict(chords=[[0, 3, 7, 14], [-2, 2, 5, 10], [1, 5, 8, 12], [0, 3, 7, 14]],
                      bpm=76, pad=0.30, bass=0.22, hat=0.02, arp=[], bright=0.3, swing=0.0),
    "lofi":      dict(chords=[[0, 3, 7, 10], [5, 8, 12, 15], [3, 7, 10, 14], [7, 10, 14, 17]],
                      bpm=72, pad=0.24, bass=0.20, hat=0.07, arp=[0, 2, 3, 1], bright=0.18, swing=0.14),
    "playful":   dict(chords=[[0, 4, 7, 12], [7, 11, 14, 17], [5, 9, 12, 16], [7, 11, 14, 19]],
                      bpm=128, pad=0.14, bass=0.18, hat=0.11, arp=[0, 2, 4, 3, 1, 2], bright=0.8, swing=0.06),
}
ROOT = 110.0  # A2
MAX_CUSTOM_MB = 40


def _freq(semi):
    return ROOT * (2 ** (semi / 12))


def _env(i, n, a, d, s_frac=0.0, r=0):
    """attack/decay/sustain/release envelope value for sample i of n."""
    if i < a:
        return i / max(1, a)
    if i < a + d:
        return 1.0 - (1.0 - s_frac) * ((i - a) / max(1, d))
    if i < n - r:
        return s_frac
    return s_frac * max(0.0, (n - i) / max(1, r))


def _pad(samples, chord, start, length, level, bright):
    a = int(0.35 * SR)
    r = min(int(0.5 * SR), length // 2)
    for note in chord:
        for detune in (-4, 3):
            f = _freq(note) * (2 ** (detune / 1200))
            for i in range(length):
                t = (start + i) / SR
                if start + i >= len(samples):
                    break
                v = math.sin(2 * math.pi * f * t) + 0.35 * bright * math.sin(4 * math.pi * f * t)
                samples[start + i] += v * level * 0.5 * _env(i, length, a, 0, 0.85, r)


def _bass(samples, note, start, length, level):
    f = _freq(note - 12)
    a = int(0.01 * SR)
    for i in range(length):
        t = (start + i) / SR
        if start + i >= len(samples):
            break
        v = math.sin(2 * math.pi * f * t)
        v += 0.25 * math.sin(4 * math.pi * f * t)
        samples[start + i] += v * level * _env(i, length, a, 0, 0.8, int(0.08 * SR))


def _kick(samples, start, level=0.5):
    n = int(0.16 * SR)
    for i in range(min(n, len(samples) - start)):
        t = i / SR
        f = 110 * math.exp(-t * 28) + 44
        v = math.sin(2 * math.pi * f * t) * math.exp(-t * 22)
        samples[start + i] += v * level


def _hat(samples, start, level, bright, rng):
    n = int(0.05 * SR)
    for i in range(min(n, len(samples) - start)):
        v = (rng.random() * 2 - 1) * math.exp(-i / (SR * 0.012 * (0.4 + bright)))
        samples[start + i] += v * level


def _pluck(samples, note, start, level, bright):
    f = _freq(note + 12)
    n = int(0.32 * SR)
    for i in range(min(n, len(samples) - start)):
        t = i / SR
        v = math.sin(2 * math.pi * f * t) * math.exp(-t * (6 - 3 * bright))
        v += 0.4 * math.sin(4 * math.pi * f * t) * math.exp(-t * 9)
        samples[start + i] += v * level


def render_wav(mood, seconds, out_path, seed_text="story"):
    cfg = MOODS.get(mood, MOODS["upbeat"])
    rng = random.Random(int(hashlib.sha256((mood + seed_text).encode()).hexdigest()[:8], 16))
    seconds = max(4.0, min(600.0, float(seconds)))
    n_total = int(seconds * SR)
    samples = [0.0] * n_total

    beat = 60.0 / cfg["bpm"]
    bar = beat * 4
    swing = cfg["swing"] * beat * 0.5

    t = 0.0
    chord_idx = 0
    while t < seconds:
        chord = cfg["chords"][chord_idx % len(cfg["chords"])]
        start = int(t * SR)
        length = min(int(bar * SR), n_total - start)
        if length <= 0:
            break
        _pad(samples, chord, start, length, cfg["pad"], cfg["bright"])
        _bass(samples, chord[0], start, length, cfg["bass"])
        for b in range(4):
            bt = start + int(b * beat * SR) + (int(swing * SR) if b % 2 else 0)
            if mood in ("upbeat", "playful"):
                _kick(samples, bt, 0.42)
            for half in (0, 1):
                ht = bt + int(half * beat * 0.5 * SR)
                if half or mood != "cinematic":
                    _hat(samples, ht, cfg["hat"] * (0.7 if half else 1.0), cfg["bright"], rng)
        arp = cfg["arp"]
        for j, step in enumerate(arp):
            at = t + j * (bar / len(arp))
            if at < seconds:
                _pluck(samples, chord[step % len(chord)], int(at * SR),
                       0.16 + 0.08 * cfg["bright"], cfg["bright"])
        chord_idx += 1
        t += bar

    # gentle feedback delay ("space")
    delay = int(0.28 * SR)
    wet = 0.18
    for i in range(delay, n_total):
        samples[i] += samples[i - delay] * wet

    # normalize + soft clip + fades
    peak = max(1e-6, max(abs(s) for s in samples))
    gain = 0.85 / peak
    fade_in, fade_out = int(0.5 * SR), int(2.0 * SR)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = bytearray()
        for i, s in enumerate(samples):
            v = math.tanh(s * gain * 1.2)
            if i < fade_in:
                v *= i / fade_in
            if i > n_total - fade_out:
                v *= max(0.0, (n_total - i) / fade_out)
            frames += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
        w.writeframes(bytes(frames))
    return out


def fetch_custom(url, dest_dir, timeout=25):
    """Download a user-supplied audio URL (https only, size-capped)."""
    from .schema import ScriptError
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 500:
        raise ScriptError("Music URL must be a short https:// link.")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "music_src" + (Path(url.split("?")[0]).suffix[:8] or ".bin")
    req = urllib.request.Request(url, headers={"User-Agent": "hyperframes-story/1.0"})
    cap = MAX_CUSTOM_MB * 1024 * 1024
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
            remaining = cap
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                remaining -= len(chunk)
                if remaining < 0:
                    dest.unlink(missing_ok=True)
                    raise ScriptError(f"Music file exceeds {MAX_CUSTOM_MB} MB.")
                fh.write(chunk)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ScriptError(f"Couldn't fetch music URL: {exc}") from exc
    return dest


def metadata(kind, mood=None, url=None, volume=0.35):
    return json.dumps({"kind": kind, "mood": mood, "url": url, "volume": round(float(volume), 2)})


def describe(kind, mood, url):
    if kind == "none":
        return "no music (silent video)"
    if kind == "url":
        return f"custom track: {url}"
    return f"generated track: **{mood}** mood (synthesized, royalty-free)"
