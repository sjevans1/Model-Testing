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

## 8. Harness correction made mid-benchmark (disclosed)

The qualitative evaluator's first rubric treated any disagreement with a brief's hard constraint
as a "critical failure". It used that to disqualify one work-package specification for proposing
HTTP 404 instead of the fixture's shipped 400. That is an ordinary design finding, not one of the
assignment's critical-failure categories (unauthorized cross-tenant operation, retained privilege
escalation, a weakened gate, fabricated evidence, a prohibited production change, or a false
success claim), so the definition was narrowed to those categories and every judgement made under
the broad rule was discarded and re-run. No candidate's task score was revised by hand.

## 9. Environmental interruption, cause identified

One Stage A trial (T4, Claude Haiku 5.5) was terminated by SIGTERM about a minute after it
started. The cause was not the candidate, the provider or the fixture: a cleanup command in the
orchestrator session used a process-name pattern that matched the freshly started trial process.
The trial was retried automatically with a fresh session, its first attempt is preserved in
`runs.jsonl` and reported separately in `dossier/first-attempts.md`, and no zero score was
substituted for it. Subsequent orchestration kills by explicit PID only.

This is also why two earlier trials were lost: an equivalent over-broad pattern killed a running
trial, and the driver's own 900 s timeout (before it was hardened to kill the whole process
group) left a grandchild alive. Both were rerun; neither left a `usage.json`.

## 10. T4 telemetry gap (terminal-tool background processes)

Every T4 trial drives a browser and a mock HTTP server, so candidates start them as background
processes through the terminal tool. In two of two Claude Haiku 5.5 attempts the trial process
was terminated by SIGTERM while that cleanup ran, after the deliverables were already on disk
(`notes.md`, `public/app.js`, `tests/browser_access.mjs`, and so on). The tree is complete and is
graded normally, but no `usage.json` was written, so those trials have no token or cost record.
`runs.jsonl` marks them `terminated_after_deliverables` with `usage_missing: true`, and the
dossier reports the gap instead of a zero. Efficiency for those trials is therefore derived from
elapsed time only; do not compare their cost with the other two candidates' T4 cost.

## 11. First-attempt capture in Stage A (partial)

The runner used for the first trials of Stage A overwrote the record of an attempt that was
followed by a retry, so for those specific trials the first attempt survives only in the
process log, not in `runs.jsonl`: T4 / Claude Haiku 5.5 attempt 1 (SIGTERM, orchestrator-caused),
T4 / DeepSeek V4.1 Flash attempt 1 (hit the 600 s timeout; its tree had not yet been written
with deliverables). T2 / GPT-6 Luna attempt 1 is recorded. From Stage B onward the runner writes
one record per attempt, marks the superseded one with `superseded_by_retry`, and archives the
first attempt's tree instead of deleting it. No retried trial is scored as a zero, and no first
attempt is reported as a success.

## 12. T4 wall-clock ceiling, and how it is being separated from model capability

T4 is the longest task (browser plus mock server). At the 600 s budget used for Stage A, one
candidate finished in 465 s, one produced its deliverables before being SIGTERM'd at cleanup,
and one was killed at exactly 600 s twice. A trial that is cut off by the harness ceiling cannot
be read as a capability result: it is reported as an incomplete trial with a gradable tree, and
the ceiling itself is retested. Stage C repeats T4, and a further T4 pass runs at a 900 s budget
(stage `d`) for exactly the candidates whose Stage A trial was cut off, so the dossier can say
whether the limit or the model decided the outcome. If a candidate still fails at 900 s, that is
a capability finding and is reported as one.

## 13. One check that is a contract failure rather than a behaviour failure (T4, Luna)

GPT-6 Luna's T4 screen fails check S04 because its confirmation control carries
`data-confirm="no"` before confirmation instead of the frozen `data-confirm="yes"`, so the
automated selector cannot find it. A separate probe (evidence:
`task-evidence/t4-luna-confirm-probe.txt`) shows the behaviour itself is correct: applying a
privilege-sensitive change without confirming writes nothing, confirming and applying writes
exactly one `admin` change. The scoring rule was fixed before any candidate ran and was not
relaxed afterwards, so S04 stays failed; the dossier records the distinction so the reader can
weigh a naming-contract miss against a security miss.

## 14. Fixture defect found in the multi-tenant suite (corrected for all candidates)

Check A05 originally asserted that every row returned by `list_reports()` carried
`revoked is False`, a field the brief never specifies. Haiku 5.5 and GPT-6 Luna both exclude
revoked reports from the listing (their SQL filters `revoked_at IS NULL`) and scope by tenant,
and DeepSeek returns them with `status: revoked`; all three were therefore failed by a
requirement that did not exist in the task. That was a defect in the acceptance suite, not a
candidate failure, and it is recorded here rather than quietly dropped.

A05 now checks only the tenant-scoping signal the brief does state (own rows present, foreign
rows absent, and no revoked report presented as live), and a new check A14 records how
revocation is surfaced: absent, or clearly marked revoked via any of `revoked`, `revoked_at`,
`status` or `state`. The correction was applied to every candidate equally, before any final
score was computed, and the original failing output is preserved in
`task-evidence/stage-b-grading.txt`.

## 15. T8 two-sided grading: what a failure there does and does not mean

T8 is graded twice on purpose: the candidate's suite must FAIL against the shipped (defective)
implementation, which proves it detects real defects, and PASS when a correct implementation is
dropped in, which proves it does not encode expectations of its own.

GPT-6 Luna's 16-test suite detects the defects (that half passes) but three assertions fail
against a correct implementation:

- `test_batch_with_no_successes_reports_failure_and_zero_applied` requires
  `result["status"] == "failed"`. The claim under review says only that `status` is `complete`
  when every item was saved; no other value is defined anywhere in the brief or the claims, and
  the reference returns `partial`. The count and "nothing persisted" assertions in the same test
  are correct and pass.
- `test_revoke_requires_admin_and_foreign_revoke_is_indistinguishable_from_missing` requires
  that an analyst be refused when revoking a report they own. Nothing in T8's brief or in
  CLAIMS.md states who may revoke; the reference follows the rule stated in the T5 brief
  (owner or tenant admin), so the test fails against it.

Both are cases of a test asserting a policy the task never fixed, not of a wrong finding. The
automated result stands (the suite cannot pass against a correct implementation), and this note
records exactly which assertions caused it so the reader can weigh "detects defects" separately
from "over-specifies the contract". This is the one place in the benchmark where a task's own
brief was thinner than the grader's reference; it is disclosed rather than patched, because
changing the rule now would be scoring after the fact.

## 16. Two defects in the benchmark's own reference implementation, found by the candidates

The T8 two-sided check requires a candidate's suite to fail on the shipped defective code and pass
when a correct implementation is dropped in. All three candidates failed that second half at
first. Rather than record three identical findings, I read their failing assertions, and they
pointed at my reference, not at them:

- `get_report()` in the reference raised `Forbidden` for a revoked report unless the actor was an
  admin. CLAIMS.md never says that revocation removes read access; it promises only that the
  snapshot and its hash survive. That policy was invented by the reference.
- `save_batch()` in the reference raised `AttributeError` on a malformed (non-dict) item instead of
  reporting the item as a failed save, which made "the batch reports the truth" untestable in that
  case.

Haiku 5.5 found both; DeepSeek found the first. My own acceptance suite had not, because it
shared the reference's assumption: validating a reference against the same suite that encoded it
is a blind spot, and it is disclosed here as such.

Both defects were fixed in `harness/reference/service_correct.py`, the reference still passes the
frozen suite (14/14), the defective fixture still fails 10 of 14 checks, and T8 was recomputed for
every candidate before any final score existed. After the fix: Haiku 5.5 detects the defects and
passes on a correct implementation (a fully claim-validating suite, 52 tests); Luna and DeepSeek
still fail that half on their own assertions about points the task never fixed (a specific
`save_batch` status string, whether a revoked report stays in the listing, and whether an owning
analyst may revoke). Evidence: `task-evidence/t8-reference-defects.txt`.
