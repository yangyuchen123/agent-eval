/**
 * Drive pi (the coding agent) with DeepSeek V4 Flash on one SWE-bench task.
 *
 * Usage:
 *   node run_pi_agent.mjs <workdir> <problem_file>
 *
 * The agent works in <workdir> (a repo checked out at base_commit), reads
 * the problem from <problem_file>, and edits files. The caller collects the
 * diff afterwards — this script only runs the agent.
 *
 * Requirements:
 *   - @earendil-works/pi-coding-agent importable from NODE_PATH or cwd
 *   - ~/.pi/agent/auth.json with a `deepseek` API key (already configured)
 *   - the `deepseek-v4-flash` model in ~/.pi/agent/models-store.json
 */
import { readFileSync } from "node:fs";
import { createAgentSession, ModelRuntime } from "@earendil-works/pi-coding-agent";

const [workdir, problemFile] = process.argv.slice(2);
if (!workdir || !problemFile) {
  console.error("usage: node run_pi_agent.mjs <workdir> <problem_file>");
  process.exit(2);
}

const problem = readFileSync(problemFile, "utf-8");

const modelRuntime = await ModelRuntime.create();
const model = modelRuntime.getModel("deepseek", "deepseek-v4-flash");
if (!model) {
  console.error("deepseek-v4-flash not found in model registry");
  process.exit(2);
}
console.log(`[pi] model: ${model.provider}/${model.id}  cwd: ${workdir}`);

const { session } = await createAgentSession({
  cwd: workdir,
  model,
  modelRuntime,
  thinkingLevel: "medium",
});

const prompt = [
  "You are working in a git repository checked out at the exact commit",
  "where the following issue was reported. Read the relevant code, find",
  "the bug, and fix it by editing source files.",
  "",
  "Rules:",
  "1. Do NOT modify any test files.",
  "2. Make the smallest change that fixes the issue.",
  "3. You may run the existing test suite to verify, but do not rely on",
  "   network access for anything beyond what the repo already provides.",
  "",
  "===== ISSUE =====",
  problem,
  "",
  "When you are done, summarize the change you made.",
].join("\n");

try {
  session.subscribe((event) => {
    if (event.type === "message_update" &&
        event.assistantMessageEvent?.type === "text_delta") {
      process.stdout.write(event.assistantMessageEvent.delta);
    }
  });
  await session.prompt(prompt);
  console.log("\n[pi] session finished");
} finally {
  session.dispose();
}
