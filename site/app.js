import {
  validateComposition,
  encodePacket,
  parseIssueInput,
  parseStatus,
  trustedAssetURL,
} from "./core.mjs";

const $ = (selector) => document.querySelector(selector);
const config = window.SITE_CONFIG;
const repo = `${config.owner}/${config.repo}`;
const repoURL = `https://github.com/${repo}`;
const policy = config.pilot;
const storageKey = `hyperframes:pilot:${repo}:recent`;
let html = "",
  metadata = null,
  view = "",
  trackingNumber = null;
let timer,
  trackEpoch = 0,
  pollStarted = 0,
  galleryPage = 0,
  galleryBusy = false;
const seenReleases = new Set();

function message(id, text = "", error = false) {
  const el = $(id);
  el.textContent = text;
  el.classList.toggle("error", error);
  el.hidden = !text;
}
function recent() {
  try {
    const data = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return Array.isArray(data)
      ? data.filter((n) => Number.isSafeInteger(n) && n > 0).slice(0, 10)
      : [];
  } catch {
    return [];
  }
}
function saveRecent(number) {
  const items = [number, ...recent().filter((n) => n !== number)].slice(0, 10);
  try {
    localStorage.setItem(storageKey, JSON.stringify(items));
  } catch {
    /* storage may be blocked */
  }
  drawRecent();
}
function drawRecent() {
  const list = $("#recent-requests");
  list.replaceChildren();
  for (const number of recent()) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button";
    button.textContent = `Request #${number} →`;
    button.addEventListener("click", () => {
      $("#request-link").value = String(number);
      startTracking();
    });
    li.append(button);
    list.append(li);
  }
  if (!list.children.length) {
    const li = document.createElement("li");
    li.textContent = "No requests tracked yet.";
    list.append(li);
  }
}
async function api(path) {
  const response = await fetch(`https://api.github.com/repos/${repo}${path}`, {
    headers: { Accept: "application/vnd.github+json" },
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    if (response.status === 403 || response.status === 429)
      throw new Error(
        "GitHub’s public request limit has been reached. Please wait a few minutes, or check your request directly on GitHub.",
      );
    if (response.status === 404)
      throw new Error(
        "We couldn’t find that request or video in this studio. Check the link and try again.",
      );
    throw new Error(
      "GitHub is temporarily unavailable. Please try again shortly.",
    );
  }
  return response.json();
}
function friendlyError(error) {
  return error.name === "TimeoutError" || error instanceof TypeError
    ? "We couldn’t reach GitHub. Check your connection and try again."
    : error.message;
}
function invalidateHandoff() {
  $("#handoff").hidden = true;
  $("#request-packet").value = "";
  $("#copy-message").textContent = "";
  $("#prepare").disabled =
    !metadata ||
    !$("#title").value.trim() ||
    !$("#consent").checked ||
    !policy.enabled;
}
function clearFile() {
  html = "";
  metadata = null;
  $("#file").value = "";
  $("#dropzone").hidden = false;
  $("#file-summary").hidden = true;
  $("#dimensions").textContent = "Matched to your script";
  invalidateHandoff();
}
function setFile(text, name) {
  // Clear the previous selection on errors, preventing stale-file submissions.
  clearFile();
  try {
    const parsed = validateComposition(text, policy);
    html = text;
    metadata = parsed;
    $("#file-name").textContent = name;
    $("#file-detail").textContent =
      `${(parsed.bytes / 1024).toFixed(1)} KB · ${parsed.width} × ${parsed.height} · ${parsed.duration}s`;
    $("#dimensions").textContent = `${parsed.width} × ${parsed.height}`;
    $("#dropzone").hidden = true;
    $("#file-summary").hidden = false;
    if (!$("#title").value.trim())
      $("#title").value = name.replace(/\.html?$/i, "").slice(0, 100);
    message("#file-message");
    invalidateHandoff();
  } catch (error) {
    message("#file-message", error.message, true);
  }
}
let fileEpoch = 0;
async function readFile(file) {
  const epoch = ++fileEpoch;
  clearFile();
  if (!file) return;
  if (!/\.html?$/i.test(file.name))
    return message("#file-message", "Please choose a .html file.", true);
  if (file.size > policy.max_html_bytes)
    return message(
      "#file-message",
      `This pilot accepts files up to ${policy.max_html_bytes / 1024} KB.`,
      true,
    );
  try {
    const text = await file.text();
    if (epoch === fileEpoch) setFile(text, file.name);
  } catch {
    message(
      "#file-message",
      "We couldn’t read that file. Please choose it again.",
      true,
    );
  }
}

function videoCard(release) {
  const assets = release.assets || [];
  const video = assets.find(
    (a) =>
      /^video\.(mp4|webm|mov)$/.test(a.name) &&
      trustedAssetURL(a.browser_download_url, repo),
  );
  if (!video) return null;
  const thumb = assets.find(
    (a) =>
      /^thumbnail\.(jpg|png)$/.test(a.name) &&
      trustedAssetURL(a.browser_download_url, repo),
  );
  const card = document.createElement("article");
  card.className = "card video-card";
  const player = document.createElement("video");
  player.controls = true;
  player.preload = "none";
  player.playsInline = true;
  player.src = video.browser_download_url;
  if (thumb) player.poster = thumb.browser_download_url;
  player.setAttribute("aria-label", release.name || "Rendered video");
  const meta = document.createElement("div");
  meta.className = "video-meta";
  const title = document.createElement("h3");
  title.textContent = release.name || "Untitled video";
  const info = document.createElement("p");
  const date = new Date(release.published_at || release.created_at);
  info.textContent = `${Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} · ${(video.size / (1024 * 1024)).toFixed(1)} MB · ${video.name.split(".").pop().toUpperCase()}`;
  const actions = document.createElement("div");
  actions.className = "video-actions";
  const download = document.createElement("a");
  download.className = "secondary";
  download.textContent = "↓ Download video";
  download.href = video.browser_download_url;
  download.setAttribute("download", "");
  const details = document.createElement("a");
  details.textContent = "Details ↗";
  details.href = `${repoURL}/releases/tag/${encodeURIComponent(release.tag_name)}`;
  details.target = "_blank";
  details.rel = "noopener noreferrer";
  actions.append(download, details);
  meta.append(title, info, actions);
  card.append(player, meta);
  return card;
}
async function loadGallery(reset = false) {
  if (galleryBusy) return;
  galleryBusy = true;
  $("#refresh-gallery").disabled = true;
  $("#more-videos").disabled = true;
  if (reset) {
    galleryPage = 0;
    seenReleases.clear();
    $("#gallery").replaceChildren();
  }
  $("#gallery-empty").hidden = true;
  message("#gallery-message", "Fetching the latest videos…");
  try {
    const releases = await api(`/releases?per_page=30&page=${galleryPage + 1}`);
    galleryPage++;
    for (const release of releases) {
      if (
        release.draft ||
        !release.tag_name?.startsWith("video-") ||
        seenReleases.has(release.id)
      )
        continue;
      const card = videoCard(release);
      if (card) {
        $("#gallery").append(card);
        seenReleases.add(release.id);
      }
    }
    $("#video-count").textContent = seenReleases.size
      ? `(${seenReleases.size} loaded)`
      : "";
    $("#more-videos").hidden = releases.length < 30;
    $("#gallery-empty").hidden =
      seenReleases.size > 0 || releases.length === 30;
    message(
      "#gallery-message",
      !seenReleases.size && releases.length === 30
        ? "No video releases on this page. Load more to look further back."
        : "",
    );
  } catch (error) {
    message("#gallery-message", friendlyError(error), true);
  } finally {
    galleryBusy = false;
    $("#refresh-gallery").disabled = false;
    $("#more-videos").disabled = false;
  }
}

async function statusComments(number) {
  const all = [];
  for (let page = 1; page <= 5; page++) {
    const comments = await api(
      `/issues/${number}/comments?per_page=100&page=${page}`,
    );
    all.push(...comments);
    // Our single bot comment is patched in place, so don't keep paginating once found.
    if (parseStatus(all) || comments.length < 100) return all;
  }
  throw new Error(
    "This request has many comments. Please check its status directly on GitHub.",
  );
}
function paintStatus(state) {
  const labels = {
    queued: "Queued",
    creating: "Creating video",
    ready: "Ready",
    rejected: "Not accepted",
    failed: "Needs attention",
    waiting: "Waiting for review",
  };
  $("#tracking-status").textContent = labels[state.status];
  $("#tracking-detail").textContent = state.message;
  const index = ["queued", "creating", "ready"].indexOf(state.status);
  ["queued", "creating", "ready"].forEach((s, i) =>
    $(`#progress-${s}`).classList.toggle("done", index >= i),
  );
}
async function refreshTracking(epoch) {
  const number = trackingNumber;
  if (!number || epoch !== trackEpoch || view !== "track") return;
  try {
    const issue = await api(`/issues/${number}`);
    if (epoch !== trackEpoch) return;
    if (issue.pull_request)
      throw new Error(
        "That link is a pull request. Please use the issue created by your video submission.",
      );
    if (!issue.title?.startsWith("[Video]") && !issue.body?.includes("HF1."))
      throw new Error(
        "That issue is not a video request. Please use the link from the video submission form.",
      );
    $("#tracking-result").hidden = false;
    $("#tracking-title").textContent =
      issue.title.replace(/^\[Video\]\s*/, "") || `Request #${number}`;
    $("#tracking-issue").href = `${repoURL}/issues/${number}`;
    saveRecent(number);
    const comments = await statusComments(number);
    if (epoch !== trackEpoch) return;
    let state = parseStatus(comments);
    if (!state)
      state = {
        status: "waiting",
        message:
          issue.state === "closed"
            ? "This request was closed without a published status. Please ask the owner to check it."
            : "Waiting for GitHub to check your request. Only approved pilot accounts can render. If this does not change, ask the owner to check the workflow.",
      };
    paintStatus(state);
    message("#track-message");
    if (state.status === "ready" && state.tag === `video-pilot-${number}`) {
      const release = await api(
        `/releases/tags/${encodeURIComponent(state.tag)}`,
      );
      if (epoch !== trackEpoch) return;
      const card = videoCard(release);
      if (!card)
        throw new Error(
          "The video file is not available. Please check the release or ask the owner.",
        );
      $("#tracking-video").replaceChildren(card);
      return;
    }
    if (
      ["ready", "failed", "rejected"].includes(state.status) ||
      issue.state === "closed"
    )
      return;
    if (Date.now() - pollStarted < 25 * 60 * 1000)
      timer = setTimeout(() => refreshTracking(epoch), 90000);
    else
      message(
        "#track-message",
        "Automatic checks are paused. Click Find video to check again, or open your request on GitHub.",
      );
  } catch (error) {
    if (epoch === trackEpoch)
      message(
        "#track-message",
        friendlyError(error) + " Click Find video to retry.",
        true,
      );
    // Stop rather than repeatedly hammering a rate-limited/offline API.
  } finally {
    if (epoch === trackEpoch) $("#track-request").disabled = false;
  }
}
function startTracking() {
  clearTimeout(timer);
  ++trackEpoch;
  $("#tracking-result").hidden = true;
  $("#tracking-video").replaceChildren();
  try {
    trackingNumber = parseIssueInput($("#request-link").value, repo);
    pollStarted = Date.now();
    $("#track-request").disabled = true;
    message("#track-message", "Looking up your request…");
    history.replaceState(null, "", `#track/${trackingNumber}`);
    refreshTracking(trackEpoch);
  } catch (error) {
    $("#track-request").disabled = false;
    message("#track-message", error.message, true);
  }
}
function navigate() {
  const [target, number] = location.hash.slice(1).split("/");
  view = ["create", "gallery", "track"].includes(target) ? target : "create";
  clearTimeout(timer);
  ++trackEpoch;
  $("#track-request").disabled = false;
  for (const el of document.querySelectorAll(".view"))
    el.hidden = el.id !== `view-${view}`;
  for (const el of document.querySelectorAll("nav a")) {
    const active = el.dataset.view === view;
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  }
  if (view === "gallery" && !galleryPage) loadGallery();
  if (view === "track") {
    drawRecent();
    if (/^[1-9]\d{0,8}$/.test(number || "")) {
      $("#request-link").value = number;
      startTracking();
    }
  }
}
$("#repository-link").href = repoURL;
$("#pilot-info").href =
  `${repoURL}/issues/new?title=${encodeURIComponent("Pilot access request")}&body=${encodeURIComponent("I would like to join the free video-rendering pilot. Please approve my GitHub account.")}`;
$("#pilot-info").target = "_blank";
$("#pilot-info").rel = "noopener noreferrer";
$("#file-limit").textContent =
  `HyperFrames HTML · up to ${policy.max_html_bytes / 1024} KB · up to ${policy.max_duration_seconds} seconds`;
$("#quota-note").textContent = policy.enabled
  ? `Free pilot · ${policy.per_user_daily} requests per person / day · ${policy.global_daily} total / day`
  : "The pilot is currently paused. You can still explore the gallery.";
$("#dropzone").addEventListener("click", () => $("#file").click());
$("#file").addEventListener("change", (event) =>
  readFile(event.target.files[0]),
);
for (const type of ["dragover", "dragleave", "drop"])
  $("#dropzone").addEventListener(type, (event) => {
    event.preventDefault();
    $("#dropzone").classList.toggle("dragging", type === "dragover");
    if (type === "drop") readFile(event.dataTransfer.files[0]);
  });
// Never let dropping an HTML file elsewhere navigate the studio to it.
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());
$("#remove-file").addEventListener("click", () => {
  ++fileEpoch;
  clearFile();
  message("#file-message");
});
$("#title").addEventListener("input", invalidateHandoff);
$("#consent").addEventListener("change", invalidateHandoff);
$("#load-example").addEventListener("click", async () => {
  const epoch = ++fileEpoch;
  $("#load-example").disabled = true;
  try {
    const response = await fetch("examples/product-launch.html");
    if (!response.ok)
      throw new Error("The example could not be loaded. Please try again.");
    const text = await response.text();
    if (epoch === fileEpoch) {
      $("#title").value = "My product launch";
      setFile(text, "product-launch.html");
    }
  } catch (error) {
    message("#file-message", error.message, true);
  } finally {
    $("#load-example").disabled = false;
  }
});
$("#prepare").addEventListener("click", () => {
  if (!metadata || !$("#consent").checked || !policy.enabled) return;
  try {
    const packet = encodePacket(html, $("#title").value);
    $("#request-packet").value = packet;
    // Only a short title enters the URL. The large HTML packet uses the clipboard,
    // avoiding URL-length limits, proxy logs, and silent truncation.
    const params = new URLSearchParams({
      template: "render-video.yml",
      title: `[Video] ${$("#title").value.trim()}`,
    });
    $("#submit-request").href = `${repoURL}/issues/new?${params}`;
    $("#handoff").hidden = false;
    $("#copy-request").focus();
  } catch (error) {
    message("#file-message", error.message, true);
  }
});
$("#copy-request").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#request-packet").value);
    $("#copy-message").textContent =
      "Copied! Now open the GitHub form and paste your request.";
  } catch {
    $("#handoff details").open = true;
    $("#request-packet").focus();
    $("#request-packet").select();
    $("#copy-message").textContent =
      "Clipboard access is blocked. Copy the selected request using your device’s copy command.";
  }
});
$("#refresh-gallery").addEventListener("click", () => loadGallery(true));
$("#more-videos").addEventListener("click", () => loadGallery());
$("#track-request").addEventListener("click", startTracking);
$("#request-link").addEventListener("keydown", (event) => {
  if (event.key === "Enter") startTracking();
});
$("#clear-history").addEventListener("click", () => {
  try {
    localStorage.removeItem(storageKey);
  } catch {}
  drawRecent();
});
window.addEventListener("hashchange", navigate);
// Remove obsolete credentials from versions of the technical composer, if present.
for (const store of ["localStorage", "sessionStorage"]) {
  try {
    for (const key of Object.keys(window[store]))
      if (key === "hfgh_token" || /^hf[.:_-].*(token|pat)/i.test(key))
        window[store].removeItem(key);
  } catch {
    /* storage disabled */
  }
}
navigate();
