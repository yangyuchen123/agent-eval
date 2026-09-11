// Blade LLM3 provider for pi (openai-completions gateway).
// Model configured via LLM_* env (LLM_API_KEY / LLM_API_BASE_URL / LLM_MODEL).
export default function (pi) {
  pi.registerProvider("blade", {
    name: "Blade LLM3",
    baseUrl: process.env.LLM_API_BASE_URL || "https://llm3.bladeai.com.cn/v1",
    apiKey: "$LLM_API_KEY",
    api: "openai-completions",
    models: [
      { id: process.env.LLM_MODEL || "gpt-5.6-luna", name: "GPT-5.6 Luna (Blade)", reasoning: true, input: ["text"], cost: { input: 0, output: 0 }, contextWindow: 200000, maxTokens: 32000 },
    ],
  });
}
