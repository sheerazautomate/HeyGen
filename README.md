# HyperFrames Studio — a GitHub-only video pilot

A public, non-technical website for turning **HyperFrames-compatible `script.html`** into an MP4.
People choose their file, submit a guided request using their GitHub account, then watch and download
finished videos on the same site. **No visitor tokens, repository write access, API keys, or installations.**

## The product choices

- **GitHub-only:** GitHub Pages hosts the studio; Issues accept requests; Actions renders; Releases store videos.
- **GitHub sign-in:** users authenticate on GitHub's submission page, not inside the studio. Pages cannot
  securely implement a standalone login/upload backend. The GitHub handoff is intentional and visible.
- **Public:** requests (including source HTML) and videos are public. Base64 is transport encoding, **not encryption**.
- **Approved-user pilot:** the website and gallery are open to everyone, but only approved GitHub accounts render.
- **Free to pilot users:** no billing integration. This is not a promise of unlimited or free infrastructure.

## User journey

1. Open the studio and choose a compatible `.html` file, or click **Try an example**.
2. Name the video, accept public sharing, and click **Prepare my video**.
3. Click **Copy your render request** and **Open the GitHub form**.
4. Sign in to GitHub, paste into **Render request**, check public sharing, and click **Create**.
5. Copy the resulting issue link into the studio's **Track a request** page.
6. See **Queued → Creating video → Ready**, or a readable rejection/failure explanation. Watch/download on
   that page or in the **Public gallery**.

The site never executes uploaded HTML. It only reads metadata and prepares a transport packet. Large
request packets go through the clipboard, not query strings (which would truncate realistic HTML files).
A manual-copy fallback works when browser clipboard permission is blocked.

## Owner setup / launch checklist

1. **Merge these changes into the repository's default branch.** Issue workflows and issue forms must
   exist there; deploying only the Pages site from a feature branch is not enough.
2. Keep the repository **public**, with **Issues** and **Actions** enabled. Allow the checked-in workflows
   and the GitHub-maintained actions they use. Organization policy must permit job-scoped `issues: write`
   and `contents: write` permissions.
3. In **Settings → Pages**, select **GitHub Actions** as the source. `deploy-pages.yml` builds/deploys on
   relevant changes to `main`, or can be run manually. The site for this repository is
   `https://sheerazautomate.github.io/HeyGen/`.
4. Review [`.github/pilot.json`](.github/pilot.json). Initially **only `sheerazautomate` is approved**.
   Add the exact GitHub usernames of invited users to `approved_users`.
5. Wait for **Test studio and pilot** to pass, including its **sandbox-smoke** job. Submit the bundled
   example from an approved account. Confirm its bot comment, public release, gallery playback, download,
   and request tracking all work. Try an unapproved account and confirm it is rejected without rendering.
6. Only then invite the rest of the pilot. Monitor Actions/storage usage and check GitHub's applicable
   Pages/Actions terms and limits before opening a broadly available rendering service.

**No new repository secrets are needed for the pilot.** It uses short-lived job-scoped `GITHUB_TOKEN`s in
trusted jobs. The existing `HEYGEN_API_KEY`, if present, is **not** passed to the pilot renderer.

### Pilot limits

| Limit | Initial value |
| --- | --- |
| Approved users | `sheerazautomate` only |
| Requests per user per UTC day | 2 |
| Requests across approved users per UTC day | 10 |
| Source HTML | 24 KiB (also bounded by GitHub's form length) |
| Declared duration | More than 0, up to 30 seconds |
| Dimensions | Even positive dimensions, max 1920 per side and 2,073,600 total pixels |
| Output | MP4, standard quality, 30 fps |
| Render container | 2 CPUs, 4 GiB memory, 512 PIDs, 12-minute execution timeout |
| Media output | MP4 up to 256 MiB; optional JPEG up to 5 MiB |
| Intermediate Actions artifacts | 3 days |
| Published releases | Until the owner removes them |

To avoid editable-request quota bypasses, **all issues created by an approved user that day count against
admission**, including ordinary, rejected, failed, renamed, edited, and closed issues. Earlier issue numbers
reserve slots. Edits/reopening do not trigger a new render. Only `issues: opened` does. Limits reset at
**00:00 UTC**. There are no automatic retries. Administrative policy changes/reruns are trusted operator
operations, not an immutable billing ledger.

Quotas control **render admission**, not all Actions usage: unapproved submissions still run a cheap gate,
image builds and status/publishing jobs consume resources, and eligible jobs can run concurrently subject
to GitHub's concurrency limits. These are not financial spending guarantees. Use GitHub's account-level
budgets/usage monitoring too. Keep the allowlist small.

Set `enabled` to `false` to pause new admissions; redeploy Pages to update the visible notice. Cancel
already-running workflows in Actions if needed. The actual duration cap in `scripts/pilot/render.sh` is
also 30 seconds: keep policy and container limits aligned if changing the pilot size.

## Supported compositions

This is **not** arbitrary-website capture, text-to-video, or an AI avatar generator. Input must be one
self-contained HyperFrames composition declaring `data-composition-id`, `data-width`, `data-height`, and
`data-duration`. Two compatible examples are in [`examples/`](examples/).

The pilot runs **offline**. It localizes these exact script sources to package-lock-pinned local files:

- `https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js`
- `https://cdn.jsdelivr.net/npm/@hyperframes/core/dist/hyperframe.runtime.iife.js`
- `https://cdn.jsdelivr.net/npm/@hyperframes/core@0.8.58/dist/hyperframe.runtime.iife.js`

The unversioned runtime maps to the bundled HyperFrames 0.8.58 runtime. Inline HTML/CSS/JS and inline data
assets can work. Other external scripts, fonts, images, audio, and video do not load; remote fonts fall
back to installed fonts. Relative file references are not uploaded alongside the HTML. Unknown external
URLs are never fetched by a privileged preparation step. Missing external resources may cause an
incomplete-looking video or a render failure, so use self-contained inputs.

## Architecture and trust boundaries

```text
GitHub Pages (no auth tokens)
  → clipboard request → GitHub Issue form (GitHub authenticates the user)
  → admit job: approval + quota + consent + metadata checks; snapshot input
  → render job: offline, non-root, resource-limited Docker container
  → publish job on a FRESH runner: MP4/JPEG → GitHub Release; update bot comment
  → Pages: public read-only API → status + inline player + download
```

- Submitted code does **not** run in the admission or publishing jobs.
- The container has no network, writable root filesystem, GitHub/HeyGen credentials, repository checkout,
  Docker socket, host home, or privileged capabilities. Only the input HTML and a dedicated output directory
  are mounted. Dependencies install before input execution.
- Runtime stdout is discarded (not interpreted as Actions workflow commands, nor allowed to fill logs).
- Only fixed-name, bounded, regular MP4/JPEG files are copied out. Symlinks/FIFOs/invalid signatures are
  rejected. No renderer-supplied manifest, path, command, tag, or status output is trusted by the publisher.
- Source metadata crosses from the trusted gate to the publisher separately from renderer output.
- The site uses text nodes for titles/messages, validates media URLs, trusts status only from
  `github-actions[bot]`, and has a restrictive CSP. There is deliberately no live HTML preview.
- Public status uses one bot comment updated in place. Browser tracking polls every 90 seconds for up to
  25 minutes to conserve the unauthenticated GitHub API allowance. Recent issue numbers stay only in local
  browser storage. No password/token is stored; the previous UI's stored `hfgh_token` is cleared.

**Residual risk:** Docker is a containment layer, not a guarantee against browser/kernel/container escapes.
Metadata validation does not make JavaScript safe; execution limits are enforced by the container/timeouts.
This design is for a small approved pilot on disposable **GitHub-hosted runners**, never a self-hosted
runner holding credentials or other tenants' data. Review/pin infrastructure image/action digests and
monitor dependency updates before expanding. Malformed media is not a full content-safety validation.

## Local development and tests

Python 3.11+ serves/builds the site; Node 22 is used for tests and rendering.

```bash
python3 scripts/build_site.py
python3 -m http.server 4173 --bind 0.0.0.0 --directory build/site
# Open http://localhost:4173 (or the forwarded preview URL).

npm ci
npm test                           # Python gate/security tests + JS helper tests
npx playwright install --with-deps chromium
npm run test:browser                # Mocked GitHub API, real browser interaction
```

The build bundles examples and injects public repo/limit configuration. To build for another repository,
set `GITHUB_REPOSITORY=owner/repo`. Do not serve the repository root as the public website.

For a real isolated-render smoke test on a Linux Docker host:

```bash
docker build -t pilot-renderer scripts/pilot
mkdir -p build/request
cp tests/fixtures/smoke.html build/request/index.html
bash scripts/pilot/run_sandbox.sh
# Outputs: build/media/video.mp4 and thumbnail.jpg
```

The CI workflow runs both the browser suite and this Docker test. Local browser suites use mocked GitHub
responses; they do not create issues, dispatch workflows, publish releases, or prove live GitHub permissions.
A live end-to-end request still needs the launch checklist above.

## Operations and troubleshooting

- **Not approved:** add the username to `approved_users` on the default branch; ask for a new request.
- **Limit reached:** wait until the next UTC day. Editing/closing a request does not refund its slot.
- **Waiting forever:** check Actions is enabled, the workflow exists on the default branch, and repository
  policies permit its token permissions. Cancellation or an admission infrastructure failure can prevent
  the status comment being posted. Open the issue/Actions page; no pretend progress percentage is shown.
- **Failed rendering:** verify a self-contained composition, offline-supported scripts, valid dimensions,
  and limits. Reproduce trusted test content in the sandbox. Do not run arbitrary HTML on a privileged
  host to debug it. Container logs are intentionally not published.
- **API limit/network problem:** tracking stops with an explanation instead of retrying indefinitely. Use
  the issue directly or try again later. Public API quotas are shared by IP, so large audiences need a backend.
- **Video missing:** check the publishing job and `video-pilot-<issue-number>` release. A successful video
  may exist even if a subsequent status API call failed; check the public gallery.
- **Removal:** delete the release/assets and associated tag, intermediate workflow artifacts as needed,
  and the request containing the HTML. Public copies/downloads cannot be recalled. Ask the owner for removal;
  there is no private mode or automated retention/deletion portal in this pilot.
- **Live deployment:** feature-branch files/preview do not change the public Pages site or default-branch
  workflows until merged and deployed. This implementation does not auto-push or mutate repository settings.

## Repository map

```text
site/                         Public studio, upload handoff, tracker, gallery
examples/                     Example HyperFrames compositions
.github/ISSUE_TEMPLATE/        Guided Create a video form
.github/pilot.json            Approved accounts, quotas, input limits
.github/workflows/
  pilot-render.yml            Gate → isolated render → publish → status
  deploy-pages.yml            Build and publish Pages
  test.yml                    Unit/browser tests and Docker smoke test
  render.yml                  Legacy owner-only manual/cloud renderer
scripts/
  build_site.py               Static site builder
  pilot/                      Gate/client, sandbox image/runner, output checks, publisher
  prepare_composition.py      Legacy manual renderer helper
  cloud_render.py             Legacy owner-operated cloud helper
tests/                        Unit, browser, and trusted render fixture
docs/legacy-rendering.md       Previous technical/admin workflow documentation
```

The previous PAT-based browser UI has been replaced. The legacy manual/cloud Actions workflow is kept
for **trusted repository operators only**; it is not used for public submissions and does not have the
pilot's sandbox boundaries. See [legacy operator documentation](docs/legacy-rendering.md) for those commands.
For seamless non-GitHub sign-in, direct uploads, private videos, billing, or larger audiences, add a real
backend/auth/object-storage layer instead of putting a privileged token in GitHub Pages.
