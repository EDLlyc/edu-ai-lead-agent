"""Crash-visible started/terminal attempt journal with a validated SHA-256 chain."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .io import MAX_JOURNAL_BYTES, ModelPanelIOError, SecureEvidenceStore
from .models import (
    AttemptJournalRecord,
    AttemptStatus,
    JournalEventKind,
    PanelAttempt,
    canonical_json_bytes,
    evidence_sha256,
    require_aware,
)
from .parsing import ModelPanelParseError, strict_json_object
from .privacy import PrivacyProfile, require_privacy_safe


class AttemptJournalError(ValueError):
    """The append-only attempt lifecycle or hash chain is invalid."""


class AttemptJournal:
    def __init__(self, *, store: SecureEvidenceStore, path: Path) -> None:
        self._store = store
        self._path = store.require_output_path(path)

    def append(self, attempt: PanelAttempt, *, recorded_at: datetime) -> AttemptJournalRecord:
        moment = require_aware(recorded_at, label="journal append time")
        require_privacy_safe(attempt, profile=PrivacyProfile.PRIVATE_EVIDENCE)
        appended: AttemptJournalRecord | None = None

        def build(current: bytes) -> bytes:
            nonlocal appended
            records = _parse_records(current)
            if records and moment < records[-1].recorded_at:
                raise AttemptJournalError("journal timestamps must be monotonic")
            _validate_next(records, attempt)
            previous = None if not records else records[-1].event_sha256
            event_kind = (
                JournalEventKind.ATTEMPT_STARTED
                if attempt.status is AttemptStatus.STARTED
                else JournalEventKind.ATTEMPT_TERMINAL
            )
            payload: dict[str, object] = {
                "schema_version": "model-panel-journal-v1",
                "seq_no": len(records),
                "event_kind": event_kind,
                "recorded_at": moment,
                "attempt": attempt,
                "previous_event_sha256": previous,
            }
            appended = AttemptJournalRecord(
                schema_version="model-panel-journal-v1",
                seq_no=len(records),
                event_kind=event_kind,
                recorded_at=moment,
                attempt=attempt,
                previous_event_sha256=previous,
                event_sha256=evidence_sha256(payload),
            )
            require_privacy_safe(appended, profile=PrivacyProfile.PRIVATE_EVIDENCE)
            return canonical_json_bytes(appended) + b"\n"

        self._store.append_line_locked(self._path, build)
        if appended is None:
            raise AttemptJournalError("journal append did not produce a record")
        return appended

    def load(self) -> tuple[AttemptJournalRecord, ...]:
        try:
            payload = self._store.read_bytes(self._path, maximum=MAX_JOURNAL_BYTES)
            return _parse_records(payload)
        except ModelPanelIOError as exc:
            raise AttemptJournalError("attempt journal could not be loaded") from exc


def _parse_records(payload: bytes) -> tuple[AttemptJournalRecord, ...]:
    if not payload:
        return ()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AttemptJournalError("attempt journal must be UTF-8") from exc
    if not text.endswith("\n"):
        raise AttemptJournalError("attempt journal ends with an incomplete row")
    lines = text.splitlines()
    if not lines or any(not line for line in lines):
        raise AttemptJournalError("attempt journal contains an empty row")
    records: list[AttemptJournalRecord] = []
    for line in lines:
        try:
            raw = strict_json_object(line)
            record = AttemptJournalRecord.model_validate_json(canonical_json_bytes(raw))
        except (ModelPanelParseError, ValidationError) as exc:
            raise AttemptJournalError("attempt journal row is invalid") from exc
        expected_previous = None if not records else records[-1].event_sha256
        if record.seq_no != len(records) or record.previous_event_sha256 != expected_previous:
            raise AttemptJournalError("attempt journal chain is not contiguous")
        if records and record.recorded_at < records[-1].recorded_at:
            raise AttemptJournalError("journal timestamps must be monotonic")
        records.append(record)
    _validate_lifecycles(records)
    return tuple(records)


def _validate_lifecycles(records: list[AttemptJournalRecord]) -> None:
    starts: dict[str, PanelAttempt] = {}
    terminals: set[str] = set()
    for record in records:
        attempt_ref = record.attempt.attempt_ref
        if record.event_kind is JournalEventKind.ATTEMPT_STARTED:
            if attempt_ref in starts:
                raise AttemptJournalError("attempt journal contains a duplicate start")
            starts[attempt_ref] = record.attempt
        else:
            started = starts.get(attempt_ref)
            if started is None or attempt_ref in terminals:
                raise AttemptJournalError("attempt terminal is missing one unique start")
            _validate_terminal_binding(started, record.attempt)
            terminals.add(attempt_ref)


def _validate_next(
    records: tuple[AttemptJournalRecord, ...],
    attempt: PanelAttempt,
) -> None:
    starts = {
        record.attempt.attempt_ref: record.attempt
        for record in records
        if record.event_kind is JournalEventKind.ATTEMPT_STARTED
    }
    terminals = {
        record.attempt.attempt_ref
        for record in records
        if record.event_kind is JournalEventKind.ATTEMPT_TERMINAL
    }
    if attempt.status is AttemptStatus.STARTED:
        if attempt.attempt_ref in starts:
            raise AttemptJournalError("attempt already has a started event")
        return
    started = starts.get(attempt.attempt_ref)
    if started is None or attempt.attempt_ref in terminals:
        raise AttemptJournalError("terminal attempt requires one open started event")
    _validate_terminal_binding(started, attempt)


def _validate_terminal_binding(started: PanelAttempt, terminal: PanelAttempt) -> None:
    fields = (
        "run_ref",
        "manifest_sha256",
        "authorization_sha256",
        "attempt_ref",
        "pair_ref",
        "case_ref",
        "evaluator_model_ref",
        "presentation_order",
        "repeat_index",
        "request_fingerprint",
        "max_attempts",
        "started_at",
    )
    if any(getattr(started, field) != getattr(terminal, field) for field in fields):
        raise AttemptJournalError("terminal attempt drifted from its started identity")
