import {
  validateComposition,
  encodePacket,
  parseIssueInput,
  parseStatus,
  trustedAssetURL,
  extractVariables,
} from "./core.mjs";

const $ = (selector) => document.querySelector(selector);
const config = window.SITE_CONFIG;
const repo = `${config.owner}/${config.repo}`;
const repoURL = `https://github.com/${repo}`;
const policy = config.pilot;
const storageKey = `hyperframes:personal:${repo}:recent`;
let html = "",
  metadata = null,
  view = "",
  trackingNumber = null,
  currentVariables = {};
let timer,
  trackEpoch = 0,
  pollStarted = 0,
  galleryPage = 0,
  galleryBusy = false;
const seenReleases = new Set();

function safeEl(id) {
  return document.getElementById(id) || document.querySelector(id);
}
function message(id, text = "", error = false) {
  const el = $(id);
  if (!el) return;
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
  } catch {}
  drawRecent();
}
function drawRecent() {
  const list = $("#recent-requests");
  if (!list) return;
  list.replaceChildren();
  for (const number of recent()) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button";
    button.textContent = `Pro Request #${number} →`;
    button.addEventListener("click", () => {
      const input = $("#request-link");
      if (input) input.value = String(number);
      startTracking();
    });
    li.append(button);
    list.append(li);
  }
  if (!list.children.length) {
    const li = document.createElement("li");
    li.textContent = "No pro requests tracked yet.";
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
        "GitHub API limit reached. Private repo needs you logged into GitHub. Try Actions tab directly or wait.",
      );
    if (response.status === 404)
      throw new Error(
        "Not found — private repo? Make sure you're logged into GitHub and have access, or check the issue link.",
      );
    throw new Error(
      "GitHub is temporarily unavailable. Please try again shortly.",
    );
  }
  return response.json();
}
function friendlyError(error) {
  return error.name === "TimeoutError" || error instanceof TypeError
    ? "We couldn't reach GitHub. Check your connection and try again."
    : error.message;
}
function invalidateHandoff() {
  const handoff = $("#handoff");
  const packet = $("#request-packet");
  const copyMsg = $("#copy-message");
  const prepare = $("#prepare");
  const titleEl = $("#title");
  const consent = $("#consent");
  if (handoff) handoff.hidden = true;
  if (packet) packet.value = "";
  if (copyMsg) copyMsg.textContent = "";
  if (prepare) {
    prepare.disabled =
      !metadata ||
      !titleEl?.value?.trim() ||
      !consent?.checked ||
      !policy.enabled;
  }
}
function clearFile() {
  html = "";
  metadata = null;
  currentVariables = {};
  const fileInput = $("#file");
  const dropzone = $("#dropzone");
  const fileSummary = $("#file-summary");
  const previewWrap = $("#preview-wrap");
  const varsCard = $("#variables-card");
  const varsList = $("#variables-list");
  const dimensions = $("#dimensions");
  const durationDisplay = $("#duration-display");
  if (fileInput) fileInput.value = "";
  if (dropzone) dropzone.hidden = false;
  if (fileSummary) fileSummary.hidden = true;
  if (previewWrap) previewWrap.hidden = true;
  if (varsCard) varsCard.hidden = true;
  if (varsList) varsList.replaceChildren();
  if (dimensions) dimensions.textContent = "Matched to your script • up to 4K";
  if (durationDisplay) durationDisplay.textContent = `${policy.max_duration_seconds / 60} minutes`;
  invalidateHandoff();
  const iframe = $("#preview-frame");
  if (iframe) {
    try { iframe.srcdoc = ""; } catch {}
  }
}
function renderVariablesEditor(varsSchema) {
  const container = $("#variables-list");
  const card = $("#variables-card");
  if (!container || !card) return;
  container.replaceChildren();
  currentVariables = {};

  if (!varsSchema || !varsSchema.length) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  for (const v of varsSchema) {
    if (!v.id) continue;
    const row = document.createElement("div");
    row.className = "var-row";
    const label = document.createElement("label");
    label.textContent = v.label || v.id;
    label.htmlFor = `var-${v.id}`;
    const input = document.createElement("input");
    input.id = `var-${v.id}`;
    input.placeholder = v.default || "";
    input.value = v.default || "";
    input.dataset.varId = v.id;
    currentVariables[v.id] = v.default || "";

    input.addEventListener("input", () => {
      currentVariables[v.id] = input.value;
      invalidateHandoff();
      try { updatePreviewWithVars(); } catch {}
    });

    const hint = document.createElement("small");
    hint.className = "small muted";
    hint.textContent = `${v.type || "string"} • id: ${v.id}`;

    row.append(label, input, hint);
    container.append(row);
  }
}
function updatePreviewWithVars() {
  const iframe = $("#preview-frame");
  if (!iframe || !html) return;
  try {
    let previewHtml = html;
    if (Object.keys(currentVariables).length > 0) {
      const varsJson = JSON.stringify(currentVariables);
      const injection = `<script>window.__hyperframes={getVariables:()=>${varsJson}};</script>`;
      if (previewHtml.includes("</head>")) {
        previewHtml = previewHtml.replace("</head>", injection + "</head>");
      } else {
        previewHtml = injection + previewHtml;
      }
    }
    iframe.srcdoc = previewHtml;
  } catch (e) {
    console.warn("preview failed", e);
  }
}
function setFile(text, name) {
  clearFile();
  try {
    const parsed = validateComposition(text, policy);
    html = text;
    metadata = parsed;
    const sizeMB = (parsed.bytes / (1024 * 1024)).toFixed(2);
    const sizeLabel = parsed.bytes > 1024 * 1024 ? `${sizeMB} MB` : `${(parsed.bytes / 1024).toFixed(1)} KB`;
    const fileName = $("#file-name");
    const fileDetail = $("#file-detail");
    const dimensions = $("#dimensions");
    const durationDisplay = $("#duration-display");
    const dropzone = $("#dropzone");
    const fileSummary = $("#file-summary");
    const previewWrap = $("#preview-wrap");
    const previewFrame = $("#preview-frame");
    const titleEl = $("#title");
    if (fileName) fileName.textContent = name;
    if (fileDetail) fileDetail.textContent =
      `${sizeLabel} · ${parsed.width} × ${parsed.height} · ${parsed.duration}s · ${parsed.variables?.length || 0} vars`;
    if (dimensions) dimensions.textContent = `${parsed.width} × ${parsed.height} • ${Math.round((parsed.width * parsed.height)/1000000*10)/10}MP`;
    if (durationDisplay) durationDisplay.textContent = `${parsed.duration}s / max ${policy.max_duration_seconds}s`;
    if (dropzone) dropzone.hidden = true;
    if (fileSummary) fileSummary.hidden = false;

    if (previewWrap) previewWrap.hidden = false;
    if (previewFrame) {
      try { previewFrame.srcdoc = text; } catch {}
    }

    if (parsed.variables && parsed.variables.length) {
      renderVariablesEditor(parsed.variables);
    } else {
      const vars = extractVariables(text);
      if (vars.length) renderVariablesEditor(vars);
    }

    if (titleEl && !titleEl.value.trim())
      titleEl.value = name.replace(/\.html?$/i, "").slice(0, 100);
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
      `File is ${(file.size/1024/1024).toFixed(2)} MB, limit is ${policy.max_html_bytes / 1024 / 1024} MB in pro mode.`,
      true,
    );
  try {
    const text = await file.text();
    if (epoch === fileEpoch) setFile(text, file.name);
  } catch {
    message(
      "#file-message",
      "We couldn't read that file. Please choose it again.",
      true,
    );
  }
}

function updateProSummary() {
  const el = $("#pro-summary");
  if (!el) return;
  const fps = $("#fps")?.value || "30";
  const quality = $("#quality")?.value || "standard";
  const format = $("#format")?.value || "mp4";
  const varsCount = Object.keys(currentVariables).length;
  el.textContent = `Pro settings: ${quality} quality • ${fps}fps • ${format.toUpperCase()} • ${varsCount} variable overrides • ${metadata?.width || 0}x${metadata?.height || 0} • private`;
}

function videoCard(release) {
  const assets = release.assets || [];
  let video = assets.find(
    (a) =>
      /^video\.mp4$/.test(a.name) &&
      trustedAssetURL(a.browser_download_url, repo),
  );
  if (!video) {
    video = assets.find(
      (a) =>
        /^video\.(mp4|webm|mov)$/.test(a.name) &&
        trustedAssetURL(a.browser_download_url, repo),
    );
  }
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
  player.setAttribute("aria-label", release.name || "Pro rendered video");
  const meta = document.createElement("div");
  meta.className = "video-meta";
  const title = document.createElement("h3");
  title.textContent = release.name || "Untitled pro video";
  const info = document.createElement("p");
  const date = new Date(release.published_at || release.created_at);
  const format = video.name.split(".").pop().toUpperCase();
  info.textContent = `${Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} · ${(video.size / (1024 * 1024)).toFixed(1)} MB · ${format} • Private`;
  const actions = document.createElement("div");
  actions.className = "video-actions";
  const download = document.createElement("a");
  download.className = "secondary";
  download.textContent = `↓ Download ${format}`;
  download.href = video.browser_download_url;
  download.setAttribute("download", "");
  const details = document.createElement("a");
  details.textContent = "Details ↗";
  details.href = `${repoURL}/releases/tag/${encodeURIComponent(release.tag_name)}`;
  details.target = "_blank";
  details.rel = "noopener noreferrer";
  actions.append(download, details);

  const otherFormats = assets.filter(a => /^video\.(webm|mov|mp4)$/.test(a.name) && a.name !== video.name && trustedAssetURL(a.browser_download_url, repo));
  if (otherFormats.length) {
    const otherDiv = document.createElement("div");
    otherDiv.className = "small muted";
    otherDiv.style.marginTop = "8px";
    otherDiv.textContent = `Also available: ${otherFormats.map(f => f.name).join(", ")}`;
    meta.append(title, info, actions, otherDiv);
  } else {
    meta.append(title, info, actions);
  }

  card.append(player, meta);
  return card;
}
async function loadGallery(reset = false) {
  if (galleryBusy) return;
  galleryBusy = true;
  const refreshBtn = $("#refresh-gallery");
  const moreBtn = $("#more-videos");
  const gallery = $("#gallery");
  const empty = $("#gallery-empty");
  const count = $("#video-count");
  if (refreshBtn) refreshBtn.disabled = true;
  if (moreBtn) moreBtn.disabled = true;
  if (reset) {
    galleryPage = 0;
    seenReleases.clear();
    if (gallery) gallery.replaceChildren();
  }
  if (empty) empty.hidden = true;
  message("#gallery-message", "Fetching private releases… (requires GitHub auth for private repo)");
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
      if (card && gallery) {
        gallery.append(card);
        seenReleases.add(release.id);
      }
    }
    if (count) count.textContent = seenReleases.size
      ? `(${seenReleases.size} loaded)`
      : "";
    if (moreBtn) moreBtn.hidden = releases.length < 30;
    if (empty) empty.hidden =
      seenReleases.size > 0 || releases.length === 30;
    message(
      "#gallery-message",
      !seenReleases.size && releases.length === 30
        ? "No video releases on this page. Load more to look further back."
        : seenReleases.size === 0 ? "No private videos found. Create your first pro video!" : "",
    );
  } catch (error) {
    message("#gallery-message", friendlyError(error) + " For private repo, ensure you're logged into GitHub and have access. Or use Track page.", true);
  } finally {
    galleryBusy = false;
    if (refreshBtn) refreshBtn.disabled = false;
    if (moreBtn) moreBtn.disabled = false;
  }
}

async function statusComments(number) {
  const all = [];
  for (let page = 1; page <= 5; page++) {
    const comments = await api(
      `/issues/${number}/comments?per_page=100&page=${page}`,
    );
    all.push(...comments);
    if (parseStatus(all) || comments.length < 100) return all;
  }
  throw new Error(
    "This request has many comments. Please check its status directly on GitHub.",
  );
}
function paintStatus(state) {
  const labels = {
    queued: "Queued • Pro",
    creating: "Creating video • 4CPU/8GB",
    ready: "Ready • Private",
    rejected: "Not accepted",
    failed: "Needs attention",
    waiting: "Waiting for review",
  };
  const statusEl = $("#tracking-status");
  const detailEl = $("#tracking-detail");
  if (statusEl) statusEl.textContent = labels[state.status] || state.status;
  if (detailEl) detailEl.textContent = state.message;
  const index = ["queued", "creating", "ready"].indexOf(state.status);
  ["queued", "creating", "ready"].forEach((s, i) => {
    const el = $(`#progress-${s}`);
    if (el) el.classList.toggle("done", index >= i);
  });
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
    const isStory = issue.title?.startsWith("[Story]");
    if (!isStory && !issue.title?.startsWith("[Video]") && !issue.body?.includes("HF1."))
      throw new Error(
        "That issue is not a video request. Please use the link from the video submission form.",
      );
    const result = $("#tracking-result");
    const titleEl = $("#tracking-title");
    const issueLink = $("#tracking-issue");
    if (result) result.hidden = false;
    if (titleEl) titleEl.textContent =
      issue.title.replace(/^\[(Video|Story)\]\s*/, "") || `Pro Request #${number}`;
    if (issueLink) issueLink.href = `${repoURL}/issues/${number}`;
    saveRecent(number);
    const comments = await statusComments(number);
    if (epoch !== trackEpoch) return;
    let state = parseStatus(comments);
    if (!state)
      state = {
        status: "waiting",
        message:
          issue.state === "closed"
            ? "This request was closed without a published status. Check Actions tab."
            : "Waiting for GitHub to check your pro request. Private mode has no approval needed. If stuck, check Actions workflow is enabled on default branch.",
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
          "The video file is not available. Please check the private release or ask the owner.",
        );
      const videoWrap = $("#tracking-video");
      if (videoWrap) videoWrap.replaceChildren(card);
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
  } finally {
    const trackBtn = $("#track-request");
    if (epoch === trackEpoch && trackBtn) trackBtn.disabled = false;
  }
}
function startTracking() {
  clearTimeout(timer);
  ++trackEpoch;
  const result = $("#tracking-result");
  const videoWrap = $("#tracking-video");
  if (result) result.hidden = true;
  if (videoWrap) videoWrap.replaceChildren();
  try {
    const input = $("#request-link");
    trackingNumber = parseIssueInput(input?.value || "", repo);
    pollStarted = Date.now();
    const trackBtn = $("#track-request");
    if (trackBtn) trackBtn.disabled = true;
    message("#track-message", "Looking up your pro request…");
    history.replaceState(null, "", `#track/${trackingNumber}`);
    refreshTracking(trackEpoch);
  } catch (error) {
    const trackBtn = $("#track-request");
    if (trackBtn) trackBtn.disabled = false;
    message("#track-message", error.message, true);
  }
}
function navigate() {
  const hash = location.hash.slice(1).split("/");
  const target = hash[0];
  const number = hash[1];
  view = ["create", "gallery", "track"].includes(target) ? target : "create";
  clearTimeout(timer);
  ++trackEpoch;
  const trackBtn = $("#track-request");
  if (trackBtn) trackBtn.disabled = false;
  for (const el of document.querySelectorAll(".view")) {
    if (el.id === `view-${view}`) el.hidden = false;
    else el.hidden = true;
  }
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
      const input = $("#request-link");
      if (input) input.value = number;
      startTracking();
    }
  }
}

function init() {
  try {
    const repoLink = $("#repository-link");
    const pilotInfo = $("#pilot-info");
    const fileLimit = $("#file-limit");
    const quotaNote = $("#quota-note");
    if (repoLink) repoLink.href = repoURL;
    if (pilotInfo) {
      pilotInfo.href = repoURL;
      pilotInfo.target = "_blank";
      pilotInfo.rel = "noopener noreferrer";
    }
    if (fileLimit) fileLimit.textContent =
      `HyperFrames HTML · up to ${policy.max_html_bytes / 1024 / 1024} MB · up to ${policy.max_duration_seconds / 60} minutes · 4K ready`;
    if (quotaNote) quotaNote.textContent = policy.private_mode
      ? `Private • Unlimited (1000/day soft) • 4K • 60fps • High • Network enabled • ${policy.allow_external_assets ? "External assets OK" : ""}`
      : `Free pilot · ${policy.per_user_daily} requests per person / day · ${policy.global_daily} total / day`;

    const dropzone = $("#dropzone");
    const fileInput = $("#file");
    if (dropzone && fileInput) {
      dropzone.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", (event) =>
        readFile(event.target.files[0]),
      );
      for (const type of ["dragover", "dragleave", "drop"])
        dropzone.addEventListener(type, (event) => {
          event.preventDefault();
          dropzone.classList.toggle("dragging", type === "dragover");
          if (type === "drop") readFile(event.dataTransfer.files[0]);
        });
    }
    window.addEventListener("dragover", (event) => event.preventDefault());
    window.addEventListener("drop", (event) => event.preventDefault());
    const removeBtn = $("#remove-file");
    if (removeBtn) removeBtn.addEventListener("click", () => {
      ++fileEpoch;
      clearFile();
      message("#file-message");
    });
    const titleEl = $("#title");
    const consent = $("#consent");
    const quality = $("#quality");
    const fps = $("#fps");
    const format = $("#format");
    const resolution = $("#resolution");
    if (titleEl) titleEl.addEventListener("input", invalidateHandoff);
    if (consent) consent.addEventListener("change", invalidateHandoff);
    if (quality) quality.addEventListener("change", invalidateHandoff);
    if (fps) fps.addEventListener("change", invalidateHandoff);
    if (format) format.addEventListener("change", invalidateHandoff);
    if (resolution) resolution.addEventListener("change", invalidateHandoff);

    const loadExample = $("#load-example");
    if (loadExample) loadExample.addEventListener("click", async () => {
      const epoch = ++fileEpoch;
      loadExample.disabled = true;
      try {
        const response = await fetch("examples/product-launch.html");
        if (!response.ok)
          throw new Error("The example could not be loaded. Please try again.");
        const text = await response.text();
        if (epoch === fileEpoch) {
          if (titleEl) titleEl.value = "My product launch - pro";
          setFile(text, "product-launch.html");
        }
      } catch (error) {
        message("#file-message", error.message, true);
      } finally {
        loadExample.disabled = false;
      }
    });
    const prepare = $("#prepare");
    if (prepare) prepare.addEventListener("click", () => {
      const consentEl = $("#consent");
      if (!metadata || !consentEl?.checked || !policy.enabled) return;
      try {
        const options = {
          fps: $("#fps")?.value || "30",
          quality: $("#quality")?.value || "standard",
          format: $("#format")?.value || "mp4",
          resolution: $("#resolution")?.value || "original",
          variables: currentVariables,
        };
        const packet = encodePacket(html, $("#title")?.value || "video", options);
        const packetEl = $("#request-packet");
        const submit = $("#submit-request");
        const handoff = $("#handoff");
        const copyBtn = $("#copy-request");
        if (packetEl) packetEl.value = packet;
        if (submit) {
          const params = new URLSearchParams({
            template: "render-video.yml",
            title: `[Video] ${($("#title")?.value || "video").trim()}`,
          });
          submit.href = `${repoURL}/issues/new?${params}`;
        }
        if (handoff) handoff.hidden = false;
        updateProSummary();
        if (copyBtn) copyBtn.focus();
      } catch (error) {
        message("#file-message", error.message, true);
      }
    });
    // ---- Story mode card ----
    const STORY_ASPECT_LABELS = {
      "16:9": "16:9 (1920×1080)",
      "9:16": "9:16 (1080×1920)",
      "1:1": "1:1 (1080×1080)",
    };
    const STORY_FORMAT_LABELS = { mp4: "mp4", webm: "webm (alpha)", mov: "mov (ProRes)" };
    const stOpen = $("#st-open");
    if (stOpen) {
      const updateStoryLink = () => {
        const msg = $("#st-msg");
        const repoVal = ($("#st-repo")?.value || "").trim();
        const musicUrl = ($("#st-music-url")?.value || "").trim();
        if (!/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(repoVal)) {
          stOpen.removeAttribute("href");
          if (msg) {
            msg.hidden = repoVal.length === 0;
            msg.textContent = repoVal.length === 0 ? "" :
              "Enter a full public repo URL like https://github.com/owner/repo";
          }
          return;
        }
        if (msg) msg.hidden = true;
        const params = new URLSearchParams({
          template: "story-video.yml",
          title: `[Story] ${repoVal.replace(/^https:\/\/github\.com\//, "").replace(/\/$/, "")}`,
          repo_url: repoVal.replace(/\/$/, ""),
          tone: $("#st-tone")?.value || "cinematic",
          pace: $("#st-pace")?.value || "balanced",
          length: $("#st-length")?.value || "30",
          aspect: STORY_ASPECT_LABELS[$("#st-aspect")?.value || "16:9"],
          music_mood: $("#st-mood")?.value || "upbeat",
          quality: $("#st-quality")?.value || "standard",
          fps: $("#st-fps")?.value || "30",
          video_format: STORY_FORMAT_LABELS[$("#st-format")?.value || "mp4"],
        });
        if (musicUrl) params.set("music_url", musicUrl);
        stOpen.href = `${repoURL}/issues/new?${params}`;
      };
      ["st-repo", "st-tone", "st-pace", "st-length", "st-aspect", "st-mood",
        "st-quality", "st-fps", "st-format", "st-music-url"].forEach((id) => {
        const el = $(`#${id}`);
        if (el) {
          el.addEventListener("input", updateStoryLink);
          el.addEventListener("change", updateStoryLink);
        }
      });
      updateStoryLink();
    }

    const copyBtn = $("#copy-request");
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      const packetEl = $("#request-packet");
      const copyMsg = $("#copy-message");
      const handoff = $("#handoff");
      try {
        await navigator.clipboard.writeText(packetEl?.value || "");
        if (copyMsg) copyMsg.textContent =
          "Copied pro request! Now open the GitHub form and paste it.";
      } catch {
        const details = handoff?.querySelector("details");
        if (details) details.open = true;
        if (packetEl) {
          packetEl.focus();
          packetEl.select();
        }
        if (copyMsg) copyMsg.textContent =
          "Clipboard blocked. Copy manually using your device's copy command.";
      }
    });
    const refreshGallery = $("#refresh-gallery");
    const moreVideos = $("#more-videos");
    const trackRequest = $("#track-request");
    const requestLink = $("#request-link");
    const clearHistory = $("#clear-history");
    if (refreshGallery) refreshGallery.addEventListener("click", () => loadGallery(true));
    if (moreVideos) moreVideos.addEventListener("click", () => loadGallery());
    if (trackRequest) trackRequest.addEventListener("click", startTracking);
    if (requestLink) requestLink.addEventListener("keydown", (event) => {
      if (event.key === "Enter") startTracking();
    });
    if (clearHistory) clearHistory.addEventListener("click", () => {
      try {
        localStorage.removeItem(storageKey);
      } catch {}
      drawRecent();
    });
    window.addEventListener("hashchange", navigate);
    for (const store of ["localStorage", "sessionStorage"]) {
      try {
        for (const key of Object.keys(window[store]))
          if (key === "hfgh_token" || /^hf[.:_-].*(token|pat)/i.test(key))
            window[store].removeItem(key);
      } catch {}
    }
    navigate();
  } catch (e) {
    console.error("Studio init failed", e);
    const msg = document.getElementById("file-message");
    if (msg) {
      msg.textContent = "Studio failed to initialize: " + e.message;
      msg.hidden = false;
      msg.classList.add("error");
    }
  }
}

init();
