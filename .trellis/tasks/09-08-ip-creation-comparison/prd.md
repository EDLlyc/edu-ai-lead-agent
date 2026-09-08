# IP creation comparison — local roadshow improvement

## Authorized scope

The user approved the first improvement only: make the creation studio visibly explain
reference images → actual submitted creative brief → generated output. Implement locally,
with no deployment, provider generation, sharing, or unrelated changes. After reviewing the
screenshots, the user confirmed a local Git commit of the seven frontend files, related spec,
and task records; no remote push or deployment is included.

## Design

Keep the existing warm-paper, teal/clay editorial studio. Add a spacious full-width comparison
section, with numbered source images, a readable brief, and a dominant original-ratio output.
On narrow screens stack in the same reading order. Images open a keyboard-accessible large
preview. Reuse existing safe media/profile and modal conventions; add no dependencies.

## Acceptance criteria

- Freeze ordered reference cards, prompt, taxonomy and profile identity at submission, and bind
  the snapshot to the returned job. Editing the form afterwards cannot rewrite output provenance.
- Only show a comparison for a matching succeeded job and ready output. Never mix previous output,
  a pending next submission, a rejected request, another profile or different job's references.
  Do not fabricate historical briefs when no current-session snapshot exists.
- Source and result images use safe original preview resources, contain rather than crop.
  Private images use the existing profile-header blob transport; revoke owned object URLs.
- Zoom has a named dialog, close control, Escape/backdrop handling, focus containment/restoration,
  and named failure/loading states. Preview never triggers generation, download counting or share.
- Preserve current queued/running/failed feedback, idempotent retries and explicit sharing.
- Verify strict TypeScript, lint, focused component tests, build, and desktop/mobile browser layout.
  Attempt a visual capture with existing real media; disclose any mocked transport or test-only data.

## Execution ownership

Implementer owns creation page, comparison component/style files, and focused frontend tests.
Coordinator owns this task, docs/spec notes if needed, and isolated browser validation artifacts.
Checker reviews/fixes only this task's frontend changes. Preserve the unrelated dirty worktree.
