# Topic golden set

- Cases: 17 (11 operator-labelled real headlines, the rest rule-derived examples)
- Must-select headlines fetched ahead of leftover capacity: 8/8

| Scoring version | Must select eligible | Must select with priority | Should-not rejected | Passed | Failing cases |
|---|---|---|---|---|---|
| `scoring-v1-preview.11-qualified-authoritative-priority` | 3/8 | 2/7 | 4/9 | 7/17 | g01-higher-education-classified-reform, g02-five-year-education-priorities, g03-higher-education-expansion, g05-new-industrialisation-yaowen, r01-provincial-exam-reform, n05-trade-forum-incidental-ai, g07-rumor-arrest-negative, n06-gov-yaowen-diplomatic-meeting, n07-gov-yaowen-water-investment, n08-gov-yaowen-trade-talks |
| `scoring-v1-preview.13-education-policy-signal` | 7/8 | 6/7 | 4/9 | 11/17 | g05-new-industrialisation-yaowen, n05-trade-forum-incidental-ai, g07-rumor-arrest-negative, n06-gov-yaowen-diplomatic-meeting, n07-gov-yaowen-water-investment, n08-gov-yaowen-trade-talks |
| `scoring-v1-preview.14-negative-incident-industrial-tech` | 8/8 | 7/7 | 5/9 | 13/17 | n05-trade-forum-incidental-ai, n06-gov-yaowen-diplomatic-meeting, n07-gov-yaowen-water-investment, n08-gov-yaowen-trade-talks |
| `scoring-v1-preview.15-gov-yaowen-topic-gate` | 8/8 | 7/7 | 8/9 | 16/17 | n05-trade-forum-incidental-ai |

## Failing cases in the current default

- `n05-trade-forum-incidental-ai` 中外经贸合作论坛在京举行 — expected should_not_select; got eligible=True, priority=False (no_topic_priority_policy), cohort=frontier_science_technology
