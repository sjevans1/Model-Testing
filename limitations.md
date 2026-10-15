# Limitations, confounding factors and remaining uncertainty

BENCH-MODEL-001. Everything here is a statement about evidence the benchmark could not
produce, or a factor that could distort the comparison. Read it before acting on any number
in `scores.csv`.

## 1. Routing deviation for Claude Haiku 5.5 (material)

The three candidates were requested through the configured OpenCode Go subscription. Two of
them (`gpt-6-luna`, `deepseek-v4.1-flash`) run on the built-in `opencode-go` provider. Haiku
5.5 cannot: the installed Hermes build (v0.21.5+8495, commit `cbffbeec`) maps OpenCode Go
model families to wires in `hermes_cli/models.py::_OPENCODE_API_MODE_PREFIXES`, and in that
build the `opencode-go` tuple has no `claude-*` entry:

```
"opencode-go": ((("gpt-", "grok-", "muse-spark"), "codex_responses"),
                (("minimax-", "qwen", "union-alpha"), "anthropic_messages")),
```

so `claude-haiku-5-5` was routed to `/chat/completions`, which the relay rejects with
`ModelProtocolUnsupported`; Hermes then silently fell back to the configured fallback provider
(`openrouter/deepseek-v4.1-flash`). That was observed directly during preflight: a oneshot
pinned to `claude-haiku-5-5` on `opencode-go` reported `model=deepseek/deepseek-v4.1-flash`,
`provider=openrouter` in its usage ledger.

Haiku's wire on the relay is the Anthropic Messages API (`/messages`), which requires the
credential in `x-api-key` (a `Bearer` header returns HTTP 401 `Go requires a credential`; an
`x-api-key` request returns 200). To run Haiku at all, this benchmark declares an equivalent
route inside its **isolated** benchmark home (`hermes-home/config.yaml`, provider
`go-anthropic`: same relay URL, `api_mode: anthropic_messages`, same API key). The user's own
configuration was not modified.

Upstream has already fixed the table (in v0.22.1 / `origin/main` the `opencode-go` tuple reads
`(("claude-", "minimax-", "qwen", "union-alpha"), "anthropic_messages")`), so after the
pending Hermes update the deviation disappears entirely.

What this means for the numbers: Haiku's agent loop, tools, prompt, budget and fixtures are
identical to the other two; only the provider route used to reach the same model differs.
Tool availability, context, latency accounting and token accounting are all from the same
Hermes code path. The risk that remains is that a relay-side difference between the two wires
(streaming behaviour, prompt-cache reporting) makes Haiku's latency or cache figures not
perfectly comparable. Treat Haiku's cost/latency as indicative, not as a like-for-like relay
measurement.

## 2. No fallback, deliberately

The benchmark home has no `fallback_providers` entry, so a candidate can never be silently
substituted for another model. Every trial record carries `substituted` (computed by comparing
the requested model id with the model in the usage ledger); no trial in the final set shows a
substitution.

## 3. Telemetry: what is measured and what is modelled

- Measured per trial: wall-clock elapsed, exit status, API call count, uncached input tokens,
  output tokens, cache-read tokens, cache-write tokens, reasoning tokens, session id, files
  changed, deliverables present, and Hermes's own `estimated_cost_usd`.
- Hermes reports `cost_status: unknown` / `cost_source: none` for OpenCode Go (the relay does
  not return per-token pricing), so **cost in this dossier is metered-equivalent, computed by
  the harness from the published OpenCode Go rate card**, not billed spend.
- The rate card is applied per trial on aggregate token counts. The published prices are
  tiered per *request* (Haiku 5.5 at 100K prompt tokens, GPT-6 Luna at 272K; DeepSeek V4.1
  Flash peak/off-peak by UTC hour). A trial is scored at the low tier when its total prompt
  tokens sit under the threshold, and at the high tier when they exceed it; a trial whose
  requests straddle the threshold is therefore an approximation. DeepSeek's peak window is
  01:00-04:00 and 06:00-10:00 UTC on weekdays.
- `input_tokens` and `cache_read_tokens` are reported separately by Hermes and are treated as
  mutually exclusive (uncached vs cached prompt tokens). If the underlying provider counts them
  inclusively, absolute costs shift but the comparison between candidates does not, because the
  same convention is applied to all three.
- The `$1.50` metered-equivalent ceiling per candidate was enforced by the driver: a candidate
  that reached it would have had remaining trials skipped. No candidate hit the ceiling.

## 4. Stage C (consistency repeats) was conditional

The assignment makes Stage C conditional on "quotas and operational conditions". Two trials in
Stage A were lost to provider stalls (`gpt-6-luna` on T2 was killed after 87 s with no usage
record, and another trial stalled for ~18 minutes with no output before being killed). The
driver was hardened (process-group kill on timeout, one automatic retry with a fresh session,
`agent.max_turns: 60`) and the affected trials rerun. Because that recovery consumed budget and
wall-clock, any Stage C repeats that were run are marked with `attempt` > 1 in `runs.jsonl`,
and unrun repeats are simply absent rather than scored as zero. Consistency evidence is
therefore thinner than the full assignment asked for; see section 6.

## 5. Environment and harness facts that bound the evidence

- All candidates ran the same Hermes build, the same briefs, the same fixtures, the same
  `--reasoning medium` flag, the same `--yolo` permission model, and the same
  `agent.max_turns: 60`, each in a fresh session, sequentially (never concurrently), with the
  execution order rotated per task so no candidate is always first.
- Candidates ran in an **isolated HERMES_HOME** that has no skills, no memory provider, no
  plugins and no cron. That makes the three candidates' context identical, which is what the
  control requirement asks for, but it is *not* the production profile: every candidate saw a
  smaller tool/skill surface than the real OpenJM and Workspace-Platform agents see.
- `lightpanda` was the browser for T4 on all candidates (its CDP build is Chromium 155 based).
- Hidden acceptance tests were never placed in a candidate tree; graders run on a scratch copy
  afterwards. Candidates could not see expected values.
- One trial can change the fixture's in-memory state, so T4's grader restarts the mock API
  before every scenario; without that, later scenarios inherit an earlier scenario's role
  change.

## 6. What the benchmark does not establish

- **No direct comparison against GLM-5.3 Flash.** It appears here only as the qualitative
  evaluator. Nothing in this dossier supports a claim that any tested model is better or worse
  than GLM-5.3 Flash in its current supervisory role.
- **One primary trial per (task, candidate).** Task-level scores are single observations. A
  candidate that scored 78 has not been shown to be better than one that scored 74.
- **No long-horizon or multi-session work.** Every trial is a single bounded session; nothing
  here speaks to week-long missions, context-compaction behaviour under sustained load, or
  recovery after an interruption.
- **T4 responsiveness is unverified.** The browser build accepts
  `Emulation.setDeviceMetricsOverride` but does not reflow layout, so the 390px check reports
  SKIPPED for every candidate. Mobile behaviour was not measured at all.
- **T6's "interrupted nested run" check** is verified by forcing the budget
  (`NESTED_TIMEOUT_S=1`). A candidate could satisfy it by raising the budget without
  understanding the failure; the other five checks make that an incomplete pass rather than a
  free one, but it is not a complete proof of understanding.
- **T1/T2/T7 are judged, not measured.** They use a fixed rubric, an anonymised payload and
  GLM-5.3 Flash as evaluator (as the assignment permits). Judging is a source of variance: the
  evaluator scored all artifacts in one pass, and a re-run would move individual numbers.
- **Test-suite execution evidence inside candidate trees** is limited to what each candidate
  left behind and what the graders re-ran; where a candidate's own test requires the browser or
  a port, the grader re-runs it under the same environment and records the outcome.
- **Nothing was run against production systems.** No production repository, branch, database,
  credential or deployment was touched; every fixture is a synthetic copy. The sandbox trees
  have no git remote, so no candidate could push even by mistake.

## 7. Threats to validity that were not eliminated

- **Prompt-cache state.** Warm relay-side caches favour whoever runs second on a given model.
  Execution order was rotated per task, but not balanced per (task, model) pair.
- **Provider load.** Two trials were lost to stalls. Latency numbers carry that provider noise.
- **Reasoning-effort mapping.** `--reasoning medium` was passed to all three. The providers map
  effort differently, and no attempt was made to equalise *effective* reasoning budget; where a
  provider ignored the flag, that trial is not marked.
- **Judge knowledge leakage.** The evaluator is a model that may have priors about the
  candidates. Payloads were scrubbed of model names, but writing style can still be
  recognisable.
