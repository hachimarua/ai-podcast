import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  dispatchPodcastWorkflow,
  formatDispatchErrorLog,
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

