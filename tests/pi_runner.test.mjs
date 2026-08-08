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
    name: "inspect_tree",
    description: "Inspect a tree branch.",
    input_schema: {
      type: "object",
      properties: { node_id: { type: "string" } },
      required: ["node_id"],
    },
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
    name: "adjust_depths",
    description: "Adjust pending depths.",
    input_schema: {
      type: "object",
      properties: { edits: { type: "array" } },
      required: ["edits"],
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

test("batch tools enforce ordering and retain safe outcome history", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const calls = [];
  globalThis.fetch = async (_url, options) => {
    const request = JSON.parse(options.body);
    calls.push(request);
    const result = request.name === "read_batch"
      ? {
          committable_raw: {
            scope: "COMMITTABLE SOURCE",
            content: "sensitive raw markdown",
            line_count: 10,
            token_count: 100,
          },
          read_only_context: {
            scope: "READ-ONLY CONTEXT",
            next_raw_content: "sensitive next context",
            next_raw_line_count: 2,
            next_raw_token_count: 20,
            prior_clean_content: "sensitive prior context",
            prior_continuation: null,
          },
          known_ids: ["private_id"],
        }
      : request.name === "submit_clean"
        ? options.body.includes("invalid clean")
          ? {
              valid: false,
              errors: ["Alignment failed."],
              warnings: ["Cleaned text is short."],
              inferred_cutoff_batch_line: 4,
            }
          : {
              valid: true,
              commit_ready: false,
              errors: [],
              warnings: [],
              tree_advisories: [{ code: "proof_should_be_statement_sibling" }],
            }
        : request.name === "adjust_depths"
          ? { valid: true, commit_ready: true, errors: [], warnings: [], applied_edits: request.arguments.edits }
          : request.name === "inspect_tree"
            ? { ancestors: [], children: [], total_children: 0, next_child_offset: null }
            : { status: "ok" };
    return new Response(JSON.stringify(result));
  };

  const workflow = {
    read: false,
    validSubmission: false,
    commitReady: false,
    committed: false,
  };
  const observed = [];
  let nowMs = 0;
  const tools = buildTools(SPECS, "http://127.0.0.1/tools", workflow, {
    now: () => nowMs += 5,
    onToolResult: (summary) => observed.push(summary),
  });
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
  await byName.inspect_tree.execute("call-inspect", { node_id: "book" });

  const invalidSubmit = await byName.submit_clean.execute("call-invalid", {
    cleaned_text: "invalid clean",
    cutoff_kind: "clean_boundary",
  });
  assert.equal(textPayload(invalidSubmit).valid, false);

  await byName.submit_clean.execute("call-4", {
    cleaned_text: "clean",
    cutoff_kind: "clean_boundary",
  });
  const blockedCommit = await byName.commit_batch.execute("call-blocked", {});
  assert.match(textPayload(blockedCommit).error, /commit_ready is false/);
  await byName.adjust_depths.execute("call-adjust", {
    edits: [{ node_id: "section_d", depth: 2 }],
  });
  await byName.commit_batch.execute("call-5", {});

  assert.equal(workflow.committed, true);
  assert.deepEqual(workflow.toolHistory, observed);
  assert.deepEqual(
    observed.map(({ toolName, outcome }) => [toolName, outcome]),
    [
      ["submit_clean", "application_error"],
      ["read_batch", "ok"],
      ["read_batch", "application_error"],
      ["inspect_tree", "ok"],
      ["submit_clean", "invalid"],
      ["submit_clean", "ok"],
      ["commit_batch", "application_error"],
      ["adjust_depths", "ok"],
      ["commit_batch", "ok"],
    ],
  );
  assert.equal(observed[4].errorCount, 1);
  assert.equal(observed[4].warningCount, 1);
  assert.equal(observed[5].treeAdvisoryCount, 1);
  assert.equal(observed[7].appliedDepthEditCount, 1);
  assert.equal(observed[1].rawTokenCount, 100);
  assert.doesNotMatch(JSON.stringify(observed), /sensitive|private_id/);
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
