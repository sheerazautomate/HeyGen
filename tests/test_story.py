"""Story mode tests - schema, analysis, generation, composition, music, commands."""
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from story import (analyze, commands, compose, fetch_repo, music, offline, product,
                   prompts, schema)
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

    def test_stats_keep_value_label(self):
        script = make_script()
        stats = next(s for s in script["scenes"] if s["template"] == "stats")
        self.assertGreaterEqual(len(stats["slots"]["stats"]), 2)
        self.assertIn("value", stats["slots"]["stats"][0])
        self.assertEqual(stats["slots"]["stats"][0]["value"], "1.2k")

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

    def test_safe_no_music_label_maps_to_internal_none(self):
        form = commands.parse_issue_form(FORM_BODY.replace("### Music\n\nlofi", "### Music\n\nno music"))
        self.assertEqual(form["music_mood"], "none")


SCAFFOLD_README = """This is a new [**React Native**](https://reactnative.dev) project,
bootstrapped using [`@react-native-community/cli`](https://github.com/react-native-community/cli).

# Getting Started

> **Note**: Make sure you have completed the Set Up Your Environment guide.

## Step 1: Start Metro

First, you will need to run **Metro**, the JavaScript build tool for React Native.

```sh
npm start
```

## Step 2: Build and run your app

```sh
npm run android
```

# Learn More

- React Native Website - learn more about React Native.
- Learn the Basics - a guided tour of the React Native basics.
- Blog - read the latest official React Native Blog posts.
"""

ANDROID_MANIFEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
  <uses-permission android:name="android.permission.CAMERA" />
  <uses-permission android:name="android.permission.READ_MEDIA_IMAGES" />
  <application android:name=".MainApplication">
    <activity android:name=".MainActivity" />
  </application>
</manifest>
"""

SETTINGS_SCREEN = """import React from 'react';
export default function SettingsScreen() {
  return (
    <View>
      <Row label="Show Coordinates" />
      <Row label="Show Address" />
      <Row label="Edit Watermark" />
      <Input label="Latitude" placeholder="e.g. 31.520370" />
    </View>
  );
}
"""


def _scaffolded_app(root):
    """A repo whose README is framework boilerplate but which IS a real product."""
    root = Path(root)
    (root / "README.md").write_text(SCAFFOLD_README)
    (root / "app.json").write_text(json.dumps({"name": "GeoProof", "displayName": "GeoProof"}))
    (root / "package.json").write_text(json.dumps({
        "name": "GeoProof",
        "dependencies": {"react-native": "0.86.0",
                         "react-native-vision-camera": "^4",
                         "react-native-geolocation-service": "^5",
                         "react-native-share": "^10"}}))
    (root / "android" / "app" / "src" / "main").mkdir(parents=True)
    (root / "android" / "app" / "src" / "main" / "AndroidManifest.xml").write_text(ANDROID_MANIFEST)
    (root / "src" / "screens").mkdir(parents=True)
    (root / "src" / "screens" / "SettingsScreen.tsx").write_text(SETTINGS_SCREEN)
    (root / "src" / "screens" / "CameraScreen.tsx").write_text("export default function CameraScreen(){}")
    (root / "src" / "screens" / "GalleryScreen.tsx").write_text("export default function GalleryScreen(){}")
    return root


class ProductUnderstandingTest(unittest.TestCase):
    """The script must be about the PRODUCT, not about the repository."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _scaffolded_app(self.tmp)
        # no GH token in tests -> pure source-level inference
        self.brief = analyze.analyze_repo(self.tmp, "https://github.com/acme/GeoProof")
        self.product = self.brief["product"]

    def test_scaffold_readme_detected_as_boilerplate(self):
        self.assertTrue(product.readme_is_boilerplate(SCAFFOLD_README))
        self.assertTrue(self.product["readme_is_boilerplate"])

    def test_real_product_readme_is_not_boilerplate(self):
        self.assertFalse(product.readme_is_boilerplate(FIXTURE_README))

    def test_toolchain_never_becomes_the_tagline(self):
        """Regression: tagline was 'First, you will need to run Metro...'."""
        self.assertNotIn("metro", self.brief["tagline"].lower())
        self.assertNotIn("build tool", self.brief["tagline"].lower())

    def test_boilerplate_bullets_never_become_features(self):
        """Regression: 'Learn the Basics' was rendered as a product feature."""
        blob = " ".join(self.brief["features"]).lower()
        for junk in ("learn the basics", "react native website", "blog", "metro"):
            self.assertNotIn(junk, blob)

    def test_capabilities_inferred_from_permissions_and_deps(self):
        keys = {c["key"] for c in self.product["capabilities"]}
        self.assertIn("location", keys)
        self.assertIn("camera", keys)
        for cap in self.product["capabilities"]:
            self.assertTrue(cap["evidence"], f"{cap['key']} must cite evidence")

    def test_surfaces_are_product_screens_not_native_shells(self):
        surfaces = self.product["surfaces"]
        self.assertIn("Camera", surfaces)
        self.assertIn("Gallery", surfaces)
        self.assertNotIn("Main", surfaces)
        self.assertNotIn("Main Application", surfaces)

    def test_ui_vocabulary_captures_the_products_own_words(self):
        vocab = " ".join(self.product["vocabulary"]).lower()
        self.assertIn("show coordinates", vocab)
        self.assertIn("edit watermark", vocab)

    def test_app_is_end_user_and_library_is_developer(self):
        self.assertEqual(self.product["audience"], "end_user")
        lib = tempfile.mkdtemp()
        Path(lib, "README.md").write_text(FIXTURE_README)
        Path(lib, "package.json").write_text(json.dumps({"name": "wombat"}))
        self.assertEqual(
            analyze.analyze_repo(lib, "https://github.com/acme/wombat")["product"]["audience"],
            "developer")

    def test_end_user_script_has_no_repo_metadata_scenes(self):
        """No LOC counts, no dependency chips, no terminal for an end-user app."""
        raw, _ = offline.generate_offline(self.brief, "hype", "balanced", 45, "9:16",
                                          "upbeat", {"quality": "high", "fps": 30, "format": "mp4"})
        script, _ = schema.normalize_script(raw)
        templates = [s["template"] for s in script["scenes"]]
        self.assertNotIn("stack", templates)
        self.assertNotIn("code_showcase", templates)
        self.assertNotIn("stats", templates)
        blob = json.dumps(script).lower()
        for junk in ("lines of code", "source files", "dependencies", "the repo in digits",
                     "metro", "npm start", "boilerplate"):
            self.assertNotIn(junk, blob, f"repo-speak leaked into the script: {junk}")

    def test_end_user_script_talks_about_what_it_does(self):
        raw, _ = offline.generate_offline(self.brief, "hype", "balanced", 45, "9:16",
                                          "upbeat", {"quality": "high", "fps": 30, "format": "mp4"})
        script, _ = schema.normalize_script(raw)
        blob = json.dumps(script).lower()
        self.assertTrue(any(w in blob for w in ("location", "gps", "camera", "coordinates")),
                        "script never mentions what the product actually does")

    def test_developer_script_keeps_stack_and_terminal(self):
        """The fix must not strip legitimate proof from developer tools."""
        lib = tempfile.mkdtemp()
        Path(lib, "README.md").write_text(FIXTURE_README)
        Path(lib, "package.json").write_text(json.dumps(
            {"name": "wombat", "dependencies": {"chalk": "^5", "commander": "^12"}}))
        brief = analyze.analyze_repo(lib, "https://github.com/acme/wombat")
        raw, _ = offline.generate_offline(brief, "corporate", "balanced", 45, "16:9", "corporate", {})
        script, _ = schema.normalize_script(raw)
        templates = [s["template"] for s in script["scenes"]]
        self.assertIn("code_showcase", templates)
        self.assertIn("stack", templates)

    def test_prompt_brief_hides_repo_stats_from_end_user_projects(self):
        slim = analyze.brief_for_prompt(self.brief)
        self.assertNotIn("repo_stats", slim)
        self.assertNotIn("stack", slim)
        self.assertIn("capabilities_with_evidence", slim)
        self.assertIn("ui_vocabulary", slim)
        self.assertIn("readme_note", slim)  # boilerplate withheld, writer told why

    def test_prompt_brief_keeps_repo_stats_for_developer_projects(self):
        lib = tempfile.mkdtemp()
        Path(lib, "README.md").write_text(FIXTURE_README)
        Path(lib, "package.json").write_text(json.dumps({"name": "wombat"}))
        slim = analyze.brief_for_prompt(analyze.analyze_repo(lib, "https://github.com/acme/wombat"))
        self.assertIn("repo_stats", slim)
        self.assertIn("install_commands", slim)

    def test_system_prompt_forbids_repo_and_toolchain_talk(self):
        sp = prompts.system_prompt().lower()
        self.assertIn("product", sp)
        self.assertIn("lines of code", sp)  # named as banned
        self.assertIn("metro", sp)          # toolchain named as banned
        self.assertIn("may not", sp)        # truth rules present

    def test_no_secrets_leak_through_product_inference(self):
        root = Path(self.tmp)
        (root / "src" / "screens" / "LoginScreen.tsx").write_text(
            'const label = "Sign in"; const API_KEY = "sk-abcdefabcdefabcdefabcdef12";')
        brief = analyze.analyze_repo(self.tmp, "https://github.com/acme/GeoProof")
        blob = json.dumps(brief)
        self.assertNotIn("sk-abcdefabcdef", blob)


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
