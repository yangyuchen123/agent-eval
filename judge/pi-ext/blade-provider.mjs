// LLM providers for the pi judge.
// - siliconflow (judge default): Qwen/Qwen3-8B via SiliconFlow gateway
// - blade: local LLM3 gateway (LLM_* env)
export default function (pi) {
  pi.registerProvider("siliconflow", {
    name: "SiliconFlow",
    baseUrl: process.env.SILICONFLOW_BASE_URL || "https://api.siliconflow.cn/v1",
    apiKey: "$SILICONFLOW_API_KEY",
    api: "openai-completions",
    models: [
      { id: process.env.JUDGE_MODEL || "Qwen/Qwen3-8B", name: "Qwen3 8B (SiliconFlow)", reasoning: false, input: ["text"], cost: { input: 0, output: 0 }, contextWindow: 128000, maxTokens: 4096 },
    ],
  });
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
