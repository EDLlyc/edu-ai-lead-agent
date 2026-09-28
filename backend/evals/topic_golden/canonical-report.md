# Topic golden set

- Cases: 13 (7 operator-labelled real headlines, the rest rule-derived examples)
- Must-select headlines fetched ahead of leftover capacity: 7/7

| Scoring version | Must select eligible | Must select with priority | Should-not rejected | Passed | Failing cases |
|---|---|---|---|---|---|
| `scoring-v1-preview.11-qualified-authoritative-priority` | 2/7 | 1/6 | 4/6 | 6/13 | g01-higher-education-classified-reform, g02-five-year-education-priorities, g03-higher-education-expansion, g05-new-industrialisation-yaowen, r01-provincial-exam-reform, n05-trade-forum-incidental-ai, g07-rumor-arrest-negative |
| `scoring-v1-preview.13-education-policy-signal` | 6/7 | 5/6 | 4/6 | 10/13 | g05-new-industrialisation-yaowen, n05-trade-forum-incidental-ai, g07-rumor-arrest-negative |
| `scoring-v1-preview.14-negative-incident-industrial-tech` | 7/7 | 6/6 | 5/6 | 12/13 | n05-trade-forum-incidental-ai |

## Failing cases in the current default

- `n05-trade-forum-incidental-ai` 中外经贸合作论坛在京举行 — expected should_not_select; got eligible=True, priority=False (no_topic_priority_policy), cohort=frontier_science_technology
