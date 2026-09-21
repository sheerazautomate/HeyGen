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
from model import CONSENT, MARKER, InvalidRequest, enforce_quota, parse_request, validate_html
from admit import admit
from check_outputs import collect
from offline import localize

POLICY = json.loads(Path('.github/pilot.json').read_text())
HTML = '<div data-composition-id="main" data-width="1920" data-height="1080" data-duration="5"></div>'


def body(html=HTML, **overrides):
    packet = {'version': 1, 'title': 'Hello 🌍 <script>', 'html': html, 'public': True, **overrides}
    encoded = base64.b64encode(json.dumps(packet, ensure_ascii=False).encode()).decode()
    return f'### Render request\n\n```text\nHF1.{encoded}\n```\n\n### Public sharing\n\n{CONSENT}'


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

    def test_invalid_packet(self):
        for value in ('HF1.bad', 'HF1.e30=', 'HF1.W10='):
            with self.subTest(value=value), self.assertRaises(InvalidRequest):
                parse_request(value + '\n' + CONSENT, POLICY)

    def test_missing_consent(self):
        with self.assertRaises(InvalidRequest): parse_request(body().replace('[X]', '[ ]'), POLICY)

    def test_public_required(self):
        with self.assertRaises(InvalidRequest): parse_request(body(public=False), POLICY)

    def test_multiple_packets(self):
        with self.assertRaises(InvalidRequest): parse_request(body() + '\n' + body(), POLICY)

    def test_empty_large_or_plain_html(self):
        for text in ('', 'a' * 24577, '<h1>Ordinary HTML</h1>', HTML + HTML):
            with self.subTest(text=text[:20]), self.assertRaises(InvalidRequest): validate_html(text, POLICY)

    def test_duration_and_dimensions(self):
        for before, after in [('"5"', '"nan"'), ('"5"', '"inf"'), ('"5"', '"31"'),
                              ('"5"', '"-1"'), ('"1920"', '"1921"'), ('"1080"', '"1920"'),
                              ('"1080"', '"0"'), ('"1080"', '"abc"')]:
            with self.subTest(after=after), self.assertRaises(InvalidRequest):
                validate_html(HTML.replace(before, after), POLICY)

    def test_portrait(self):
        text = HTML.replace('data-width="1920"', 'data-width="1080"').replace('data-height="1080"', 'data-height="1920"')
        self.assertEqual(validate_html(text, POLICY)['height'], 1920)

    def test_quota_counts_invalid_edited_closed_issues(self):
        previous = [issue(1, body='edited', title='renamed', state='closed'), issue(2)]
        enforce_quota(issue(2), previous, POLICY)
        with self.assertRaises(InvalidRequest): enforce_quota(issue(3), previous + [issue(3)], POLICY)

    def test_global_quota_and_future_issues(self):
        policy = {**POLICY, 'approved_users': ['a', 'b'], 'global_daily': 2}
        items = [issue(1, 'a'), issue(2, 'b'), issue(3, 'a')]
        enforce_quota(items[1], items, policy)
        with self.assertRaises(InvalidRequest): enforce_quota(items[2], items, policy)

    def test_quota_fails_closed_on_missing_index(self):
        with self.assertRaises(InvalidRequest): enforce_quota(issue(2), [issue(1)], POLICY)

    def test_other_users_and_days_do_not_count(self):
        items = [issue(1, 'stranger'), issue(2, created_at='2026-09-20T10:00:00Z'), issue(3)]
        enforce_quota(items[-1], items, POLICY)

    def test_offline_replacements_do_not_fetch_anything(self):
        known = 'https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js'
        result = localize(f'<script src="{known}"></script><script src="https://evil.test/a.js"></script>')
        self.assertIn('src="gsap.min.js"', result)
        self.assertIn('src="https://evil.test/a.js"', result)
        self.assertNotIn('src="gsap.min.js"', localize(f'<script src="{known}?evil"></script>'))


class AdmissionTests(unittest.TestCase):
    def run_admit(self, api, policy=POLICY):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'GITHUB_RUN_ID': '44'}):
            return admit(api, {'issue': issue()}, policy, Path(temp))

    def test_admitted(self):
        api = FakeAPI()
        result = self.run_admit(api)
        self.assertEqual(result['issue'], 1)
        self.assertNotIn('html', result)
        self.assertIn('"status": "queued"', api.writes[0][1]['body'])

    def test_not_approved(self):
        api = FakeAPI()
        self.assertIsNone(self.run_admit(api, {**POLICY, 'approved_users': []}))
        self.assertIn('not approved', api.writes[0][1]['body'])

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
