import assert from "node:assert/strict";
import test from "node:test";

import {
  extractLatestEpisodeId,
  isAuthorized,
  shortcutIdempotencyKey,
  validateReactionPayload,
} from "../src/index.js";

test("extractLatestEpisodeId reads the first RSS item only", () => {
  const xml = `
    <rss><channel>
      <item><guid isPermaLink="false">podcast_20260715_065320.mp3</guid></item>
      <item><guid isPermaLink="false">podcast_20260714_051905.mp3</guid></item>
    </channel></rss>`;
  assert.equal(extractLatestEpisodeId(xml), "podcast_20260715_065320");
});

test("extractLatestEpisodeId falls back to the enclosure URL", () => {
  const xml = `
    <item>
      <enclosure url="https://example.test/episodes/podcast_20260719_040000.mp3?x=1" />
    </item>`;
  assert.equal(extractLatestEpisodeId(xml), "podcast_20260719_040000");
});

test("extractLatestEpisodeId rejects malformed identifiers", () => {
  assert.equal(extractLatestEpisodeId("<item><guid>latest.mp3</guid></item>"), null);
});

test("isAuthorized accepts only the configured bearer token", () => {
  const authorized = new Request("https://example.test/v1/reactions", {
    headers: { authorization: "Bearer correct-token" },
  });
  const wrong = new Request("https://example.test/v1/reactions", {
    headers: { authorization: "Bearer wrong-token" },
  });
  assert.equal(isAuthorized(authorized, "correct-token"), true);
  assert.equal(isAuthorized(wrong, "correct-token"), false);
  assert.equal(isAuthorized(authorized, ""), false);
});

test("validateReactionPayload accepts the three closed reaction codes", () => {
  const now = new Date("2026-07-15T00:00:00.000Z");
  for (const reaction of ["new", "known", "tried"]) {
    const result = validateReactionPayload({ reaction }, now);
    assert.equal(result.ok, true);
    assert.equal(result.reaction, reaction);
    assert.equal(result.occurredAt, now.toISOString());
  }
});

test("validateReactionPayload rejects free text and stale timestamps", () => {
  const now = new Date("2026-07-15T00:00:00.000Z");
  assert.deepEqual(validateReactionPayload({ reaction: "great" }, now), {
    ok: false,
    error: "invalid_reaction",
  });
  assert.deepEqual(
    validateReactionPayload(
      { reaction: "new", occurred_at: "2026-07-13T00:00:00.000Z" },
      now,
    ),
    { ok: false, error: "occurred_at_out_of_range" },
  );
});

test("shortcutIdempotencyKey deduplicates only the same reaction minute", () => {
  const first = new Date("2026-07-15T00:00:01.000Z");
  const sameMinute = new Date("2026-07-15T00:00:59.000Z");
  const nextMinute = new Date("2026-07-15T00:01:00.000Z");
  assert.equal(
    shortcutIdempotencyKey("new", first),
    shortcutIdempotencyKey("new", sameMinute),
  );
  assert.notEqual(
    shortcutIdempotencyKey("new", first),
    shortcutIdempotencyKey("known", first),
  );
  assert.notEqual(
    shortcutIdempotencyKey("new", first),
    shortcutIdempotencyKey("new", nextMinute),
  );
});
