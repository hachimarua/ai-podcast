import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  validateVoiceFeedbackPayload,
} from "../src/index.js";

test("validateVoiceFeedbackPayload validates valid payload with snake_case and camelCase", () => {
  const now = new Date("2026-10-02T06:00:00.000Z");
  const payloadSnake = {
    request_id: "req-123",
    raw_utterance: "AIポッドキャスト、今日の1本目は少し簡単すぎた",
    episode_id: "podcast_20261001_041700",
    feedback_type: "difficulty",
    difficulty_signal: "too_easy",
    usefulness_signal: "useful",
    comment: "今日の1本目は少し簡単すぎた",
    source: "nagi_voice",
  };
  const res1 = validateVoiceFeedbackPayload(payloadSnake, now);
  assert.equal(res1.ok, true);
  assert.equal(res1.requestId, "req-123");
  assert.equal(res1.rawUtterance, "AIポッドキャスト、今日の1本目は少し簡単すぎた");
  assert.equal(res1.episodeId, "podcast_20261001_041700");
  assert.equal(res1.difficultySignal, "too_easy");

  const payloadCamel = {
    requestId: "req-456",
    rawUtterance: "2本目はかなりためになった",
    difficultySignal: "appropriate",
    resolveLatest: true,
  };
  const res2 = validateVoiceFeedbackPayload(payloadCamel, now);
  assert.equal(res2.ok, true);
  assert.equal(res2.requestId, "req-456");
  assert.equal(res2.rawUtterance, "2本目はかなりためになった");
  assert.equal(res2.resolveLatest, true);
  assert.equal(res2.occurredAt, now.toISOString());
});

test("validateVoiceFeedbackPayload rejects missing raw_utterance or request_id", () => {
  const now = new Date("2026-10-02T06:00:00.000Z");
  assert.deepEqual(validateVoiceFeedbackPayload({}, now), {
    ok: false,
    error: "invalid_raw_utterance",
  });
  assert.deepEqual(
    validateVoiceFeedbackPayload({ raw_utterance: "test" }, now),
    { ok: false, error: "invalid_request_id" },
  );
});

test("validateVoiceFeedbackPayload rejects out-of-range occurred_at", () => {
  const now = new Date("2026-10-02T06:00:00.000Z");
  assert.deepEqual(
    validateVoiceFeedbackPayload(
      {
        request_id: "req-1",
        raw_utterance: "test",
        occurred_at: "2026-09-01T00:00:00.000Z",
      },
      now,
    ),
    { ok: false, error: "occurred_at_out_of_range" },
  );
});

function createMockDb() {
  const rows = [];
  return {
    rows,
    prepare(query) {
      return {
        bind(...args) {
          return {
            async first() {
              if (query.includes("FROM voice_feedbacks WHERE request_id = ?")) {
                const reqId = args[0];
                return rows.find((r) => r.request_id === reqId) || null;
              }
              return null;
            },
            async run() {
              if (query.includes("INSERT INTO voice_feedbacks")) {
                const [
                  id,
                  request_id,
                  episode_id,
                  raw_utterance,
                  feedback_type,
                  difficulty_signal,
                  usefulness_signal,
                  comment,
                  metadata,
                  occurred_at,
                  received_at,
                  source,
                ] = args;
                rows.push({
                  id,
                  request_id,
                  episode_id,
                  raw_utterance,
                  feedback_type,
                  difficulty_signal,
                  usefulness_signal,
                  comment,
                  metadata,
                  occurred_at,
                  received_at,
                  source,
                });
                return { meta: { changes: 1 } };
              }
              return { meta: { changes: 0 } };
            },
            async all() {
              if (query.includes("FROM voice_feedbacks")) {
                const limit = args[0] || 20;
                return { results: rows.slice(0, limit) };
              }
              return { results: [] };
            },
          };
        },
      };
    },
  };
}

test("POST /v1/voice-feedback requires authorization", async () => {
  const env = { FEEDBACK_TOKEN: "secret-token" };
  const request = new Request("https://example.test/v1/voice-feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ request_id: "req-1", raw_utterance: "hello" }),
  });
  const res = await worker.fetch(request, env);
  assert.equal(res.status, 401);
});

test("POST /v1/voice-feedback stores feedback and returns 201, idempotent replay returns 200", async () => {
  const db = createMockDb();
  const env = {
    FEEDBACK_TOKEN: "secret-token",
    AI_RADIO_FEEDBACK_DB: db,
    PODCAST_FEED_URL: "https://example.test/podcast.xml",
  };

  const payload = {
    request_id: "req-100",
    raw_utterance: "AIポッドキャスト、難易度がちょうど良かった",
    episode_id: "podcast_20261001_041700",
    feedback_type: "difficulty",
    difficulty_signal: "appropriate",
  };

  const req1 = new Request("https://example.test/v1/voice-feedback", {
    method: "POST",
    headers: {
      authorization: "Bearer secret-token",
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const res1 = await worker.fetch(req1, env);
  assert.equal(res1.status, 201);
  const body1 = await res1.json();
  assert.equal(body1.ok, true);
  assert.equal(body1.duplicate, false);
  assert.equal(body1.request_id, "req-100");
  assert.equal(body1.episode_id, "podcast_20261001_041700");
  assert.equal(db.rows.length, 1);

  // Idempotent retry with same payload
  const req2 = new Request("https://example.test/v1/voice-feedback", {
    method: "POST",
    headers: {
      authorization: "Bearer secret-token",
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const res2 = await worker.fetch(req2, env);
  assert.equal(res2.status, 200);
  const body2 = await res2.json();
  assert.equal(body2.ok, true);
  assert.equal(body2.duplicate, true);
  assert.equal(body2.request_id, "req-100");
  assert.equal(db.rows.length, 1);

  // Conflict retry with different raw_utterance
  const req3 = new Request("https://example.test/v1/voice-feedback", {
    method: "POST",
    headers: {
      authorization: "Bearer secret-token",
      "content-type": "application/json",
    },
    body: JSON.stringify({ ...payload, raw_utterance: "異なる発話" }),
  });
  const res3 = await worker.fetch(req3, env);
  assert.equal(res3.status, 409);
});

test("GET /v1/voice-feedback/recent lists saved feedbacks", async () => {
  const db = createMockDb();
  db.rows.push({
    id: "id-1",
    request_id: "req-1",
    episode_id: "ep-1",
    raw_utterance: "テスト感想",
    feedback_type: "general",
    difficulty_signal: null,
    usefulness_signal: null,
    comment: null,
    occurred_at: "2026-10-02T06:00:00.000Z",
    received_at: "2026-10-02T06:00:01.000Z",
    source: "nagi_voice",
  });
  const env = {
    FEEDBACK_TOKEN: "secret-token",
    AI_RADIO_FEEDBACK_DB: db,
  };
  const req = new Request("https://example.test/v1/voice-feedback/recent?limit=5", {
    headers: { authorization: "Bearer secret-token" },
  });
  const res = await worker.fetch(req, env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.feedbacks.length, 1);
  assert.equal(body.feedbacks[0].request_id, "req-1");
});

test("POST /v1/voice-feedback does not leak raw_utterance, comment, or metadata to console logs", async () => {
  const db = createMockDb();
  const env = {
    FEEDBACK_TOKEN: "secret-token",
    AI_RADIO_FEEDBACK_DB: db,
    PODCAST_FEED_URL: "https://example.test/podcast.xml",
  };

  const originalLog = console.log;
  const originalError = console.error;
  const logged = [];
  console.log = (...args) => logged.push(args.join(" "));
  console.error = (...args) => logged.push(args.join(" "));

  try {
    const payload = {
      request_id: "req-privacy-check",
      raw_utterance: "極秘の発話内容が含まれるテスト発話です",
      comment: "秘密のコメント本文",
      metadata: { private_note: "個人識別情報" },
    };

    const req = new Request("https://example.test/v1/voice-feedback", {
      method: "POST",
      headers: {
        authorization: "Bearer secret-token",
        "content-type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const res = await worker.fetch(req, env);
    assert.equal(res.status, 201);

    for (const line of logged) {
      assert.doesNotMatch(line, /極秘の発話内容/);
      assert.doesNotMatch(line, /秘密のコメント本文/);
      assert.doesNotMatch(line, /個人識別情報/);
    }
  } finally {
    console.log = originalLog;
    console.error = originalError;
  }
});

test("top-level request exception in fetch emits fixed ai_radio_feedback_request_failed without payload data", async () => {
  const brokenDb = {
    prepare() {
      throw new Error("D1 connection lost");
    },
  };
  const env = {
    FEEDBACK_TOKEN: "secret-token",
    AI_RADIO_FEEDBACK_DB: brokenDb,
  };

  const originalError = console.error;
  const loggedErrors = [];
  console.error = (...args) => loggedErrors.push(args.join(" "));

  try {
    const req = new Request("https://example.test/v1/voice-feedback", {
      method: "POST",
      headers: {
        authorization: "Bearer secret-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        request_id: "req-err-check",
        raw_utterance: "例外発生時の秘密発話",
      }),
    });

    const res = await worker.fetch(req, env);
    assert.equal(res.status, 500);
    const body = await res.json();
    assert.equal(body.ok, false);
    assert.equal(body.error, "internal_error");

    assert.equal(loggedErrors.length, 1);
    assert.equal(loggedErrors[0], "ai_radio_feedback_request_failed");
    assert.doesNotMatch(loggedErrors[0], /例外発生時の秘密発話/);
  } finally {
    console.error = originalError;
  }
});

