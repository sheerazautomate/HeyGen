import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/pilot'))
from model import CONSENT_PRIVATE, CONSENT_PUBLIC, MARKER, InvalidRequest, enforce_quota, parse_request, validate_html
from admit import admit
from check_outputs import collect
from offline import localize

POLICY = json.loads(Path('.github/pilot.json').read_text())
HTML = '<div data-composition-id="main" data-width="1920" data-height="1080" data-duration="5"></div>'


def body(html=HTML, **overrides):
    # Pro version 2 with private
    packet = {'version': 2, 'title': 'Hello 🌍 <script>', 'html': html, 'private': True, 'fps': 30, 'quality': 'standard', 'format': 'mp4', 'variables': {}, **overrides}
    encoded = base64.b64encode(json.dumps(packet, ensure_ascii=False).encode()).decode()
    return f'### Render request\n\n```text\nHF1.{encoded}\n```\n\n### Private use\n\n{CONSENT_PRIVATE}'


def issue(number=1, author='sheerazautomate', **overrides):
    return {'number': number, 'user': {'login': author}, 'title': '[Video] hello',
            'created_at': '2026-09-21T10:00:00Z', 'state': 'open', 'body': body(), **overrides}


class FakeAPI:
    repo = 'owner/repo'

    def __init__(self, item=None, comments=None, issues=None):
        self.issue = item or issue()
        self.comments = comments or []
        self.issues = issues or [self.issue]
        self.writes = []

    def pages(self, path):
        return self.comments if path.endswith('/comments') else self.issues

    def request(self, path, method='GET', data=None):
        if method == 'GET': return self.issue
        self.writes.append((path, data))
        return {'id': 123}


class ValidationTests(unittest.TestCase):
    def test_examples(self):
        for path in Path('examples').glob('*.html'):
            self.assertGreater(validate_html(path.read_text(), POLICY)['duration'], 0)

    def test_round_trip(self):
        self.assertEqual(parse_request(body(), POLICY)['html'], HTML)
        self.assertEqual(parse_request(body(), POLICY)['title'], 'Hello 🌍 <script>')
        self.assertEqual(parse_request(body(fps=60), POLICY)['fps'], 60)
        self.assertEqual(parse_request(body(quality='high'), POLICY)['quality'], 'high')

    def test_invalid_packet(self):
        for value in ('HF1.bad', 'HF1.e30=', 'HF1.W10='):
            with self.subTest(value=value), self.assertRaises(InvalidRequest):
                parse_request(value + '\n' + CONSENT_PRIVATE, POLICY)

    def test_missing_consent(self):
        with self.assertRaises(InvalidRequest): 
            # No consent at all
            packet = {'version': 2, 'title': 'x', 'html': HTML, 'private': True}
            encoded = base64.b64encode(json.dumps(packet).encode()).decode()
            parse_request(f'HF1.{encoded}', POLICY)

    def test_private_allowed(self):
        # Private should be allowed now
        self.assertEqual(parse_request(body(private=True), POLICY)['html'], HTML)
        # Also old public v1 still allowed for backward compat
        packet = {'version': 1, 'title': 'Hello', 'html': HTML, 'public': True}
        encoded = base64.b64encode(json.dumps(packet).encode()).decode()
        body_text = f'HF1.{encoded}\n{CONSENT_PUBLIC}'
        self.assertEqual(parse_request(body_text, POLICY)['html'], HTML)

    def test_multiple_packets(self):
        with self.assertRaises(InvalidRequest): parse_request(body() + '\n' + body(), POLICY)

    def test_empty_large_or_plain_html(self):
        # 10MB limit now, so 11MB should fail
        huge = 'a' * (11 * 1024 * 1024)
        for text in ('', huge, '<h1>Ordinary HTML</h1>', HTML + HTML):
            with self.subTest(text=text[:20]), self.assertRaises(InvalidRequest): validate_html(text, POLICY)

    def test_duration_and_dimensions(self):
        # New limits: duration up to 600, dimension up to 4096
        for before, after in [('\"5\"', '\"nan\"'), ('\"5\"', '\"inf\"'),
                              ('\"5\"', '\"601\"'),  # over 600 should fail
                              ('\"5\"', '\"-1\"'), ('\"1920\"', '\"5000\"'), ('\"1080\"', '\"5000\"'),
                              ('\"1080\"', '\"0\"'), ('\"1080\"', '\"abc\"')]:
            with self.subTest(after=after), self.assertRaises(InvalidRequest):
                validate_html(HTML.replace(before, after), POLICY)

    def test_valid_pro_dimensions(self):
        # 4K should be valid now
        html_4k = HTML.replace('data-width="1920"', 'data-width="3840"').replace('data-height="1080"', 'data-height="2160"')
        self.assertEqual(validate_html(html_4k, POLICY)['width'], 3840)
        # 10 min duration should be valid
        html_long = HTML.replace('data-duration="5"', 'data-duration="500"')
        self.assertEqual(validate_html(html_long, POLICY)['duration'], 500)

    def test_portrait(self):
        text = HTML.replace('data-width="1920"', 'data-width="1080"').replace('data-height="1080"', 'data-height="1920"')
        self.assertEqual(validate_html(text, POLICY)['height'], 1920)

    def test_quota_private_mode_no_limit(self):
        # In private_mode, quota should not raise
        policy = {**POLICY, 'private_mode': True, 'approved_users': ['a'], 'per_user_daily': 2, 'global_daily': 2}
        items = [issue(1, 'a'), issue(2, 'a'), issue(3, 'a')]
        # Should not raise even though over limit, because private_mode
        enforce_quota(items[2], items, policy)

    def test_quota_counts_when_not_private(self):
        # When not private, old logic still applies
        policy = {**POLICY, 'private_mode': False, 'approved_users': ['sheerazautomate'], 'per_user_daily': 2, 'global_daily': 10}
        previous = [issue(1, body='edited', title='renamed', state='closed'), issue(2)]
        enforce_quota(issue(2), previous, policy)

    def test_offline_replacements_keep_external(self):
        known = 'https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js'
        result = localize(f'<script src="{known}"></script><script src="https://evil.test/a.js"></script>')
        self.assertIn('src="gsap.min.js"', result)
        self.assertIn('src="https://evil.test/a.js"', result)
        # External assets should be kept (network allowed in pro)
        self.assertIn('https://evil.test/a.js', result)


class AdmissionTests(unittest.TestCase):
    def run_admit(self, api, policy=POLICY):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'GITHUB_RUN_ID': '44'}):
            return admit(api, {'issue': issue()}, policy, Path(temp))

    def test_admitted_private_mode(self):
        api = FakeAPI()
        result = self.run_admit(api)
        self.assertEqual(result['issue'], 1)
        self.assertNotIn('html', result)
        self.assertIn('"status": "queued"', api.writes[0][1]['body'])
        self.assertIn('fps', result)

    def test_private_mode_allows_any_user(self):
        # In private_mode, even if approved_users empty, should allow
        api = FakeAPI(item=issue(author='randomuser'))
        result = self.run_admit(api, {**POLICY, 'private_mode': True, 'approved_users': []})
        self.assertIsNotNone(result)

    def test_disabled(self):
        api = FakeAPI()
        self.assertIsNone(self.run_admit(api, {**POLICY, 'enabled': False}))
        self.assertIn('paused', api.writes[0][1]['body'])

    def test_edited_snapshot_rejected(self):
        api = FakeAPI(issue(body=body(title='Changed')))
        self.assertIsNone(self.run_admit(api))
        self.assertIn('edited', api.writes[0][1]['body'])

    def test_rerun_skipped(self):
        api = FakeAPI(comments=[{'user': {'login': 'github-actions[bot]', 'type': 'Bot'}, 'body': MARKER}])
        self.assertIsNone(self.run_admit(api)); self.assertEqual(api.writes, [])

    def test_forged_status_not_trusted(self):
        api = FakeAPI(comments=[{'user': {'login': 'stranger', 'type': 'User'}, 'body': MARKER}])
        self.assertIsNotNone(self.run_admit(api))


class OutputTests(unittest.TestCase):
    def test_regular_mp4(self):
        with tempfile.TemporaryDirectory() as d:
            source, dest = Path(d) / 'source', Path(d) / 'dest'; source.mkdir()
            source.joinpath('video.mp4').write_bytes(b'\x00\x00\x00\x18ftypisomtest')
            collect(source, dest)
            self.assertTrue(dest.joinpath('video.mp4').is_file())

    def test_webm_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            source, dest = Path(d) / 'source', Path(d) / 'dest'; source.mkdir()
            source.joinpath('video.webm').write_bytes(b'\x1a\x45\xdf\xa3' + b'\x00'*2000)
            source.joinpath('video.mp4').write_bytes(b'\x00\x00\x00\x18ftypisomtest')
            collect(source, dest)
            self.assertTrue(dest.joinpath('video.webm').is_file())

    def test_reject_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            source, dest = Path(d) / 'source', Path(d) / 'dest'; source.mkdir()
            source.joinpath('video.mp4').symlink_to('/etc/passwd')
            with self.assertRaises(OSError): collect(source, dest)

    def test_reject_fifo(self):
        with tempfile.TemporaryDirectory() as d:
            source, dest = Path(d) / 'source', Path(d) / 'dest'; source.mkdir()
            os.mkfifo(source / 'video.mp4')
            with self.assertRaises(ValueError): collect(source, dest)

    def test_reject_arbitrary_output(self):
        with tempfile.TemporaryDirectory() as d:
            source, dest = Path(d) / 'source', Path(d) / 'dest'; source.mkdir()
            source.joinpath('video.mp4').write_text('<script>alert(1)</script>')
            with self.assertRaises(ValueError): collect(source, dest)


if __name__ == '__main__': unittest.main()
