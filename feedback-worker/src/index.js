const ALLOWED_REACTIONS = new Set(["new", "known", "tried"]);
const REACTION_MESSAGES = {
  new: "初耳で記録しました",
  known: "知ってたで記録しました",
  tried: "試したで記録しました",
};
const MAX_BODY_BYTES = 4096;
const MAX_CLOCK_SKEW_MS = 24 * 60 * 60 * 1000;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function plain(message, status = 200) {
  return new Response(message, {
    status,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function secretMatches(left, right) {
  if (typeof left !== "string" || typeof right !== "string") return false;
  let difference = left.length ^ right.length;
  const maxLength = Math.max(left.length, right.length);
  for (let index = 0; index < maxLength; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0;
}

export function isAuthorized(request, expectedToken) {
  if (!expectedToken) return false;
  const authorization = request.headers.get("authorization") || "";
  const match = authorization.match(/^Bearer\s+(.+)$/i);
  return Boolean(match && secretMatches(match[1], expectedToken));
}

export function extractLatestEpisodeId(feedXml) {
  if (typeof feedXml !== "string") return null;
  const firstItem = feedXml.match(/<item\b[\s\S]*?<\/item>/i)?.[0] || "";
  const guidMatch = firstItem.match(
    /<guid\b[^>]*>\s*(podcast_\d{8}_\d{6})\.mp3\s*<\/guid>/i,
  );
  if (guidMatch) return guidMatch[1];

  const enclosureMatch = firstItem.match(
    /<enclosure\b[^>]*\burl=["'][^"']*\/(podcast_\d{8}_\d{6})\.mp3(?:[?&][^"']*)?["']/i,
  );
  return enclosureMatch?.[1] || null;
}

export function validateReactionPayload(payload, now = new Date()) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, error: "invalid_json" };
  }
  if (!ALLOWED_REACTIONS.has(payload.reaction)) {
    return { ok: false, error: "invalid_reaction" };
  }

  const occurredAt = payload.occurred_at ? new Date(payload.occurred_at) : now;
  if (Number.isNaN(occurredAt.getTime())) {
    return { ok: false, error: "invalid_occurred_at" };
  }
  if (Math.abs(now.getTime() - occurredAt.getTime()) > MAX_CLOCK_SKEW_MS) {
    return { ok: false, error: "occurred_at_out_of_range" };
  }
  return {
    ok: true,
    reaction: payload.reaction,
    occurredAt: occurredAt.toISOString(),
  };
}

function validateIdempotencyKey(value) {
  return typeof value === "string" && /^[A-Za-z0-9._:-]{8,128}$/.test(value);
}

export function shortcutIdempotencyKey(reaction, now = new Date()) {
  return `shortcut:${reaction}:${Math.floor(now.getTime() / 60000)}`;
}

async function fetchLatestEpisodeId(feedUrl) {
  if (!feedUrl) throw new Error("feed_url_missing");
  const response = await fetch(feedUrl, {
    headers: { accept: "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8" },
    cf: { cacheTtl: 300, cacheEverything: true },
  });
  if (!response.ok) throw new Error("feed_unavailable");
  const episodeId = extractLatestEpisodeId(await response.text());
  if (!episodeId) throw new Error("episode_not_found");
  return episodeId;
}

async function resolveEpisode(db, reaction, feedUrl) {
  if (reaction !== "tried") {
    return {
      episodeId: await fetchLatestEpisodeId(feedUrl),
      linkedReactionId: null,
    };
  }

  const previous = await db
    .prepare(
      "SELECT id, episode_id FROM reactions WHERE reaction = 'new' ORDER BY occurred_at DESC, received_at DESC LIMIT 1",
    )
    .first();
  if (!previous) return null;
  return {
    episodeId: previous.episode_id,
    linkedReactionId: previous.id,
  };
}

async function readJsonBody(request) {
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > MAX_BODY_BYTES) throw new Error("body_too_large");
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) {
    throw new Error("body_too_large");
  }
  return JSON.parse(text);
}

async function createReaction(request, env, options = {}) {
  const idempotencyKey =
    options.idempotencyKey || request.headers.get("x-idempotency-key");
  if (!validateIdempotencyKey(idempotencyKey)) {
    return json({ ok: false, error: "invalid_idempotency_key" }, 400);
  }

  let payload;
  if (options.reaction) {
    payload = { reaction: options.reaction };
  } else {
    try {
      payload = await readJsonBody(request);
    } catch (error) {
      const code = error instanceof Error ? error.message : "invalid_json";
      return json(
        { ok: false, error: code === "body_too_large" ? code : "invalid_json" },
        code === "body_too_large" ? 413 : 400,
      );
    }
  }

  const validated = validateReactionPayload(payload);
  if (!validated.ok) return json({ ok: false, error: validated.error }, 400);

  const existing = await env.AI_RADIO_FEEDBACK_DB
    .prepare(
      "SELECT episode_id, reaction, occurred_at FROM reactions WHERE idempotency_key = ? LIMIT 1",
    )
    .bind(idempotencyKey)
    .first();
  if (existing) {
    if (existing.reaction !== validated.reaction) {
      return json({ ok: false, error: "idempotency_conflict" }, 409);
    }
    return json({
      ok: true,
      duplicate: true,
      episode_id: existing.episode_id,
      reaction: existing.reaction,
      occurred_at: existing.occurred_at,
      message: REACTION_MESSAGES[existing.reaction],
    });
  }

  let resolved;
  try {
    resolved = await resolveEpisode(
      env.AI_RADIO_FEEDBACK_DB,
      validated.reaction,
      env.PODCAST_FEED_URL,
    );
  } catch {
    return json({ ok: false, error: "episode_resolution_unavailable" }, 503);
  }
  if (!resolved) {
    return json(
      {
        ok: false,
        error: "no_recent_new_reaction",
        message: "対応する初耳の記録がありません",
      },
      409,
    );
  }

  const id = crypto.randomUUID();
  const receivedAt = new Date().toISOString();
  const insertResult = await env.AI_RADIO_FEEDBACK_DB
    .prepare(
      "INSERT OR IGNORE INTO reactions (id, idempotency_key, episode_id, reaction, occurred_at, received_at, source, linked_reaction_id) VALUES (?, ?, ?, ?, ?, ?, 'apple_shortcuts', ?)",
    )
    .bind(
      id,
      idempotencyKey,
      resolved.episodeId,
      validated.reaction,
      validated.occurredAt,
      receivedAt,
      resolved.linkedReactionId,
    )
    .run();

  if ((insertResult.meta?.changes ?? 1) === 0) {
    const raced = await env.AI_RADIO_FEEDBACK_DB
      .prepare(
        "SELECT episode_id, reaction, occurred_at FROM reactions WHERE idempotency_key = ? LIMIT 1",
      )
      .bind(idempotencyKey)
      .first();
    if (!raced || raced.reaction !== validated.reaction) {
      return json({ ok: false, error: "idempotency_conflict" }, 409);
    }
    return json({
      ok: true,
      duplicate: true,
      episode_id: raced.episode_id,
      reaction: raced.reaction,
      occurred_at: raced.occurred_at,
      message: REACTION_MESSAGES[raced.reaction],
    });
  }

  return json(
    {
      ok: true,
      duplicate: false,
      episode_id: resolved.episodeId,
      reaction: validated.reaction,
      occurred_at: validated.occurredAt,
      message: REACTION_MESSAGES[validated.reaction],
    },
    201,
  );
}

async function shortcutResponse(response) {
  const body = await response.json();
  const message = body.message || body.error || "記録できませんでした";
  return plain(message, response.status);
}

async function listRecentReactions(request, env) {
  const url = new URL(request.url);
  const requestedLimit = Number(url.searchParams.get("limit") || 20);
  const limit = Number.isInteger(requestedLimit)
    ? Math.min(Math.max(requestedLimit, 1), 50)
    : 20;
  const result = await env.AI_RADIO_FEEDBACK_DB
    .prepare(
      "SELECT episode_id, reaction, occurred_at FROM reactions ORDER BY occurred_at DESC, received_at DESC LIMIT ?",
    )
    .bind(limit)
    .all();
  return json({ ok: true, reactions: result.results || [] });
}

export async function dispatchPodcastWorkflow(env, options = {}) {
  const token = env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    console.error("GITHUB_DISPATCH_TOKEN is not configured");
    return { ok: false, error: "token_missing" };
  }

  const repo = env.GITHUB_REPO || "hachimarua/ai-podcast";
  const workflow = env.GITHUB_WORKFLOW_FILE || "podcast.yml";
  const ref = options.ref || "main";
  const inputs = options.inputs || {};

  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
  const fetchImpl = options.fetch || fetch;

  try {
    const response = await fetchImpl(url, {
      method: "POST",
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${token}`,
        "user-agent": "ai-radio-feedback-worker",
        "x-github-api-version": "2022-11-28",
      },
      body: JSON.stringify({
        ref,
        inputs,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(
        `GitHub workflow dispatch failed (${response.status}): ${errorText}`,
      );
      return { ok: false, status: response.status, error: errorText };
    }

    console.log(`Successfully dispatched ${workflow} on ${repo} (${ref})`);
    return { ok: true, status: response.status };
  } catch (error) {
    const message = error instanceof Error ? error.message : "network_error";
    console.error(`GitHub workflow dispatch network error: ${message}`);
    return { ok: false, error: message };
  }
}

export default {
  async scheduled(event, env, ctx) {
    console.log(
      `Cron triggered: ${event.cron || "17 19 * * *"} at ${new Date().toISOString()}`,
    );
    const result = await dispatchPodcastWorkflow(env);
    if (!result.ok) {
      console.error("Cron podcast dispatch failed:", result);
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "ai-radio-feedback" });
    }

    if (!isAuthorized(request, env.FEEDBACK_TOKEN)) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }

    try {
      const shortcutMatch = url.pathname.match(
        /^\/v1\/reactions\/(new|known|tried)$/,
      );
      if (request.method === "POST" && shortcutMatch) {
        const reaction = shortcutMatch[1];
        const response = await createReaction(request, env, {
          reaction,
          idempotencyKey: shortcutIdempotencyKey(reaction),
        });
        return await shortcutResponse(response);
      }
      if (request.method === "POST" && url.pathname === "/v1/reactions") {
        return await createReaction(request, env);
      }
      if (request.method === "GET" && url.pathname === "/v1/reactions/recent") {
        return await listRecentReactions(request, env);
      }
      return json({ ok: false, error: "not_found" }, 404);
    } catch {
      console.error("ai_radio_feedback_request_failed");
      return json({ ok: false, error: "internal_error" }, 500);
    }
  },
};
