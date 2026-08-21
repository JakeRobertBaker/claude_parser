# Pi SDK adapter

## Decision

The Pi integration uses Pi's JavaScript SDK as the agent loop and OpenRouter/model
integration layer. It does not give Pi general coding tools. A fresh persistent Pi
session is created for every batch with exactly five custom tools:

1. `read_batch`
2. `inspect_tree`
3. `submit_clean`
4. `adjust_depths`
5. `commit_batch`

The existing Python `BatchToolsService` remains authoritative for payload assembly,
annotation and KaTeX validation, cutoff alignment, pending clean state,
proposed-tree construction, depth edits, persistence, and commit state. The Pi runner fetches tool specifications from a
localhost-only JSON transport and delegates every tool execution back to that
service.

## Why this shape

Pi's SDK provides the multi-turn tool loop, model normalization, provider retries,
session state, thinking-level handling, and the user's existing Pi authentication.
The Python application does not need to reimplement those policies.

The integration still has one Python-to-Node subprocess boundary because Pi's SDK
is JavaScript. Unlike the old CLI integration, standard input/output is not an
interactive control channel:

- Python writes a small invocation configuration to a temporary JSON file.
- Tool calls use a random-port localhost HTTP endpoint.
- The Node process writes one concise JSON report to stdout.
- Python's existing per-batch timeout owns the process deadline.

This keeps raw and cleaned Markdown out of command-line arguments and prevents
stream framing from affecting tool execution.

## Live and persistent logs

Every Pi attempt receives a unique directory below
`STATE/logs/pi/chunk_NNN/`. The runner writes `current.json` before creating the
agent so a running or failed attempt is easy to locate. By default each attempt
contains:

- Pi's native, incrementally persisted JSONL session with completed messages
  (sensitive: it contains source, cleaned text, tool results, and reasoning);
- `events.jsonl`, a live content-safe timeline of lifecycle, tool status,
  usage/cost, errors, sanitized application outcomes, and throttled streaming
  character counts; and
- `manifest.json`, which records status and artifact locations.

The safe event stream does not contain message text, thinking, tool arguments,
full tool results, or raw/clean Markdown. It does contain deliberately bounded
tool-outcome projections: status, counts, cutoff metrics, and sanitized validation
messages. Source-heading titles remain in the native tool result for agent review
but only their count enters the safe projection. `logs/chunk_NNN.json` remains the
concise application-facing report and links these detailed artifacts. It also
retains a `workflow.toolHistory` entry for every tool attempt. These summaries
distinguish transport completion from application outcomes such as a duplicate
read, invalid submission, or rejected commit.

For unusual debugging, `--pi-debug-stream-log` adds `stream.jsonl` with every raw
Pi stream event. This can contain the source Markdown, cleaned output, reasoning,
and partial tool calls; it is intentionally off by default and should be treated
as sensitive.

The report and safe session-start event record both the thinking level requested
by the model selector and the effective level after Pi applies the model's
supported levels. A clamp such as `medium -> high` is reported explicitly.

## Architectural status

The localhost bridge is an intentional migration seam, not necessarily the final
abstraction. JavaScript Pi tools cannot directly invoke a live Python service object;
some explicit inter-process boundary is required unless the agent loop or the batch
service changes language. This implementation uses HTTP rather than stdin/stdout for
that boundary.

After real-run evidence is available, reconsider whether to:

- keep this topology and split the MCP and JSON transports into separately named
  adapters;
- implement an in-process Python agent loop on the OpenRouter SDK; or
- move agent-facing orchestration into TypeScript.

The second option removes the process boundary but makes this project responsible
for tool-loop history, retry and stop policy, and provider-specific reasoning/tool
message behavior. The current design deliberately buys Pi's mature policies first.

## Capability restrictions

The runner supplies a custom resource loader with no extensions, skills, prompt
templates, themes, or `AGENTS.md` context. Its tool allowlist contains only the five
batch tools, so Pi's `read`, `write`, `edit`, `bash`, `grep`, `find`, and `ls` tools
are absent.

The runner adds workflow guards beyond the Python validation:

- tree inspection, submission, depth adjustment, and commit cannot run before `read_batch`.
- `read_batch` returns the large batch payload only once per agent session.
- `adjust_depths` operates only on a valid pending submission and can change only
  current-batch annotation hyphens.
- `commit_batch` cannot run until the latest proposal reports `commit_ready=true`
  and cannot override the service-inferred cutoff. A valid proposal remains
  uncommittable while required proof-placement advisories are unresolved.

If the model stops before committing, the runner gives it at most two targeted
follow-up turns. The parsing service still verifies that the batch was actually
submitted and that a committed source line exists.

## OpenRouter Python SDK alternative

The official Python SDK would remove Node and make tool callbacks fully in-process,
but it is a lean API client: this project would own the agent loop, tool-call message
history, retry/stop policy, provider quirks, and future reasoning compatibility.
That is a reasonable future adapter if the Node boundary proves costly. It is not
the first implementation because Pi already supplies those agent policies and is
the user's configured model runtime.

## Setup and use

Install JavaScript dependencies once from the repository root:

```bash
npm install
```

Run with an explicit Pi/OpenRouter model:

```bash
uv run python -m math_parser.cli \
  --raw path/to/raw.md \
  --state path/to/state \
  --llm-adapter pi-sdk \
  --task-model openrouter/anthropic/your-model
```

Pi model selectors may include a thinking suffix supported by Pi, such as `:high`.
If `--task-model` is omitted, Pi selects its configured default. Authentication is
resolved by Pi's `ModelRuntime` from its normal credential sources, including the
user's Pi auth store and `OPENROUTER_API_KEY`.

For an inexpensive smoke test, add `--max-sections 1` and use a new state directory.

## Batch boundary behavior

`--batch-tokens` defines the `committable_raw.content` work target. The planner
also supplies `read_only_context.next_raw_content` controlled by
`--next-raw-context-tokens` (default 2000). This context is read-only: it lets the
agent see that a definition, proof, list, or similar unit at the end of the batch
continues, then roll back before that unit. Both prompt instructions and submit
validation prevent following context from being committed early. A conservative
semantic guard also rejects a clean cutoff after a trailing
definition/theorem/proof/etc. heading when the following context visibly remains
under that heading.

Every `submit_clean` declares either `clean_boundary` or `continuation`. A
continuation must name the proposed tree's active leaf; this ID is validated,
saved in `state.json`, and returned as structured `prior_continuation` metadata in
the next batch. New continuations are permitted only for an oversized unit opened
at the start of a batch; a later unit crossing the boundary must be rolled back.
Prior clean prose is supplied as `read_only_context.prior_clean_content`, a whole-line
suffix bounded by `--prior-clean-context-tokens` (default 2000).

## Math and tree review

Every submission is parsed with KaTeX, regardless of the selected agent adapter.
Math inside code spans and fences is ignored. Doubled alphabetic escapes such as
`\\mathbf` are normalized to `\mathbf` and reported by location; unclosed math
delimiters and remaining KaTeX parse failures reject the submission.

`read_batch` nests source text beneath an explicitly labelled `committable_raw`
object and boundary context beneath a separately labelled `read_only_context`
object. `tree_context` provides the major generic-container outline, complete
active trace, and local sibling windows with explicit omission counts. An agent can
page through an older branch using `inspect_tree`. A valid `submit_clean` returns
every node created by that batch with its annotation depth and resolved parent.
The candidate remains in memory: `adjust_depths` can transactionally repair its
current-batch hierarchy. `commit_ready` becomes true only after blocking tree
advisories are resolved, and only `commit_batch` writes the reviewed clean file.
Aligned invalid submissions still return committable/raw/read-only tail diagnostics,
so the agent can remove only an offending preview-derived suffix. Tree review also
reports proofs nested beneath their statements and likely unrepresented generic
Markdown headings as structured advisories.

Proof-placement advisories are blocking: `valid=true` may accompany
`commit_ready=false`, and both the runner and Python service reject an early
commit. Source-heading advisories are nonblocking because a source heading may be
intentionally represented by another node; the prompt requires the agent to review
and justify them. Heading coverage cannot detect a structural transition that has
no Markdown heading, such as credits or licensing prose following a final exercise.
