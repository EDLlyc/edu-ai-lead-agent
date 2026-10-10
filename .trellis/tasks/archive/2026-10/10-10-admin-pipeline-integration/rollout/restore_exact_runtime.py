import copy
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/var/tmp/edu-admin-pipeline-20261010T061720Z")
from common import (
    BASE,
    ROOT,
    STAGE,
    TARGETS,
    atomic_text,
    content_manifest,
    db_state,
    environment,
    idle,
    inspect,
    name,
    preserved,
    render,
    require,
    runtime_hash,
    save,
    sha,
)
from cutover import graceful_stop, running, start, untouched

backup = Path("/var/backups/edu-ai/admin-pipeline-20261010T062459Z")
before = json.loads((backup / "before.json").read_text())
frozen = json.loads((backup / "frozen.json").read_text())
keys = ["CONTENT_SCORING_VERSION", "CONTENT_SLOT_RANKING_VERSION"]
siblings = [
    "acquisition-scheduler",
    "governance-scheduler",
    "official-account-weekly-scheduler",
]
items = inspect([name(s) for s in TARGETS + siblings])
reference = {k: environment(items[name(siblings[0])])[k] for k in keys}
require(
    all(
        {k: environment(items[name(s)])[k] for k in keys} == reference for s in siblings
    ),
    "legacy_siblings_disagree",
)
require(
    all(re.fullmatch("[a-z0-9_.-]+", v) for v in reference.values()),
    "nonversion_reference",
)
for service in TARGETS:
    item = copy.deepcopy(items[name(service)])
    require(item["Image"] == BASE, "restoration_image_changed")
    env = environment(item)
    env.update(reference)
    item["Config"]["Env"] = [k + "=" + v for k, v in env.items()]
    require(
        runtime_hash(item) == before["containers"][name(service)]["runtime_hash"],
        "reconstructed_runtime_not_exact",
    )
state = db_state()
idle(state)
preserved(frozen, state)
for volume in before["volumes"].values():
    require(
        content_manifest(volume["source"]) == volume["files"],
        "restoration_journal_changed",
    )
old_render = render()
original = (ROOT / "compose.yaml").read_text()
patched = original
for service in TARGETS:
    pattern = re.compile(
        r"(?ms)^  " + re.escape(service) + r":\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)"
    )
    match = pattern.search(patched)
    require(match is not None, "restoration_block_missing")
    block = match.group()
    require(
        all(not re.search(r"^      " + key + ":", block, re.MULTILINE) for key in keys),
        "explicit_version_exists",
    )
    addition = "".join(
        "      " + key + ": " + json.dumps(reference[key]) + "\n" for key in keys
    )
    new = block.replace("    environment:\n", "    environment:\n" + addition, 1)
    require(new != block, "environment_block_missing")
    patched = patched[: match.start()] + new + patched[match.end() :]
shutil.copy2(ROOT / "compose.yaml", backup / "compose.failed-rollback.yaml")
(backup / "compose.failed-rollback.yaml").chmod(0o600)
graceful_stop(TARGETS)
preserved(frozen, db_state())
atomic_text(ROOT / "compose.yaml", patched, 0o600)
expected = copy.deepcopy(old_render)
for service in TARGETS:
    expected["services"][service]["environment"].update(reference)
require(render() == expected, "restoration_render_drift")
start(TARGETS)
restored = running(TARGETS, BASE)
for service in TARGETS:
    require(
        runtime_hash(restored[name(service)])
        == before["containers"][name(service)]["runtime_hash"],
        "restored_runtime_not_exact",
    )
untouched(before)
preserved(frozen, db_state())
for volume in before["volumes"].values():
    require(
        content_manifest(volume["source"]) == volume["files"],
        "restored_journal_changed",
    )
result = {
    "result": "ORIGINAL_RUNTIME_RESTORED",
    "at": __import__("datetime")
    .datetime.now(__import__("datetime").timezone.utc)
    .isoformat(),
    "services": TARGETS,
    "legacy_image": BASE,
    "preserved_versions": reference,
    "full_runtime_hashes_match": True,
    "original_work_and_journals_preserved": True,
    "unrelated_containers_unchanged": True,
    "env_file_unchanged": sha(ROOT / ".env") == before["config_hashes"][".env"],
}
save(backup / "exact-runtime-restoration.json", result)
save(STAGE / "exact-runtime-restoration.json", result)
print(json.dumps(result))
