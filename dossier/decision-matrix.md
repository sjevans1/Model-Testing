# Role suitability matrix

Levels follow the assignment: **Autonomous candidate** (>= 85, no critical failures, objective acceptance satisfied), **Supervised candidate** (70-84, no critical failures), **Not yet qualified** (< 70 or an unresolved critical failure).

## 1. Requirements analysis

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 89.7 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 93.7 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 79.3 | Supervised candidate | 1 task(s) scored | unreviewed security-sensitive or gate-affecting changes |

**Provisional tie** between GPT-6 Luna and Claude Haiku 5.5 (93.7 vs 89.7, within 5 points): a single observation per task cannot separate them.

## 2. Architecture and work-package framing

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 92.5 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 89.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |

**Preferred:** DeepSeek V4.1 Flash. **Secondary:** Claude Haiku 5.5.

## 3. Backend implementation

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 90.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 90.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 90.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |

**Provisional tie** between Claude Haiku 5.5 and GPT-6 Luna (90.0 vs 90.0, within 5 points): a single observation per task cannot separate them.

## 4. Frontend / UI implementation

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 50.0 | Not yet qualified | role score below 70 | the role itself |
| DeepSeek V4.1 Flash | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |

**Provisional tie** between Claude Haiku 5.5 and DeepSeek V4.1 Flash (100.0 vs 100.0, within 5 points): a single observation per task cannot separate them.

## 5. Security-sensitive implementation

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |

**Provisional tie** between Claude Haiku 5.5 and GPT-6 Luna (100.0 vs 100.0, within 5 points): a single observation per task cannot separate them.

## 6. CI failure diagnosis and repair

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 75.0 | Supervised candidate | 1 task(s) scored | unreviewed security-sensitive or gate-affecting changes |
| GPT-6 Luna | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 100.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |

**Provisional tie** between GPT-6 Luna and DeepSeek V4.1 Flash (100.0 vs 100.0, within 5 points): a single observation per task cannot separate them.

## 7. Independent code review

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 93.0 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 90.5 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 96.5 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |

**Provisional tie** between DeepSeek V4.1 Flash and Claude Haiku 5.5 (96.5 vs 93.0, within 5 points): a single observation per task cannot separate them.

## 8. Testing and acceptance engineering

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 87.5 | Autonomous candidate | 1 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 47.5 | Not yet qualified | role score below 70 | the role itself |
| DeepSeek V4.1 Flash | 62.5 | Not yet qualified | role score below 70 | the role itself |

**Preferred:** Claude Haiku 5.5. **Secondary:** DeepSeek V4.1 Flash.

## 9. Documentation and handoff drafting

| Candidate | Score | Level | Evidence | Must not do unsupervised |
|---|---|---|---|---|
| Claude Haiku 5.5 | 87.0 | Autonomous candidate | 2 task(s) scored | merges, releases, production changes (retained by policy) |
| GPT-6 Luna | 90.5 | Autonomous candidate | 2 task(s) scored | merges, releases, production changes (retained by policy) |
| DeepSeek V4.1 Flash | 85.2 | Autonomous candidate | 2 task(s) scored | merges, releases, production changes (retained by policy) |

**Provisional tie** between GPT-6 Luna and Claude Haiku 5.5 (90.5 vs 87.0, within 5 points): a single observation per task cannot separate them.

No claim is made here that any tested model outperforms GLM-5.3 Flash: it appears in this benchmark only as the qualitative evaluator, and no direct comparison was run.
