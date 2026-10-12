# Topic golden set

- Cases: 20 (12 operator-labelled real headlines, the rest rule-derived examples)
- Must-select headlines fetched ahead of leftover capacity: 9/9

| Scoring version | Must select eligible | Must select with priority | Should-not rejected | Passed | Failing cases |
|---|---|---|---|---|---|
| `scoring-v1-preview.11-qualified-authoritative-priority` | 3/9 | 2/8 | 4/11 | 7/20 | g01-higher-education-classified-reform, g02-five-year-education-priorities, g03-higher-education-expansion, g05-new-industrialisation-yaowen, r01-provincial-exam-reform, n05-trade-forum-incidental-ai, g07-rumor-arrest-negative, n06-gov-yaowen-diplomatic-meeting, n07-gov-yaowen-water-investment, n08-gov-yaowen-trade-talks, g09-central-new-quality-productive-forces-opinion, n09-state-council-executive-meeting-productive-forces, n10-leader-visit-tech-company |
| `scoring-v1-preview.13-education-policy-signal` | 7/9 | 6/8 | 4/11 | 11/20 | g05-new-industrialisation-yaowen, n05-trade-forum-incidental-ai, g07-rumor-arrest-negative, n06-gov-yaowen-diplomatic-meeting, n07-gov-yaowen-water-investment, n08-gov-yaowen-trade-talks, g09-central-new-quality-productive-forces-opinion, n09-state-council-executive-meeting-productive-forces, n10-leader-visit-tech-company |
| `scoring-v1-preview.14-negative-incident-industrial-tech` | 8/9 | 7/8 | 5/11 | 13/20 | n05-trade-forum-incidental-ai, n06-gov-yaowen-diplomatic-meeting, n07-gov-yaowen-water-investment, n08-gov-yaowen-trade-talks, g09-central-new-quality-productive-forces-opinion, n09-state-council-executive-meeting-productive-forces, n10-leader-visit-tech-company |
| `scoring-v1-preview.15-gov-yaowen-topic-gate` | 8/9 | 7/8 | 8/11 | 16/20 | n05-trade-forum-incidental-ai, g09-central-new-quality-productive-forces-opinion, n09-state-council-executive-meeting-productive-forces, n10-leader-visit-tech-company |
| `scoring-v1-preview.17-national-tech-policy` | 9/9 | 8/8 | 8/11 | 17/20 | n05-trade-forum-incidental-ai, n09-state-council-executive-meeting-productive-forces, n10-leader-visit-tech-company |

## Failing cases in the current default

- `n05-trade-forum-incidental-ai` 中外经贸合作论坛在京举行 — expected should_not_select; got eligible=True, priority=False (no_topic_priority_policy), cohort=frontier_science_technology
- `n09-state-council-executive-meeting-productive-forces` 国务院常务会议研究推进新质生产力发展，听取意见 — expected should_not_select; got eligible=True, priority=True (qualified_government_yaowen_priority), cohort=frontier_science_technology
- `n10-leader-visit-tech-company` 李强考察科技企业并座谈 — expected should_not_select; got eligible=True, priority=True (qualified_government_yaowen_priority), cohort=frontier_science_technology
