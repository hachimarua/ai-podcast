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

function createMockD1() {
  const store = new Map();
  return {
    _store: store,
    prepare(query) {
      let bound = [];
      return {
        bind(...args) {
          bound = args;
          return this;
        },
        async run() {
          if (query.startsWith("INSERT INTO cron_dispatches")) {
            const [dispatchDate, dispatchedAt] = bound;
            if (store.has(dispatchDate)) {
              throw new Error("UNIQUE constraint failed: cron_dispatches.dispatch_date");
            }
            store.set(dispatchDate, {
              dispatch_date: dispatchDate,
              status: "in_progress",
              dispatched_at: dispatchedAt,
              workflow_file: "podcast.yml",
              error_message: null,
            });
            return { meta: { changes: 1 } };
          }
          if (query.startsWith("UPDATE cron_dispatches SET status = 'completed'")) {
            const [completedAt, dispatchDate] = bound;
            const row = store.get(dispatchDate);
            if (row) {
              row.status = "completed";
              row.completed_at = completedAt;
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          if (query.startsWith("UPDATE cron_dispatches SET status = 'failed'")) {
            const [errorMsg, dispatchDate] = bound;
            const row = store.get(dispatchDate);
            if (row) {
              row.status = "failed";
              row.error_message = errorMsg;
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          if (query.startsWith("UPDATE cron_dispatches SET status = 'in_progress'")) {
            const [dispatchedAt, dispatchDate] = bound;
            const row = store.get(dispatchDate);
            if (row && row.status !== "completed") {
              row.status = "in_progress";
              row.dispatched_at = dispatchedAt;
              row.error_message = null;
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          return { meta: { changes: 0 } };
        },
        async first() {
          if (query.startsWith("SELECT status, dispatched_at FROM cron_dispatches")) {
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

  // 1st call -> acquired
  const lock1 = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock1.acquired, true);

  // 2nd call (3 seconds later) -> blocked (lock_active)
  const now2 = new Date(now.getTime() + 3000);
  const lock2 = await acquireCronDispatchLock(db, date, now2);
  assert.equal(lock2.acquired, false);
  assert.equal(lock2.reason, "lock_active");

  // Complete lock
  await completeCronDispatchLock(db, date, now2);

  // 3rd call after completion -> blocked (already_completed)
  const lock3 = await acquireCronDispatchLock(db, date, new Date(now.getTime() + 60000));
  assert.equal(lock3.acquired, false);
  assert.equal(lock3.reason, "already_completed");
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
});

test("acquireCronDispatchLock recovers after failed dispatch", async () => {
  const db = createMockD1();
  const date = "2026-10-13";
  const now = new Date("2026-10-12T19:17:00.000Z");

  const lock1 = await acquireCronDispatchLock(db, date, now);
  assert.equal(lock1.acquired, true);

  // Mark as failed
  await failCronDispatchLock(db, date, "network_error");

  // Retry immediately -> should acquire
  const lock2 = await acquireCronDispatchLock(db, date, new Date(now.getTime() + 5000));
  assert.equal(lock2.acquired, true);
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


