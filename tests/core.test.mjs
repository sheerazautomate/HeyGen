import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  validateComposition,
  encodePacket,
  parseIssueInput,
  parseStatus,
  trustedAssetURL,
} from "../site/core.mjs";
const policy = JSON.parse(readFileSync(".github/pilot.json"));
const html = readFileSync("examples/product-launch.html", "utf8");

test("validates shipped examples without executing them", () => {
  for (const file of ["product-launch", "vertical-teaser"]) {
    assert.ok(
      validateComposition(readFileSync(`examples/${file}.html`, "utf8"), policy)
        .duration > 0,
    );
  }
});
test("unicode HTML survives GitHub packet encoding", () => {
  const input = html + "こんにちは 🌍 اردو";
  const packet = encodePacket(input, "🌍 Video");
  const decoded = JSON.parse(Buffer.from(packet.slice(4), "base64").toString());
  assert.equal(decoded.html, input);
  assert.equal(decoded.title, "🌍 Video");
  assert.equal(decoded.public, true);
});
test("rejects invalid HTML, missing dimensions, and oversized files", () => {
  for (const source of [
    "",
    "<h1>Hello</h1>",
    html.repeat(3),
    html.replace('data-width="1920"', 'data-width="9999"'),
  ]) {
    assert.throws(() => validateComposition(source, policy));
  }
});
test("requires a video title", () =>
  assert.throws(() => encodePacket(html, "  ")));
test("request link parsing stays in the configured repository", () => {
  for (const value of [
    "#42",
    "42",
    "https://github.com/owner/repo/issues/42",
    "https://github.com/owner/repo/issues/42#issuecomment-2",
  ])
    assert.equal(parseIssueInput(value, "owner/repo"), 42);
  for (const value of [
    "0",
    "https://evil.test/owner/repo/issues/42",
    "https://github.com/other/repo/issues/42",
    "https://github.com/owner/repo/pull/42",
    "https://github.com/owner/repo/issues/42/evil",
    "javascript:alert(1)",
  ])
    assert.throws(() => parseIssueInput(value, "owner/repo"));
});
test("only accepts status from the actions bot", () => {
  const comment = {
    user: { login: "github-actions[bot]", type: "Bot" },
    body: '<!-- hyperframes-pilot:v1 -->\n```json\n{"status":"ready","message":"Ready"}\n```',
  };
  assert.equal(parseStatus([comment]).status, "ready");
  assert.equal(
    parseStatus([{ ...comment, user: { login: "attacker", type: "User" } }]),
    null,
  );
  assert.equal(
    parseStatus([
      { ...comment, body: comment.body.replace("ready", "arbitrary") },
    ]),
    null,
  );
});
test("media URLs must be real assets in this repository", () => {
  assert.ok(
    trustedAssetURL(
      "https://github.com/owner/repo/releases/download/video-pilot-1/video.mp4",
      "owner/repo",
    ),
  );
  for (const url of [
    "javascript:alert(1)",
    "https://github.com.evil.test/owner/repo/releases/download/video.mp4",
    "https://github.com/other/repo/releases/download/video.mp4",
  ])
    assert.equal(trustedAssetURL(url, "owner/repo"), false);
});
