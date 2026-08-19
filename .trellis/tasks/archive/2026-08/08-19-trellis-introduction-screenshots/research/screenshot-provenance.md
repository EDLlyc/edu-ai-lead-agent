# Screenshot provenance

## Source package

- Directory: `docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z/`
- Capture ID: `f5cd8de936a5-20260818T063838Z`
- Capture mode: `deterministic-fixture`
- Source commit recorded by the package: `f5cd8de936a57dfd61c01101b7cb2a2412b2eb25`
- Browser/API relationship: the package manifest records `browser_api_interception: none` and `api_ui_semantic_match: true` for each case.
- Provenance statement: screenshots come from browser-originated localhost runs against an isolated deterministic fixture. They are evidence of reproducible UI/API execution and bounded tool behavior, not live-provider intelligence or production operation.

## Approved source images

| File | SHA-256 | Meaning |
| --- | --- | --- |
| `overview.png` | `a62e617947a9c1de290fa822c6852c23a0573bfee1384eefde6c2e302fef3352` | Three captured cases: multi-tool research, controlled copy validation, and safe refusal. |
| `multi-tool-research.png` | `7f5a26b54e384e8a5ea9bbe7928971441b998eb91bb33b97f48082fe00512505` | A completed multi-tool local run with safe citations and a visible redacted trace. |

## Safety review

- The package states that no provider body, prompt, credential, private path or durable trace is stored in the screenshots or paired artifacts.
- The images are RGB PNGs with previously stripped metadata.
- The report must not copy run IDs, localhost origins, timestamps, command lines, provider names or performance figures into captions.
- The screenshot already contains synthetic/fixture UI content. The report must label this accurately rather than describing it as a production business result.

## Use boundary

These images are used only to illustrate the claim that a Trellis-managed project can leave observable, inspectable artifacts around an AI-assisted workflow. They are not a Trellis product UI, and they are not evidence of a live model or deployed production service.
