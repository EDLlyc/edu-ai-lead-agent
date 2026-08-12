# Unblock current copy runs on link dates

## Goal

Prevent source-link date tokens and legacy date checks from turning current daily copy runs into review_required; retain bounded repair and preserve hard evidence/output errors.

## Requirements

- R1: The deterministic copy validator must not inspect dates embedded in source URLs or in the
  system-owned source note as narrative factual claims.
- R2: For the active compact Moments policy, a narrative date that does not occur in the locked
  evidence must be retained as an observable warning, not a terminal validation error.
- R3: The repair prompt may receive the warning, but a remaining date warning must not prevent
  audit, package creation, or direct Enterprise WeChat delivery when all hard validation and audit
  requirements pass.
- R4: Existing hard evidence-binding, typed-output, provider, and publishing-boundary validation
  behavior is unchanged.
- R5: Production must reprocess only the current Shanghai-business-day run that was falsely held
  for this condition; historical runs remain untouched.

## Acceptance Criteria

- [ ] A source footer/source note whose URL path or publication note contains `YYYY-MM` or
  `YYYY-MM-DD` produces no `unbound_date` issue.
- [ ] An otherwise-valid compact-policy draft containing a narrative unbound date is valid for
  pipeline progression and persists `unbound_date` as a warning.
- [ ] The same draft under a non-compact policy preserves its existing terminal behavior.
- [ ] Unit tests cover both the URL false positive and policy-specific warning behavior.
- [ ] Focused tests, static checks for changed modules, and a production check verify that today's
  previously blocked run can proceed without creating duplicate or historical work.

## Confirmed Facts

- At 2026-08-12 18:03 CST, production run `71e447eb-35a6-438c-80af-826268e94cea` reached
  `review_required` after its second draft. Its only remaining error was `unbound_date`.
- The footer is appended after generation. The durable source note records the source publication
  date, but the validator previously scanned all generated and system-owned fields while its
  evidence text excluded `EligibleEvidence.published_at`.
- The active production policy is `preview-v10-compact-content-warning-recovery`; it already
  treats copy quality and several editorial/content issues as warnings.
- The user has explicitly requested that format and other editorial checks not stop material
  generation or sending.

## Out of Scope

- Changing topic selection, historical-run reconciliation, image generation, or WeCom transport.
- Deleting durable production records or weakening hard evidence/output-integrity checks.
- Rewriting content that is already accepted and delivered.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
