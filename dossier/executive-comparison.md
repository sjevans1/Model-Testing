# Executive comparison

Scores are out of 100 on the documented weights (functional 35, security 25, instruction 15, testing 10, maintainability 10, efficiency 5). `n/a` means the trial had not produced a gradable result. A trial with a critical failure keeps its raw score but is excluded from qualification.

| Task | Area | Claude Haiku 5.5 | GPT-6 Luna | DeepSeek V4.1 Flash |
|---|---|---|---|---|
| T1 | Requirements + planning | 89.7 | 91.8 | 77.1 |
| T2 | Work-package framing | 90.7 | 89.0 | 85.7 |
| T3 | Backend feature | 96.8 | 96.8 | 96.8 |
| T4 | Frontend/admin safety | 100.0 | 67.9 | 100.0 |
| T5 | Security + isolation | 96.8 | 96.8 | 96.8 |
| T6 | CI diagnosis + repair | 76.3 | 94.7 | 94.7 |
| T7 | Independent code review | 93.8 | 91.7 | 96.4 |
| T8 | Test design + acceptance | 100.0 | 76.3 | 77.4 |

`*` = critical failure recorded for that trial.

## Headline metrics

| Candidate | Overall (mean of graded tasks) | Tasks graded | First-attempt success | Final success | Critical failures | Total time | Metered-equivalent cost |
|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | 93.0 | 8 | 7 | 8 | 0 | 1473.8s | $0.8667 |
| GPT-6 Luna | 88.1 | 8 | 7 | 8 | 0 | 1603.7s | $0.2225 |
| DeepSeek V4.1 Flash | 90.6 | 8 | 6 | 8 | 0 | 3204.8s | $0.4928 |
