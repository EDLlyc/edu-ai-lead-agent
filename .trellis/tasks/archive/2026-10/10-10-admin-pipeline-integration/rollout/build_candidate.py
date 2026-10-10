"""Offline legacy-derived build after source gate; no production service mutation."""

import json
import os

from common import BASE, STAGE, TARGETS, inspect, name, require, run, save, sha

os.umask(0o077)
commit = (STAGE / "source-commit.txt").read_text().strip()
manifest = json.loads((STAGE / "context/verification/manifest.json").read_text())
require(
    manifest["source_commit"] == commit
    and manifest["legacy_image"] == BASE
    and manifest["full_legacy_manifest"],
    "build_manifest_invalid",
)
require(
    all(item["Image"] == BASE for item in inspect([name(s) for s in TARGETS]).values()),
    "legacy_base_changed",
)
alias = "offline.local/edu-ai/edu-ai-lead-agent-backend:admin-pipeline-base-83a41e41"
tag = "offline.local/edu-ai/edu-ai-lead-agent-backend:admin-pipeline-" + commit[:7]
run(["docker", "tag", BASE, alias])
require(
    run(["docker", "image", "inspect", "--format", "{{.Id}}", alias]).strip() == BASE,
    "base_tag_mismatch",
)
log = run(
    [
        "docker",
        "build",
        "--pull=false",
        "--network=none",
        "--build-arg",
        "LEGACY_IMAGE=" + alias,
        "-t",
        tag,
        str(STAGE / "context"),
    ],
    timeout=240,
)
(STAGE / "build.log").write_text(log)
image = run(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).strip()
require(image.startswith("sha256:") and len(image) == 71, "candidate_image_invalid")
smoke = json.loads(
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image,
            "/opt/admin-pipeline-release/smoke.py",
        ],
        timeout=240,
    )
)
require(smoke.get("status") == "PASS", "offline_smoke_failed")
resolved = run(
    [
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        "offline.local/edu-ai/edu-ai-lead-agent-backend@" + image,
    ]
).strip()
require(resolved == image, "digest_reference_mismatch")
assets = json.loads((STAGE / "frontend-sha256.json").read_text())
require(
    all(sha(STAGE / "dist-admin" / key) == value for key, value in assets.items()),
    "frontend_hash_mismatch",
)
value = {
    "image": image,
    "source_commit": commit,
    "legacy_image": BASE,
    "frontend": assets,
    "manifest": "manifest.json",
    "offline_smoke": smoke,
}
save(STAGE / "manifest.json", manifest)
save(STAGE / "candidate.json", value)
print(json.dumps(value))
