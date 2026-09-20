# Native workflow capability inspection — `adapters/claude_workflow`

**Inspection date:** 2026-09-20 (UTC probe at `2026-09-20T13:28:48Z`)
**Inspected by:** OB2-10 workflow lane, offline inspection only.
**Paid model calls made during this inspection: none.** No prompt was ever sent: only
`claude --version`, `claude --help`, `claude plugin --help`, `claude agents --help`,
reads of `~/.claude/settings.json`, directory listings, and a fetch of the public
documentation page. `claude -p` was never invoked.

Every line below is labelled **VERIFIED** (observed on this machine or stated by the
current official documentation, with the observation quoted) or **UNVERIFIED** (could
not be established without executing a paid run). Nothing here is a guess.

---

## 1. Exact versions and environment

| Item | Value | Status |
|---|---|---|
| `claude` binary | `/Users/shelbyklein/.local/bin/claude` | VERIFIED (`which claude`) |
| Claude Code version | `2.1.278 (Claude Code)` | VERIFIED (`claude --version`) |
| Python | `3.11.5` | VERIFIED (`python3 -V`) |
| Host CPUs | `16` | VERIFIED (`sysctl -n hw.ncpu`) |
| Platform | macOS (Darwin 25.1.0), arm64 user install | VERIFIED |
| Documentation source | `https://code.claude.com/docs/en/workflows`, "Orchestrate subagents at scale with dynamic workflows" | VERIFIED (reachable, fetched 2026-09-20) |
| Bundled authoring skill | `/workflow-authoring` present and loadable in this configuration | VERIFIED (skill loaded; docs state it "requires Claude Code v2.1.248 or later" and is "unavailable" when workflows are disabled) |

## 2. Are native workflows available in *this machine's* configuration?

**Status: VERIFIED AVAILABLE, in-session only.**

Evidence, all observed locally:

- `claude --version` → `2.1.278`, above every version floor the documentation names
  (`2.1.202` size guideline, `2.1.203` ultracode, `2.1.216` symlink check,
  `2.1.248` `/workflow-authoring`, `2.1.269` concurrency env var, `2.1.271` usage-limit pause).
- `~/.claude/settings.json` does **not** contain `disableWorkflows`. Keys present:
  `$schema, agentPushNotifEnabled, autoMode, effortLevel, enabledPlugins,
  extraKnownMarketplaces, feedbackSurveyState, hooks, inputNeededNotifEnabled, model,
  modelSettings, permissions, skipDangerousModePermissionPrompt, skipWorkflowUsageWarning,
  statusLine, todoFeatureEnabled, tui, voiceEnabled`.
- `skipWorkflowUsageWarning: true` is set, which is a workflow-specific setting — this
  configuration has already interacted with the workflow runtime at least once.
- No managed/policy settings file: `/Library/Application Support/ClaudeCode/` does not exist.
- No `CLAUDE_CODE_DISABLE_WORKFLOWS` and no `CLAUDE_CODE_WORKFLOW_*` variables in the
  environment (checked with `env | grep -i workflow`).
- The `/workflow-authoring` bundled skill loaded successfully. Per the documentation,
  "When workflows are disabled, the bundled workflow commands and the `/workflow-authoring`
  skill are unavailable." Its availability is therefore positive evidence that workflows
  are enabled here.
- `~/.claude/workflows/` does **not** exist and neither does any project
  `.claude/workflows/`: **no saved workflow commands exist on this machine.** This adapter
  ships the first versioned script.

**Critical shape finding — VERIFIED.** There is **no `claude workflow` CLI subcommand.**
The full `claude --help` command list is: `agents, attach, auth, auto-mode, doctor,
gateway, import, install, logs, mcp, plugin, project, respawn, rm, setup-token, stop,
ultrareview, update`. Workflows are activated *inside a session* — by the in-session
`Workflow` tool, by `/workflows`, by a saved `/<name>` command, or by the bundled
`/deep-research` — never by a standalone shell command. Consequences for this bench:

- The bench cannot drive a native workflow by shelling out to a dedicated runner binary.
  Any live execution must be a configured `claude` session invocation that the operator
  records explicitly (`LiveExecutor(run_command=[...])`).
- Because the entry point is a model session, **any live execution is a paid call.**
  The offline `FakeExecutor` path is therefore the only path this lane exercises.

**Plan entitlement: UNVERIFIED.** The documentation says dynamic workflows are
"available on all paid plans, with Anthropic API access, and on Amazon Bedrock, Google
Cloud's Agent Platform, and Microsoft Foundry. On Pro, turn them on from the Dynamic
workflows row in `/config`." This account's plan tier was not probed (doing so is not
needed for offline work and risks touching auth state). Treat entitlement as unverified
until the operator records it.

## 3. Headless activation

**Status: DOCUMENTED-SUPPORTED, LOCALLY UNVERIFIED.**

- The documentation states workflows are available "in the CLI, the Desktop app, the IDE
  extensions, non-interactive mode with `claude -p`, and the Agent SDK". So headless
  activation exists in principle. **VERIFIED as documentation; UNVERIFIED on this machine**
  (verifying it requires running a prompt, which is a paid call and is out of scope).
- **The `ultracode` keyword is *not* a headless opt-in.** The documentation is explicit:
  the keyword is an opt-in "only in a prompt you type yourself", and it "doesn't start a
  workflow when it reaches the session another way", listing first "a prompt passed with
  `-p`". A headless launch therefore cannot rely on the keyword. (Before `v2.1.210` it
  could; this machine is on `2.1.278`, past that change.) VERIFIED as documentation.
- In `claude -p` and the Agent SDK, no approval prompt is shown; the `Workflow` tool call
  goes through ordinary permission evaluation. To let it start, the documentation lists a
  `Workflow` or `Workflow(<name>)` allow rule, auto permission mode, bypass-permissions
  mode, a `PreToolUse` hook returning `allow`, or a host `--permission-prompt-tool`.
  **This machine's `permissions.allow` contains no `Workflow` entry** (VERIFIED: grep of
  `~/.claude/settings.json` found zero allow rules mentioning `Workflow`). A headless
  launch as configured today would therefore depend on `autoMode` classification or an
  explicit rule the operator has not yet added.
- Whether Claude actually *chooses* to emit a `Workflow` tool call for a given headless
  prompt is model behaviour, not a switch: **UNVERIFIED and not reliably controllable.**
  A saved workflow invoked by name (`/<name>`) is the more deterministic route, and no
  saved workflows exist here yet.

## 4. Does a workflow opt-in change reasoning effort or substitute models?

### 4a. Effort — **CONFOUND PRESENT. Flagged.**

Two distinct opt-ins must not be conflated:

| Opt-in | Effort behaviour | Status |
|---|---|---|
| `ultracode` **keyword** typed in a prompt | Documentation: "The keyword only chooses how Claude structures the work". No effort change is documented. | VERIFIED as documentation; not independently measured. |
| `/effort ultracode` or `claude --effort ultracode` or the `ultracode` setting | Documentation: "Ultracode is a Claude Code setting that **combines `xhigh` reasoning effort with automatic workflow orchestration**." | VERIFIED as documentation. |

> **CONFOUND.** `/effort ultracode` raises reasoning effort to `xhigh` *and* turns on
> automatic workflow orchestration in the same switch. A comparison whose graph arm is
> launched with `/effort ultracode` and whose solo arm is launched at a lower effort is
> **not** evidence that orchestration improved quality — effort and orchestration moved
> together. Any such run must be recorded as confounded. The bench must pin the effort
> level identically across arms and opt in to the workflow by the keyword or by invoking a
> saved workflow by name, never by changing the effort level. This machine's session
> default is `effortLevel: "medium"` (VERIFIED from `~/.claude/settings.json`).

Per-agent effort is also settable inside the script (`agent(prompt, {effort})`), which
means a script can silently raise effort for some nodes. The shipped
`graph-candidate.v1.js` deliberately sets **no** `effort` and **no** `model` on any
`agent()` call, so every node inherits the session's resolved values and the arm stays
comparable. VERIFIED by reading the shipped script.

### 4b. Model substitution — **POSSIBLE, NOT CONFIGURED HERE.**

- Documentation: workflow agents pick a model "in the same order it uses for subagents";
  a model the script names for a stage counts as the per-invocation model; "When nothing
  else assigns one, the agent runs on your session's model."
- Documentation: when an organization's `availableModels` allowlist blocks a model the
  script requests, "that agent runs on a substituted model instead", and the `/workflows`
  progress view "shows a warning naming both the requested and substituted models".
- **On this machine `availableModels` is absent from `~/.claude/settings.json` and there is
  no managed settings file** (VERIFIED), so no allowlist-driven substitution is configured.
  `model` is `"opus[1m]"` and `modelSettings` is present (VERIFIED key presence only).
- Whether the *effective* model of each node matches the requested one in a real run:
  **UNVERIFIED.** It can only be established from a run's progress view or trace. The
  adapter therefore logs `model.requested` and leaves `model.effective = null` with
  `verified: false` on every event it emits offline, per contract §3.

## 5. Is previously successful work replayed after failure or resume?

**Status: DOCUMENTED, LOCALLY UNVERIFIED (verifying requires a paid run).**

Documented native behaviour, quoted from the workflows page and the `/workflow-authoring`
reference:

- A run is "Resumable in the same session". Relaunch is
  `Workflow({scriptPath, resumeFromRunId})`; "the longest unchanged prefix of `agent()`
  calls returns cached results instantly; the first edited/new call and everything after
  it runs live."
- Per-agent replay rules: **Completed** → "returns its saved result", but "The first agent
  whose prompt differs from the previous run … runs again, and so does every agent after
  it, even ones that completed." **Still running when you stopped** → "starts over."
  **Failed** → "runs again, and so does every agent that started after it, even ones that
  completed."
- Consequence the documentation states outright: "If a script starts A, B, C, and D in
  that order and B fails, relaunching returns A from cache and runs B, C, and D again."
  So the native runtime's replay is **prefix-based and position-based, not
  content-addressed**: completed work *after* a failure is re-executed and re-billed.
- `Date.now()`, `Math.random()` and argless `new Date()` throw inside a script precisely so
  that a relaunch reproduces the same `agent()` calls.
- Saved results live under the session's directory in `~/.claude/projects/`. If they cannot
  be found, relaunch fails with a `nothing to resume` error rather than silently starting over.
- **There are no run artifacts under `~/.claude/projects/` matching a workflow run on this
  machine** (VERIFIED: search for workflow script/transcript directories returned nothing),
  so native replay could not be observed here, only read.

> **Implication for the bench, and why this adapter does not rely on native replay.**
> Native replay re-runs completed agents that started after the failure point, and its
> identity check is "did the prompt differ", not an artifact-hash check. That is not
> strong enough for an experiment that must not double-count usage or duplicate an
> externally visible effect. The bench-controlled `run()` in this adapter therefore keeps
> its **own** restart state and reuses a completed node **only** after an explicit
> `sourceRevision` **and** artifact-hash identity check, and guards side effects with an
> append-only, keyed effects log. Both replay behaviours — native and bench — are logged;
> the bench one is what the tests exercise.

## 6. Runtime limits the native runtime applies (documentation, VERIFIED as such)

Recorded because they bound any future live arm; none of them is enforced by this adapter's
offline path, and the adapter never claims them as its own enforcement.

| Native constraint | Value |
|---|---|
| Concurrent agents | up to 16 by default, fewer with fewer CPUs; `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` 1–256 (needs ≥ v2.1.269). The authoring reference states the cap as `min(16, available CPUs - 2)`. This host has 16 CPUs. |
| Items per `parallel()`/`pipeline()` call | 4096, longer lists are an explicit error |
| Agents per run | 1000 |
| Prompt-cache stagger | up to 5000 ms, `CLAUDE_CODE_WORKFLOW_PREFIX_STAGGER_MS` |
| Mid-run user input | not possible |
| Filesystem/shell from the script itself | none; only agents touch the disk |
| `import()` in a script | fails before the run starts |
| Size guideline | `workflowSizeGuideline`, default `medium` (`small` on Pro ≥ v2.1.271). **Absent from this machine's settings** (VERIFIED), so the default is in force. |
| Token/cost ceiling | **none.** The "Large workflow" warning at >25 agents or >1.5M projected tokens is explicitly "advisory: it doesn't pause or limit the run". |

> Therefore a token or cost limit on a native workflow arm is **`unavailable`**, never
> `enforced`. `methods/graph.json` labels them accordingly.

## 7. Summary table

| Question | Answer | Status |
|---|---|---|
| Native workflows available in this configuration? | Yes, in-session only; no CLI subcommand | VERIFIED |
| Saved workflows present? | None; this adapter ships the first versioned script | VERIFIED |
| Headless (`claude -p`) activation supported? | Documented yes; needs an explicit `Workflow` allow rule (absent here); keyword opt-in does **not** work headless | Documentation VERIFIED, local behaviour UNVERIFIED |
| Workflow opt-in raises reasoning effort? | `/effort ultracode` does (`xhigh` + orchestration) — **CONFOUND**. Bare keyword documented as structure-only | VERIFIED as documentation |
| Model substitution possible? | Yes via `availableModels` allowlist; none configured here; per-node `model` overrides exist and the shipped script sets none | VERIFIED locally that none is configured; effective model per run UNVERIFIED |
| Previously successful work replayed after failure? | Yes, prefix/position-based: completed agents after the failure point re-run. Content identity is not checked | Documentation VERIFIED, local behaviour UNVERIFIED |
| Any provider-enforced token/cost cap? | No; warning only | VERIFIED as documentation |
| Anything measured by executing a workflow here? | **No. Zero paid calls.** All adapter evidence in this lane is synthetic/offline | VERIFIED |

## 8. What the operator must record before a live arm

`methods/graph.json` stays `configured: false` until all of these are filled in, and this
file should be re-dated when they are:

1. Plan/entitlement that makes dynamic workflows available, and the surface used.
2. The exact `run_command` given to `LiveExecutor` (the configured `claude` invocation).
3. The permission route that lets the `Workflow` call start headlessly (allow rule, hook,
   or auto mode) — none exists today.
4. Session model and effort level, pinned identically to the comparison arms, and an
   explicit statement that `/effort ultracode` was **not** used (or, if it was, the run is
   marked confounded).
5. Observed effective model per node from the run's progress view or trace, which is what
   turns `model.effective` from `null` into a verified value.
