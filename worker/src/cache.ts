/** KV-backed cache shared across the Worker tools. */

import type { Env } from "./types.js";

export async function cacheGet<T>(env: Env, key: string): Promise<T | null> {
  return await env.CACHE.get<T>(key, "json");
}

export async function cachePut<T>(env: Env, key: string, value: T): Promise<void> {
  const ttl = Math.max(60, Number(env.CACHE_TTL_SECONDS) || 86400);
  await env.CACHE.put(key, JSON.stringify(value), { expirationTtl: ttl });
}
