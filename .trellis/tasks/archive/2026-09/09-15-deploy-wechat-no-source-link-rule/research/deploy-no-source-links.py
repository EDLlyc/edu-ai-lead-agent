#!/usr/bin/env python3
"""One reviewed no-source-link deployment. No migration, model or social calls."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, cast

PREVIOUS_REVISION = "d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2"
PREVIOUS_LEGACY_REVISION = PREVIOUS_REVISION
REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend"
PREVIOUS_ID = "sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d"
PREVIOUS_REF = REPOSITORY + "@" + PREVIOUS_ID
BASE_ARCHIVE_SHA256 = "23493bf1382b2965e5a8118412ba19b9d02f07052fc937fd7c04fdbae90262a1"
APP = Path("/opt/edu-ai-lead-agent")
BACKUP_ROOT = Path("/opt/edu-ai-release-backups")
LOCK = Path("/var/lock/edu-ai-deploy.lock")
SCHEMA = "20260914_0047"
MIN_SINGLE_DATE = "2026-09-16"
SINGLE_ACCOUNT = "ae3a5056a1c78eddf728060ecc5287b6a93e48d99e496bc9a22292a2b4eb8fd7"
EXPECTED_OWNER_ROWS = 14
MAX_FUTURE_WECOM_JOBS = 3
MIN_WECOM_QUIESCE_LEAD_SECONDS = 10 * 60
MIN_WECOM_READY_LEAD_SECONDS = 5 * 60
SERVICES = (
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "content-scheduler",
    "content-worker",
    "official-account-weekly-dag-worker",
    "official-account-weekly-scheduler",
    "official-account-local-worker",
    "wechat-official-account-draft-worker",
    "wecom-dispatcher",
)
STOP_ORDER = (
    "wechat-official-account-draft-worker",
    "official-account-weekly-scheduler",
    "official-account-weekly-dag-worker",
    "official-account-local-worker",
    "wecom-dispatcher",
    "content-scheduler",
    "content-worker",
    "governance-scheduler",
    "governance-worker",
    "acquisition-scheduler",
    "acquisition-worker",
    "acquisition-api",
)
PROFILES = (
    "governance",
    "content",
    "official-account-weekly-dag",
    "official-account-local",
    "wechat-official-account-draft",
    "wecom",
)
FILES = {
    "domain/official_account_source_presentation.py": "6bd12a2e24551ffaca1cd370d3284169463602ac8bcff0390a7dd693e77fb57a",
    "domain/official_account_editor_handoff_v2.py": "0851427717287b591ba6f9835abec530c978619a3da7a538d8dbbca9df34fd65",
    "application/services/official_account_strict_prepared.py": "919ff0a12cc015d9b5815022f7a3e0369cdb5cb90763c8b3a47e8df38435a6b1",
    "application/services/wechat_official_account_draft.py": "b116c3dba73623778f78c04c0d49f6292bdbb348b8ebd3f28046cd7b35c4965a",
    "infrastructure/wechat_official_account/prepared_artifacts.py": "70de4170346170a28b72daf1e24993f3b412d09519868cfc1e90d8855b002050",
}
MWF_FLAGS = {
    "OFFICIAL_ACCOUNT_SINGLE_ENABLED": "true",
    "OFFICIAL_ACCOUNT_SINGLE_MIN_DATE": MIN_SINGLE_DATE,
    "OFFICIAL_ACCOUNT_SINGLE_ACCOUNT_FINGERPRINT": SINGLE_ACCOUNT,
    "OFFICIAL_ACCOUNT_SINGLE_PREPARE_MINUTES": "60",
    "OFFICIAL_ACCOUNT_SINGLE_CATCHUP_HOURS": "6",
    "OFFICIAL_ACCOUNT_SINGLE_MAX_ATTEMPTS": "3",
    "OFFICIAL_ACCOUNT_SINGLE_RETRY_BASE_SECONDS": "60",
    "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED": "false",
    "OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED": "false",
    "WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED": "false",
}
TABLES = (
    "acquisition_jobs",
    "governance_jobs",
    "topic_selection_jobs",
    "content_slot_jobs",
    "brand_ingestion_jobs",
    "copy_generation_jobs",
    "image_artifacts",
    "official_account_article_runs",
    "official_account_weekly_dag_runs",
    "wechat_mp_draft_jobs",
)
IDLE_QUERY = (
    "SELECT "
    + " + ".join(
        f"(SELECT count(*) FROM {table} WHERE status::text IN ('queued','retry_scheduled','running','outcome_unknown'))"
        for table in TABLES
    )
    + """ + (SELECT count(*) FROM wecom_delivery_jobs
WHERE status::text IN ('queued','running','partial','delivery_unknown')
OR text_status::text = 'unknown' OR image_status::text = 'unknown')"""
)
SINGLE_EDITION_QUERY = "SELECT count(*) FROM official_account_single_editions"
OWNER_QUERY = """SELECT COALESCE(jsonb_agg(to_jsonb(o)
ORDER BY account_fingerprint,key_kind,key_value),'[]'::jsonb)::text
FROM official_account_draft_owners o"""
HISTORICAL_COHORT_SHA256 = (
    "19bb31ea5747b84aade2ff0837238f1634da84b5d052ddb813c48603654c82ca"
)
HISTORICAL_DATES = (
    "2026-08-04",
    "2026-08-05",
    "2026-08-07",
    "2026-08-08",
    "2026-08-09",
    "2026-08-10",
    "2026-08-11",
)
HISTORICAL_COHORT_QUERY = """SELECT COALESCE(jsonb_agg(
jsonb_build_object('job',to_jsonb(j),'run',to_jsonb(r)) ORDER BY j.id),'[]'::jsonb)::text
FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id
WHERE j.status::text='queued' AND r.scoring_profile::text='preview'"""
WECOM_ACTIVE_QUERY = """SELECT jsonb_build_object(
'observed_at_epoch',EXTRACT(EPOCH FROM statement_timestamp())::text,
'jobs',COALESCE(jsonb_agg(jsonb_build_object(
'id',j.id::text,
'delivery_window_id',j.delivery_window_id::text,
'content_slot_selection_id',j.content_slot_selection_id::text,
'sequence_ordinal',j.sequence_ordinal,
'mode',j.mode,
'status',j.status,
'text_status',j.text_status,
'image_status',j.image_status,
'include_copy',j.include_copy,
'include_image',j.include_image,
'attempt_count',j.attempt_count,
'next_attempt_at_epoch',EXTRACT(EPOCH FROM j.next_attempt_at)::text,
'not_before_epoch',EXTRACT(EPOCH FROM j.not_before)::text,
'expires_at_epoch',EXTRACT(EPOCH FROM j.expires_at)::text,
'lease_owner',j.lease_owner,
'lease_token',j.lease_token::text,
'lease_expires_at_epoch',EXTRACT(EPOCH FROM j.lease_expires_at)::text,
'heartbeat_at_epoch',EXTRACT(EPOCH FROM j.heartbeat_at)::text,
'last_error_code',j.last_error_code,
'created_at_epoch',EXTRACT(EPOCH FROM j.created_at)::text,
'started_at_epoch',EXTRACT(EPOCH FROM j.started_at)::text,
'completed_at_epoch',EXTRACT(EPOCH FROM j.completed_at)::text,
'attempt_rows',(SELECT count(*) FROM wecom_delivery_attempts a WHERE a.job_id=j.id)
) ORDER BY j.id),'[]'::jsonb))::text
FROM wecom_delivery_jobs j
WHERE j.status::text IN ('queued','running','partial','delivery_unknown')
OR j.text_status::text='unknown' OR j.image_status::text='unknown'"""
BUSINESS_DATE_QUERY = "SELECT (now() AT TIME ZONE 'Asia/Shanghai')::date::text"

SMOKE = r"""
import asyncio,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
import httpx
from pydantic import SecretStr
from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
from app.domain.official_account_editor_handoff_v2 import render_editor_handoff_v2_body
from app.domain.official_account_source_presentation import (
    READABLE_SOURCE_PRESENTATION_VERSION,render_readable_sources,
)
from app.infrastructure.official_account_marketing_footer import load_official_account_marketing_framing
from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient
expected=json.loads(sys.argv[1]); current=sys.argv[2]=='current'
root=Path('/app/app'); tree={}
for p in sorted(root.rglob('*')):
    if '__pycache__' in p.parts or p.suffix == '.pyc': continue
    if p.is_symlink(): raise RuntimeError('app_symlink')
    if p.is_file(): tree[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
if current:
    if {k:tree.get(k) for k in expected} != expected: raise RuntimeError('six_file_mismatch')
source=SimpleNamespace(source_name='education.news.cn',source_url='https://education.news.cn/fixture/c.html')
article=SimpleNamespace(title='科学教育来源测试',digest='科学教育来源测试',lead='从观察开始。',
    sections=(),conclusion='保持真实来源。',author='程岳',sources=(source,source))
header,header_bytes,footer,footer_bytes=load_official_account_marketing_framing()
old=render_editor_handoff_v2_body(article=article,media=(),header=header,footer=footer).body_html
if old.count('查看权威原文') != 2: raise RuntimeError('legacy_render_changed')
v1=render_editor_handoff_v2_body(article=article,media=(),header=header,footer=footer,
    source_presentation=READABLE_SOURCE_PRESENTATION_VERSION).body_html
if v1.count('新闻来源：新华网') != 1 or '阅读原文' not in v1: raise RuntimeError('v1_changed')
preserved={'untouched':{k:v for k,v in tree.items() if k not in expected},
    'legacy_html':hashlib.sha256(old.encode()).hexdigest(),
    'v1_html':hashlib.sha256(v1.encode()).hexdigest(),
    'banners':[hashlib.sha256(b).hexdigest() for b in (header_bytes,footer_bytes)]}
policy=None
if current:
    from app.domain.official_account_source_presentation import (
        CURRENT_SOURCE_PRESENTATION_VERSION,NO_LINK_SOURCE_PRESENTATION_VERSION,
        source_presentation_content_url,
    )
    if CURRENT_SOURCE_PRESENTATION_VERSION != NO_LINK_SOURCE_PRESENTATION_VERSION or CURRENT_SOURCE_PRESENTATION_VERSION != 'wechat-source-presentation-v2-no-links': raise RuntimeError('v2_version')
    v2=render_readable_sources(article,version=CURRENT_SOURCE_PRESENTATION_VERSION)
    forbidden=('<a','href=','http','阅读原文','查看原文','查看权威原文')
    if v2.count('新闻来源：新华网') != 1 or any(v in v2 for v in forbidden): raise RuntimeError('v2_sources')
    if source_presentation_content_url(article,CURRENT_SOURCE_PRESENTATION_VERSION) is not None: raise RuntimeError('v2_url')
    requests=[]
    async def draft_payload():
        async def handler(request):
            payload=json.loads(request.content);requests.append((request.url.path,payload))
            if request.url.path == '/cgi-bin/stable_token':
                return httpx.Response(200,json={'access_token':'fixture-token','expires_in':7200})
            return httpx.Response(200,json={'media_id':'fixture-draft'})
        transport=httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client=WeChatOfficialAccountApiClient(client=http,app_id=SecretStr('fixture-app'),app_secret=SecretStr('fixture-secret'))
            await client.add_draft(WeChatDraftArticleRequest(title='科学教育',author='程岳',digest='摘要',content=v2,
                content_source_url=None,thumb_media_id='fixture-thumb',need_open_comment=False,only_fans_can_comment=False))
    asyncio.run(draft_payload())
    if [v[0] for v in requests] != ['/cgi-bin/stable_token','/cgi-bin/draft/add']: raise RuntimeError('draft_routes')
    outgoing=requests[-1][1]
    if 'content_source_url' in outgoing['articles'][0]: raise RuntimeError('draft_source_field')
    policy={'version':CURRENT_SOURCE_PRESENTATION_VERSION,'content_source_url':None,
        'draft_source_field_present':False,'v2_html':hashlib.sha256(v2.encode()).hexdigest()}
print(json.dumps({'preserved':preserved,'policy':policy},sort_keys=True))
"""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def validate_historical_cohort(rows: object, business_date: str) -> tuple[str, ...]:
    """Permit only the sealed, unclaimable historical jobs; never a preview-wide exemption."""
    require(isinstance(rows, list) and len(rows) == 7, "historical_cohort_count")
    assert isinstance(rows, list)
    encoded = json.dumps(
        rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    require(
        hashlib.sha256(encoded).hexdigest() == HISTORICAL_COHORT_SHA256,
        "historical_cohort_changed",
    )
    today = date.fromisoformat(business_date)
    ids: list[str] = []
    dates: list[str] = []
    for row in rows:
        require(
            isinstance(row, dict) and set(row) == {"job", "run"},
            "historical_cohort_shape",
        )
        job, run = row["job"], row["run"]
        require(
            isinstance(job, dict) and isinstance(run, dict), "historical_cohort_shape"
        )
        require(
            job["status"] == "queued"
            and type(job["attempt_count"]) is int
            and job["attempt_count"] == 0
            and all(
                job[field] is None
                for field in ("lease_owner", "lease_token", "lease_expires_at")
            )
            and run["scoring_profile"] == "preview"
            and run["timezone"] == "Asia/Shanghai"
            and job["run_id"] == run["id"],
            "historical_cohort_state",
        )
        require(
            isinstance(job["id"], str)
            and re.fullmatch(r"[0-9a-f-]{36}", job["id"]) is not None,
            "historical_cohort_identity",
        )
        require(isinstance(run["business_date"], str), "historical_cohort_date")
        require(
            date.fromisoformat(run["business_date"]) < today,
            "historical_cohort_claimable",
        )
        ids.append(job["id"])
        dates.append(run["business_date"])
    require(
        len(set(ids)) == 7 and tuple(sorted(dates)) == HISTORICAL_DATES,
        "historical_cohort_membership",
    )
    return tuple(ids)


def _epoch(value: object, code: str) -> Decimal:
    require(
        isinstance(value, str)
        and re.fullmatch(r"[0-9]{10}(?:\.[0-9]{1,6})?", value) is not None,
        code,
    )
    assert isinstance(value, str)
    return Decimal(value)


def validate_future_wecom_jobs(
    snapshot: object, *, minimum_lead_seconds: int
) -> tuple[int, str]:
    """Permit only a bounded, frozen set of future nonclaimable formal jobs."""
    require(
        type(minimum_lead_seconds) is int and minimum_lead_seconds >= 0,
        "wecom_lead_seconds",
    )
    require(
        isinstance(snapshot, dict) and set(snapshot) == {"observed_at_epoch", "jobs"},
        "wecom_snapshot_shape",
    )
    assert isinstance(snapshot, dict)
    observed_at = _epoch(snapshot["observed_at_epoch"], "wecom_observed_at")
    rows = snapshot["jobs"]
    require(
        isinstance(rows, list) and len(rows) <= MAX_FUTURE_WECOM_JOBS,
        "wecom_future_count",
    )
    assert isinstance(rows, list)
    expected_fields = {
        "id",
        "delivery_window_id",
        "content_slot_selection_id",
        "sequence_ordinal",
        "mode",
        "status",
        "text_status",
        "image_status",
        "include_copy",
        "include_image",
        "attempt_count",
        "next_attempt_at_epoch",
        "not_before_epoch",
        "expires_at_epoch",
        "lease_owner",
        "lease_token",
        "lease_expires_at_epoch",
        "heartbeat_at_epoch",
        "last_error_code",
        "created_at_epoch",
        "started_at_epoch",
        "completed_at_epoch",
        "attempt_rows",
    }
    uuid_pattern = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    )
    identities: list[str] = []
    for row in rows:
        require(
            isinstance(row, dict) and set(row) == expected_fields,
            "wecom_future_shape",
        )
        assert isinstance(row, dict)
        identity = row["id"]
        window_id = row["delivery_window_id"]
        selection_id = row["content_slot_selection_id"]
        ordinal = row["sequence_ordinal"]
        require(
            isinstance(identity, str)
            and uuid_pattern.fullmatch(identity) is not None
            and isinstance(window_id, str)
            and uuid_pattern.fullmatch(window_id) is not None
            and isinstance(selection_id, str)
            and uuid_pattern.fullmatch(selection_id) is not None
            and type(ordinal) is int
            and 1 <= ordinal <= 3,
            "wecom_future_identity",
        )
        assert isinstance(identity, str)
        assert isinstance(window_id, str)
        assert isinstance(ordinal, int)
        require(identity not in identities, "wecom_future_duplicate")
        identities.append(identity)
        require(
            row["mode"] == "formal"
            and row["status"] == "queued"
            and row["text_status"] == "pending"
            and row["image_status"] == "pending"
            and row["include_copy"] is True
            and row["include_image"] is True
            and type(row["attempt_count"]) is int
            and row["attempt_count"] == 0
            and type(row["attempt_rows"]) is int
            and row["attempt_rows"] == 0,
            "wecom_future_state",
        )
        require(
            all(
                row[field] is None
                for field in (
                    "lease_owner",
                    "lease_token",
                    "lease_expires_at_epoch",
                    "heartbeat_at_epoch",
                    "last_error_code",
                    "started_at_epoch",
                    "completed_at_epoch",
                )
            ),
            "wecom_future_started",
        )
        created_at = _epoch(row["created_at_epoch"], "wecom_future_created_at")
        next_attempt_at = _epoch(
            row["next_attempt_at_epoch"], "wecom_future_next_attempt_at"
        )
        not_before = _epoch(row["not_before_epoch"], "wecom_future_not_before")
        expires_at = _epoch(row["expires_at_epoch"], "wecom_future_expires_at")
        require(
            created_at <= observed_at
            and next_attempt_at == not_before
            and not_before > observed_at
            and not_before - observed_at >= minimum_lead_seconds
            and expires_at > not_before,
            "wecom_future_window",
        )
    require(identities == sorted(identities), "wecom_future_order")
    encoded = json.dumps(
        rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return len(rows), hashlib.sha256(encoded).hexdigest()


def validate_owner_rows(rows: object) -> str:
    """Bind the activated M/W/F history barrier without exposing row values."""
    require(
        isinstance(rows, list) and len(rows) == EXPECTED_OWNER_ROWS, "owner_row_count"
    )
    assert isinstance(rows, list)
    keys: set[tuple[str, str]] = set()
    barrier_count = 0
    for row in rows:
        require(isinstance(row, dict), "owner_row_shape")
        assert isinstance(row, dict)
        required = {
            "account_fingerprint",
            "key_kind",
            "key_value",
            "owner",
            "status",
            "provenance_fingerprint",
            "created_at",
            "updated_at",
        }
        require(required <= set(row), "owner_row_shape")
        created_at_value = row["created_at"]
        updated_at_value = row["updated_at"]
        require(
            isinstance(created_at_value, str) and isinstance(updated_at_value, str),
            "owner_timestamp",
        )
        assert isinstance(created_at_value, str)
        assert isinstance(updated_at_value, str)
        try:
            created_at = datetime.fromisoformat(created_at_value)
            updated_at = datetime.fromisoformat(updated_at_value)
        except ValueError as exc:
            raise RuntimeError("owner_timestamp") from exc
        require(
            created_at.utcoffset() is not None
            and updated_at.utcoffset() is not None
            and updated_at >= created_at,
            "owner_timestamp",
        )
        require(row["account_fingerprint"] == SINGLE_ACCOUNT, "owner_account")
        kind, value = row["key_kind"], row["key_value"]
        require(
            isinstance(kind, str)
            and kind in {"article", "event", "history"}
            and isinstance(value, str)
            and 1 <= len(value) <= 64,
            "owner_key",
        )
        key = (kind, value)
        require(key not in keys, "owner_duplicate")
        keys.add(key)
        require(
            isinstance(row["owner"], str)
            and 1 <= len(row["owner"]) <= 120
            and isinstance(row["provenance_fingerprint"], str)
            and re.fullmatch(r"[0-9a-f]{64}", row["provenance_fingerprint"])
            is not None,
            "owner_identity",
        )
        if key == ("history", "import-v1"):
            barrier_count += 1
            require(
                row["owner"] == "history-import-v1" and row["status"] == "ready",
                "owner_barrier",
            )
        else:
            require(
                kind in {"article", "event"}
                and row["status"] in {"acknowledged", "conflict"},
                "owner_status",
            )
    require(barrier_count == 1, "owner_barrier")
    # The single-edition scheduler intentionally refreshes only updated_at.
    # Freeze every other stored field so control/ownership drift still fails closed.
    safety_rows = [
        {key: value for key, value in row.items() if key != "updated_at"}
        for row in rows
    ]
    encoded = json.dumps(
        safety_rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def replace_json_value(value: object, old: str, new: str) -> object:
    if isinstance(value, dict):
        return {key: replace_json_value(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_json_value(item, old, new) for item in value]
    return new if value == old else value


def safe_file(path: Path) -> bytes:
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink_input")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "unsafe_file")
        require(before.st_size <= 2 * 1024 * 1024, "metadata_oversized")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            require(bool(chunk), "short_file_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        current = path.lstat()
        require(
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
            "file_changed_during_read",
        )
        return b"".join(chunks)
    finally:
        os.close(fd)


def file_hash(path: Path) -> str:
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink_archive")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "unsafe_archive")
        digest = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            digest.update(block)
        after = os.fstat(fd)
        current = path.lstat()
        require(
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
            "archive_changed_during_read",
        )
        return digest.hexdigest()
    finally:
        os.close(fd)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    require(len(result) == len(pairs), "duplicate_manifest_key")
    return result


def load_manifest(path: Path, expected_hash: str) -> dict[str, Any]:
    raw = safe_file(path)
    require(hashlib.sha256(raw).hexdigest() == expected_hash, "manifest_hash")
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "version",
            "revision",
            "previous_revision",
            "base_ref",
            "base_archive_sha256",
            "candidate_tag",
            "candidate_ref",
            "candidate_image_id",
            "archive",
            "archive_sha256",
            "app_files",
            "validator",
            "validator_sha256",
        },
        "manifest_fields",
    )
    require(
        all(isinstance(value[key], str) for key in set(value) - {"app_files"})
        and value["app_files"] == FILES,
        "manifest_types",
    )
    require(value["version"] == "no-source-links-offline-v1", "manifest_version")
    require(
        re.fullmatch(r"[0-9a-f]{40}", value["revision"]) is not None
        and value["revision"] != PREVIOUS_REVISION,
        "revision_mismatch",
    )
    require(
        value["previous_revision"] == PREVIOUS_REVISION
        and value["base_ref"] == PREVIOUS_REF,
        "base_identity",
    )
    require(
        value["base_archive_sha256"] == BASE_ARCHIVE_SHA256,
        "base_archive_hash",
    )
    require(
        re.fullmatch(
            re.escape(REPOSITORY) + r":no-source-links-[0-9a-f]{12}",
            value["candidate_tag"],
        )
        is not None,
        "tag",
    )
    require(value["candidate_tag"].endswith(value["revision"][:12]), "tag_revision")
    require(
        re.fullmatch(
            re.escape(REPOSITORY) + r"@sha256:[0-9a-f]{64}", value["candidate_ref"]
        )
        is not None,
        "reference",
    )
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value["candidate_image_id"]) is not None,
        "image_id",
    )
    require(
        value["candidate_ref"] == REPOSITORY + "@" + value["candidate_image_id"],
        "candidate_reference_identity",
    )
    require(
        value["candidate_ref"] != PREVIOUS_REF
        and value["candidate_image_id"] != PREVIOUS_ID,
        "unchanged_image",
    )
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.tar(?:\.gz)?", value["archive"])
        is not None,
        "archive_name",
    )
    require(
        re.fullmatch(r"[0-9a-f]{64}", value["archive_sha256"]) is not None,
        "archive_hash_shape",
    )
    require(
        value["validator"] == "validate-no-source-link-overlay.py"
        and re.fullmatch(r"[0-9a-f]{64}", value["validator_sha256"]) is not None,
        "validator_identity",
    )
    return cast(dict[str, Any], value)


def replace_image(body: bytes, reference: str) -> bytes:
    old = b"APP_IMAGE=" + PREVIOUS_REF.encode()
    rows = body.splitlines(keepends=True)
    matches = [
        i for i, line in enumerate(rows) if line.strip().startswith(b"APP_IMAGE=")
    ]
    require(
        len(matches) == 1 and rows[matches[0]].rstrip(b"\r\n") == old,
        "base_release_env",
    )
    i = matches[0]
    rows[i] = rows[i].replace(old, b"APP_IMAGE=" + reference.encode(), 1)
    return b"".join(rows)


def atomic_restore(path: Path, body: bytes, details: os.stat_result) -> None:
    require(not path.is_symlink(), "marker_symlink")
    fd, name = tempfile.mkstemp(prefix=".source-presentation-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), details.st_uid, details.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(details.st_mode))
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        require(not path.is_symlink(), "marker_symlink")
        os.replace(name, path)
        name = ""
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if name:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass


class Deployment:
    def __init__(self, manifest_path: Path, manifest: dict[str, Any]):
        self.manifest_path = manifest_path
        self.manifest = manifest
        self.before: dict[str, tuple[bytes, os.stat_result]] = {}
        self.dependencies: dict[str, str] = {}
        self.env_hash = ""
        self.compose_hash = ""
        self.base_inspect: dict[str, Any] | None = None
        self.primary_env: tuple[bytes, os.stat_result] | None = None
        self.compose_snapshot: tuple[bytes, os.stat_result] | None = None
        self.owner_sha256: str | None = None
        self.future_wecom_count: int | None = None
        self.future_wecom_sha256: str | None = None
        self.base_config: dict[str, object] | None = None
        self.backup_dir = BACKUP_ROOT / ("no-source-links-" + manifest["revision"][:12])

    def log(self, phase: str) -> None:
        print("source_presentation_deploy phase=" + phase, flush=True)

    def command(
        self, args: list[str], *, timeout: int = 60, image: str | None = None
    ) -> str:
        env = {
            k: v
            for k, v in os.environ.items()
            if k != "APP_IMAGE" and not k.startswith("COMPOSE_")
        }
        if image is not None:
            env["APP_IMAGE"] = image
        try:
            result = subprocess.run(
                args,
                cwd=APP,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise RuntimeError("command_failed") from exc
        return result.stdout

    def compose(self, *args: str, timeout: int = 60, image: str | None = None) -> str:
        command = [
            "docker",
            "compose",
            "--project-name",
            "edu-ai-lead-agent",
            "-f",
            str(APP / "compose.yaml"),
            "--env-file",
            str(APP / ".env"),
            "--env-file",
            str(APP / ".release.env"),
        ]
        for profile in PROFILES:
            command.extend(("--profile", profile))
        return self.command([*command, *args], timeout=timeout, image=image)

    def scalar(self, query: str) -> str:
        return self.compose(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
            "sh",
            query,
        ).strip()

    def inspect(self, identity: str, *, image: bool = False) -> dict[str, Any]:
        result = json.loads(
            self.command(
                ["docker", *(("image",) if image else ()), "inspect", identity]
            )
        )
        require(isinstance(result, list) and len(result) == 1, "inspect_count")
        return cast(dict[str, Any], result[0])

    def service(self, name: str) -> dict[str, Any]:
        ids = self.compose("ps", "-a", "-q", name).split()
        require(
            len(ids) == 1 and re.fullmatch(r"[0-9a-f]{64}", ids[0]) is not None,
            "service_count",
        )
        return self.inspect(ids[0])

    def idle(
        self, *, minimum_wecom_lead_seconds: int = MIN_WECOM_QUIESCE_LEAD_SECONDS
    ) -> None:
        business_date = self.scalar(BUSINESS_DATE_QUERY)
        before = validate_historical_cohort(
            json.loads(self.scalar(HISTORICAL_COHORT_QUERY)), business_date
        )
        wecom_before = validate_future_wecom_jobs(
            json.loads(self.scalar(WECOM_ACTIVE_QUERY)),
            minimum_lead_seconds=minimum_wecom_lead_seconds,
        )
        active_count = self.scalar(IDLE_QUERY)
        after = validate_historical_cohort(
            json.loads(self.scalar(HISTORICAL_COHORT_QUERY)), business_date
        )
        wecom_after = validate_future_wecom_jobs(
            json.loads(self.scalar(WECOM_ACTIVE_QUERY)),
            minimum_lead_seconds=minimum_wecom_lead_seconds,
        )
        single_count = self.scalar(SINGLE_EDITION_QUERY)
        owners_before = validate_owner_rows(json.loads(self.scalar(OWNER_QUERY)))
        owners_after = validate_owner_rows(json.loads(self.scalar(OWNER_QUERY)))
        if self.owner_sha256 is None:
            self.owner_sha256 = owners_before
        if self.future_wecom_count is None and self.future_wecom_sha256 is None:
            self.future_wecom_count, self.future_wecom_sha256 = wecom_before
        require(
            before == after
            and wecom_before == wecom_after
            and wecom_before == (self.future_wecom_count, self.future_wecom_sha256)
            and active_count == str(len(before) + wecom_before[0])
            and single_count == "0"
            and owners_before == owners_after == self.owner_sha256,
            "queue_or_owner_not_idle",
        )

    def config(self, reference: str) -> dict[str, Any]:
        value = json.loads(self.compose("config", "--format", "json", image=reference))
        require(
            all(value["services"][name]["image"] == reference for name in SERVICES),
            "compose_image",
        )
        for service in (
            "official-account-weekly-dag-worker",
            "official-account-weekly-scheduler",
            "wechat-official-account-draft-worker",
        ):
            environment = value["services"][service]["environment"]
            for key, expected in MWF_FLAGS.items():
                if key.startswith("OFFICIAL_ACCOUNT_SINGLE_") or key in environment:
                    require(
                        str(environment.get(key)).lower() == expected,
                        "mwf_flag_changed",
                    )
        if self.base_config is not None and reference != PREVIOUS_REF:
            require(
                replace_json_value(value, reference, PREVIOUS_REF) == self.base_config,
                "compose_non_image_changed",
            )
        return cast(dict[str, Any], value)

    def verify(
        self,
        reference: str,
        image_id: str,
        *,
        minimum_wecom_lead_seconds: int = MIN_WECOM_READY_LEAD_SECONDS,
    ) -> None:
        for name in SERVICES:
            item = self.service(name)
            require(
                item["Config"]["Image"] == reference and item["Image"] == image_id,
                "service_image",
            )
            require(
                item["State"]["Status"] == "running" and item["RestartCount"] == 0,
                "service_state",
            )
            require(
                item["State"].get("Health", {}).get("Status", "healthy") == "healthy",
                "service_health",
            )
        for name, identity in self.dependencies.items():
            item = self.service(name)
            require(
                item["Id"] == identity
                and item["State"]["Status"] == "running"
                and item["RestartCount"] == 0,
                "dependency_changed",
            )
            require(
                item["State"].get("Health", {}).get("Status") == "healthy",
                "dependency_health",
            )
        require(
            self.scalar("SELECT version_num FROM alembic_version") == SCHEMA,
            "schema_changed",
        )
        require(
            date.fromisoformat(self.scalar(BUSINESS_DATE_QUERY))
            < date.fromisoformat(MIN_SINGLE_DATE),
            "single_activation_window_elapsed",
        )
        health = json.loads(
            self.command(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--max-time",
                    "5",
                    "--max-filesize",
                    "65536",
                    "http://127.0.0.1:8000/healthz",
                ]
            )
        )
        require(
            health.get("status") == "ok" and health.get("environment") == "production",
            "api_health",
        )
        require(
            file_hash(APP / ".env") == self.env_hash
            and file_hash(APP / "compose.yaml") == self.compose_hash,
            "protected_config_changed",
        )
        for filename, (original, _details) in self.before.items():
            expected = (
                replace_image(original, reference)
                if filename == ".release.env"
                else original
                if reference == PREVIOUS_REF
                else (self.manifest["revision"] + "\n").encode()
            )
            require(safe_file(APP / filename) == expected, "active_marker_changed")
        self.idle(minimum_wecom_lead_seconds=minimum_wecom_lead_seconds)

    def wait_ready(
        self,
        reference: str,
        image_id: str,
        *,
        minimum_wecom_lead_seconds: int = MIN_WECOM_READY_LEAD_SECONDS,
    ) -> None:
        deadline = time.monotonic() + 90
        while True:
            try:
                self.verify(
                    reference,
                    image_id,
                    minimum_wecom_lead_seconds=minimum_wecom_lead_seconds,
                )
                return
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("startup_health_timeout") from None
                time.sleep(2)

    def preflight(self) -> None:
        require(os.geteuid() == 0, "root_required")
        backup_info = BACKUP_ROOT.stat()
        require(
            not BACKUP_ROOT.is_symlink()
            and stat.S_ISDIR(backup_info.st_mode)
            and backup_info.st_uid == 0
            and backup_info.st_gid == 0
            and stat.S_IMODE(backup_info.st_mode) == 0o700,
            "backup_root_unsafe",
        )
        require(
            not self.backup_dir.exists() and not self.backup_dir.is_symlink(),
            "backup_already_exists",
        )
        for filename in (".release.env", ".release-commit", "RELEASE_COMMIT"):
            path = APP / filename
            self.before[filename] = (safe_file(path), path.stat())
            details = self.before[filename][1]
            require(
                details.st_uid == 0
                and details.st_gid == 0
                and not stat.S_IMODE(details.st_mode) & 0o022,
                "release_marker_permissions",
            )
        require(
            self.before[".release-commit"][0].strip().decode() == PREVIOUS_REVISION,
            "live_revision",
        )
        require(
            self.before["RELEASE_COMMIT"][0].strip().decode()
            == PREVIOUS_LEGACY_REVISION,
            "live_legacy_revision",
        )
        replace_image(self.before[".release.env"][0], self.manifest["candidate_ref"])
        self.env_hash = file_hash(APP / ".env")
        self.primary_env = (safe_file(APP / ".env"), (APP / ".env").stat())
        self.compose_hash = file_hash(APP / "compose.yaml")
        self.compose_snapshot = (
            safe_file(APP / "compose.yaml"),
            (APP / "compose.yaml").stat(),
        )
        require(
            stat.S_IMODE(self.primary_env[1].st_mode) == 0o600
            and not stat.S_IMODE(self.compose_snapshot[1].st_mode) & 0o022,
            "protected_config_permissions",
        )
        self.base_inspect = self.inspect(PREVIOUS_REF, image=True)
        require(self.base_inspect["Id"] == PREVIOUS_ID, "live_image")
        require(
            self.base_inspect["Config"]
            .get("Labels", {})
            .get("org.opencontainers.image.revision")
            == PREVIOUS_REVISION,
            "live_label",
        )
        self.dependencies = {
            name: self.service(name)["Id"] for name in ("postgres", "minio")
        }
        self.base_config = self.config(PREVIOUS_REF)
        self.verify(
            PREVIOUS_REF,
            PREVIOUS_ID,
            minimum_wecom_lead_seconds=MIN_WECOM_QUIESCE_LEAD_SECONDS,
        )
        self.idle(minimum_wecom_lead_seconds=MIN_WECOM_QUIESCE_LEAD_SECONDS)

    def smoke(self, reference: str, current: bool) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                self.command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--pull",
                        "never",
                        "--network",
                        "none",
                        "--read-only",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--entrypoint",
                        "python",
                        reference,
                        "-B",
                        "-c",
                        SMOKE,
                        json.dumps(FILES),
                        "current" if current else "previous",
                    ],
                    timeout=60,
                )
            ),
        )

    def validate_archive(self) -> dict[str, Any]:
        archive = self.manifest_path.parent / self.manifest["archive"]
        require(file_hash(archive) == self.manifest["archive_sha256"], "archive_hash")
        validator = self.manifest_path.parent / self.manifest["validator"]
        require(
            file_hash(validator) == self.manifest["validator_sha256"],
            "validator_hash",
        )
        validated = json.loads(
            self.command(
                [
                    sys.executable,
                    "-B",
                    str(validator),
                    "--archive",
                    str(archive),
                    "--candidate-tag",
                    self.manifest["candidate_tag"],
                    "--candidate-ref",
                    self.manifest["candidate_ref"],
                    "--revision",
                    self.manifest["revision"],
                ],
                timeout=300,
            )
        )
        require(
            validated.get("status") == "valid"
            and validated.get("manifest_digest") == self.manifest["candidate_image_id"]
            and validated.get("base_manifest_digest") == PREVIOUS_ID
            and validated.get("overlay_layers") == 1,
            "archive_graph",
        )
        require(
            file_hash(archive) == self.manifest["archive_sha256"], "archive_changed"
        )
        return cast(dict[str, Any], validated)

    def load_candidate(self) -> None:
        archive = self.manifest_path.parent / self.manifest["archive"]
        self.validate_archive()
        self.command(["docker", "load", "-i", str(archive)], timeout=240)
        require(
            file_hash(archive) == self.manifest["archive_sha256"], "archive_changed"
        )
        by_tag = self.inspect(self.manifest["candidate_tag"], image=True)
        by_ref = self.inspect(self.manifest["candidate_ref"], image=True)
        require(
            by_tag["Id"] == by_ref["Id"] == self.manifest["candidate_image_id"],
            "candidate_identity",
        )
        require(
            by_ref["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
            == self.manifest["revision"],
            "candidate_label",
        )
        base = self.base_inspect
        require(base is not None, "missing_base")
        assert base is not None
        for key in set(base["Config"]) | set(by_ref["Config"]):
            if key != "Labels":
                require(
                    base["Config"].get(key) == by_ref["Config"].get(key),
                    "candidate_runtime_config_changed",
                )
        previous_layers, layers = base["RootFS"]["Layers"], by_ref["RootFS"]["Layers"]
        require(
            layers[: len(previous_layers)] == previous_layers
            and len(layers) - len(previous_layers) == 1,
            "candidate_not_overlay",
        )
        previous_smoke = self.smoke(PREVIOUS_REF, False)
        candidate_smoke = self.smoke(self.manifest["candidate_ref"], True)
        require(
            previous_smoke.get("preserved") == candidate_smoke.get("preserved"),
            "untouched_app_or_legacy_changed",
        )
        policy = candidate_smoke.get("policy")
        require(
            isinstance(policy, dict)
            and policy.get("version") == "wechat-source-presentation-v2-no-links"
            and policy.get("content_source_url") is None
            and policy.get("draft_source_field_present") is False,
            "no_link_policy_smoke",
        )
        self.config(self.manifest["candidate_ref"])

    def backup(self) -> None:
        self.backup_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        require(
            self.primary_env is not None and self.compose_snapshot is not None,
            "missing_environment_backup",
        )
        require(
            self.future_wecom_count is not None
            and self.future_wecom_sha256 is not None,
            "missing_wecom_snapshot",
        )
        assert self.primary_env is not None
        assert self.compose_snapshot is not None
        snapshots = {
            **self.before,
            ".env": self.primary_env,
            "compose.yaml": self.compose_snapshot,
        }
        metadata = {}
        for filename, (body, details) in snapshots.items():
            with (self.backup_dir / filename).open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            metadata[filename] = {
                "sha256": hashlib.sha256(body).hexdigest(),
                "mode": stat.S_IMODE(details.st_mode),
                "uid": details.st_uid,
                "gid": details.st_gid,
            }
        with (self.backup_dir / "file-metadata.json").open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(metadata, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        with (self.backup_dir / "candidate.json").open("xb") as stream:
            stream.write(json.dumps(self.manifest, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        preflight_state = {
            "future_nonclaimable_wecom_jobs": self.future_wecom_count,
            "future_nonclaimable_wecom_sha256": self.future_wecom_sha256,
            "future_wecom_minimum_lead_seconds": MIN_WECOM_QUIESCE_LEAD_SECONDS,
        }
        with (self.backup_dir / "preflight-state.json").open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(preflight_state, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())

    def success_receipt(self) -> None:
        # Primary .env is backed up but never installed/restored by this operator:
        # its only live configuration mutation is APP_IMAGE in .release.env.
        self.idle(minimum_wecom_lead_seconds=MIN_WECOM_READY_LEAD_SECONDS)
        require(
            self.future_wecom_count is not None
            and self.future_wecom_sha256 is not None,
            "missing_wecom_snapshot",
        )
        receipt = {
            "status": "deployed",
            "revision": self.manifest["revision"],
            "previous_revision": PREVIOUS_REVISION,
            "image_reference": self.manifest["candidate_ref"],
            "image_id": self.manifest["candidate_image_id"],
            "archive_sha256": self.manifest["archive_sha256"],
            "app_files": FILES,
            "schema_head": SCHEMA,
            "application_service_count": len(SERVICES),
            "model_calls": 0,
            "social_calls": 0,
            "migration_executed": False,
            "preserved_historical_copy_jobs": 7,
            "historical_cohort_sha256": HISTORICAL_COHORT_SHA256,
            "single_editions": 0,
            "draft_owner_rows": EXPECTED_OWNER_ROWS,
            "draft_owner_sha256": self.owner_sha256,
            "future_nonclaimable_wecom_jobs": self.future_wecom_count,
            "future_nonclaimable_wecom_sha256": self.future_wecom_sha256,
            "future_wecom_minimum_ready_lead_seconds": MIN_WECOM_READY_LEAD_SECONDS,
            "minimum_single_date": MIN_SINGLE_DATE,
            "standard_release_provenance": "incomplete",
        }
        with (self.backup_dir / "result.json").open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(receipt, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())

    def fence(self) -> None:
        for filename, (body, _details) in self.before.items():
            require(safe_file(APP / filename) == body, "live_marker_drift")
        self.verify(
            PREVIOUS_REF,
            PREVIOUS_ID,
            minimum_wecom_lead_seconds=MIN_WECOM_QUIESCE_LEAD_SECONDS,
        )
        self.idle(minimum_wecom_lead_seconds=MIN_WECOM_QUIESCE_LEAD_SECONDS)

    def post_quiescence_fence(self) -> None:
        """Recheck every protected activation input after writers have stopped."""
        require(
            self.primary_env is not None and self.compose_snapshot is not None,
            "missing_environment_backup",
        )
        assert self.primary_env is not None
        assert self.compose_snapshot is not None
        for filename, (body, _details) in self.before.items():
            require(safe_file(APP / filename) == body, "post_stop_marker_drift")
        require(
            safe_file(APP / ".env") == self.primary_env[0]
            and safe_file(APP / "compose.yaml") == self.compose_snapshot[0],
            "post_stop_config_drift",
        )
        require(
            self.scalar("SELECT version_num FROM alembic_version") == SCHEMA,
            "post_stop_schema_drift",
        )
        candidate = self.inspect(self.manifest["candidate_ref"], image=True)
        candidate_tag = self.inspect(self.manifest["candidate_tag"], image=True)
        require(
            candidate["Id"]
            == candidate_tag["Id"]
            == self.manifest["candidate_image_id"]
            and candidate["Config"]
            .get("Labels", {})
            .get("org.opencontainers.image.revision")
            == self.manifest["revision"],
            "post_stop_candidate_drift",
        )
        self.config(self.manifest["candidate_ref"])
        self.idle(minimum_wecom_lead_seconds=MIN_WECOM_QUIESCE_LEAD_SECONDS)

    def stop(self) -> None:
        self.compose("stop", "-t", "30", *STOP_ORDER, timeout=120)

    def activate(self) -> None:
        body, details = self.before[".release.env"]
        atomic_restore(
            APP / ".release.env",
            replace_image(body, self.manifest["candidate_ref"]),
            details,
        )
        atomic_restore(
            APP / ".release-commit",
            (self.manifest["revision"] + "\n").encode(),
            self.before[".release-commit"][1],
        )
        atomic_restore(
            APP / "RELEASE_COMMIT",
            (self.manifest["revision"] + "\n").encode(),
            self.before["RELEASE_COMMIT"][1],
        )

    def start(self, reference: str) -> None:
        self.compose(
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--pull",
            "never",
            "--force-recreate",
            *SERVICES,
            timeout=180,
            image=reference,
        )

    def rollback(self) -> None:
        self.log("rollback_started")
        failures = []
        try:
            self.stop()
        except BaseException:  # noqa: BLE001 -- rollback must survive cancellation and signals
            failures.append("stop")
        for filename, (body, details) in self.before.items():
            try:
                atomic_restore(APP / filename, body, details)
            except BaseException:  # noqa: BLE001 -- continue the best-effort rollback sequence
                failures.append("restore")
        try:
            self.start(PREVIOUS_REF)
            self.wait_ready(
                PREVIOUS_REF,
                PREVIOUS_ID,
                minimum_wecom_lead_seconds=0,
            )
        except BaseException:  # noqa: BLE001 -- record terminal recovery failure
            failures.append("restart")
            try:
                self.stop()
            except BaseException:  # noqa: BLE001 -- keep recovery fail-closed
                failures.append("incident_stop")
        require(not failures, "rollback_incomplete")
        self.log("rollback_completed")


def execute(operation: Deployment) -> None:
    operation.log("preflight")
    operation.preflight()
    operation.log("load_and_smoke_before_stop")
    operation.load_candidate()
    operation.backup()
    operation.fence()
    # Set before stop: a failing command may already have stopped several writers.
    quiesce_attempted = False
    try:
        operation.log("quiesce")
        quiesce_attempted = True
        operation.stop()
        operation.post_quiescence_fence()
        operation.activate()
        operation.log("start_candidate")
        operation.start(operation.manifest["candidate_ref"])
        operation.wait_ready(
            operation.manifest["candidate_ref"],
            operation.manifest["candidate_image_id"],
        )
        operation.success_receipt()
        operation.log("completed")
    except BaseException:
        if quiesce_attempted:
            operation.rollback()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly authorize this one deployment",
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        require(os.geteuid() == 0, "root_required")
        manifest = load_manifest(args.manifest.absolute(), args.manifest_sha256)
        if not args.execute:
            Deployment(args.manifest.absolute(), manifest).validate_archive()
            print(
                "source_presentation_deploy phase=manifest_validated_no_execution",
                flush=True,
            )
            return 0
        fd = os.open(
            LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
        )
        with os.fdopen(fd, "w") as lock:
            lock_info = os.fstat(lock.fileno())
            require(
                stat.S_ISREG(lock_info.st_mode)
                and lock_info.st_nlink == 1
                and lock_info.st_uid == 0
                and lock_info.st_gid == 0
                and stat.S_IMODE(lock_info.st_mode) == 0o600,
                "unsafe_deployment_lock",
            )
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def interrupted(_signum: int, _frame: object) -> NoReturn:
                raise RuntimeError("deployment_interrupted")

            signal.signal(signal.SIGTERM, interrupted)
            execute(Deployment(args.manifest.absolute(), manifest))
    except BaseException as exc:  # noqa: BLE001 -- emit one bounded operator error code
        code = (
            str(exc)
            if type(exc) is RuntimeError and re.fullmatch(r"[a-z_]+", str(exc))
            else "operation_failed"
        )
        print("source_presentation_deploy phase=failed code=" + code, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
