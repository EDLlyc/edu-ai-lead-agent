#!/usr/bin/env python3
"""Read-only production snapshot; output only counts/hashes and exact target states."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "release_common", Path(__file__).with_name("release-common.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = _load()
HISTORY_TABLES = (
    "official_account_single_editions",
    "official_account_article_runs",
    "official_account_article_versions",
    "official_account_article_context_images",
    "official_account_article_attempts",
    "official_account_render_versions",
    "official_account_generated_visuals",
    "official_account_strict_visual_audits",
    "official_account_generated_visual_evals",
    "official_account_local_media",
    "official_account_local_drafts",
    "official_account_local_draft_body_media",
    "official_account_manual_reviews",
    "official_account_weekly_dag_runs",
    "official_account_weekly_dag_nodes",
    "official_account_weekly_dag_attempts",
    "wechat_mp_draft_jobs",
    "wechat_mp_draft_items",
    "wechat_mp_draft_attempts",
)
RUNTIME_METADATA = {
    ".env": {"mode": 0o600, "uid": 1000, "gid": 1001},
    "compose.yaml": {"mode": 0o600, "uid": 0, "gid": 0},
}
INDEX_SNAPSHOT_QUERY = f"""(
SELECT jsonb_build_object(
 'name',c.relname,
 'table',t.relname,
 'unique',i.indisunique,
 'valid',i.indisvalid,
 'ready',i.indisready,
 'columns',(SELECT jsonb_agg(a.attname ORDER BY k.ord)
   FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum,ord)
   JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
   WHERE k.ord <= i.indnkeyatts),
 'predicate',pg_get_expr(i.indpred,i.indrelid))
FROM pg_index i
JOIN pg_class c ON c.oid=i.indexrelid
JOIN pg_class t ON t.oid=i.indrelid
WHERE c.relname='{C.BODY_CHECKSUM_INDEX}' AND pg_table_is_visible(t.oid))"""


def runtime_files(root: Path = Path("/opt/edu-ai-lead-agent")) -> dict:
    base = C.archived("deploy")
    result = {}
    for name in (".env", "compose.yaml"):
        path = root / name
        body = base.safe_file(path)
        info = path.stat()
        result[name] = {
            "sha256": C.digest(body),
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
        }
    return result


def snapshot_query() -> str:
    hashes = []
    for table in HISTORY_TABLES:
        hashes.append(
            "'"
            + table
            + "', (SELECT jsonb_build_object('count',count(*),'sha256',encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text,'UTF8')),'hex')) FROM "
            + table
            + " t)"
        )
    hashes.append(
        "'owners', (SELECT jsonb_build_object('count',count(*),'sha256',encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(t)-'updated_at' ORDER BY account_fingerprint,key_kind,key_value),'[]'::jsonb)::text,'UTF8')),'hex')) FROM official_account_draft_owners t)"
    )
    return (
        "SELECT jsonb_build_object('database',jsonb_build_object("
        + "'schema_head',(SELECT version_num FROM alembic_version),"
        + "'body_checksum_index',"
        + INDEX_SNAPSHOT_QUERY
        + "),'history',jsonb_build_object("
        + ",".join(hashes)
        + "),'target',"
        + f"""(
SELECT jsonb_build_object(
 'edition_count',(SELECT count(*) FROM official_account_single_editions),
 'edition_id',e.id,'business_date',e.business_date,'status',e.status,
 'lease_clear',e.lease_token IS NULL AND e.lease_expires_at IS NULL,
 'article_run_id',e.article_run_id,'event_id',e.event_id,
 'prepared_absent',e.prepared_artifact IS NULL AND e.receipt_fingerprint IS NULL,
 'article_status',r.status,'article_stage',r.current_stage,
 'article_version_id',r.active_article_version_id,
 'article_lease_clear',r.lease_token IS NULL AND r.lease_owner IS NULL AND r.lease_expires_at IS NULL,
 'visual_count',(SELECT count(*) FROM official_account_generated_visuals WHERE run_id=r.id),
 'visual_id',v.id,'visual_status',v.status,'visual_version_id',v.article_version_id,
 'visual_run_id',v.run_id,'visual_error',v.error_code,
 'owner_count',(SELECT count(*) FROM official_account_draft_owners WHERE owner=e.id::text),
 'owner_valid',EXISTS(SELECT 1 FROM official_account_draft_owners o WHERE o.owner=e.id::text AND o.key_kind='event' AND o.key_value=e.event_id::text AND o.status='outcome_unknown' AND o.account_fingerprint=e.account_fingerprint)
) FROM official_account_single_editions e
JOIN official_account_article_runs r ON r.id=e.article_run_id
JOIN official_account_generated_visuals v ON v.id='{C.VISUAL}'
WHERE e.id='{C.EDITION}') )::text"""
    )


def validate_snapshot(
    value: object,
    *,
    database_only: bool = False,
    expected_schema: str = C.PREVIOUS_SCHEMA,
) -> dict:
    expected_keys = (
        {"database", "history", "target"}
        if database_only
        else {"database", "history", "target", "runtime_files"}
    )
    C.require(isinstance(value, dict) and set(value) == expected_keys, "snapshot_shape")
    C.require(
        expected_schema in {C.PREVIOUS_SCHEMA, C.TARGET_SCHEMA},
        "snapshot_expected_schema",
    )
    database = value["database"]
    C.require(
        isinstance(database, dict)
        and set(database) == {"schema_head", "body_checksum_index"}
        and database["schema_head"] == expected_schema
        and database["body_checksum_index"]
        == (
            C.BODY_CHECKSUM_INDEX_BASELINE
            if expected_schema == C.PREVIOUS_SCHEMA
            else None
        ),
        "database_baseline_changed",
    )
    target = value["target"]
    C.require(isinstance(target, dict), "target_missing")
    expected = {
        "edition_count": 1,
        "edition_id": C.EDITION,
        "business_date": C.BUSINESS_DATE,
        "status": "outcome_unknown",
        "lease_clear": True,
        "article_run_id": C.ARTICLE,
        "prepared_absent": True,
        "article_status": "result_unknown",
        "article_stage": "result_unknown",
        "article_version_id": C.VERSION,
        "article_lease_clear": True,
        "visual_count": 1,
        "visual_id": C.VISUAL,
        "visual_status": "result_unknown",
        "visual_version_id": C.VERSION,
        "visual_run_id": C.ARTICLE,
        "visual_error": "official_account_generated_visual_result_unknown",
        "owner_count": 1,
        "owner_valid": True,
        "event_id": C.EVENT,
    }
    C.require(
        set(target) == set(expected)
        and all(
            type(target.get(key)) is type(expected_value)
            and target.get(key) == expected_value
            for key, expected_value in expected.items()
        ),
        "target_state_changed",
    )
    import re

    C.require(
        isinstance(target.get("event_id"), str)
        and re.fullmatch(r"[0-9a-f-]{36}", target["event_id"]) is not None,
        "target_event",
    )
    history = value["history"]
    C.require(
        isinstance(history, dict) and set(history) == {*HISTORY_TABLES, "owners"},
        "history_shape",
    )
    for row in history.values():
        C.require(
            isinstance(row, dict)
            and set(row) == {"count", "sha256"}
            and type(row["count"]) is int
            and row["count"] >= 0
            and isinstance(row["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
            "history_value",
        )
    C.require(
        history["official_account_single_editions"]["count"] == 1
        and history["owners"]["count"] == 15,
        "history_target_count",
    )
    if not database_only:
        files = value["runtime_files"]
        C.require(
            isinstance(files, dict) and set(files) == {".env", "compose.yaml"},
            "runtime_snapshot_shape",
        )
        for name, row in files.items():
            C.require(
                isinstance(row, dict)
                and set(row) == {"sha256", "mode", "uid", "gid"}
                and {key: row[key] for key in ("mode", "uid", "gid")}
                == RUNTIME_METADATA[name]
                and type(row["uid"]) is int
                and type(row["gid"]) is int
                and type(row["mode"]) is int
                and 0 <= row["mode"] <= 0o777
                and row["mode"] & 0o022 == 0
                and (name != ".env" or row["mode"] == 0o600)
                and isinstance(row["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
                "runtime_snapshot_value",
            )
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Read through the configured production SSH alias",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a new mode-0600 hash-only receipt; never overwrite",
    )
    args = parser.parse_args()
    query = (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY; "
        + snapshot_query()
        + "; ROLLBACK;"
    )
    docker = [
        "docker",
        "compose",
        "--project-name",
        "edu-ai-lead-agent",
        "-f",
        "/opt/edu-ai-lead-agent/compose.yaml",
        "--env-file",
        "/opt/edu-ai-lead-agent/.env",
        "--env-file",
        "/opt/edu-ai-lead-agent/.release.env",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        'exec psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At',
        "sh",
    ]
    import shlex

    command = (
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "edu-ai-production",
            "sudo -n " + shlex.join(docker),
        ]
        if args.remote
        else docker
    )
    result = subprocess.run(
        command, input=query, text=True, capture_output=True, timeout=45, check=False
    )
    C.require(result.returncode == 0, "snapshot_query_failed")
    value = validate_snapshot(json.loads(result.stdout), database_only=True)
    if args.remote:
        script = """import hashlib,json,pathlib,stat
result={}
for name in ('.env','compose.yaml'):
 p=pathlib.Path('/opt/edu-ai-lead-agent')/name
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1: raise RuntimeError('unsafe_file')
 result[name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid}
print(json.dumps(result))
"""
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                "edu-ai-production",
                "sudo -n python3 -c " + shlex.quote(script),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        C.require(result.returncode == 0, "runtime_snapshot_failed")
        value["runtime_files"] = json.loads(result.stdout)
    else:
        value["runtime_files"] = runtime_files()
    validate_snapshot(value)
    body = C.canonical(value)
    if args.output:
        with args.output.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        print(C.canonical({"status": "frozen", "sha256": C.digest(body)}).decode())
    else:
        print(body.decode())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
