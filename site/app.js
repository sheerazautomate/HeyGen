/* HyperFrames Studio → GitHub Actions
 * Client-only app: turns a pasted HyperFrames composition into a git blob,
 * dispatches the `render-video` workflow, tracks the Actions run, and lists
 * finished renders (GitHub Releases tagged video-*).
 */
(() => {
  "use strict";

  /* ------------------------------------------------------------------ *
   * tiny helpers
   * ------------------------------------------------------------------ */
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const fmtBytes = (n) =>
    n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
  const timeAgo = (iso) => {
    const s = Math.max(1, (Date.now() - new Date(iso).getTime()) / 1000);
    const steps = [["d", 86400], ["h", 3600], ["m", 60], ["s", 1]];
    for (const [unit, sec] of steps) if (s >= sec) return `${Math.floor(s / sec)}${unit} ago`;
    return "just now";
  };
  const randomKey = () => {
    const b = new Uint8Array(4);
    crypto.getRandomValues(b);
    return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  };
  const show = (el, on = true) => { el.hidden = !on; };
  const setNote = (el, text, kind = "") => {
    if (!text) { show(el, false); el.innerHTML = ""; return; }
    el.className = `note ${kind}`.trim();
    el.innerHTML = text;
    show(el, true);
  };

  /* ------------------------------------------------------------------ *
   * state
   * ------------------------------------------------------------------ */
  const LS = { token: "hfgh_token", track: "hfgh_track", settings: "hfgh_settings" };
  const cfg = Object.assign({ owner: "", repo: "" }, window.SITE_CONFIG || {});
  const state = {
    token: sessionStorage.getItem(LS.token) || localStorage.getItem(LS.token) || "",
    remembered: Boolean(localStorage.getItem(LS.token)),
    pollAbort: null,
    galleryLoaded: false,
  };

  /* ------------------------------------------------------------------ *
   * GitHub API
   * ------------------------------------------------------------------ */
  async function gh(path, { method = "GET", body, auth = true, raw = false } = {}) {
    const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
    if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res;
    try {
      res = await fetch(`https://api.github.com${path}`, {
        method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new Error("Network error reaching api.github.com — check your connection.");
    }
    if (res.status === 204) return null;
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text.slice(0, 400) }; }
    if (!res.ok) {
      const msg = (data && data.message) || `HTTP ${res.status}`;
      const err = new Error(msg);
      err.status = res.status;
      if (res.status === 401) err.hint = "Token rejected — generate a new one and paste it above.";
      else if (res.status === 403 && /rate limit/i.test(msg)) err.hint = "GitHub API rate limit reached. Adding a token raises the limit from 60 to 5,000 requests/hour.";
      else if (res.status === 403) err.hint = "Forbidden — make sure the token has Contents: Read and write on this repository.";
      else if (res.status === 404) err.hint = "Not found — double-check the owner/repo (and that the token can see it).";
      throw err;
    }
    return raw ? text : data;
  }

  const repoPath = () => `${cfg.owner}/${cfg.repo}`;

  function updateRepoChip() {
    const ok = isValidRepo();
    const chip = $("#repo-chip");
    chip.classList.toggle("on", ok);
    $("#repo-chip-text").textContent = ok ? repoPath() : "not configured";
    const link = $("#repo-link");
    if (ok) { link.href = `https://github.com/${repoPath()}`; show(link, true); } else show(link, false);
    $("#foot-repo").textContent = ok ? `Serving renders for ${repoPath()}` : "";
  }

  const isValidRepo = () =>
    /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(cfg.owner || "") && /^[A-Za-z0-9_.-]+$/.test(cfg.repo || "");

  /* ------------------------------------------------------------------ *
   * token management
   * ------------------------------------------------------------------ */
  function saveToken(value, remember) {
    state.token = value.trim();
    state.remembered = remember;
    sessionStorage.removeItem(LS.token);
    localStorage.removeItem(LS.token);
    if (state.token) (remember ? localStorage : sessionStorage).setItem(LS.token, state.token);
  }

  function refreshConnUI() {
    const chip = $("#conn-status");
    const hasPat = Boolean(state.token);
    if (!hasPat) { chip.className = "chip chip-warn"; chip.textContent = "token needed to render"; }
    else { chip.className = "chip chip-ok"; chip.textContent = "token loaded"; }
    show($("#btn-forget"), hasPat);
  }

  async function verifyToken() {
    const msg = $("#conn-msg");
    if (!state.token) { setNote(msg, "Paste a personal access token first — see the guide below.", "err"); return false; }
    const btn = $("#btn-verify");
    btn.disabled = true; btn.textContent = "Checking…";
    try {
      const me = await gh("/user");
      const chip = $("#conn-status");
      chip.className = "chip chip-ok";
      chip.textContent = `connected as @${me.login}`;
      setNote(msg, `✓ Token valid for <strong>@${esc(me.login)}</strong>. You can trigger renders.`, "ok");
      return true;
    } catch (e) {
      $("#conn-status").className = "chip chip-err";
      $("#conn-status").textContent = "token problem";
      setNote(msg, `${esc(e.message)}${e.hint ? ` — ${esc(e.hint)}` : ""}`, "err");
      return false;
    } finally {
      btn.disabled = false; btn.textContent = "Verify";
    }
  }

  /* ------------------------------------------------------------------ *
   * tabs
   * ------------------------------------------------------------------ */
  function selectTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
    if (name === "videos" && !state.galleryLoaded) loadGallery();
  }
  document.querySelectorAll("[data-tab]").forEach((el) =>
    el.addEventListener("click", (ev) => {
      ev.preventDefault();
      location.hash = el.dataset.tab;
    })
  );
  window.addEventListener("hashchange", () => selectTab(location.hash.replace("#", "") || "composer"));

  /* ------------------------------------------------------------------ *
   * editor: examples, upload, checks
   * ------------------------------------------------------------------ */
  async function loadExample(rel) {
    if (!rel) return;
    const candidates = [rel, rel.replace("examples/", "../examples/")];
    for (const url of candidates) {
      try {
        const res = await fetch(url);
        if (!res.ok) continue;
        setHtml(await res.text());
        if (/vertical/.test(rel)) { $("#in-aspect").value = "9:16"; $("#in-resolution").value = "1080p"; }
        return;
      } catch { /* try next */ }
    }
    setNote($("#comp-msg"), `Could not fetch <code>${esc(rel)}</code>. On GitHub Pages this works once the site is deployed with examples bundled.`, "err");
  }

  function setHtml(text) {
    $("#in-html").value = text;
    onHtmlChanged();
  }

  function analyze(html) {
    const out = { bytes: new Blob([html]).size, composition: false, timelines: false, scenes: 0, width: 16, height: 9 };
    try {
      const doc = new DOMParser().parseFromString(html, "text/html");
      const root = doc.querySelector("[data-composition-id]");
      out.composition = Boolean(root);
      const code = doc.body.textContent || "";
      const all = html;
      out.timelines = /__timelines|__hf/.test(all);
      out.scenes = doc.querySelectorAll(".clip").length;
      if (root) {
        const w = parseFloat(root.dataset.width) || 0;
        const h = parseFloat(root.dataset.height) || 0;
        if (w > 0 && h > 0) { out.width = w; out.height = h; }
      }
    } catch { /* partial HTML is fine */ }
    return out;
  }

  function onHtmlChanged() {
    const html = $("#in-html").value;
    const a = analyze(html);
    $("#html-stats").textContent = `${fmtBytes(a.bytes)} · ${html.length.toLocaleString()} chars`;
    const mark = (ok, label) => `<span class="${ok ? "good" : "bad"}">${ok ? "✓" : "✗"} ${label}</span>`;
    $("#html-checks").innerHTML = html.trim()
      ? [mark(a.composition, "data-composition-id"), mark(a.timelines, "timeline"), `${a.scenes} clip${a.scenes === 1 ? "" : "s"}`].join(" · ")
      : "";
    try { localStorage.setItem(LS.settings, JSON.stringify(readSettings())); } catch {}
  }

  /* ------------------------------------------------------------------ *
   * live preview (official @hyperframes/player web component)
   * ------------------------------------------------------------------ */
  let playerLibPromise = null;
  function ensurePlayerLib() {
    if (window.customElements && window.customElements.get("hyperframes-player")) return Promise.resolve(true);
    if (playerLibPromise) return playerLibPromise;
    playerLibPromise = new Promise((resolve) => {
      const s = document.createElement("script");
      s.type = "module";
      s.src = "https://cdn.jsdelivr.net/npm/@hyperframes/player";
      s.onerror = () => resolve(false);
      document.head.appendChild(s);
      const started = Date.now();
      (function check() {
        if (window.customElements && window.customElements.get("hyperframes-player")) return resolve(true);
        if (Date.now() - started > 10000) return resolve(false);
        setTimeout(check, 200);
      })();
    });
    return playerLibPromise;
  }

  async function togglePreview(force) {
    const wrap = $("#preview-wrap");
    const open = force !== undefined ? force : wrap.hidden;
    show(wrap, open);
    $("#btn-preview").textContent = open ? "■ Hide preview" : "▶ Preview";
    if (open) renderPreview();
  }

  async function renderPreview() {
    const html = $("#in-html").value;
    const box = $("#player-box");
    if (!html.trim()) { box.innerHTML = '<p class="note">Nothing to preview yet.</p>'; return; }
    const a = analyze(html);
    const ratio = Math.abs(a.width / a.height - 9 / 16) < 0.02 ? "ratio-9-16" : Math.abs(a.width / a.height - 1) < 0.02 ? "ratio-1-1" : "ratio-16-9";
    box.className = `player-box ${ratio}`;
    box.innerHTML = `<div class="spin"></div>`;
    const ok = await ensurePlayerLib();
    if (!ok) {
      box.innerHTML =
        `<iframe sandbox="allow-scripts" srcdoc="${esc(html)}" title="composition preview"></iframe>` +
        `<p class="dim" style="padding:6px 10px;margin:0;font-size:12px">Player component unavailable — showing a static frame fallback.</p>`;
      return;
    }
    box.innerHTML = "";
    const player = document.createElement("hyperframes-player");
    player.setAttribute("controls", "");
    player.setAttribute("autoplay", "");
    player.setAttribute("muted", "");
    player.setAttribute("srcdoc", html);
    box.appendChild(player);
  }

  /* ------------------------------------------------------------------ *
   * settings
   * ------------------------------------------------------------------ */
  function readSettings() {
    return {
      title: $("#in-title").value.trim(),
      engine: $("#in-engine").value,
      format: $("#in-format").value,
      quality: $("#in-quality").value,
      resolution: $("#in-resolution").value,
      aspect: $("#in-aspect").value,
      fps: Math.max(1, Math.min(240, parseInt($("#in-fps").value, 10) || 30)),
      vars: $("#in-vars").value.trim(),
      lint: $("#in-lint").checked,
    };
  }

  function restoreSettings() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(LS.settings) || "{}"); } catch {}
    if (saved.engine) $("#in-engine").value = saved.engine;
    if (saved.format) $("#in-format").value = saved.format;
    if (saved.quality) $("#in-quality").value = saved.quality;
    if (saved.resolution) $("#in-resolution").value = saved.resolution;
    if (saved.aspect) $("#in-aspect").value = saved.aspect;
    if (saved.fps) $("#in-fps").value = saved.fps;
  }

  function validateVariables(raw) {
    if (!raw) return {};
    let parsed;
    try { parsed = JSON.parse(raw); } catch (e) { throw new Error(`Variables must be valid JSON: ${e.message}`); }
    if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) throw new Error("Variables must be a JSON object like {\"key\": \"value\"}");
    return parsed;
  }

  /* ------------------------------------------------------------------ *
   * render trigger
   * ------------------------------------------------------------------ */
  const stepEl = (name) => document.querySelector(`#progress-steps li[data-step="${name}"]`);
  function setStep(name, status) { // "active" | "done" | "failed" | "pending"
    const el = stepEl(name);
    if (!el) return;
    el.classList.remove("active", "done", "failed");
    if (status !== "pending") el.classList.add(status);
  }
  function resetSteps() {
    ["blob", "dispatch", "run", "render", "release"].forEach((s) => setStep(s, "pending"));
    show($("#progress-links"), false);
    $("#link-release").removeAttribute("href");
    show($("#link-release"), false);
    setNote($("#progress-msg"), "");
  }

  function setRunChip(text, kind) {
    const el = $("#run-state");
    el.className = `chip chip-${kind}`;
    el.textContent = text;
  }

  async function startRender() {
    const btn = $("#btn-render");
    const msg = $("#progress-msg");

    const owner = $("#in-owner").value.trim();
    const repo = $("#in-repo").value.trim();
    if (owner !== cfg.owner || repo !== cfg.repo) { cfg.owner = owner; cfg.repo = repo; updateRepoChip(); }
    if (!isValidRepo()) return alert("Enter a valid owner and repository first.");
    if (!state.token) { selectTabKeep("#card-connection"); return setNote(msg, "A GitHub token is required to trigger the workflow — paste one in step 1.", "err"); }

    const html = $("#in-html").value;
    if (!html.trim()) return setNote(msg, "Paste a composition first (or load an example).", "err");
    if (new Blob([html]).size > 3.5 * 1024 * 1024) return setNote(msg, "Composition is larger than 3.5 MB — trim assets or host them by URL.", "err");

    let variables;
    try { variables = validateVariables(readSettings().vars); }
    catch (e) { return setNote(msg, esc(e.message), "err"); }

    const s = readSettings();
    const title = s.title || (html.match(/<title>([^<]*)<\/title>/i)?.[1]?.trim()) || "HyperFrames render";
    const key = randomKey();

    btn.disabled = true;
    $("#card-progress").hidden = false;
    resetSteps();
    setRunChip("starting…", "warn");
    setNote(msg, "");

    const track = { key, title, owner: cfg.owner, repo: cfg.repo, ts: Date.now(), status: "starting" };
    try {
      // 1 — upload composition as a git blob (keeps the dispatch payload tiny)
      setStep("blob", "active");
      const blob = await gh(`/repos/${repoPath()}/git/blobs`, { method: "POST", body: { content: html, encoding: "utf-8" } });
      setStep("blob", "done");
      track.blobSha = blob.sha;

      // 2 — dispatch the workflow
      // NOTE: GitHub caps client_payload at 10 properties, so all render
      // settings travel packed inside one `settings_json` string.
      setStep("dispatch", "active");
      const settings = {
        engine: s.engine,
        format: s.format,
        quality: s.quality,
        resolution: s.resolution,
        aspect_ratio: s.aspect,
        fps: s.fps,
        variables_json: s.vars,
        lint: String(s.lint),
      };
      await gh(`/repos/${repoPath()}/dispatches`, {
        method: "POST",
        body: {
          event_type: "render-video",
          client_payload: {
            blob_sha: blob.sha,
            render_key: key,
            title,
            settings_json: JSON.stringify(settings),
          },
        },
      });
      setStep("dispatch", "done");
      track.status = "dispatched";
      localStorage.setItem(LS.track, JSON.stringify(track));
      setStep("run", "active");
      setRunChip("queued…", "warn");

      // 3+4 — find the run and follow it
      trackPolling(track);
    } catch (e) {
      if (stepEl("blob").classList.contains("active")) setStep("blob", "failed");
      else setStep("dispatch", "failed");
      setRunChip("failed", "err");
      setNote(msg, `${esc(e.message)}${e.hint ? ` — ${esc(e.hint)}` : ""}`, "err");
    } finally {
      btn.disabled = false;
    }
  }

  function selectTabKeep() { /* focus hint: scroll connection card into view */
    $("#card-connection").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#in-pat").focus({ preventScroll: true });
  }

  async function trackPolling(track) {
    if (state.pollAbort) state.pollAbort.aborted = true;
    const ctl = { aborted: false };
    state.pollAbort = ctl;

    const deadline = track.ts + 45 * 60 * 1000;
    let runFound = false;
    let firstWaitNoteShown = false;

    while (!ctl.aborted && Date.now() < deadline) {
      try {
        const data = await gh(`/repos/${track.owner}/${track.repo}/actions/runs?per_page=30`);
        const runs = data.workflow_runs || [];
        const run = runs.find(
          (r) => r.event === "repository_dispatch" && (r.display_title || r.name || "").includes(track.key)
        );
        if (!run) {
          if (Date.now() - track.ts > 90 * 1000 && !firstWaitNoteShown) {
            firstWaitNoteShown = true;
            setNote(
              $("#progress-msg"),
              "Still waiting for the workflow to appear. If nothing shows up, check the <em>Actions</em> tab — the workflow file must exist on the default branch.",
              ""
            );
          }
          await sleep(5000);
          continue;
        }

        if (!runFound) {
          runFound = true;
          setStep("run", "done");
          setStep("render", "active");
          show($("#progress-links"), true);
          $("#link-run").href = run.html_url;
          localStorage.setItem(LS.track, JSON.stringify({ ...track, runId: run.id, runUrl: run.html_url }));
        }

        const status = run.status;
        const conclusion = run.conclusion;
        if (status === "queued") setRunChip("queued…", "warn");
        else if (status === "in_progress") setRunChip("rendering…", "warn");

        if (status === "completed") {
          if (conclusion === "success") {
            setStep("render", "done");
            setStep("release", "done");
            setRunChip("completed ✓", "ok");
            setNote($("#progress-msg"), "🎉 Render finished — the video is attached to a GitHub Release. It should appear in the Videos tab.", "ok");
            await linkRelease(track);
            loadGallery(true);
          } else {
            setStep("render", "failed");
            setRunChip(`failed (${conclusion})`, "err");
            setNote(
              $("#progress-msg"),
              `Run ${esc(conclusion)}. Open the run to inspect logs: <a href="${esc(run.html_url)}" target="_blank" rel="noopener">${esc(run.html_url)}</a>. Common causes: invalid composition HTML (check the lint step), missing HEYGEN_API_KEY for cloud engine, or CDN assets blocked.`,
              "err"
            );
          }
          localStorage.removeItem(LS.track);
          return;
        }
      } catch (e) {
        if (e.status === 403 || e.status === 404) {
          setNote(
            $("#progress-msg"),
            `Can't read run status (${esc(e.message)}). The render may still be running — watch it on <a href="https://github.com/${esc(track.owner)}/${esc(track.repo)}/actions" target="_blank" rel="noopener">Actions</a>. Tip: give the token <strong>Actions: Read</strong>.`,
            "err"
          );
          return;
        }
      }
      await sleep(6000);
    }
  }

  async function linkRelease(track) {
    try {
      const releases = await gh(`/repos/${track.owner}/${track.repo}/releases?per_page=30`);
      const rel = (releases || []).find((r) => (r.tag_name || "").endsWith(`-${track.key}`) || (r.tag_name || "").startsWith("video-") && (r.tag_name || "").includes(track.key));
      if (rel) {
        show($("#progress-links"), true);
        const a = $("#link-release");
        a.href = rel.html_url;
        show(a, true);
      }
    } catch { /* non-fatal */ }
  }

  async function resumeTracking() {
    let track;
    try { track = JSON.parse(localStorage.getItem(LS.track) || "null"); } catch { return; }
    if (!track || !track.key) return;
    if (Date.now() - track.ts > 45 * 60 * 1000) { localStorage.removeItem(LS.track); return; }
    if (track.owner !== cfg.owner || track.repo !== cfg.repo) return;
    $("#card-progress").hidden = false;
    ["blob", "dispatch", "run"].forEach((s) => setStep(s, "done"));
    setStep("render", "active");
    setRunChip("rendering…", "warn");
    if (track.runUrl) { show($("#progress-links"), true); $("#link-run").href = track.runUrl; }
    trackPolling(track);
  }

  /* ------------------------------------------------------------------ *
   * gallery (GitHub Releases tagged video-*)
   * ------------------------------------------------------------------ */
  async function loadGallery(force = false) {
    const grid = $("#videos-grid");
    const emptyBox = $("#videos-empty");
    const msg = $("#videos-msg");
    if (!isValidRepo()) {
      show(emptyBox, true);
      setNote(msg, "Configure the repository in the Composer tab to list its renders.", "err");
      return;
    }
    if (force) state.galleryLoaded = false;
    $("#btn-refresh").disabled = true;
    grid.innerHTML = "";
    show(emptyBox, false);
    setNote(msg, `<span class="spin"></span> Loading releases from ${esc(repoPath())}…`);
    try {
      const releases = await gh(`/repos/${repoPath()}/releases?per_page=50`, { auth: Boolean(state.token) });
      const renders = (releases || []).filter((r) => (r.tag_name || "").startsWith("video-"));
      $("#videos-count").textContent = String(renders.length);
      show($("#videos-count"), renders.length > 0);
      setNote(msg, "");
      show(msg, false);
      if (!renders.length) { show(emptyBox, true); state.galleryLoaded = true; return; }
      for (const rel of renders) grid.appendChild(renderCard(rel));
      state.galleryLoaded = true;
    } catch (e) {
      setNote(msg, `${esc(e.message)}${e.hint ? ` — ${esc(e.hint)}` : ""}`, "err");
      show(emptyBox, false);
    } finally {
      $("#btn-refresh").disabled = false;
    }
  }

  function renderCard(rel) {
    const assets = rel.assets || [];
    const video = assets.find((a) => /^video\.(mp4|webm|mov)$/i.test(a.name)) || assets.find((a) => /\.(mp4|webm|mov)$/i.test(a.name));
    const thumb = assets.find((a) => /^thumbnail\.(jpg|jpeg|png)$/i.test(a.name));
    const script = assets.find((a) => /^(script|index)\.html$/i.test(a.name)) || assets.find((a) => /text\/html|\.html?$/i.test(a.name));
    const tall = /\b9:16\b/.test(rel.body || "");
    const square = /\b1:1\b/.test(rel.body || "") && !tall;

    const card = document.createElement("article");
    card.className = "card video-card";
    const media = video
      ? `<video class="vid ${tall ? "tall" : square ? "square" : ""}" controls preload="metadata" ${thumb ? `poster="${esc(thumb.browser_download_url)}"` : ""} src="${esc(video.browser_download_url)}"></video>`
      : `<div class="vid" style="display:grid;place-items:center;color:var(--muted)">no video asset</div>`;

    const engineMatch = (rel.body || "").match(/\|\s*Engine\s*\|\s*([^|]+?)\s*\|/);
    const engine = engineMatch ? engineMatch[1] : "";
    const size = video ? fmtBytes(video.size) : "";

    card.innerHTML = `
      ${media}
      <div class="video-meta">
        <div class="video-title">${esc(rel.name || rel.tag_name)}</div>
        <div class="video-sub">
          <span class="chip chip-info">${esc(rel.tag_name)}</span>
          ${engine ? `<span class="chip">${esc(engine)}</span>` : ""}
          ${size ? `<span>${esc(size)}</span>` : ""}
          <span>${esc(timeAgo(rel.published_at || rel.created_at))}</span>
        </div>
        <div class="video-actions">
          ${video ? `<a class="btn btn-sm btn-primary" href="${esc(video.browser_download_url)}" download>⬇ Download</a>` : ""}
          <a class="btn btn-sm btn-ghost" href="${esc(rel.html_url)}" target="_blank" rel="noopener">Release ↗</a>
          ${script ? `<a class="btn btn-sm btn-ghost" href="${esc(script.browser_download_url)}" target="_blank" rel="noopener">script.html</a>` : ""}
        </div>
      </div>`;
    return card;
  }

  /* ------------------------------------------------------------------ *
   * wiring
   * ------------------------------------------------------------------ */
  function init() {
    // prefill repo from URL query (?repo=owner/name) or injected config
    const q = new URLSearchParams(location.search);
    const qRepo = q.get("repo");
    if (qRepo && qRepo.includes("/")) { [cfg.owner, cfg.repo] = qRepo.split("/", 2); }
    $("#in-owner").value = cfg.owner || "";
    $("#in-repo").value = cfg.repo || "";
    updateRepoChip();
    refreshConnUI();
    restoreSettings();

    $("#in-pat").value = state.token || "";
    $("#in-remember").checked = state.remembered;

    $("#in-owner").addEventListener("change", () => { cfg.owner = $("#in-owner").value.trim(); updateRepoChip(); });
    $("#in-repo").addEventListener("change", () => { cfg.repo = $("#in-repo").value.trim(); updateRepoChip(); });

    $("#in-pat").addEventListener("change", () => {
      saveToken($("#in-pat").value, $("#in-remember").checked);
      refreshConnUI();
    });
    $("#in-remember").addEventListener("change", () => {
      saveToken($("#in-pat").value, $("#in-remember").checked);
      refreshConnUI();
    });
    $("#btn-verify").addEventListener("click", verifyToken);
    $("#btn-forget").addEventListener("click", () => {
      saveToken("", false);
      $("#in-pat").value = "";
      $("#conn-status").className = "chip chip-warn";
      $("#conn-status").textContent = "not connected";
      refreshConnUI();
      setNote($("#conn-msg"), "Token removed from this browser.");
    });

    $("#sel-example").addEventListener("change", (e) => loadExample(e.target.value));
    $("#btn-upload").addEventListener("click", () => $("#in-file").click());
    $("#in-file").addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { setHtml(String(reader.result)); if (!$("#in-title").value) $("#in-title").value = file.name.replace(/\.html?$/i, ""); };
      reader.readAsText(file);
      e.target.value = "";
    });
    $("#in-html").addEventListener("input", onHtmlChanged);

    // drag & drop
    const editorWrap = $("#editor-wrap");
    ["dragover", "drop"].forEach((ev) =>
      editorWrap.addEventListener(ev, (e) => {
        e.preventDefault();
        if (ev === "drop") {
          const file = e.dataTransfer.files && e.dataTransfer.files[0];
          if (file && /\.html?$/i.test(file.name)) {
            const reader = new FileReader();
            reader.onload = () => setHtml(String(reader.result));
            reader.readAsText(file);
          }
        }
      })
    );

    $("#btn-preview").addEventListener("click", () => togglePreview());
    $("#btn-close-preview").addEventListener("click", () => togglePreview(false));

    ["in-title", "in-vars"].forEach((id) => $("#" + id).addEventListener("change", onHtmlChanged));
    ["in-engine", "in-format", "in-quality", "in-resolution", "in-aspect", "in-fps", "in-lint"].forEach((id) =>
      $("#" + id).addEventListener("change", () => {
        try { localStorage.setItem(LS.settings, JSON.stringify(readSettings())); } catch {}
      })
    );

    $("#btn-render").addEventListener("click", startRender);
    $("#btn-refresh").addEventListener("click", () => loadGallery(true));

    onHtmlChanged();
    const tab = location.hash.replace("#", "") || "composer";
    selectTab(["composer", "videos", "guide"].includes(tab) ? tab : "composer");
    resumeTracking();

    // refresh gallery when returning to the tab
    window.addEventListener("focus", () => {
      if (document.querySelector("#panel-videos.active") && state.galleryLoaded) loadGallery(true);
    });
  }

  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
