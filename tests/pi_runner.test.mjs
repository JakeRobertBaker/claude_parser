import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  buildTools,
  createTelemetry,
  thinkingLevelSummary,
} from "../src/claude_parser/adapters/llm/pi_runner.mjs";

const SPECS = [
  {
    name: "read_batch",
    description: "Read the batch.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "submit_clean",
    description: "Submit clean text.",
    input_schema: {
      type: "object",
      properties: {
        cleaned_text: { type: "string" },
        cutoff_kind: { type: "string" },
      },
      required: ["cleaned_text", "cutoff_kind"],
    },
  },
  {
    name: "commit_batch",
    description: "Commit the batch.",
    input_schema: {
      type: "object",
      properties: {},
    },
  },
];

function textPayload(result) {
  return JSON.parse(result.content[0].text);
}

test("batch tools enforce ordering, a single read, and inferred cutoff", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const calls = [];
  globalThis.fetch = async (_url, options) => {
    const request = JSON.parse(options.body);
    calls.push(request);
    const result = request.name === "read_batch"
      ? { raw_content: "raw" }
      : request.name === "submit_clean"
        ? { valid: true }
        : { status: "ok" };
    return new Response(JSON.stringify(result));
  };

  const workflow = { read: false, validSubmission: false, committed: false };
  const tools = buildTools(SPECS, "http://127.0.0.1/tools", workflow);
  const byName = Object.fromEntries(tools.map((tool) => [tool.name, tool]));

  const prematureSubmit = await byName.submit_clean.execute(
    "call-1", { cleaned_text: "clean" }
  );
  assert.match(textPayload(prematureSubmit).error, /read_batch/);
  assert.equal(calls.length, 0);

  await byName.read_batch.execute("call-2", {});
  const duplicateRead = await byName.read_batch.execute("call-3", {});
  assert.match(textPayload(duplicateRead).error, /already called/);
  assert.equal(calls.filter((call) => call.name === "read_batch").length, 1);

  await byName.submit_clean.execute("call-4", {
    cleaned_text: "clean",
    cutoff_kind: "clean_boundary",
  });
  await byName.commit_batch.execute("call-5", {});

  assert.equal(workflow.committed, true);
  assert.deepEqual(calls.at(-1), { name: "commit_batch", arguments: {} });
  assert.deepEqual(byName.commit_batch.parameters, {
    type: "object",
    properties: {},
    additionalProperties: false,
  });
});

test("safe telemetry redacts content while debug telemetry retains raw deltas", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "pi-runner-test-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const eventPath = join(directory, "events.jsonl");
  const streamPath = join(directory, "stream.jsonl");
  let nowMs = 0;
  const telemetry = await createTelemetry({
    eventPath,
    streamPath,
    heartbeatMs: 5_000,
    now: () => nowMs,
  });

  nowMs = 6_000;
  telemetry.record({
    type: "message_update",
    assistantMessageEvent: { type: "thinking_delta", delta: "sensitive thought" },
  });
  telemetry.record({
    type: "tool_execution_start",
    toolName: "submit_clean",
    toolCallId: "call-1",
    args: { cleaned_text: "sensitive markdown" },
  });
  await telemetry.close();

  const safe = await readFile(eventPath, "utf8");
  const raw = await readFile(streamPath, "utf8");
  assert.match(safe, /stream_heartbeat/);
  assert.match(safe, /submit_clean/);
  assert.doesNotMatch(safe, /sensitive/);
  assert.match(raw, /sensitive thought/);
  assert.match(raw, /sensitive markdown/);
});

test("default telemetry does not create a raw stream log", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "pi-runner-test-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const eventPath = join(directory, "events.jsonl");
  const telemetry = await createTelemetry({ eventPath });
  telemetry.record({
    type: "message_update",
    assistantMessageEvent: { type: "text_delta", delta: "not copied" },
  });
  await telemetry.close();

  assert.equal(await readFile(eventPath, "utf8"), "");
});

test("thinking summary records Pi clamping separately from the request", () => {
  assert.deepEqual(thinkingLevelSummary("medium", "high"), {
    requestedThinkingLevel: "medium",
    effectiveThinkingLevel: "high",
    thinkingLevelClamped: true,
    clampWarning: "Pi adjusted thinking level medium -> high",
  });
});
