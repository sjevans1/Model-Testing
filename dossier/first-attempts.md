# First attempt versus final outcome

A trial that was lost to a provider stall or a rejected substitution is retried once with a fresh session; the first attempt is preserved here and never scored as a zero.

| Task | Candidate | First attempt | Retries | Final status | Final score | Note |
|---|---|---|---|---|---|---|
| T1 | DeepSeek V4.1 Flash | completed | 0 | completed | 77.1 |  |
| T1 | GPT-6 Luna | completed | 0 | completed | 91.8 |  |
| T1 | Claude Haiku 5.5 | completed | 0 | completed | 89.7 |  |
| T2 | DeepSeek V4.1 Flash | completed | 0 | completed | 85.7 |  |
| T2 | GPT-6 Luna | failed | 1 | completed | 89.0 |  |
| T2 | Claude Haiku 5.5 | completed | 0 | completed | 90.7 |  |
| T3 | DeepSeek V4.1 Flash | completed | 0 | completed | 96.8 |  |
| T3 | GPT-6 Luna | completed | 0 | completed | 96.8 |  |
| T3 | Claude Haiku 5.5 | completed | 0 | completed | 96.8 |  |
| T4 | DeepSeek V4.1 Flash | failed | 0 | failed | 100.0 | timeout |
| T4 | GPT-6 Luna | completed | 1 | dry-run | 67.9 |  |
| T4 | Claude Haiku 5.5 | failed | 0 | failed | 100.0 |  |
| T5 | DeepSeek V4.1 Flash | completed | 0 | completed | 96.8 |  |
| T5 | GPT-6 Luna | completed | 0 | completed | 96.8 |  |
| T5 | Claude Haiku 5.5 | completed | 0 | completed | 96.8 |  |
| T6 | DeepSeek V4.1 Flash | completed | 0 | completed | 94.7 |  |
| T6 | GPT-6 Luna | completed | 0 | completed | 94.7 |  |
| T6 | Claude Haiku 5.5 | completed | 0 | completed | 76.3 |  |
| T7 | DeepSeek V4.1 Flash | completed | 0 | completed | 96.4 |  |
| T7 | GPT-6 Luna | completed | 0 | completed | 91.7 |  |
| T7 | Claude Haiku 5.5 | completed | 0 | completed | 93.8 |  |
| T8 | DeepSeek V4.1 Flash | terminated_after_deliverables | 0 | terminated_after_deliverables | 77.4 | timeout |
| T8 | GPT-6 Luna | completed | 0 | completed | 76.3 |  |
| T8 | Claude Haiku 5.5 | completed | 0 | completed | 100.0 |  |
