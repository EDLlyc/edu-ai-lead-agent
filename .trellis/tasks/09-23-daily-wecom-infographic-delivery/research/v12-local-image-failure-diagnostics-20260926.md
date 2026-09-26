# V12 controlled local image outcome and future diagnostics — 2026-09-26

The controlled local v12 Arctic-cod advisory attempt ended with
`image_result_unknown_or_quality_failed` after approximately 125 seconds.
Its safe summary records one generation intent, one audit intent, and one image
intent, with `send_ready=false`. There is no `images/` artifact. The image
intent is spent and must not be replayed for this package/policy/stage. No
Enterprise WeChat send or production deployment occurred.

The old local preview caught the provider call, returned-result checks, and
all JPEG derivatives in one broad exception handler. Its single status cannot
establish whether the cause was transport/provider failure, invalid returned
image, or local rendering/encoding. In particular, no specific HTTP status or
provider response should be inferred from this historical attempt.

For **future trials only**, the R15 candidate adds a closed `image_failure`
projection to the existing non-replayable summary status. It distinguishes
allowlisted provider exception class/code (plus a sanitized typed HTTP status
and response kind only when supplied by the adapter and rechecked at the
public projection boundary), returned-result
validation, and the failing derivative step. Unknown exception classes become
`other_exception` / `provider_outcome_unknown`. Exception strings, response
bodies, secrets, prompts, and private news/copy text are not projected. This
diagnostic change neither changes the v12 image prompt nor creates a new
intent; it cannot retrospectively classify the consumed attempt.

Provider-free tests cover typed rejection and timeout, adapter image-output
validation, mutated exception metadata with private sentinels, an unknown
exception, mismatched result identity, derivative failure, and refusal of a
second attempt after an image intent. The 16 local-preview unit tests, scoped
Ruff/format, production-file strict mypy, and
`git diff --check` pass. Real-image quality, final-JPEG/390px review, fixed
recipient test and gray deployment gates remain open.
