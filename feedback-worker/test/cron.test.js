import assert from "node:assert/strict";
import test from "node:test";

import worker, { dispatchPodcastWorkflow } from "../src/index.js";

test("dispatchPodcastWorkflow returns error when GITHUB_DISPATCH_TOKEN is missing", async () => {
  const env = {};
  const result = await dispatchPodcastWorkflow(env);
  assert.equal(result.ok, false);
  assert.equal(result.error, "token_missing");
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

test("dispatchPodcastWorkflow handles GitHub API error response", async () => {
  const mockFetch = async () => {
    return {
      ok: false,
      status: 422,
      text: async () => '{"message":"Workflow does not have workflow_dispatch event"}',
    };
  };

  const env = {
    GITHUB_DISPATCH_TOKEN: "test-pat-token",
  };

  const result = await dispatchPodcastWorkflow(env, { fetch: mockFetch });
  assert.equal(result.ok, false);
  assert.equal(result.status, 422);
  assert.match(result.error, /Workflow does not have workflow_dispatch/);
});

test("worker.scheduled triggers dispatch", async () => {
  let dispatched = false;
  const mockFetch = async () => {
    dispatched = true;
    return {
      ok: true,
      status: 204,
      text: async () => "",
    };
  };

  // Temporarily override global fetch for scheduled handler
  const originalFetch = globalThis.fetch;
  globalThis.fetch = mockFetch;

  try {
    const env = {
      GITHUB_DISPATCH_TOKEN: "test-pat-token",
    };
    await worker.scheduled({ cron: "17 19 * * *" }, env, {});
    assert.equal(dispatched, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
