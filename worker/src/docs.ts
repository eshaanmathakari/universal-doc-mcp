/** Fetch README/long-description content from registries or GitHub. */

import type { Env, PackageInfo } from "./types.js";

const README_TRUNCATE = 3000;
const FETCH_TIMEOUT_MS = 10_000;

function ua(env: Env): string {
  return `scoutdocs-mcp-worker/${env.SCOUTDOCS_VERSION} (+https://github.com/eshaanmathakari/scoutdocs-mcp)`;
}

export async function fetchPyPIDescription(name: string, env: Env): Promise<string | null> {
  const resp = await safeFetch(
    `https://pypi.org/pypi/${encodeURIComponent(name)}/json`,
    env,
  );
  if (!resp) return null;
  const data = (await resp.json()) as { info?: { description?: string } };
  const desc = data.info?.description ?? "";
  if (!desc) return null;
  return desc.length > README_TRUNCATE
    ? desc.slice(0, README_TRUNCATE) + "\n\n... [truncated]"
    : desc;
}

export async function fetchNpmReadme(name: string, env: Env): Promise<string | null> {
  const resp = await safeFetch(`https://registry.npmjs.org/${encodeURIComponent(name)}`, env);
  if (!resp) return null;
  const data = (await resp.json()) as { readme?: string };
  const readme = data.readme ?? "";
  if (!readme || readme === "ERROR: No README data found!") return null;
  return readme.length > README_TRUNCATE
    ? readme.slice(0, README_TRUNCATE) + "\n\n... [truncated]"
    : readme;
}

export async function fetchGitHubReadme(repoUrl: string | null, env: Env): Promise<string | null> {
  if (!repoUrl) return null;
  const match = /github\.com\/([^/]+\/[^/]+)/.exec(repoUrl);
  if (!match) return null;
  const repo = match[1].replace(/\/$/, "");
  const resp = await safeFetch(`https://api.github.com/repos/${repo}/readme`, env, {
    headers: {
      Accept: "application/vnd.github.raw",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (!resp) return null;
  const text = await resp.text();
  return text.length > README_TRUNCATE
    ? text.slice(0, README_TRUNCATE) + "\n\n... [truncated — see full docs]"
    : text;
}

export async function fetchReadmeFor(info: PackageInfo, env: Env): Promise<string | null> {
  if (info.ecosystem === "python") {
    const text = await fetchPyPIDescription(info.name, env);
    if (text) return text;
  } else if (info.ecosystem === "javascript") {
    const text = await fetchNpmReadme(info.name, env);
    if (text) return text;
  }
  return await fetchGitHubReadme(info.repository, env);
}

async function safeFetch(url: string, env: Env, init?: RequestInit): Promise<Response | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const resp = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { "User-Agent": ua(env), ...(init?.headers || {}) },
    });
    if (!resp.ok) return null;
    return resp;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
