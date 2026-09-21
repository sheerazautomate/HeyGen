// Pure helpers shared by the browser and node:test. Never evaluate user HTML.
export function validateComposition(html, policy) {
  if (!html.trim()) throw new Error("Choose a non-empty HTML file.");
  const bytes = new TextEncoder().encode(html).length;
  if (bytes > policy.max_html_bytes)
    throw new Error(
      `This pilot accepts files up to ${policy.max_html_bytes / 1024} KB.`,
    );
  // Advisory metadata extraction only. Actions uses an HTML parser and is authoritative.
  // No DOM insertion, iframe, preview, or network requests from the uploaded document.
  const tags =
    html
      .replace(/<!--[\s\S]*?-->/g, "")
      .match(/<[a-z][^>]*\sdata-composition-id\s*=[^>]*>/gi) || [];
  if (tags.length !== 1)
    throw new Error(
      "Choose a single HyperFrames composition, not an ordinary webpage. Try the example below.",
    );
  function attribute(name) {
    const match = tags[0].match(
      new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i"),
    );
    return match ? (match[1] ?? match[2] ?? match[3]) : "";
  }
  const width = Number(attribute("data-width"));
  const height = Number(attribute("data-height"));
  const duration = Number(attribute("data-duration"));
  if (
    !Number.isFinite(duration) ||
    duration <= 0 ||
    duration > policy.max_duration_seconds
  )
    throw new Error(
      `Your composition must declare a duration between 0 and ${policy.max_duration_seconds} seconds (not zero).`,
    );
  if (
    ![width, height].every(
      (n) =>
        Number.isInteger(n) &&
        n > 0 &&
        n <= policy.max_dimension &&
        n % 2 === 0,
    ) ||
    width * height > policy.max_pixels
  )
    throw new Error(
      "Use even-numbered dimensions, up to 1920 pixels per side and 1080p total pixels.",
    );
  return { width, height, duration, bytes };
}

export function encodePacket(html, title) {
  title = title.trim();
  if (!title || [...title].length > 100)
    throw new Error("Give your video a name (up to 100 characters).");
  const bytes = new TextEncoder().encode(
    JSON.stringify({ version: 1, title, html, public: true }),
  );
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const packet = "HF1." + btoa(binary);
  if (packet.length > 60000)
    throw new Error(
      "This request is too large for the GitHub form. Please use a smaller HTML file.",
    );
  return packet;
}

export function parseIssueInput(input, repo) {
  const value = input.trim();
  let number;
  if (/^#?[1-9]\d{0,8}$/.test(value)) number = Number(value.replace("#", ""));
  else {
    let url;
    try {
      url = new URL(value);
    } catch {
      throw new Error(
        "Paste your GitHub request link, or enter its issue number.",
      );
    }
    const prefix = `/${repo}/issues/`;
    if (
      url.origin !== "https://github.com" ||
      !url.pathname.toLowerCase().startsWith(prefix.toLowerCase())
    )
      throw new Error("Use a request from this studio’s GitHub repository.");
    const tail = url.pathname.slice(prefix.length).replace(/\/$/, "");
    if (!/^[1-9]\d{0,8}$/.test(tail))
      throw new Error("That is not a valid GitHub issue link.");
    number = Number(tail);
  }
  return number;
}

export function parseStatus(comments) {
  for (const comment of [...comments].reverse()) {
    if (
      comment.user?.login !== "github-actions[bot]" ||
      comment.user?.type !== "Bot"
    )
      continue;
    if (!comment.body?.startsWith("<!-- hyperframes-pilot:v1 -->")) continue;
    const match = comment.body.match(/```json\n([^]*?)\n```/);
    if (!match) continue;
    try {
      const state = JSON.parse(match[1]);
      if (
        ["queued", "creating", "ready", "failed", "rejected"].includes(
          state.status,
        ) &&
        typeof state.message === "string"
      )
        return state;
    } catch {
      /* Ignore malformed or unrelated comments. */
    }
  }
  return null;
}

export function trustedAssetURL(url, repo) {
  try {
    const parsed = new URL(url);
    return (
      parsed.origin === "https://github.com" &&
      parsed.pathname.startsWith(`/${repo}/releases/download/`) &&
      !parsed.username &&
      !parsed.password
    );
  } catch {
    return false;
  }
}
