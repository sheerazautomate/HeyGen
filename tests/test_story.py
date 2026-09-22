"""Story mode tests - schema, analysis, generation, composition, music, commands."""
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from story import analyze, commands, compose, fetch_repo, music, offline, schema
from story.story import encode_packet, decode_packet, storyboard_md


FIXTURE_README = """# Wombat

Fast task runner for Python monorepos.

## Features

- Smart caching: never run the same task twice
- Parallel execution across CPU cores
- Config in TOML: one file, zero magic
- Watch mode for instant feedback

## Install

```bash
pip install wombat
wombat run tests
```
"""

FIXTURE_CSS = """:root {
  --bg: #0d1117; --surface: #161b22; --text: #f0f6fc; --muted: #8b949e;
  --accent: #58a6ff; --brand: #ff7b72;
}
body { background: #0d1117; color: #f0f6fc; font-family: 'Sora', sans-serif; }
code { font-family: 'JetBrains Mono', monospace; color: #58a6ff; }
a { color: #58a6ff; }
"""


def make_script(**over):
    base = {
        "tone": "cinematic", "pace": "balanced", "aspect": "16:9", "duration": 30,
        "project": {"name": "Wombat", "url": "https://github.com/acme/wombat",
                    "tagline": "Fast task runner for Python monorepos."},
        "palette": {"bg": "#0d1117", "surface": "#161b22", "text": "#f0f6fc",
                    "muted": "#8b949e", "accent": "#58a6ff", "accent2": "#ff7b72",
                    "source": "test"},
        "music": {"kind": "mood", "mood": "upbeat", "volume": 0.35},
        "scenes": [
            {"id": "s1", "template": "hero", "duration_s": 5,
             "slots": {"kicker": "A PROJECT STORY", "headline": "Run tasks at wombat speed",
                       "subline": "Fast task runner for Python monorepos."}},
            {"id": "s2", "template": "features_grid", "duration_s": 6,
             "slots": {"kicker": "INSIDE", "heading": "Why Wombat",
                       "features": [{"title": "Caching", "desc": "Never run twice"},
                                    {"title": "Parallel", "desc": "All cores"},
                                    {"title": "TOML", "desc": "Zero magic"},
                                    {"title": "Watch", "desc": "Instant feedback"}]}},
            {"id": "s3", "template": "code_showcase", "duration_s": 6,
             "slots": {"kicker": "START", "heading": "Up in seconds", "filename": "terminal",
                       "code": "pip install wombat\nwombat run tests", "caption": "Two commands."}},
            {"id": "s4", "template": "stats", "duration_s": 5,
             "slots": {"kicker": "NUMBERS", "heading": "In digits",
                       "stats": [{"value": "1.2k", "label": "lines"}, {"value": "98", "label": "tests"}]}},
            {"id": "s5", "template": "outro", "duration_s": 8,
             "slots": {"headline": "Try Wombat today", "subline": "Fast task runner.",
                       "cta_label": "Star on GitHub", "url": "github.com/acme/wombat"}},
        ],
        "render": {"quality": "standard", "fps": 30, "format": "mp4"},
        "share_copy": {"tweet": "Wombat — run tasks fast. https://github.com/acme/wombat",
                       "linkedin": "Wombat is a fast task runner. https://github.com/acme/wombat"},
    }
    base.update(over)
    return schema.normalize_script(base)[0]


class SchemaTest(unittest.TestCase):
    def test_valid_script_normalizes(self):
        script, warnings = schema.normalize_script(make_script())
        self.assertEqual(script["project"]["name"], "Wombat")
        self.assertEqual(len(script["scenes"]), 5)
        total = sum(s["duration_s"] for s in script["scenes"])
        self.assertAlmostEqual(total, script["duration"], delta=0.8)

    def test_scenes_retimed_to_duration(self):
        raw = make_script(duration=60)
        self.assertAlmostEqual(sum(s["duration_s"] for s in raw["scenes"]), 60, delta=0.8)

    def test_bad_template_falls_back(self):
        raw = make_script()
        raw["scenes"][1]["template"] = "does_not_exist"
        script, warnings = schema.normalize_script(raw)
        self.assertEqual(script["scenes"][1]["template"], "statement")
        self.assertTrue(any("unknown template" in w for w in warnings))

    def test_overlong_copy_is_clamped(self):
        raw = make_script()
        raw["scenes"][0]["slots"]["headline"] = "x " * 200
        script, warnings = schema.normalize_script(raw)
        self.assertLessEqual(len(script["scenes"][0]["slots"]["headline"]), 64)

    def test_invalid_colors_repaired(self):
        raw = make_script()
        raw["palette"]["accent"] = "not-a-color"
        script, _ = schema.normalize_script(raw)
        self.assertRegex(script["palette"]["accent"], r"^#[0-9a-f]{6}$")

    def test_low_contrast_text_fixed(self):
        raw = make_script()
        raw["palette"]["text"] = "#0d1118"  # nearly identical to bg
        script, warnings = schema.normalize_script(raw)
        self.assertTrue(schema.contrast_ratio(script["palette"]["bg"], script["palette"]["text"]) >= 4.5)

    def test_grid_counts_enforced_by_templates(self):
        script = make_script()
        self.assertIn(len(script["scenes"][1]["slots"]["features"]), (2, 3, 4, 5, 6))

    def test_custom_html_is_sanitized(self):
        raw = make_script()
        raw["scenes"].insert(1, {"id": "sx", "template": "custom", "duration_s": 4, "slots": {
            "html": '<div onclick="steal()">ok</div><script>alert(1)</script><img src="http://x/y.png">',
            "caption": "test"}})
        script, _ = schema.normalize_script(raw)
        html = script["scenes"][1]["slots"]["html"]
        self.assertNotIn("script", html.lower())
        self.assertNotIn("onclick", html.lower())
        self.assertNotIn('src="http://', html)

    def test_bad_music_url_rejected(self):
        raw = make_script()
        raw["music"] = {"kind": "url", "url": "http://insecure.example/x.mp3"}
        script, warnings = schema.normalize_script(raw)
        self.assertEqual(script["music"]["kind"], "mood")


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        root = Path(self.tmp)
        (root / "README.md").write_text(FIXTURE_README)
        (root / "styles" ).mkdir()
        (root / "styles" / "main.css").write_text(FIXTURE_CSS)
        (root / "package.json").write_text(json.dumps({
            "name": "wombat", "description": "Fast task runner",
            "dependencies": {"react": "^19", "chalk": "^5", "commander": "^12"}}))
        (root / ".env").write_text("SECRET_KEY=sk-supersecretvalue1234567890abcdef\n")
        (root / "package-lock.json").write_text("{}")

    def test_brief_fields(self):
        brief = analyze.analyze_repo(self.tmp, "https://github.com/acme/wombat")
        self.assertEqual(brief["name"], "wombat")
        self.assertIn("Fast task runner", brief["tagline"])
        self.assertTrue(any("caching" in f.lower() for f in brief["features"]))
        self.assertTrue(any("pip install" in c for c in brief["commands"]))
        self.assertIn("react", brief["stack"])

    def test_palette_from_css(self):
        brief = analyze.analyze_repo(self.tmp, "https://github.com/acme/wombat")
        self.assertIsNotNone(brief["palette"])
        self.assertEqual(brief["palette"]["bg"], "#0d1117")
        self.assertEqual(brief["palette"]["accent"], "#58a6ff")
        self.assertEqual(brief["palette_source"], "repo:styles")

    def test_fonts_detected(self):
        brief = analyze.analyze_repo(self.tmp, "https://github.com/acme/wombat")
        self.assertEqual(brief["fonts"]["display"], "Sora")
        self.assertEqual(brief["fonts"]["mono"], "Jetbrains Mono")

    def test_secrets_never_read(self):
        brief = analyze.analyze_repo(self.tmp, "https://github.com/acme/wombat")
        blob = json.dumps(brief)
        self.assertNotIn("supersecretvalue", blob)
        self.assertNotIn("SECRET_KEY", blob)

    def test_repo_url_validation(self):
        self.assertEqual(fetch_repo.validate_repo_url("https://github.com/a/b"),
                         "https://github.com/a/b")
        self.assertEqual(fetch_repo.validate_repo_url("https://github.com/a/b/"),
                         "https://github.com/a/b")
        self.assertEqual(fetch_repo.validate_repo_url("https://github.com/a/b.git"),
                         "https://github.com/a/b")
        with self.assertRaises(fetch_repo.FetchError):
            fetch_repo.validate_repo_url("https://gitlab.com/a/b")
        with self.assertRaises(fetch_repo.FetchError):
            fetch_repo.validate_repo_url("https://github.com/a/b/tree/main")

    def test_redaction(self):
        text = "token ghp_abcdefghijklmnopqrstuvwxyz1234 and key sk-abcdefabcdefabcdefabcdef12"
        out = fetch_repo.redact(text)
        self.assertNotIn("ghp_", out)
        self.assertNotIn("sk-abcdef", out)


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        root = Path(self.tmp)
        (root / "README.md").write_text(FIXTURE_README)
        (root / "styles").mkdir()
        (root / "styles" / "main.css").write_text(FIXTURE_CSS)
        (root / "package.json").write_text(json.dumps({"name": "wombat", "dependencies": {"react": "^19"}}))
        self.brief = analyze.analyze_repo(root, "https://github.com/acme/wombat")

    def test_offline_script_valid(self):
        raw, _ = offline.generate_offline(self.brief, "cinematic", "balanced", 30, "16:9",
                                          "upbeat", {"quality": "standard", "fps": 30, "format": "mp4"})
        script, _ = schema.normalize_script(raw)
        self.assertEqual(script["scenes"][0]["template"], "hero")
        self.assertEqual(script["scenes"][-1]["template"], "outro")
        self.assertTrue(any(s["template"] == "code_showcase" for s in script["scenes"]))
        self.assertEqual(script["palette"]["bg"], "#0d1117")

    def test_feature_grid_filled(self):
        raw, _ = offline.generate_offline(self.brief, "playful", "snappy", 30, "16:9",
                                          "upbeat", {"quality": "standard", "fps": 30, "format": "mp4"})
        script, _ = schema.normalize_script(raw)
        grid = next(s for s in script["scenes"] if s["template"] == "features_grid")
        self.assertIn(len(grid["slots"]["features"]), (3, 4, 6))

    def test_pace_changes_scene_count(self):
        def count(pace):
            raw, _ = offline.generate_offline(self.brief, "cinematic", pace, 60, "16:9",
                                              "upbeat", {})
            script, _ = schema.normalize_script(raw)
            return len(script["scenes"])
        self.assertLessEqual(count("snappy"), 10)
        self.assertGreaterEqual(count("snappy"), count("slow"))


class ComposeTest(unittest.TestCase):
    def test_composition_contract(self):
        html = compose.compose_html(make_script())
        self.assertIn('data-composition-id="main"', html)
        self.assertIn('data-width="1920"', html)
        self.assertIn('data-height="1080"', html)
        self.assertIn('data-duration="', html)
        self.assertIn('window.__timelines["main"] = tl;', html)
        self.assertIn('class="scene clip" id="s1" data-start="0"', html)
        self.assertIn('style="visibility: hidden"', html)  # scenes 2+ hidden
        self.assertEqual(html.count('class="scene clip"'), 5)

    def test_deterministic(self):
        a = compose.compose_html(make_script())
        b = compose.compose_html(make_script())
        self.assertEqual(a, b)

    def test_aspect_tokens(self):
        html = compose.compose_html(make_script(aspect="9:16"))
        self.assertIn('data-width="1080"', html)
        self.assertIn('data-height="1920"', html)

    def test_all_scenes_valid_html(self):
        html = compose.compose_html(make_script())
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "pilot"))
        from model import validate_html
        props = validate_html(html, {"max_html_bytes": 10 * 1024 * 1024, "max_duration_seconds": 600,
                                     "max_dimension": 4096, "max_pixels": 16777216})
        self.assertEqual(props["width"], 1920)
        self.assertEqual(props["height"], 1080)

    def test_every_frame_painted(self):
        html = compose.compose_html(make_script())
        # every scene gets the full-bleed background stack (no dead space)
        self.assertEqual(html.count('class="bg"'), 5)
        self.assertEqual(html.count("orb orb-a"), 5)
        self.assertIn('class="grain"', html)

    def test_copy_appears_verbatim(self):
        html = compose.compose_html(make_script())
        self.assertIn("Run tasks at wombat speed", html)
        self.assertIn("github.com/acme/wombat", html)


class MusicTest(unittest.TestCase):
    def test_wav_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "t.wav"
            music.render_wav("upbeat", 6, out, seed_text="wombat")
            with wave.open(str(out)) as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertEqual(w.getframerate(), 22050)
                self.assertAlmostEqual(w.getnframes() / 22050, 6, delta=0.05)

    def test_deterministic_per_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.wav"
            b = Path(tmp) / "b.wav"
            music.render_wav("lofi", 4, a, seed_text="wombat")
            music.render_wav("lofi", 4, b, seed_text="wombat")
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_all_moods_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mood in music.MOODS:
                out = Path(tmp) / f"{mood}.wav"
                music.render_wav(mood, 3, out)
                self.assertGreater(out.stat().st_size, 10000)


class CommandsTest(unittest.TestCase):
    def test_plain_render(self):
        cmd = commands.parse_command("/render")
        self.assertEqual(cmd["handle"], "/render")
        self.assertFalse(commands.has_script_changes(cmd))

    def test_render_overrides(self):
        cmd = commands.parse_command("/render quality:high fps:60 format:webm")
        self.assertEqual(cmd["render_overrides"], {"quality": "high", "fps": 60, "format": "webm"})
        self.assertFalse(commands.has_script_changes(cmd))

    def test_script_overrides_flag_regen(self):
        cmd = commands.parse_command("/render tone:playful length:45 pace:snappy")
        self.assertEqual(cmd["script_overrides"]["tone"], "playful")
        self.assertEqual(cmd["script_overrides"]["duration"], 45.0)
        self.assertTrue(commands.has_script_changes(cmd))

    def test_scene_edit(self):
        script = make_script()
        cmd = commands.parse_command('/render s2.heading:"A much better heading"')
        applied = commands.validate_scene_edits(cmd["scene_edits"], script)
        self.assertEqual(script["scenes"][1]["slots"]["heading"], "A much better heading")
        self.assertTrue(applied)

    def test_bad_scene_ref_raises(self):
        script = make_script()
        cmd = commands.parse_command('/render s9.heading:"nope"')
        with self.assertRaises(commands.CommandError):
            commands.validate_scene_edits(cmd["scene_edits"], script)

    def test_bad_value_raises(self):
        with self.assertRaises(commands.CommandError):
            commands.parse_command("/render fps:144")

    def test_music_url_shorthand(self):
        cmd = commands.parse_command('/render music:"https://cdn.example.com/t.mp3"')
        self.assertEqual(cmd["render_overrides"]["music_kind"], "url")
        self.assertEqual(cmd["render_overrides"]["music_url"], "https://cdn.example.com/t.mp3")

    def test_non_command_ignored(self):
        self.assertIsNone(commands.parse_command("nice video!"))
        self.assertIsNone(commands.parse_command(""))


FORM_BODY = """### Public repo URL

https://github.com/acme/wombat

### Tone

playful

### Pace

snappy

### Length (seconds)

45

### Aspect

9:16 (1080×1920)

### Music

lofi

### Custom music URL (optional)

_No response_

### Quality

high

### FPS

60

### Format

webm (alpha)

### Private use confirmation

- [X] This repo is mine
"""


class IssueFormTest(unittest.TestCase):
    def test_parses_all_fields(self):
        form = commands.parse_issue_form(FORM_BODY)
        self.assertEqual(form["repo_url"], "https://github.com/acme/wombat")
        self.assertEqual(form["tone"], "playful")
        self.assertEqual(form["pace"], "snappy")
        self.assertEqual(form["length"], 45.0)
        self.assertEqual(form["aspect"], "9:16")
        self.assertEqual(form["music_mood"], "lofi")
        self.assertIsNone(form["music_url"])
        self.assertEqual(form["quality"], "high")
        self.assertEqual(form["fps"], 60)
        self.assertEqual(form["format"], "webm")

    def test_story_comment_merges(self):
        form = commands.parse_issue_form(FORM_BODY)
        cmd = commands.parse_command("/story tone:corporate")
        merged = commands.merge_command_into_form(form, cmd)
        self.assertEqual(merged["tone"], "corporate")
        self.assertEqual(merged["fps"], 60)  # untouched


class PacketTest(unittest.TestCase):
    def test_roundtrip(self):
        script = make_script()
        packet = encode_packet(script, "offline", "https://github.com/acme/wombat", logo_url=None)
        packed = decode_packet(packet)
        self.assertEqual(packed["script"]["project"]["name"], "Wombat")
        self.assertEqual(packed["repo"], "https://github.com/acme/wombat")

    def test_storyboard_basics(self):
        script = make_script()
        packet = encode_packet(script, "offline", "https://github.com/acme/wombat")
        md = storyboard_md(script, {"engine": "offline", "warnings": ["test warning"]},
                           "https://github.com/acme/wombat", packet)
        self.assertIn("<!-- hyperframes-story:v1 -->", md)
        self.assertIn("### Scenes", md)
        self.assertIn("/render", md)
        self.assertIn("ST1.", md)
        self.assertIn("test warning", md)
        self.assertLess(len(md), 65000)  # GitHub comment limit


if __name__ == "__main__":
    unittest.main()
