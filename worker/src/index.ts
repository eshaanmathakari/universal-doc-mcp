/** scoutdocs-mcp Cloudflare Worker entrypoint.
 *
 * Routes:
 *   GET  /            Liveness/health (returns server info as plain text)
 *   POST /mcp         JSON-RPC request → JSON-RPC response
 *   OPTIONS /mcp      CORS preflight
 *
 * Streamable HTTP at /mcp without sessions. Tools are stateless, so each POST
 * is a self-contained request/response. Notifications (no `id`) get HTTP 204.
 */

import { dispatchMcp, getToolByName } from "./mcp.js";
import type { JsonRpcRequest } from "./mcp.js";
import type { Env } from "./types.js";

const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Authorization",
  "Access-Control-Max-Age": "86400",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      ...CORS_HEADERS,
    },
  });
}

function clientKey(request: Request): string {
  return request.headers.get("cf-connecting-ip") ?? "unknown";
}

async function checkRateLimit(
  request: Request,
  env: Env,
  bucket: "general" | "search",
): Promise<boolean> {
  const limiter = bucket === "search" ? env.RATE_LIMIT_SEARCH : env.RATE_LIMIT_MCP;
  if (!limiter) return true; // not configured (e.g. local tests)
  try {
    const { success } = await limiter.limit({ key: clientKey(request) });
    return success;
  } catch {
    return true; // fail open if the limiter errors out
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (url.pathname === "/" && request.method === "GET") {
      return new Response(
        `scoutdocs-mcp ${env.SCOUTDOCS_VERSION}\nPOST JSON-RPC to /mcp\n`,
        { status: 200, headers: { "content-type": "text/plain", ...CORS_HEADERS } },
      );
    }

    if (url.pathname !== "/mcp") {
      return new Response("not found", { status: 404, headers: CORS_HEADERS });
    }

    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405, headers: CORS_HEADERS });
    }

    // Always charge the general bucket. Charge the search bucket too if the
    // request targets the search tool — keeps expensive tools rate-limited
    // separately without double-charging cheap calls.
    if (!(await checkRateLimit(request, env, "general"))) {
      return jsonResponse(
        { jsonrpc: "2.0", id: null, error: { code: -32029, message: "rate limit exceeded" } },
        429,
      );
    }

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return jsonResponse(
        { jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } },
        400,
      );
    }

    if (!isJsonRpcRequest(body)) {
      return jsonResponse(
        { jsonrpc: "2.0", id: null, error: { code: -32600, message: "invalid request" } },
        400,
      );
    }

    if (body.method === "tools/call") {
      const toolName = (body.params as { name?: string } | undefined)?.name;
      if (toolName) {
        const tool = getToolByName(toolName);
        if (tool?.rateLimitBucket === "search") {
          if (!(await checkRateLimit(request, env, "search"))) {
            return jsonResponse(
              {
                jsonrpc: "2.0",
                id: body.id ?? null,
                error: { code: -32029, message: "search rate limit exceeded" },
              },
              429,
            );
          }
        }
      }
    }

    const response = await dispatchMcp(body, env);
    if (response === null) {
      // Notification — JSON-RPC says no response body.
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }
    return jsonResponse(response, 200);
  },
} satisfies ExportedHandler<Env>;

function isJsonRpcRequest(value: unknown): value is JsonRpcRequest {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return v.jsonrpc === "2.0" && typeof v.method === "string";
}
