// Server-only Anthropic Messages API caller.
// Reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL from process.env at call time.

export const ANTHROPIC_MODELS = [
  "claude-opus-4-7",
  "claude-sonnet-4-6",
  "claude-haiku-4-5",
] as const;

export const DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6";

export type AnthropicUsage = {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
};

export type AnthropicResult = {
  text: string;
  model: string;
  usage: AnthropicUsage;
  stop_reason?: string;
};

export async function callAnthropic(opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
}): Promise<AnthropicResult> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("Brak ANTHROPIC_API_KEY w sekretach Lovable Cloud.");
  }
  const baseUrl = (process.env.ANTHROPIC_BASE_URL ?? "https://api.anthropic.com").replace(/\/+$/, "");
  const model = opts.model || process.env.ANTHROPIC_MODEL || DEFAULT_ANTHROPIC_MODEL;

  const res = await fetch(`${baseUrl}/v1/messages`, {
    method: "POST",
    headers: {
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model,
      max_tokens: opts.maxTokens ?? 8192,
      system: opts.system,
      messages: [{ role: "user", content: opts.userPrompt }],
    }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Anthropic HTTP ${res.status}: ${body.slice(0, 500)}`);
  }
  const data: {
    content?: Array<{ type: string; text?: string }>;
    model?: string;
    stop_reason?: string;
    usage?: AnthropicUsage;
  } = await res.json();
  const chunks = (data.content ?? [])
    .filter((c) => c.type === "text" && c.text)
    .map((c) => c.text as string);
  if (chunks.length === 0) throw new Error("Anthropic response has no text content");
  return {
    text: chunks.join(""),
    model: data.model ?? model,
    usage: data.usage ?? { input_tokens: 0, output_tokens: 0 },
    stop_reason: data.stop_reason,
  };
}

export function parseAnalysisJson(raw: string): unknown {
  let s = raw.trim();
  if (s.includes("```")) {
    const parts = s.split("```");
    if (parts.length >= 2) {
      s = parts[1];
      if (s.startsWith("json")) s = s.slice(4);
    }
  }
  s = s.trim().replace(/```$/, "").trim();
  return JSON.parse(s);
}
