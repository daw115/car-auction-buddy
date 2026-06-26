// Server-only Google Vertex AI (Gemini Enterprise) caller.
// Uses a Service Account JSON to mint a short-lived OAuth2 access token
// via signed JWT (RS256, Web Crypto — works in Cloudflare Workers runtime).
// Compatible return type with callAnthropic / callGemini.

import type { AnthropicResult, AnthropicUsage } from "./anthropic.server";
import { withRetry, checkRetryableResponse, AITimeoutError } from "./ai-retry.server";

export const DEFAULT_VERTEX_MODEL = "gemini-2.5-pro";

type ServiceAccount = {
  client_email: string;
  private_key: string;
  token_uri?: string;
};

let cachedToken: { value: string; expiresAt: number } | null = null;

function loadServiceAccount(): ServiceAccount {
  const raw = process.env.GEMINI_ENTERPRISE_SA_JSON;
  if (!raw) throw new Error("Brak GEMINI_ENTERPRISE_SA_JSON w sekretach.");
  try {
    const sa = JSON.parse(raw) as ServiceAccount;
    if (!sa.client_email || !sa.private_key) {
      throw new Error("SA JSON musi zawierać client_email i private_key.");
    }
    return sa;
  } catch (err) {
    throw new Error(`GEMINI_ENTERPRISE_SA_JSON niepoprawny JSON: ${(err as Error).message}`);
  }
}

function b64urlEncode(data: ArrayBuffer | Uint8Array | string): string {
  let bytes: Uint8Array;
  if (typeof data === "string") bytes = new TextEncoder().encode(data);
  else if (data instanceof Uint8Array) bytes = data;
  else bytes = new Uint8Array(data);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function pemToArrayBuffer(pem: string): ArrayBuffer {
  const body = pem
    .replace(/-----BEGIN [^-]+-----/g, "")
    .replace(/-----END [^-]+-----/g, "")
    .replace(/\s+/g, "");
  const bin = atob(body);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

async function signJwt(sa: ServiceAccount, scope: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const payload = {
    iss: sa.client_email,
    scope,
    aud: sa.token_uri || "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  };
  const unsigned = `${b64urlEncode(JSON.stringify(header))}.${b64urlEncode(JSON.stringify(payload))}`;

  const keyData = pemToArrayBuffer(sa.private_key);
  const key = await crypto.subtle.importKey(
    "pkcs8",
    keyData,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(unsigned),
  );
  return `${unsigned}.${b64urlEncode(sig)}`;
}

async function getAccessToken(): Promise<string> {
  if (cachedToken && cachedToken.expiresAt > Date.now() + 60_000) {
    return cachedToken.value;
  }
  const sa = loadServiceAccount();
  const jwt = await signJwt(sa, "https://www.googleapis.com/auth/cloud-platform");

  const res = await fetch(sa.token_uri || "https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }).toString(),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Google OAuth HTTP ${res.status}: ${body.slice(0, 500)}`);
  }
  const data = await res.json() as { access_token: string; expires_in: number };
  cachedToken = {
    value: data.access_token,
    expiresAt: Date.now() + data.expires_in * 1000,
  };
  return data.access_token;
}

export async function callGeminiEnterprise(opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
}): Promise<AnthropicResult> {
  const projectId = process.env.GEMINI_ENTERPRISE_PROJECT_ID;
  const location = process.env.GEMINI_ENTERPRISE_LOCATION || "us-central1";
  if (!projectId) throw new Error("Brak GEMINI_ENTERPRISE_PROJECT_ID w sekretach.");

  const model = opts.model || process.env.GEMINI_ENTERPRISE_MODEL || DEFAULT_VERTEX_MODEL;

  return withRetry(
    () => singleVertexCall(projectId, location, model, opts),
    { provider: "GeminiEnterprise", maxRetries: 3, initialDelayMs: 2_000 },
  );
}

async function singleVertexCall(
  projectId: string,
  location: string,
  model: string,
  opts: { system: string; userPrompt: string; maxTokens?: number },
): Promise<AnthropicResult> {
  const TIMEOUT_MS = 120_000;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);

  const token = await getAccessToken();
  const host = location === "global"
    ? "aiplatform.googleapis.com"
    : `${location}-aiplatform.googleapis.com`;
  const url = `https://${host}/v1/projects/${projectId}/locations/${location}/publishers/google/models/${model}:generateContent`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: opts.system }] },
        contents: [{ role: "user", parts: [{ text: opts.userPrompt }] }],
        generationConfig: {
          maxOutputTokens: opts.maxTokens ?? 4096,
          temperature: 0.7,
        },
      }),
      signal: ctrl.signal,
    });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") {
      throw new AITimeoutError(
        `GeminiEnterprise: Timeout po ${Math.round(TIMEOUT_MS / 1000)}s.`,
        "GeminiEnterprise",
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  checkRetryableResponse(res, "GeminiEnterprise");

  if (res.status === 401 || res.status === 403) {
    cachedToken = null; // invalidate on auth error
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Vertex AI HTTP ${res.status}: ${body.slice(0, 500)}`);
  }

  const data = await res.json() as {
    candidates?: Array<{
      content?: { parts?: Array<{ text?: string }> };
      finishReason?: string;
    }>;
    usageMetadata?: {
      promptTokenCount?: number;
      candidatesTokenCount?: number;
      totalTokenCount?: number;
    };
    modelVersion?: string;
  };

  const parts = data.candidates?.[0]?.content?.parts ?? [];
  const text = parts.map((p) => p.text ?? "").join("");
  if (!text) throw new Error("GeminiEnterprise: Odpowiedź nie zawiera tekstu");

  const usage: AnthropicUsage = {
    input_tokens: data.usageMetadata?.promptTokenCount ?? 0,
    output_tokens: data.usageMetadata?.candidatesTokenCount ?? 0,
  };

  return {
    text,
    model: data.modelVersion ?? model,
    usage,
    stop_reason: data.candidates?.[0]?.finishReason,
  };
}
