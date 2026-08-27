# Implementation Plan

1. Add focused backend tests for the default 8–2,000-character policy, the explicit non-blank unrestricted IP policy, API schema acceptance, and IP worker request propagation.
2. Implement optional shared validator bounds and the provider-neutral request policy; opt in only from the IP generation worker while continuing to reject normalized blank input.
3. Remove the IP request schema bounds, migrate the durable prompt column to `TEXT` with a
   non-truncating downgrade guard, and regenerate/check OpenAPI artifacts without absorbing
   unrelated generated-file changes.
4. Refactor the creation-page label markup and return link, remove both textarea length attributes, and update CSS Modules with local font stacks and responsive behavior.
5. Add component tests for the missing textarea length bounds and the accessible navigation/section labels.
6. Run backend focused tests, frontend IP tests, formatting, lint, strict TypeScript, OpenAPI drift, production build, axe, and a local desktop/mobile browser smoke.
7. Dispatch independent Trellis review, apply verified fixes, sync project specs, and commit only this task's files/hunks.
