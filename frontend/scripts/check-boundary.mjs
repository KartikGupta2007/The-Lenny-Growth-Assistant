#!/usr/bin/env node
/**
 * Enforces the frontend's one architectural rule:
 *
 *   The frontend talks to the FastAPI backend and to nothing else.
 *
 * No database, no model provider, no third-party service, no CDN. The backend
 * owns every credential and every downstream call. That rule is easy to state
 * and easy to break by accident -- one `fetch` to a vendor endpoint, one
 * `VITE_API_KEY` that ships the secret to every browser -- so it is checked
 * here rather than trusted.
 *
 * Zero dependencies, so it runs anywhere `node` does. Wired into `npm run
 * lint` and `npm run build`, meaning a violation cannot reach a bundle.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, 'src');

/** The only module allowed to open a network connection. */
const API_CLIENT = 'src/api/client.ts';
/** The only module allowed to hold a URL literal or read configuration. */
const CONSTANTS = 'src/constants.ts';

/**
 * Anything that can open a connection the API client does not control.
 * `new Worker` and `importScripts` are included because a worker can fetch.
 */
const NETWORK_PRIMITIVES = [
  { pattern: /\bfetch\s*\(/, name: 'fetch()' },
  { pattern: /\bXMLHttpRequest\b/, name: 'XMLHttpRequest' },
  { pattern: /\bWebSocket\b/, name: 'WebSocket' },
  { pattern: /\bEventSource\b/, name: 'EventSource' },
  { pattern: /\bsendBeacon\b/, name: 'navigator.sendBeacon' },
  { pattern: /\bnew\s+Worker\b/, name: 'new Worker' },
  { pattern: /\bimportScripts\b/, name: 'importScripts' },
];

/**
 * Packages that only make sense if the frontend is talking to a service
 * directly. Presence in package.json is the violation -- an unused dependency
 * is still an invitation.
 */
const FORBIDDEN_DEPENDENCIES = [
  // Databases
  'pg', 'pg-promise', 'postgres', 'mysql', 'mysql2', 'mongodb', 'mongoose',
  'redis', 'ioredis', 'sqlite3', 'better-sqlite3',
  // ORMs / query builders -- these imply a direct connection
  'knex', 'prisma', '@prisma/client', 'drizzle-orm', 'typeorm', 'sequelize',
  // Model providers
  'openai', '@anthropic-ai/sdk', '@anthropic-ai/claude-agent-sdk', 'anthropic',
  '@google/generative-ai', '@google/genai', 'cohere-ai', 'ollama',
  'replicate', '@mistralai/mistralai',
  // Agent frameworks
  'langchain', 'llamaindex', 'ai',
  // Backends-as-a-service
  '@supabase/supabase-js', 'firebase', 'firebase-admin', '@aws-sdk/client-s3',
  'aws-sdk',
];

/**
 * HTTP clients. Not a boundary violation on their own, but they bypass the
 * single client that owns timeouts, the error envelope and typed failures.
 */
const FORBIDDEN_HTTP_CLIENTS = ['axios', 'ky', 'got', 'superagent', 'request'];

/** Env var name fragments that would put a secret in a public bundle. */
const SECRET_NAME_PATTERN =
  /(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|DSN|DATABASE|CONNECTION_STRING)/i;

const violations = [];

function fail(file, line, message) {
  violations.push({ file, line, message });
}

/**
 * Blank out comments so a URL in documentation does not trip the checks,
 * while leaving string literals intact -- a URL inside a string is exactly
 * what we are looking for.
 *
 * This is a character scanner rather than a regex because a regex cannot tell
 * the `//` in `https://` from the start of a line comment. Getting that wrong
 * silently swallows the rest of the line, which would hide real violations.
 * Comment characters become spaces so reported line numbers stay accurate.
 */
function stripComments(source) {
  const out = source.split('');
  let i = 0;
  let quote = null;

  const blank = (from, to) => {
    for (let k = from; k < to; k += 1) {
      if (out[k] !== '\n') out[k] = ' ';
    }
  };

  while (i < source.length) {
    const char = source[i];
    const next = source[i + 1];

    if (quote) {
      if (char === '\\') {
        i += 2;
        continue;
      }
      if (char === quote) quote = null;
      i += 1;
      continue;
    }

    if (char === "'" || char === '"' || char === '`') {
      quote = char;
      i += 1;
      continue;
    }

    if (char === '/' && next === '/') {
      let end = source.indexOf('\n', i);
      if (end === -1) end = source.length;
      blank(i, end);
      i = end;
      continue;
    }

    if (char === '/' && next === '*') {
      let end = source.indexOf('*/', i + 2);
      end = end === -1 ? source.length : end + 2;
      blank(i, end);
      i = end;
      continue;
    }

    i += 1;
  }

  return out.join('');
}

function walk(dir) {
  const entries = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      entries.push(...walk(full));
    } else if (/\.(ts|tsx|js|jsx|mjs)$/.test(name)) {
      entries.push(full);
    }
  }
  return entries;
}

function lineOf(source, index) {
  return source.slice(0, index).split('\n').length;
}

// ---------------------------------------------------------------------------
// 1. Network primitives may appear only in the API client.
// ---------------------------------------------------------------------------

for (const path of walk(SRC)) {
  const rel = relative(ROOT, path).split('\\').join('/');
  const code = stripComments(readFileSync(path, 'utf8'));

  for (const { pattern, name } of NETWORK_PRIMITIVES) {
    const match = pattern.exec(code);
    if (!match) continue;
    if (rel === API_CLIENT) continue;
    fail(
      rel,
      lineOf(code, match.index),
      `${name} outside ${API_CLIENT}. Every request must go through request() ` +
        `so it inherits the base URL, timeout and error envelope.`,
    );
  }

  // -------------------------------------------------------------------------
  // 2. Absolute URLs may appear only in constants.ts.
  // -------------------------------------------------------------------------

  const urlPattern = /https?:\/\/[^\s'"`)]+/g;
  let urlMatch;
  while ((urlMatch = urlPattern.exec(code)) !== null) {
    if (rel === CONSTANTS) continue;
    fail(
      rel,
      lineOf(code, urlMatch.index),
      `Absolute URL ${urlMatch[0]} outside ${CONSTANTS}. The frontend has one ` +
        `remote host: the backend.`,
    );
  }

  // -------------------------------------------------------------------------
  // 3. Configuration is read in one place, and never names a secret.
  // -------------------------------------------------------------------------

  const envPattern = /import\.meta\.env\.(\w+)/g;
  let envMatch;
  while ((envMatch = envPattern.exec(code)) !== null) {
    const varName = envMatch[1];
    const line = lineOf(code, envMatch.index);

    if (rel !== CONSTANTS) {
      fail(
        rel,
        line,
        `import.meta.env read outside ${CONSTANTS}. Configuration is resolved ` +
          `once, so there is one place to audit.`,
      );
    }
    if (SECRET_NAME_PATTERN.test(varName)) {
      fail(
        rel,
        line,
        `${varName} looks like a credential. Every VITE_ variable is compiled ` +
          `into the public bundle; secrets belong to the backend only.`,
      );
    }
  }

  if (/\bprocess\.env\b/.test(code)) {
    fail(rel, lineOf(code, code.indexOf('process.env')), 'process.env is not available in the browser bundle.');
  }
}

// ---------------------------------------------------------------------------
// 4. No dependency that implies talking to a service directly.
// ---------------------------------------------------------------------------

const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
const installed = {
  ...(pkg.dependencies ?? {}),
  ...(pkg.devDependencies ?? {}),
};

for (const name of Object.keys(installed)) {
  if (FORBIDDEN_DEPENDENCIES.includes(name)) {
    fail(
      'package.json',
      0,
      `Dependency "${name}" implies the frontend talks to a service directly. ` +
        `That call belongs in the backend.`,
    );
  }
  if (FORBIDDEN_HTTP_CLIENTS.includes(name)) {
    fail(
      'package.json',
      0,
      `Dependency "${name}" bypasses ${API_CLIENT}, which owns timeouts and ` +
        `the error envelope. Use request() instead.`,
    );
  }
}

// ---------------------------------------------------------------------------
// 5. No secret-shaped variable in the frontend env example.
// ---------------------------------------------------------------------------

try {
  const envExample = readFileSync(join(ROOT, '.env.example'), 'utf8');
  envExample.split('\n').forEach((raw, index) => {
    const line = raw.trim();
    if (!line || line.startsWith('#')) return;
    const [name] = line.split('=');
    if (SECRET_NAME_PATTERN.test(name)) {
      fail(
        '.env.example',
        index + 1,
        `${name} names a credential. VITE_ variables ship to the browser.`,
      );
    }
  });
} catch {
  // No .env.example is not this check's concern.
}

// ---------------------------------------------------------------------------
// 6. No external asset in the HTML shell (no CDN, no remote font).
// ---------------------------------------------------------------------------

const html = readFileSync(join(ROOT, 'index.html'), 'utf8');
const htmlUrl = /(?:src|href)\s*=\s*["']https?:\/\/[^"']+/.exec(html);
if (htmlUrl) {
  fail(
    'index.html',
    lineOf(html, htmlUrl.index),
    'External asset in the HTML shell. Everything is bundled and self-hosted.',
  );
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

if (violations.length > 0) {
  console.error('\n  Frontend boundary violations\n');
  for (const { file, line, message } of violations) {
    console.error(`  ${file}${line ? `:${line}` : ''}\n    ${message}\n`);
  }
  console.error(
    `  ${violations.length} violation(s). The frontend must talk only to the ` +
      `FastAPI backend.\n`,
  );
  process.exit(1);
}

console.log('boundary: ok — frontend talks only to the backend');
