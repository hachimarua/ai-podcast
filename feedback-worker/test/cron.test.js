import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  dispatchPodcastWorkflow,
  formatDispatchErrorLog,
  getJstDateString,
  acquireCronDispatchLock,
  completeCronDispatchLock,
  failCronDispatchLock,
} from "../src/index.js";

test("formatDispatchErrorLog formats error log safely and consistently", () => {
  assert.equal(
    formatDispatchErrorLog({ error: "token_missing" }),
    "ai_radio_dispatch_failed event=ai_radio_dispatch_failed stage=github_dispatch error_code=token_missing",
  );
  assert.equal(
    formatDispatchErrorLog({ error: "github_dispatch_failed", status: 422 }),
    "ai_radio_dispatch_failed event=ai_radio_dispatch_failed stage=github_dispatch error_code=github_dispatch_failed status=422",
  );
  assert.equal(
    formatDispatchErrorLog({ error: "network_error" }),
    "ai_radio_dispatch_failed event=ai_radio_dispatch_failed stage=github_dispatch error_code=network_error",
  );
});

test("dispatchPodcastWorkflow returns error when GITHUB_DISPATCH_TOKEN is missing without logging error", async () => {
  const originalError = console.error;
  let errorCalls = 0;
  console.error = () => {
    errorCalls++;
  };
  try {
    const env = {};
    const result = await dispatchPodcastWorkflow(env);
    assert.equal(result.ok, false);
    assert.equal(result.error, "token_missing");
    assert.equal(errorCalls, 0, "dispatchPodcastWorkflow should not log error directly");
  } finally {
    console.error = originalError;
  }
});

test("dispatchPodcastWorkflow sends POST request with correct payload and headers", async () => {
  let capturedUrl = "";
  let capturedOptions = {};

  const mockFetch = async (url, options) => {
    capturedUrl = url;
    capturedOptions = options;
    return {
      ok: true,
      status: 204,
      text: async () => "",
    };
  };

  const env = {
    GITHUB_DISPATCH_TOKEN: "test-pat-token",
    GITHUB_REPO: "test-user/test-repo",
    GITHUB_WORKFLOW_FILE: "custom-podcast.yml",
  };

  const result = await dispatchPodcastWorkflow(env, {
    ref: "develop",
    inputs: { force: true },
    fetch: mockFetch,
  });

  assert.equal(result.ok, true);
  assert.equal(result.status, 204);
  assert.equal(
    capturedUrl,
    "https://api.github.com/repos/test-user/test-repo/actions/workflows/custom-podcast.yml/dispatches",
  );
  assert.equal(capturedOptions.method, "POST");
  assert.equal(
    capturedOptions.headers.authorization,
    "Bearer test-pat-token",
  );
  assert.equal(
    capturedOptions.headers.accept,
    "application/vnd.github+json",
  );

  const parsedBody = JSON.parse(capturedOptions.body);
  assert.equal(parsedBody.ref, "develop");
  assert.deepEqual(parsedBody.inputs, { force: true });
});

test("dispatchPodcastWorkflow handles GitHub API error response safely without logging raw response body", async () => {
  const originalError = console.error;
  let errorCalls = 0;
  console.error = () => {
    errorCalls++;
  };
  try {
    const rawResponseBody = '{"message":"Workflow does not have workflow_dispatch event"}';
    const mockFetch = async () => {
      return {
        ok: false,
        status: 422,
        text: async () => rawResponseBody,
      };
    };

    const env = {
      GITHUB_DISPATCH_TOKEN: "test-pat-token",
    };

    const result = await dispatchPodcastWorkflow(env, { fetch: mockFetch });
    assert.equal(result.ok, false);
    assert.equal(result.status, 422);
    assert.equal(result.error, "github_dispatch_failed");
    assert.equal(errorCalls, 0, "dispatchPodcastWorkflow should not log error directly");
  } finally {
    console.error = originalError;
  }
});

test("dispatchPodcastWorkflow handles network error safely without logging", async () => {
  const originalError = console.error;
  let errorCalls = 0;
  console.error = () => {
    errorCalls++;
  };
  try {
    const mockFetch = async () => {
      throw new Error("DNS resolution failed for api.github.com");
    };

    const env = {
      GITHUB_DISPATCH_TOKEN: "test-pat-token",
    };

    const result = await dispatchPodcastWorkflow(env, { fetch: mockFetch });
    assert.equal(result.ok, false);
    assert.equal(result.error, "network_error");
    assert.equal(errorCalls, 0, "dispatchPodcastWorkflow should not log error directly");
  } finally {
    console.error = originalError;
  }
});

test("worker.scheduled triggers dispatch successfully without error logs", async () => {
  let dispatched = false;
  const mockFetch = async () => {
    dispatched = true;
    return {
      ok: true,
      status: 204,
      text: async () => "",
    };
  };

  const originalFetch = globalThis.fetch;
  const originalError = console.error;
  let errorCalls = 0;
  globalThis.fetch = mockFetch;
  console.error = () => {
    errorCalls++;
  };

  try {
    const env = {
      GITHUB_DISPATCH_TOKEN: "test-pat-token",
    };
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});
    assert.equal(dispatched, true);
    assert.equal(errorCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }
});

test("worker.scheduled logs exactly 1 error signal when token is missing", async () => {
  const originalError = console.error;
  const loggedErrors = [];
  console.error = (...args) => {
    loggedErrors.push(args);
  };

  try {
    const env = {};
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});

    assert.equal(loggedErrors.length, 1, "exactly 1 error log should be emitted");
    const logOutput = loggedErrors[0].join(" ");
    assert.match(logOutput, /^ai_radio_dispatch_failed\b/);
    assert.match(logOutput, /stage=github_dispatch/);
    assert.match(logOutput, /error_code=token_missing/);
    assert.doesNotMatch(logOutput, /Bearer/i);
    assert.doesNotMatch(logOutput, /undefined/);
  } finally {
    console.error = originalError;
  }
});

test("worker.scheduled logs exactly 1 error signal on GitHub API non-2xx without raw body or token", async () => {
  const rawResponseBody = '{"message":"Not Found: invalid workflow","documentation_url":"https://docs.github.com"}';
  const mockFetch = async () => ({
    ok: false,
    status: 404,
    text: async () => rawResponseBody,
  });

  const originalFetch = globalThis.fetch;
  const originalError = console.error;
  const loggedErrors = [];
  globalThis.fetch = mockFetch;
  console.error = (...args) => {
    loggedErrors.push(args);
  };

  try {
    const env = {
      GITHUB_DISPATCH_TOKEN: "secret-dispatch-token-xyz",
    };
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});

    assert.equal(loggedErrors.length, 1, "exactly 1 error log should be emitted");
    const logOutput = loggedErrors[0].join(" ");
    assert.match(logOutput, /^ai_radio_dispatch_failed\b/);
    assert.match(logOutput, /stage=github_dispatch/);
    assert.match(logOutput, /error_code=github_dispatch_failed/);
    assert.match(logOutput, /status=404/);
    assert.doesNotMatch(logOutput, /secret-dispatch-token-xyz/);
    assert.doesNotMatch(logOutput, /Not Found: invalid workflow/);
    assert.doesNotMatch(logOutput, /docs\.github\.com/);
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }
});

test("worker.scheduled logs exactly 1 error signal on network error without secrets or body", async () => {
  const mockFetch = async () => {
    throw new TypeError("fetch failed: connection refused");
  };

  const originalFetch = globalThis.fetch;
  const originalError = console.error;
  const loggedErrors = [];
  globalThis.fetch = mockFetch;
  console.error = (...args) => {
    loggedErrors.push(args);
  };

  try {
    const env = {
      GITHUB_DISPATCH_TOKEN: "super-secret-token",
    };
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});

    assert.equal(loggedErrors.length, 1, "exactly 1 error log should be emitted");
    const logOutput = loggedErrors[0].join(" ");
    assert.match(logOutput, /^ai_radio_dispatch_failed\b/);
    assert.match(logOutput, /stage=github_dispatch/);
    assert.match(logOutput, /error_code=network_error/);
    assert.doesNotMatch(logOutput, /super-secret-token/);
    assert.doesNotMatch(logOutput, /connection refused/);
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }
});

function createMockD1(options = {}) {
  const store = new Map();
  return {
    _store: store,
    prepare(query) {
      if (options.shouldThrowPrepare) {
        throw new Error(options.throwMessage || "D1 connection failure");
      }
      let bound = [];
      return {
        bind(...args) {
          bound = args;
          return this;
        },
        async run() {
          if (options.shouldThrowRun) {
            throw new Error(options.throwMessage || "D1 run failure");
          }
          if (query.startsWith("INSERT INTO cron_dispatches")) {
            const [dispatchDate, dispatchedAt, lockToken] = bound;
            if (store.has(dispatchDate)) {
              throw new Error("UNIQUE constraint failed: cron_dispatches.dispatch_date");
            }
            store.set(dispatchDate, {
              dispatch_date: dispatchDate,
              status: "in_progress",
              dispatched_at: dispatchedAt,
              workflow_file: "podcast.yml",
              lock_token: lockToken,
              error_message: null,
            });
            return { meta: { changes: 1 } };
          }
          if (query.startsWith("UPDATE cron_dispatches SET status = 'completed'")) {
            const completedAt = bound[0];
            const dispatchDate = bound[1];
            const lockToken = bound[2];
            const row = store.get(dispatchDate);
            if (row) {
              if (lockToken && row.lock_token !== lockToken) {
                return { meta: { changes: 0 } };
              }
              row.status = "completed";
              row.completed_at = completedAt;
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          if (query.startsWith("UPDATE cron_dispatches SET status = 'failed'")) {
            const errorMsg = bound[0];
            const dispatchDate = bound[1];
            const lockToken = bound[2];
            const row = store.get(dispatchDate);
            if (row) {
              if (lockToken && row.lock_token !== lockToken) {
                return { meta: { changes: 0 } };
              }
              row.status = "failed";
              row.error_message = errorMsg;
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          if (query.startsWith("UPDATE cron_dispatches SET status = 'in_progress'")) {
            // CAS update: bound = [nowIso, lockToken, dispatchDate, existing.status, existing.dispatched_at]
            const [nowIso, lockToken, dispatchDate, expectedStatus, expectedDispatchedAt] = bound;
            const row = store.get(dispatchDate);
            if (
              row &&
              row.status === expectedStatus &&
              row.dispatched_at === expectedDispatchedAt
            ) {
              row.status = "in_progress";
              row.dispatched_at = nowIso;
              row.lock_token = lockToken;
              row.error_message = null;
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          return { meta: { changes: 0 } };
        },
        async first() {
          if (options.shouldThrowFirst) {
            throw new Error(options.throwMessage || "D1 read failure");
          }
          if (query.startsWith("SELECT status, dispatched_at, lock_token FROM cron_dispatches")) {
            const [dispatchDate] = bound;
            return store.get(dispatchDate) || null;
          }
          return null;
        },
      };
    },
  };
}

test("getJstDateString correctly computes JST date around midnight UTC", () => {
  // UTC 2026-10-12 19:17:00 -> JST 2026-10-13 04:17:00
  const utcMorning = new Date("2026-10-12T19:17:00.000Z");
  assert.equal(getJstDateString(utcMorning), "2026-10-13");

  // UTC 2026-10-12 14:59:00 -> JST 2026-10-12 23:59:00
  const utcBeforemidnight = new Date("2026-10-12T14:59:00.000Z");
  assert.equal(getJstDateString(utcBeforemidnight), "2026-10-12");

  // UTC 2026-10-12 15:00:00 -> JST 2026-10-13 00:00:00
  const utcBoundary = new Date("2026-10-12T15:00:00.000Z");
  assert.equal(getJstDateString(utcBoundary), "2026-10-13");
});

test("acquireCronDispatchLock acquires lock on first call and blocks duplicate within lock period", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  // 1st call -> acquired with lockToken
  const lock1 = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock1.acquired, true);
  assert.ok(lock1.lockToken, "must return lockToken");

  // 2nd call (3 seconds later) -> blocked (lock_active)
  const now2 = new Date(now.getTime() + 3000);
  const lock2 = await acquireCronDispatchLock(db, date, now2);
  assert.equal(lock2.acquired, false);
  assert.equal(lock2.reason, "lock_active");

  // Complete lock using owner token
  const completeRes = await completeCronDispatchLock(db, date, lock1.lockToken, now2);
  assert.equal(completeRes.ok, true);

  // 3rd call after completion -> blocked (already_completed)
  const lock3 = await acquireCronDispatchLock(db, date, new Date(now.getTime() + 60000));
  assert.equal(lock3.acquired, false);
  assert.equal(lock3.reason, "already_completed");
});

test("completeCronDispatchLock rejects update when lockToken does not match", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  const lock = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock.acquired, true);

  // Attempt complete with wrong token -> fails
  const wrongRes = await completeCronDispatchLock(db, date, "wrong-token-1234", now);
  assert.equal(wrongRes.ok, false);

  // Attempt fail with wrong token -> fails
  const wrongFailRes = await failCronDispatchLock(db, date, "wrong-token-1234", "err");
  assert.equal(wrongFailRes.ok, false);

  // Complete with valid token -> succeeds
  const rightRes = await completeCronDispatchLock(db, date, lock.lockToken, now);
  assert.equal(rightRes.ok, true);
});

test("acquireCronDispatchLock recovers after lock timeout (stale in_progress)", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  const lock1 = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock1.acquired, true);

  // 11 minutes later without completion -> should recover and acquire
  const nowStale = new Date(now.getTime() + 11 * 60 * 1000);
  const lock2 = await acquireCronDispatchLock(db, date, nowStale);
  assert.equal(lock2.acquired, true);
  assert.notEqual(lock2.lockToken, lock1.lockToken);
});

test("acquireCronDispatchLock CAS prevents concurrent duplicate takeovers of stale lock", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  // Initial acquire
  const lock1 = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock1.acquired, true);

  // 11 minutes later, two workers race simultaneously to take over the stale lock
  const nowStale = new Date(now.getTime() + 11 * 60 * 1000);
  const [race1, race2] = await Promise.all([
    acquireCronDispatchLock(db, date, nowStale),
    acquireCronDispatchLock(db, date, nowStale),
  ]);

  // Exactly one worker must acquire, and the other must be blocked
  const acquiredCount = (race1.acquired ? 1 : 0) + (race2.acquired ? 1 : 0);
  assert.equal(acquiredCount, 1, "exactly 1 worker should win the race");

  const loser = race1.acquired ? race2 : race1;
  assert.equal(loser.acquired, false);
  assert.ok(
    loser.reason === "race_lost" || loser.reason === "lock_active",
    `loser reason must be race_lost or lock_active, got: ${loser.reason}`,
  );
});

test("acquireCronDispatchLock returns race_lost when another worker updates row before CAS UPDATE", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  // First lock
  await acquireCronDispatchLock(db, date, now);

  // Simulate stale lock
  const nowStale = new Date(now.getTime() + 11 * 60 * 1000);

  // Interleaving simulation: right before UPDATE run, competitor updates the record
  const originalPrepare = db.prepare.bind(db);
  db.prepare = function (query) {
    const stmt = originalPrepare(query);
    if (query.startsWith("UPDATE cron_dispatches SET status = 'in_progress'")) {
      const originalRun = stmt.run.bind(stmt);
      stmt.run = async function () {
        const row = db._store.get(date);
        if (row) {
          row.dispatched_at = new Date(nowStale.getTime() + 1000).toISOString();
          row.lock_token = "competitor-token";
        }
        return originalRun();
      };
    }
    return stmt;
  };

  const lock = await acquireCronDispatchLock(db, date, nowStale);
  assert.equal(lock.acquired, false);
  assert.equal(lock.reason, "race_lost");
});

test("acquireCronDispatchLock recovers after failed dispatch", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  const lock1 = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock1.acquired, true);

  // Mark as failed
  await failCronDispatchLock(db, date, lock1.lockToken, "network_error");

  // Retry immediately -> should acquire
  const lock2 = await acquireCronDispatchLock(db, date, new Date(now.getTime() + 5000));
  assert.equal(lock2.acquired, true);
});

test("acquireCronDispatchLock handles D1 failure fail-closed with error log", async () => {
  const originalError = console.error;
  const loggedErrors = [];
  console.error = (...args) => {
    loggedErrors.push(args);
  };

  try {
    // DB that throws fatal connection error on run
    const failingDb = createMockD1({
      shouldThrowRun: true,
      throwMessage: "D1 storage service unavailable",
    });

    const result = await acquireCronDispatchLock(failingDb, "2026-10-13");
    assert.equal(result.acquired, false);
    assert.equal(result.reason, "db_error");

    assert.equal(loggedErrors.length, 1);
    const logStr = loggedErrors[0].join(" ");
    assert.match(logStr, /^ai_radio_cron_db_error/);
    assert.match(logStr, /D1 storage service unavailable/);
  } finally {
    console.error = originalError;
  }
});

test("worker.scheduled fails closed without dispatching when D1 has an outage", async () => {
  let dispatchCalls = 0;
  const mockFetch = async () => {
    dispatchCalls++;
    return { ok: true, status: 204, text: async () => "" };
  };

  const originalFetch = globalThis.fetch;
  const originalError = console.error;
  const loggedErrors = [];
  globalThis.fetch = mockFetch;
  console.error = (...args) => {
    loggedErrors.push(args);
  };

  try {
    const failingDb = createMockD1({
      shouldThrowRun: true,
      throwMessage: "D1 completely down",
    });

    const env = {
      AI_RADIO_FEEDBACK_DB: failingDb,
      GITHUB_DISPATCH_TOKEN: "test-token",
    };

    await worker.scheduled({ cron: "17 19 * * *" }, env, {});

    // Must NOT call dispatch
    assert.equal(dispatchCalls, 0, "must fail-closed and skip dispatch during D1 outage");
    assert.ok(loggedErrors.some((log) => log.join(" ").includes("ai_radio_cron_db_error")));
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }
});

test("worker.scheduled skips duplicate dispatch when D1 lock is already held", async () => {
  const db = createMockD1();
  let dispatchCalls = 0;
  const mockFetch = async () => {
    dispatchCalls++;
    return { ok: true, status: 204, text: async () => "" };
  };

  const originalFetch = globalThis.fetch;
  globalThis.fetch = mockFetch;

  try {
    const env = {
      AI_RADIO_FEEDBACK_DB: db,
      GITHUB_DISPATCH_TOKEN: "test-token",
    };

    // 1st scheduled run
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});
    assert.equal(dispatchCalls, 1, "first call should dispatch");

    // 2nd scheduled run (simulating duplicate trigger 2 seconds later)
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});
    assert.equal(dispatchCalls, 1, "second duplicate call must be skipped");
  } finally {
    globalThis.fetch = originalFetch;
  }
});



