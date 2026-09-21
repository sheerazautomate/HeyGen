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
  } catch {}
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
    button.textContent = `Pro Request #${number} →`;
    button.addEventListener("click", () => {
      $("#request-link").value = String(number);
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
  $("#handoff").hidden = true;
  $("#request-packet").value = "";
  $("#copy-message").textContent = "";
  const hasVars = Object.keys(currentVariables).length > 0;
  $("#prepare").disabled =
    !metadata ||
    !$("#title").value.trim() ||
    !$("#consent").checked ||
    !policy.enabled;

  // Update pro summary if visible
  if (!$("#handoff").hidden) updateProSummary();
}
function clearFile() {
  html = "";
  metadata = null;
  currentVariables = {};
  $("#file").value = "";
  $("#dropzone").hidden = false;
  $("#file-summary").hidden = true;
  $("#preview-wrap").hidden = true;
  $("#variables-card").hidden = true;
  $("#variables-list").replaceChildren();
  $("#dimensions").textContent = "Matched to your script • up to 4K";
  $("#duration-display").textContent = `${policy.max_duration_seconds / 60} minutes`;
  invalidateHandoff();
  const iframe = $("#preview-frame");
  if (iframe) iframe.srcdoc = "";
}
function renderVariablesEditor(varsSchema) {
  const container = $("#variables-list");
  container.replaceChildren();
  currentVariables = {};

  if (!varsSchema || !varsSchema.length) {
    $("#variables-card").hidden = true;
    return;
  }

  $("#variables-card").hidden = false;
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
    // Set initial
    currentVariables[v.id] = v.default || "";

    input.addEventListener("input", () => {
      currentVariables[v.id] = input.value;
      invalidateHandoff();
      updatePreviewWithVars();
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
    // Inject variables into preview via script override
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
    $("#file-name").textContent = name;
    $("#file-detail").textContent =
      `${sizeLabel} · ${parsed.width} × ${parsed.height} · ${parsed.duration}s · ${parsed.variables?.length || 0} vars`;
    $("#dimensions").textContent = `${parsed.width} × ${parsed.height} • ${Math.round((parsed.width * parsed.height)/1000000*10)/10}MP`;
    $("#duration-display").textContent = `${parsed.duration}s / max ${policy.max_duration_seconds}s`;
    $("#dropzone").hidden = true;
    $("#file-summary").hidden = false;

    // Preview
    $("#preview-wrap").hidden = false;
    $("#preview-frame").srcdoc = text;

    // Variables
    if (parsed.variables && parsed.variables.length) {
      renderVariablesEditor(parsed.variables);
    } else {
      // Try extract via regex fallback
      const vars = extractVariables(text);
      if (vars.length) renderVariablesEditor(vars);
    }

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
  const fps = $("#fps").value;
  const quality = $("#quality").value;
  const format = $("#format").value;
  const varsCount = Object.keys(currentVariables).length;
  el.innerHTML = `<strong>Pro settings:</strong> ${quality} quality • ${fps}fps • ${format.toUpperCase()} • ${varsCount} variable overrides • ${metadata?.width || 0}x${metadata?.height || 0} • private`;
}

function videoCard(release) {
  const assets = release.assets || [];
  // Prefer mp4, but accept webm/mov as well
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

  // Show other formats if available
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
  $("#refresh-gallery").disabled = true;
  $("#more-videos").disabled = true;
  if (reset) {
    galleryPage = 0;
    seenReleases.clear();
    $("#gallery").replaceChildren();
  }
  $("#gallery-empty").hidden = true;
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
        : seenReleases.size === 0 ? "No private videos found. Create your first pro video!" : "",
    );
  } catch (error) {
    message("#gallery-message", friendlyError(error) + " For private repo, ensure you're logged into GitHub and have access. Or use Track page.", true);
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
      issue.title.replace(/^\[Video\]\s*/, "") || `Pro Request #${number}`;
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
    message("#track-message", "Looking up your pro request…");
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
$("#pilot-info").href = repoURL;
$("#pilot-info").target = "_blank";
$("#pilot-info").rel = "noopener noreferrer";
$("#file-limit").textContent =
  `HyperFrames HTML · up to ${policy.max_html_bytes / 1024 / 1024} MB · up to ${policy.max_duration_seconds / 60} minutes · 4K ready`;
$("#quota-note").textContent = policy.private_mode
  ? `Private • Unlimited (1000/day soft) • 4K • 60fps • High • Network enabled • ${policy.allow_external_assets ? "External assets OK" : ""}`
  : `Free pilot · ${policy.per_user_daily} requests per person / day · ${policy.global_daily} total / day`;

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
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());
$("#remove-file").addEventListener("click", () => {
  ++fileEpoch;
  clearFile();
  message("#file-message");
});
$("#title").addEventListener("input", invalidateHandoff);
$("#consent").addEventListener("change", invalidateHandoff);
$("#quality").addEventListener("change", invalidateHandoff);
$("#fps").addEventListener("change", invalidateHandoff);
$("#format").addEventListener("change", invalidateHandoff);
$("#resolution").addEventListener("change", invalidateHandoff);

$("#load-example").addEventListener("click", async () => {
  const epoch = ++fileEpoch;
  $("#load-example").disabled = true;
  try {
    const response = await fetch("examples/product-launch.html");
    if (!response.ok)
      throw new Error("The example could not be loaded. Please try again.");
    const text = await response.text();
    if (epoch === fileEpoch) {
      $("#title").value = "My product launch - pro";
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
    const options = {
      fps: $("#fps").value,
      quality: $("#quality").value,
      format: $("#format").value,
      resolution: $("#resolution").value,
      variables: currentVariables,
    };
    const packet = encodePacket(html, $("#title").value, options);
    $("#request-packet").value = packet;
    const params = new URLSearchParams({
      template: "render-video.yml",
      title: `[Video] ${$("#title").value.trim()}`,
    });
    $("#submit-request").href = `${repoURL}/issues/new?${params}`;
    $("#handoff").hidden = false;
    updateProSummary();
    $("#copy-request").focus();
  } catch (error) {
    message("#file-message", error.message, true);
  }
});
$("#copy-request").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#request-packet").value);
    $("#copy-message").textContent =
      "Copied pro request! Now open the GitHub form and paste it.";
  } catch {
    $("#handoff details").open = true;
    $("#request-packet").focus();
    $("#request-packet").select();
    $("#copy-message").textContent =
      "Clipboard blocked. Copy manually using your device's copy command.";
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
for (const store of ["localStorage", "sessionStorage"]) {
  try {
    for (const key of Object.keys(window[store]))
      if (key === "hfgh_token" || /^hf[.:_-].*(token|pat)/i.test(key))
        window[store].removeItem(key);
  } catch {}
}
navigate();
