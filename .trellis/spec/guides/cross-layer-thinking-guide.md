# Cross-Layer Thinking Guide

> **Purpose**: Think through data flow across layers before implementing.

---

## The Problem

**Most bugs happen at layer boundaries**, not within layers.

Common cross-layer bugs:

- API returns format A, frontend expects format B
- Database stores X, service transforms to Y, but loses data
- Multiple layers implement the same logic differently

---

## Before Implementing Cross-Layer Features

### Step 1: Map the Data Flow

Draw out how data moves:

```
Source → Transform → Store → Retrieve → Transform → Display
```

For each arrow, ask:

- What format is the data in?
- What could go wrong?
- Who is responsible for validation?
- For a successful external-provider response, which representations are valid (for example JSON,
  direct raster bytes, or an asynchronous task), and does the adapter dispatch by `Content-Type`
  before parsing?

### Step 2: Identify Boundaries

| Boundary              | Common Issues                     |
| --------------------- | --------------------------------- |
| API ↔ Service         | Type mismatches, missing fields   |
| Service ↔ Database    | Format conversions, null handling |
| Backend ↔ Frontend    | Serialization, date formats       |
| Component ↔ Component | Props shape changes               |

### Step 3: Define Contracts

For each boundary:

- What is the exact input format?
- What is the exact output format?
- What errors can occur?

---

## Common Cross-Layer Mistakes

### Mistake 1: Implicit Format Assumptions

**Bad**: Assuming date format without checking

**Good**: Explicit format conversion at boundaries

### Mistake 2: Scattered Validation

**Bad**: Validating the same thing in multiple layers

**Good**: Validate once at the entry point

### Mistake 3: Leaky Abstractions

**Bad**: Component knows about database schema

**Good**: Each layer only knows its neighbors

### Mistake 4: Treating One Provider Representation As The Business Result

An external provider can report success through several transport representations while the
business requirement is usually narrower: one validated, durable artifact that can continue the
workflow. A provider changing its preferred representation must not silently weaken validation or
strand downstream work when an already-approved deterministic fallback exists.

Before changing a provider response contract:

- [ ] Verify the provider's current primary representation from authoritative documentation
- [ ] Keep a closed compatibility set for already-supported valid representations
- [ ] Classify syntax/representation failure separately from URL, address, media, signature,
      dimension, identity, and other security/integrity failures
- [ ] Decide which exact failure classes may consume each retry/repair budget; never make every
      output-validation failure retryable
- [ ] Persist the retry cause and a replay-stable distinct idempotency fingerprint before another
      paid call
- [ ] Keep compensation inputs bound to the same durable business object (for example, only use
      brand assets already reserved for the same artifact)
- [ ] Test the proxy-positive/outcome-negative case: provider HTTP success plus unusable output,
      followed by one recovery and then deterministic fallback
- [ ] Prove fallback success reaches the real downstream eligibility query, while fallback failure
      creates neither a durable artifact nor a delivery job
- [ ] Keep raw response bodies, Base64, temporary URLs, prompts, credentials and private paths out
      of errors, logs, snapshots and APIs

**Real-world example**: An image gateway returned a non-empty `b64_json` value that failed strict
Base64 decoding. The adapter correctly rejected the bytes, but the material workflow classified
all image-output validation as terminal, so an accepted topic and copy produced no delivery job.
The fix requested the provider's documented URL representation, retained strict URL/Base64/raster
validation, allowed only the exact representation-syntax reason one durable recovery, and then used
the artifact's pre-reserved approved catalog image. Unsafe URL, signature, size and dimension
failures remained terminal.

### Mistake 5: Every Consumer Parses The Same Payload

**Bad**: A command reads JSONL events and casts fields inline:

```typescript
const thread = (ev as { thread?: string }).thread;
const labels = (ev as { labels?: string[] }).labels;
```

This looks local, but it means every consumer owns a private version of the
event contract. The next field change will update one command and miss another.

**Good**: Decode once at the event boundary, then export typed projections:

```typescript
if (!isThreadEvent(ev)) return false;
return ev.thread === filter.thread;
```

**Rule**: For append-only logs, JSON streams, RPC payloads, or config files,
create one owner for:

- event / payload type definitions
- type guards and normalization from `unknown`
- metadata projections used by UI commands
- reducers that replay state from the source of truth

Rendering code may format fields, but it must not redefine the payload contract.

### Mistake 6: Updating The Gate Owner But Not Its Runtime Consumers

A validated configuration can still fail at runtime when a downstream adapter, worker, or CLI
keeps an older copy of the enablement predicate. This is especially dangerous for default-off
production features: settings and Compose can render successfully while the long-lived process
starts, exits, and restarts forever.

When changing an environment, capability, or production-acknowledgement rule:

- [ ] Search for every comparison of the old environment/value, not only the settings validator
- [ ] Trace settings validation through the real process entrypoint to adapter construction
- [ ] Keep the settings model as the canonical cross-field owner; duplicate downstream checks may
      only add defense in depth and must express the same accepted states
- [ ] Add a contract test that constructs the real downstream adapter from the newly accepted
      settings, with provider transport replaced by a fake
- [ ] Exercise the production-shaped process or container for at least one bounded idle cycle; a
      successful Compose render or initial `running` state is not readiness

**Real-world example**: a WeChat draft worker gained a production acknowledgement and passed its
settings and Compose tests, but the settings-bound HTTP client still required
`APP_ENV=development`. The container reached `running`, then returned
`wechat_mp_config_disabled` and restarted every few seconds. Aligning the adapter predicate with
the canonical settings gate, adding a real production client-construction test, and requiring an
idle-cycle stability probe closed the gap.

---

## Checklist for Cross-Layer Features

Before implementation:

- [ ] Mapped the complete data flow
- [ ] Identified all layer boundaries
- [ ] Defined format at each boundary
- [ ] Decided where validation happens

After implementation:

- [ ] Tested with edge cases (null, empty, invalid)
- [ ] Verified error handling at each boundary
- [ ] Checked data survives round-trip
- [ ] Checked that consumers import shared decoders / projections instead of
      casting payload fields locally
- [ ] Checked that derived state points back to the source event identifier
      (`seq`, `id`, `version`) instead of inventing a second cursor

### Final Deliverable Projection Parity

When one governed fact appears in several generated files or UI projections, a passing unit test
does not prove that a named local delivery was built from the current code.

- [ ] Enumerate the canonical fields and every projection before editing (for example source URL,
      credit, rights and block placement across Markdown, JSON, manifest, API and UI)
- [ ] Assert projection parity from one typed source instead of checking each representation only
      for internal validity
- [ ] Build the named final directory only after the last renderer, semantic or auxiliary-projection
      change; never overwrite or silently reuse an earlier delivery
- [ ] Rebuild once in memory with the accepted browser sidecar and require the content identity,
      artifact identity and ZIP SHA-256 to match the named directory
- [ ] Repeat browser and format-specific validation against that exact final directory, not a
      staging predecessor

**Real-world example**: An official-account handoff passed backend, frontend and browser tests, but its first
named bundle predated the rule that removed generic emphasis text. A later bundle then exposed
source/credit/placement in JSON and UI while omitting them from Markdown. Current-code hash replay
plus cross-projection assertions caught both gaps and forced a fresh, non-overwriting final export.

## Choose The Business Fact, Not An Upstream Proxy

Cross-layer rules often have several plausible clocks: created, selected, generated, queued,
attempted, and delivered. Name the user-visible fact first, then trace the complete durable lineage
that proves it. Do not substitute the nearest upstream row merely because it is easier to query.

For any cooldown, deduplication, billing, or audience-frequency rule:

- define the authoritative terminal state and mode (for example, formal + delivered);
- join through the typed origin lineage instead of matching only a shared ID;
- filter authoritative rows before latest/earliest aggregation and de-duplicate fan-out;
- keep orthogonal history on its own clock (editorial selection can still drive theme diversity even
  when delivery drives audience repetition);
- version the semantic identity when changing the clock so stored runs replay under their original
  meaning;
- test the proxy-positive/outcome-negative case, every non-authoritative terminal state, duplicate
  lineage, and the exact time-window boundary in the real persistence engine.

**Real-world example**: a seven-day audience-repeat veto originally used topic selection history.
That treated selected-but-never-delivered content as something the audience had already seen. The
correct contract uses a formal terminal delivery through selection -> copy -> package -> delivery,
while selection history continues to own same-day exclusion and theme-repetition penalties.

---

## Cross-Platform Template Consistency

In Trellis, command templates (e.g., `record-session.md`) exist in **multiple platforms** with identical or near-identical content. This is a cross-layer boundary.

### Checklist: After Modifying Any Command Template

- [ ] Find all platforms with the same command: `find src/templates/*/commands/trellis/ -name "<command>.*"`
- [ ] Update all platform copies (Markdown `.md` and TOML `.toml`)
- [ ] For Gemini TOML: adapt line continuations (`\\` vs `\`) and triple-quoted strings
- [ ] Run `/trellis:check-cross-layer` to verify nothing was missed

**Real-world example**: Updated `record-session.md` in Claude to use `--mode record`, but forgot iFlow, Kilo, OpenCode, and Gemini — caught by cross-layer check.

---

## Generated Runtime Template Upgrade Consistency

Some generated files are both documentation and runtime input. In Trellis,
`.trellis/workflow.md` is parsed by `get_context.py`, `workflow_phase.py`,
SessionStart filters, and per-turn hooks. Template changes must be validated
against both fresh init and upgrade paths.

### Checklist: After Modifying A Runtime-Parsed Template

- [ ] Identify every runtime parser that reads the template, not just the file
      writer that installs it
- [ ] Check whether relevant syntax lives outside obvious managed regions
      such as tag blocks
- [ ] Verify fresh `init` output and a versioned `update` scenario that writes
      the older `.trellis/.version`
- [ ] Add an upgrade regression using an older pristine template fixture, then
      assert the installed file reaches the current packaged shape
- [ ] Update the backend spec that owns the runtime contract

---

## Versioned Documentation Boundary

Versioned documentation is a cross-layer boundary: source paths, `docs.json`
version routing, and the rendered version selector must all describe the same
release line.

### Checklist: Before Editing Versioned Docs

- [ ] Identify the target release line: stable, beta, or RC
- [ ] Verify the edited MDX path matches that line:
  - stable: `docs-site/{start,advanced,...}` and `docs-site/zh/{start,advanced,...}`
  - beta: `docs-site/beta/**` and `docs-site/zh/beta/**`
  - RC: `docs-site/rc/**` and `docs-site/zh/rc/**`
- [ ] Verify `docs.json` navigation points the version label to the same paths
- [ ] Grep the opposite tree for release-line-specific terms before committing
- [ ] Treat beta content appearing under root release paths as a source-path bug,
      not a rendering bug

**Real-world example**: A beta-only task workflow change documented
`prd.md` + `design.md` + `implement.md`, task-creation consent, and Codex
mode banners under root `start/` and `advanced/` paths. The docs site then
served 0.6 beta behavior under the Release selector. The fix was to restore root
release docs, move the 0.6 content to `beta/` and `zh/beta/`, and add a grep
audit for beta markers against the root release tree.

**Real-world example**: Codex inline mode changed workflow platform markers from
`[Codex]` / `[Kilo, Antigravity, Windsurf]` to `[codex-sub-agent]` /
`[codex-inline, Kilo, Antigravity, Windsurf]`. Fresh init was correct, but
`trellis update` only merged `[workflow-state:*]` blocks and preserved stale
markers outside those blocks. Result: upgraded projects got new hook scripts
but old workflow routing, so `get_context.py --mode phase --platform codex`
could return empty Phase 2.1 detail.

---

## Mode-Detection Probe Checklist

When a CLI auto-detects a mode by probing a remote resource (e.g., checking if `index.json` exists to decide marketplace vs direct download):

### Before implementing:

- [ ] Probe runs in **ALL** code paths that use the result (interactive, `-y`, `--flag` combos)
- [ ] 404 vs transient error are distinguished — don't treat both as "not found"
- [ ] Transient errors **abort or retry**, never silently switch modes
- [ ] Shared state (caches, prefetched data) is **reset** when context changes (e.g., user switches source)
- [ ] **Shortcut paths** (e.g., `--template` skipping picker) must have the same error-handling quality as the probed path — check that downstream functions don't call catch-all wrappers

### After implementing:

- [ ] Trace every path from probe result to the mode-decision branch — no fallthrough
- [ ] External format contracts (giget URI, raw URLs) are tested or at least documented as comments
- [ ] Metadata reads consume a complete response or use a streaming parser — never parse a fixed-size prefix as full JSON
- [ ] When reconstructing a composite identifier from parsed parts, verify **all** fields are included and in the **correct position** (e.g., `provider:repo/path#ref` not `provider:repo#ref/path`)
- [ ] Verify that **action functions** called after a shortcut don't internally use the old catch-all fetch — they must use the probe-quality variant when error distinction matters

**Real-world example**: Custom registry flow had 8 bugs across 3 review rounds: (1) probe only ran in interactive mode, (2) transient errors fell through to wrong mode, (3) giget URI had `#ref` in wrong position, (4) prefetched templates leaked across source switches, (5) `--template` shortcut bypassed probe but `downloadTemplateById` internally used catch-all `fetchTemplateIndex`, turning timeouts into "Template not found".

**Real-world example**: Agent-session update hints fetched npm `latest` metadata with `response.read(4096)` and then parsed it as complete JSON. The `@mindfoldhq/trellis` package metadata exceeded 4 KB, so the JSON was truncated, parse failed silently, and the first session injection showed no update hint. Fix: read the complete response before parsing, and add a regression where `version` is followed by an 8 KB metadata tail.

---

## Cross-Platform Template Consistency

In Trellis, command templates (e.g., `record-session.md`) exist in **multiple platforms** with identical or near-identical content. This is a cross-layer boundary.

### Checklist: After Modifying Any Command Template

- [ ] Find all platforms with the same command: `find src/templates/*/commands/trellis/ -name "<command>.*"`
- [ ] Update all platform copies (Markdown `.md` and TOML `.toml`)
- [ ] For Gemini TOML: adapt line continuations (`\\` vs `\`) and triple-quoted strings
- [ ] Run `/trellis:check-cross-layer` to verify nothing was missed

**Real-world example**: Updated `record-session.md` in Claude to use `--mode record`, but forgot iFlow, Kilo, OpenCode, and Gemini — caught by cross-layer check.

---

## Generated Runtime Template Upgrade Consistency

Some generated files are both documentation and runtime input. In Trellis,
`.trellis/workflow.md` is parsed by `get_context.py`, `workflow_phase.py`,
SessionStart filters, and per-turn hooks. Template changes must be validated
against both fresh init and upgrade paths.

### Checklist: After Modifying A Runtime-Parsed Template

- [ ] Identify every runtime parser that reads the template, not just the file
  writer that installs it
- [ ] Check whether relevant syntax lives outside obvious managed regions
  such as tag blocks
- [ ] Verify fresh `init` output and a versioned `update` scenario that writes
  the older `.trellis/.version`
- [ ] Add an upgrade regression using an older pristine template fixture, then
  assert the installed file reaches the current packaged shape
- [ ] Update the backend spec that owns the runtime contract

**Real-world example**: Codex inline mode changed workflow platform markers from
`[Codex]` / `[Kilo, Antigravity, Windsurf]` to `[codex-sub-agent]` /
`[codex-inline, Kilo, Antigravity, Windsurf]`. Fresh init was correct, but
`trellis update` only merged `[workflow-state:*]` blocks and preserved stale
markers outside those blocks. Result: upgraded projects got new hook scripts
but old workflow routing, so `get_context.py --mode phase --platform codex`
could return empty Phase 2.1 detail.

---

## Mode-Detection Probe Checklist

When a CLI auto-detects a mode by probing a remote resource (e.g., checking if `index.json` exists to decide marketplace vs direct download):

### Before implementing:
- [ ] Probe runs in **ALL** code paths that use the result (interactive, `-y`, `--flag` combos)
- [ ] 404 vs transient error are distinguished — don't treat both as "not found"
- [ ] Transient errors **abort or retry**, never silently switch modes
- [ ] Shared state (caches, prefetched data) is **reset** when context changes (e.g., user switches source)
- [ ] **Shortcut paths** (e.g., `--template` skipping picker) must have the same error-handling quality as the probed path — check that downstream functions don't call catch-all wrappers

### After implementing:
- [ ] Trace every path from probe result to the mode-decision branch — no fallthrough
- [ ] External format contracts (giget URI, raw URLs) are tested or at least documented as comments
- [ ] Metadata reads consume a complete response or use a streaming parser — never parse a fixed-size prefix as full JSON
- [ ] When reconstructing a composite identifier from parsed parts, verify **all** fields are included and in the **correct position** (e.g., `provider:repo/path#ref` not `provider:repo#ref/path`)
- [ ] Verify that **action functions** called after a shortcut don't internally use the old catch-all fetch — they must use the probe-quality variant when error distinction matters

**Real-world example**: Custom registry flow had 8 bugs across 3 review rounds: (1) probe only ran in interactive mode, (2) transient errors fell through to wrong mode, (3) giget URI had `#ref` in wrong position, (4) prefetched templates leaked across source switches, (5) `--template` shortcut bypassed probe but `downloadTemplateById` internally used catch-all `fetchTemplateIndex`, turning timeouts into "Template not found".

**Real-world example**: Agent-session update hints fetched npm `latest` metadata with `response.read(4096)` and then parsed it as complete JSON. The `@mindfoldhq/trellis` package metadata exceeded 4 KB, so the JSON was truncated, parse failed silently, and the first session injection showed no update hint. Fix: read the complete response before parsing, and add a regression where `version` is followed by an 8 KB metadata tail.

---

## When to Create Flow Documentation

Create detailed flow docs when:

- Feature spans 3+ layers
- Multiple teams are involved
- Data format is complex
- Feature has caused bugs before

---

## Event Log / Projection Boundary

Append-only logs are cross-layer contracts. A single event travels through:

```
CLI input → event writer → events.jsonl → reader → filter → reducer → display
```

### Checklist: After Adding A New Event Kind Or Field

- [ ] Add the event kind to the central event taxonomy
- [ ] Add a typed event variant or type guard at the event layer
- [ ] Add normalization helpers for array/object fields that come from
      user input or JSON
- [ ] Keep `seq` / `id` assignment in the event writer only
- [ ] Make filters and reducers consume the typed event guard, not local casts
- [ ] Make display code consume reducer output or typed events, not raw JSON
- [ ] Add at least one regression that proves history replay and live filtering
      use the same filter model

**Real-world example**: Thread channels added `kind: "thread"`, `description`,
`context`, labels, and `lastSeq`. The first implementation replayed thread
state correctly, but several commands still re-parsed event payload fields with
local casts. The fix was to make the core event layer own `ThreadChannelEvent`
and `isThreadEvent`, make `reduceChannelMetadata` the only channel metadata
projection, and make `reduceThreads` the only thread replay reducer.

---

## Provider Batch Completion Is A Cross-Layer Contract

A provider batch crosses transport classification, orchestration, artifact validation and mutation.
A successful canary proves request compatibility once; it does not prove that quota or availability
will hold for the remaining items.

### Checklist: Provider Batch To Mutation

- [ ] Classify body-free provider failures into stable categories at the transport boundary.
- [ ] Decide explicitly which categories are item-local and which trip a batch circuit breaker.
- [ ] On a shared transient failure, preserve completed results and mark the ordered remainder as
      not called; never invent suggestions or continue consuming calls.
- [ ] Treat concurrency and request rate as separate controls; add bounded, testable pacing without
      silently multiplying per-item attempts.
- [ ] Separate `diagnostic-valid` artifacts from `mutation-ready` artifacts.
- [ ] Enforce whole-plan completeness before the first repository mutation, not inside the row loop.
- [ ] Test a shared failure after a successful prefix and prove both call-count cessation and zero
      partial mutations.

**Real-world example**: An IP metadata repair flow reused a passing image canary, but a later shared
provider failure would have allowed the batch to continue and the successful prefix to be applied.
The fix added paced calls, transient circuit breaking with exact-set checkpoints, and a complete-plan
gate before any CAS.
