import { randomUUID } from "node:crypto";
import { appendFile, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import {
  createAgentSession,
  createExtensionRuntime,
  defineTool,
  ModelRuntime,
  resolveCliModel,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

const SYSTEM_PROMPT = `You are a single-purpose markdown cleaning task agent.
Use the provided batch tools to read, clean, validate, and commit exactly one batch.
Do not merely describe work. Finish by successfully calling commit_batch.
You have no filesystem, shell, coding, skill, or extension capabilities.`;

const EMPTY_PARAMETERS = {
  type: "object",
  properties: {},
  additionalProperties: false,
};

const CUTOFF_FIELDS = [
  "valid",
  "inferred_cutoff_batch_line",
  "match_confidence",
  "batch_line_count",
  "rollback_lines",
  "next_raw_context_violation",
  "cutoff_kind",
  "continuation_node_id",
];

export function resourceLoader() {
  return {
    getExtensions: () => ({
      extensions: [],
      errors: [],
      runtime: createExtensionRuntime(),
    }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => SYSTEM_PROMPT,
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [],
    getAppendSystemPromptSources: () => [],
    extendResources: () => {},
    reload: async () => {},
  };
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(30_000),
  });
  const body = await response.text();
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    throw new Error(`Batch tool server returned non-JSON (${response.status}): ${body.slice(0, 500)}`);
  }
  if (!response.ok) {
    throw new Error(payload.error ?? `Batch tool request failed with HTTP ${response.status}`);
  }
  return payload;
}

function cutoffSummary(result) {
  return Object.fromEntries(
    CUTOFF_FIELDS
      .filter((field) => Object.hasOwn(result, field))
      .map((field) => [field, result[field]]),
  );
}

function boundedMessages(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((message) => typeof message === "string")
    .slice(0, 20)
    .map((message) => message.slice(0, 500));
}

function toolResultSummary(toolName, toolCallId, result, durationMs) {
  const outcome = result?.status === "error"
    ? "application_error"
    : toolName === "submit_clean" && result?.valid !== true
      ? "invalid"
      : "ok";
  const summary = {
    toolName,
    toolCallId,
    durationMs,
    outcome,
  };

  if (toolName === "read_batch" && outcome === "ok") {
    return {
      ...summary,
      batchLineCount: result.batch_line_count,
      rawTokenCount: result.raw_token_count,
      nextRawContextLineCount: result.next_raw_context_line_count,
      nextRawContextTokenCount: result.next_raw_context_token_count,
      priorCleanContextCharacters: typeof result.prior_clean_context === "string"
        ? result.prior_clean_context.length
        : 0,
      knownIdCount: Array.isArray(result.known_ids) ? result.known_ids.length : 0,
      hasPriorContinuation: result.prior_continuation != null,
    };
  }
  if (toolName === "submit_clean") {
    const errors = boundedMessages(result?.errors);
    const warnings = boundedMessages(result?.warnings);
    return {
      ...summary,
      ...cutoffSummary(result ?? {}),
      errorCount: errors.length,
      warningCount: warnings.length,
      errors,
      warnings,
    };
  }
  return {
    ...summary,
    status: result?.status,
    error: typeof result?.error === "string" ? result.error.slice(0, 500) : null,
  };
}

export function buildTools(specs, endpoint, workflow, options = {}) {
  const expected = new Set(["read_batch", "submit_clean", "commit_batch"]);
  const available = new Set(specs.map((spec) => spec.name));
  for (const name of expected) {
    if (!available.has(name)) throw new Error(`Batch tool server is missing ${name}`);
  }
  const now = options.now ?? (() => Date.now());
  const onToolResult = options.onToolResult ?? (() => {});
  workflow.toolHistory ??= [];

  return specs
    .filter((spec) => expected.has(spec.name))
    .map((spec) => {
      let parameters = spec.input_schema;
      if (spec.name === "commit_batch") {
        // Pi may only accept the service-inferred cutoff. It cannot override it.
        parameters = EMPTY_PARAMETERS;
      }

      return defineTool({
        name: spec.name,
        label: spec.name,
        description: spec.description,
        parameters,
        executionMode: "sequential",
        execute: async (toolCallId, params) => {
          const startedAt = now();
          const finish = (result) => {
            const summary = toolResultSummary(
              spec.name,
              toolCallId,
              result,
              Math.max(0, now() - startedAt),
            );
            workflow.toolHistory.push(summary);
            onToolResult(summary);
            return {
              content: [{ type: "text", text: JSON.stringify(result) }],
              details: {},
            };
          };
          if (spec.name === "read_batch" && workflow.read) {
            return finish({
              status: "error",
              error: "read_batch was already called. Use the batch content already present in this conversation.",
            });
          }
          if (spec.name !== "read_batch" && !workflow.read) {
            return finish({
              status: "error",
              error: "Call read_batch before using other tools.",
            });
          }
          if (spec.name === "commit_batch" && !workflow.validSubmission) {
            return finish({
              status: "error",
              error: "Call submit_clean until valid=true before commit_batch.",
            });
          }

          const args = spec.name === "commit_batch" ? {} : params;
          const result = await fetchJson(endpoint, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ name: spec.name, arguments: args }),
          });

          if (spec.name === "read_batch") workflow.read = true;
          if (spec.name === "submit_clean") {
            workflow.validSubmission = result.valid === true;
            workflow.submission = cutoffSummary(result);
          }
          if (spec.name === "commit_batch") workflow.committed = result.status === "ok";

          return finish(result);
        },
      });
    });
}

function usageFromMessage(message) {
  if (!message || typeof message !== "object" || !message.usage) return undefined;
  return message.usage;
}

function safeProjection(event, state, nowMs, heartbeatMs) {
  const base = { timestamp: new Date(nowMs).toISOString() };

  if (event.type === "message_update") {
    const update = event.assistantMessageEvent ?? {};
    let phase;
    if (update.type === "text_delta") phase = "text";
    else if (update.type === "thinking_delta") phase = "thinking";
    else if (update.type === "toolcall_delta") phase = "tool_call";
    if (!phase) return null;

    state.streamedCharacters[phase] += typeof update.delta === "string" ? update.delta.length : 0;
    if (nowMs - state.lastHeartbeatMs < heartbeatMs) return null;
    state.lastHeartbeatMs = nowMs;
    return {
      ...base,
      type: "stream_heartbeat",
      phase,
      streamedCharacters: { ...state.streamedCharacters },
    };
  }

  switch (event.type) {
    case "agent_start":
    case "agent_settled":
    case "turn_start":
    case "compaction_start":
    case "summarization_retry_attempt_start":
    case "summarization_retry_finished":
      return { ...base, type: event.type, reason: event.reason, source: event.source };
    case "agent_end":
      return {
        ...base,
        type: event.type,
        messageCount: Array.isArray(event.messages) ? event.messages.length : 0,
        willRetry: event.willRetry,
      };
    case "turn_end":
      return {
        ...base,
        type: event.type,
        usage: usageFromMessage(event.message),
        toolResultCount: Array.isArray(event.toolResults) ? event.toolResults.length : 0,
      };
    case "message_start":
      return { ...base, type: event.type, role: event.message?.role };
    case "message_end":
      return {
        ...base,
        type: event.type,
        role: event.message?.role,
        usage: usageFromMessage(event.message),
      };
    case "tool_execution_start":
      return {
        ...base,
        type: event.type,
        toolName: event.toolName,
        toolCallId: event.toolCallId,
      };
    case "tool_execution_end":
      return {
        ...base,
        type: event.type,
        toolName: event.toolName,
        toolCallId: event.toolCallId,
        isError: event.isError,
      };
    case "auto_retry_start":
    case "summarization_retry_scheduled":
      return {
        ...base,
        type: event.type,
        attempt: event.attempt,
        maxAttempts: event.maxAttempts,
        delayMs: event.delayMs,
        errorMessage: event.errorMessage,
      };
    case "auto_retry_end":
      return {
        ...base,
        type: event.type,
        attempt: event.attempt,
        success: event.success,
        finalError: event.finalError,
      };
    case "compaction_end":
      return {
        ...base,
        type: event.type,
        reason: event.reason,
        aborted: event.aborted,
        willRetry: event.willRetry,
        errorMessage: event.errorMessage,
      };
    case "queue_update":
      return {
        ...base,
        type: event.type,
        steeringCount: event.steering?.length ?? 0,
        followUpCount: event.followUp?.length ?? 0,
      };
    case "thinking_level_changed":
      return { ...base, type: event.type, level: event.level };
    default:
      return null;
  }
}

function serialize(value) {
  return `${JSON.stringify(value, (_key, item) => typeof item === "bigint" ? item.toString() : item)}\n`;
}

export async function createTelemetry({
  eventPath,
  streamPath,
  heartbeatMs = 5_000,
  now = () => Date.now(),
}) {
  await writeFile(eventPath, "", "utf8");
  if (streamPath) await writeFile(streamPath, "", "utf8");

  let writes = Promise.resolve();
  const state = {
    lastHeartbeatMs: now(),
    streamedCharacters: { text: 0, thinking: 0, tool_call: 0 },
  };
  const append = (path, value) => {
    writes = writes.then(() => appendFile(path, serialize(value), "utf8"));
  };

  return {
    record(event) {
      if (streamPath) {
        append(streamPath, { timestamp: new Date(now()).toISOString(), event });
      }
      const projected = safeProjection(event, state, now(), heartbeatMs);
      if (projected) append(eventPath, projected);
    },
    safe(event) {
      append(eventPath, { timestamp: new Date(now()).toISOString(), ...event });
    },
    async close() {
      await writes;
    },
  };
}

export function thinkingLevelSummary(requestedThinkingLevel, effectiveThinkingLevel) {
  const normalizedRequested = requestedThinkingLevel ?? null;
  const thinkingLevelClamped = normalizedRequested !== null
    && normalizedRequested !== effectiveThinkingLevel;
  return {
    requestedThinkingLevel: normalizedRequested,
    effectiveThinkingLevel,
    thinkingLevelClamped,
    clampWarning: thinkingLevelClamped
      ? `Pi adjusted thinking level ${normalizedRequested} -> ${effectiveThinkingLevel}`
      : null,
  };
}

async function writeJsonAtomic(path, value) {
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporary, path);
}

function validateConfig(config) {
  if (!config.toolEndpoint) throw new Error("Pi runner requires toolEndpoint");
  if (!config.logRoot) throw new Error("Pi runner requires logRoot");
  if (!/^[A-Za-z0-9_.-]+$/.test(config.invocationId ?? "")) {
    throw new Error("Pi runner requires a safe invocationId");
  }
}

async function main() {
  const configPath = process.argv[2];
  if (!configPath) throw new Error("Usage: node pi_runner.mjs <config.json>");

  const config = JSON.parse(await readFile(configPath, "utf8"));
  validateConfig(config);

  const chunkDir = join(config.logRoot, config.invocationId);
  const attemptId = `${new Date().toISOString().replaceAll(":", "-")}_${process.pid}_${randomUUID().slice(0, 8)}`;
  const attemptDir = join(chunkDir, attemptId);
  await mkdir(attemptDir, { recursive: true });

  const sessionManager = SessionManager.create(config.cwd, attemptDir);
  const eventPath = join(attemptDir, "events.jsonl");
  const streamPath = config.debugStreamLog ? join(attemptDir, "stream.jsonl") : undefined;
  const telemetry = await createTelemetry({ eventPath, streamPath });
  const artifacts = {
    attemptDirectory: attemptDir,
    nativeSession: sessionManager.getSessionFile(),
    safeEvents: eventPath,
    debugStream: streamPath ?? null,
    currentManifest: join(chunkDir, "current.json"),
  };
  const manifest = {
    invocationId: config.invocationId,
    attemptId,
    status: "running",
    startedAt: new Date().toISOString(),
    requestedModel: config.model ?? null,
    debugStreamLog: Boolean(config.debugStreamLog),
    artifacts,
  };
  await writeJsonAtomic(artifacts.currentManifest, manifest);
  await writeJsonAtomic(join(attemptDir, "manifest.json"), manifest);

  let session;
  let unsubscribe;
  let settingsManager;
  let finalReport;
  try {
    const modelRuntime = await ModelRuntime.create();
    settingsManager = SettingsManager.create(config.cwd);
    const resolved = config.model
      ? resolveCliModel({ cliModel: config.model, modelRuntime })
      : { model: undefined, thinkingLevel: undefined, warning: undefined, error: undefined };
    if (resolved.error) throw new Error(resolved.error);

    const specs = await fetchJson(config.toolEndpoint);
    const workflow = {
      read: false,
      validSubmission: false,
      committed: false,
      submission: null,
      toolHistory: [],
    };
    const customTools = buildTools(specs, config.toolEndpoint, workflow, {
      onToolResult: (summary) => telemetry.safe({
        type: "tool_result_summary",
        ...summary,
      }),
    });
    const toolNames = customTools.map((tool) => tool.name);

    const created = await createAgentSession({
      cwd: config.cwd,
      model: resolved.model,
      thinkingLevel: resolved.thinkingLevel,
      modelRuntime,
      resourceLoader: resourceLoader(),
      tools: toolNames,
      customTools,
      sessionManager,
      settingsManager,
    });
    session = created.session;
    const {
      requestedThinkingLevel,
      effectiveThinkingLevel,
      thinkingLevelClamped,
      clampWarning,
    } = thinkingLevelSummary(resolved.thinkingLevel, session.thinkingLevel);
    const warnings = [resolved.warning, clampWarning].filter(Boolean);

    telemetry.safe({
      type: "session_created",
      model: session.model ? `${session.model.provider}/${session.model.id}` : null,
      requestedThinkingLevel,
      effectiveThinkingLevel,
      thinkingLevelClamped,
      warnings,
    });
    unsubscribe = session.subscribe((event) => telemetry.record(event));

    await session.prompt(config.prompt, { expandPromptTemplates: false });

    // Give a model that stopped early two bounded opportunities to finish the
    // protocol. The Python service remains the authority on actual success.
    for (let attempt = 0; attempt < 2 && !workflow.committed; attempt += 1) {
      const reminder = workflow.validSubmission
        ? "The cleaned batch is valid but not committed. Call commit_batch now."
        : workflow.read
          ? "The batch is not committed. Complete submit_clean validation, then call commit_batch."
          : "You have not started the required workflow. Call read_batch and complete the batch now.";
      await session.prompt(reminder, { expandPromptTemplates: false });
    }

    finalReport = {
      success: workflow.committed,
      invocationId: config.invocationId,
      model: session.model ? `${session.model.provider}/${session.model.id}` : null,
      requestedThinkingLevel,
      effectiveThinkingLevel,
      thinkingLevelClamped,
      modelFallbackMessage: created.modelFallbackMessage,
      warnings,
      workflow,
      error: session.agent.state.errorMessage,
      stats: session.getSessionStats(),
      artifacts,
    };
    telemetry.safe({
      type: "run_end",
      success: workflow.committed,
      stats: finalReport.stats,
      error: finalReport.error,
    });

    const completedManifest = {
      ...manifest,
      status: workflow.committed ? "succeeded" : "failed",
      finishedAt: new Date().toISOString(),
      requestedThinkingLevel,
      effectiveThinkingLevel,
      thinkingLevelClamped,
    };
    await writeJsonAtomic(artifacts.currentManifest, completedManifest);
    await writeJsonAtomic(join(attemptDir, "manifest.json"), completedManifest);
    process.stdout.write(`${JSON.stringify(finalReport)}\n`);

    if (!workflow.committed) {
      throw new Error(session.agent.state.errorMessage ?? "Pi agent stopped without committing the batch.");
    }
  } catch (error) {
    telemetry.safe({
      type: "runner_error",
      error: error instanceof Error ? error.message : String(error),
    });
    const failedManifest = {
      ...manifest,
      status: "failed",
      finishedAt: new Date().toISOString(),
      error: error instanceof Error ? error.message : String(error),
    };
    await writeJsonAtomic(artifacts.currentManifest, failedManifest);
    await writeJsonAtomic(join(attemptDir, "manifest.json"), failedManifest);
    throw error;
  } finally {
    unsubscribe?.();
    session?.dispose();
    await settingsManager?.flush();
    await telemetry.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
