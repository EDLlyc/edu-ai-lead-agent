from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from app.domain.governance_value_objects import stable_passage_id
from app.domain.value_objects import is_sha256_hex

_BOILERPLATE_PATTERNS = (
    re.compile(r"^(?:责任编辑|编辑|审核|校对)[\uff1a:]?\s*.{0,80}$"),
    re.compile(r"^(?:来源|稿件来源)[\uff1a:]?\s*.{0,100}$"),
    re.compile(r"^(?:版权声明|免责声明)[\uff1a:]?\s*.{0,120}$"),
    re.compile(r"^(?:上一篇|下一篇|返回首页|关闭窗口)(?:\s*.{0,40})?$"),
)
_SENSITIVE_PATTERNS = (
    (
        "national_id",
        "[REDACTED_NATIONAL_ID]",
        re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
        False,
    ),
    (
        "mobile_phone",
        "[REDACTED_MOBILE]",
        re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
        False,
    ),
    (
        "email",
        "[REDACTED_EMAIL]",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"),
        False,
    ),
    (
        "credential_material",
        "[QUARANTINED_CREDENTIAL]",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
            r"(?i:(?:api[_-]?key|access[_-]?token)\s*[:=]\s*[A-Za-z0-9_\-]{12,})"
        ),
        True,
    ),
)
_CJK_OR_WORD = re.compile(r"[\u3400-\u9fff]|[a-z0-9]+", re.IGNORECASE)
_SPLIT_BOUNDARIES = frozenset("。\uff01\uff1f!?\uff1b;\n")


@dataclass(frozen=True, slots=True)
class SensitiveDataSignal:
    kind: str
    count: int
    action: str


@dataclass(frozen=True, slots=True)
class NormalizedPassage:
    passage_id: UUID
    ordinal: int
    passage_hash: str
    text: str
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    candidate_id: UUID
    input_content_hash: str
    normalization_version: str
    passage_schema_version: str
    normalized_text: str
    normalized_hash: str
    simhash_hex: str
    passages: tuple[NormalizedPassage, ...]
    sensitive_data_signals: tuple[SensitiveDataSignal, ...]
    boilerplate_lines_removed: int
    requires_quarantine: bool


@dataclass(frozen=True, slots=True)
class _MappedCharacter:
    value: str
    source_start: int
    source_end: int


def normalized_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def simhash64(value: str) -> str:
    tokens = [token.casefold() for token in _CJK_OR_WORD.findall(value)]
    if not tokens:
        return "0000000000000000"
    features = (
        tokens
        if len(tokens) < 3
        else ["\x1e".join(tokens[i : i + 3]) for i in range(len(tokens) - 2)]
    )
    weights = [0] * 64
    for feature, count in Counter(features).items():
        digest = int.from_bytes(sha256(feature.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            weights[bit] += count if digest & (1 << bit) else -count
    result = 0
    for bit, weight in enumerate(weights):
        if weight > 0:
            result |= 1 << bit
    return f"{result:016x}"


def simhash_distance(first: str, second: str) -> int:
    if not re.fullmatch(r"[0-9a-fA-F]{16}", first) or not re.fullmatch(r"[0-9a-fA-F]{16}", second):
        raise ValueError("SimHash values must be 16 hexadecimal characters")
    return (int(first, 16) ^ int(second, 16)).bit_count()


def normalize_and_segment(
    *,
    candidate_id: UUID,
    source_text: str,
    normalization_version: str,
    passage_schema_version: str,
    input_content_hash: str | None = None,
    max_passage_characters: int = 1_200,
    min_passage_characters: int = 240,
) -> NormalizedDocument:
    if not source_text.strip():
        raise ValueError("source text must not be blank")
    if not normalization_version.strip() or not passage_schema_version.strip():
        raise ValueError("normalization and passage schema versions must not be blank")
    if max_passage_characters < 200:
        raise ValueError("maximum passage size must be at least 200 characters")
    if min_passage_characters < 1 or min_passage_characters > max_passage_characters:
        raise ValueError("minimum passage size must be positive and no larger than maximum")
    if input_content_hash is not None and not is_sha256_hex(input_content_hash):
        raise ValueError("input content hash must be a lowercase SHA-256 hex digest")

    mapped = _unicode_mapped_characters(source_text)
    mapped, sensitive_signals, requires_quarantine = _redact_sensitive_data(mapped)
    mapped, boilerplate_lines_removed = _normalize_layout(mapped)
    normalized_text = "".join(character.value for character in mapped)
    if not normalized_text:
        raise ValueError("normalization removed the complete source text")
    passages = _segment_passages(
        candidate_id=candidate_id,
        mapped=mapped,
        normalization_version=normalization_version,
        passage_schema_version=passage_schema_version,
        max_characters=max_passage_characters,
        min_characters=min_passage_characters,
    )
    return NormalizedDocument(
        candidate_id=candidate_id,
        input_content_hash=input_content_hash or normalized_sha256(source_text),
        normalization_version=normalization_version,
        passage_schema_version=passage_schema_version,
        normalized_text=normalized_text,
        normalized_hash=normalized_sha256(normalized_text),
        simhash_hex=simhash64(normalized_text),
        passages=passages,
        sensitive_data_signals=sensitive_signals,
        boilerplate_lines_removed=boilerplate_lines_removed,
        requires_quarantine=requires_quarantine,
    )


def _unicode_mapped_characters(source_text: str) -> list[_MappedCharacter]:
    decomposed: list[_MappedCharacter] = []
    index = 0
    while index < len(source_text):
        start = index
        if source_text[index] == "\r":
            index += 1
            if index < len(source_text) and source_text[index] == "\n":
                index += 1
            decomposed.append(_MappedCharacter("\n", start, index))
            continue
        index += 1
        for character in unicodedata.normalize("NFKD", source_text[start:index]):
            value = "\n" if character in {"\u2028", "\u2029"} else character
            decomposed.append(_MappedCharacter(value, start, index))
    return _compose_mapped_nfkc(decomposed)


def _compose_mapped_nfkc(decomposed: list[_MappedCharacter]) -> list[_MappedCharacter]:
    mapped: list[_MappedCharacter] = []
    cluster: list[_MappedCharacter] = []

    def flush_cluster() -> None:
        if not cluster:
            return
        normalized = unicodedata.normalize("NFC", "".join(character.value for character in cluster))
        source_start = min(character.source_start for character in cluster)
        source_end = max(character.source_end for character in cluster)
        mapped.extend(
            _MappedCharacter(character, source_start, source_end) for character in normalized
        )
        cluster.clear()

    for character in decomposed:
        if not cluster or unicodedata.combining(character.value):
            cluster.append(character)
            continue
        current = "".join(item.value for item in cluster)
        current_normalized = unicodedata.normalize("NFC", current)
        with_starter = unicodedata.normalize("NFC", current + character.value)
        if len(with_starter) < len(current_normalized) + 1:
            cluster.append(character)
            continue
        flush_cluster()
        cluster.append(character)
    flush_cluster()
    return mapped


def _redact_sensitive_data(
    mapped: list[_MappedCharacter],
) -> tuple[list[_MappedCharacter], tuple[SensitiveDataSignal, ...], bool]:
    signals: list[SensitiveDataSignal] = []
    requires_quarantine = False
    for kind, replacement, pattern, quarantine in _SENSITIVE_PATTERNS:
        text = "".join(character.value for character in mapped)
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        replaced: list[_MappedCharacter] = []
        cursor = 0
        for match in matches:
            replaced.extend(mapped[cursor : match.start()])
            source_start = mapped[match.start()].source_start
            source_end = mapped[match.end() - 1].source_end
            replaced.extend(
                _MappedCharacter(character, source_start, source_end) for character in replacement
            )
            cursor = match.end()
        replaced.extend(mapped[cursor:])
        mapped = replaced
        action = "quarantined" if quarantine else "redacted"
        signals.append(SensitiveDataSignal(kind=kind, count=len(matches), action=action))
        requires_quarantine = requires_quarantine or quarantine
    return mapped, tuple(signals), requires_quarantine


def _normalize_layout(mapped: list[_MappedCharacter]) -> tuple[list[_MappedCharacter], int]:
    lines: list[tuple[list[_MappedCharacter], _MappedCharacter | None]] = []
    current: list[_MappedCharacter] = []
    for character in mapped:
        if character.value == "\n":
            lines.append((_collapse_inline_whitespace(current), character))
            current = []
        else:
            current.append(character)
    lines.append((_collapse_inline_whitespace(current), None))

    result: list[_MappedCharacter] = []
    pending_newlines: list[_MappedCharacter] = []
    removed = 0
    for line, newline in lines:
        line_text = "".join(character.value for character in line)
        if (
            line_text
            and len(line_text) <= 160
            and any(pattern.fullmatch(line_text) for pattern in _BOILERPLATE_PATTERNS)
        ):
            removed += 1
            if newline is not None:
                pending_newlines.append(newline)
            continue
        if not line_text:
            if newline is not None:
                pending_newlines.append(newline)
            continue
        if result:
            separator_count = 2 if len(pending_newlines) >= 2 else 1
            separators = pending_newlines or [
                _MappedCharacter("\n", line[0].source_start, line[0].source_start)
            ]
            for separator_index in range(separator_count):
                source = separators[min(separator_index, len(separators) - 1)]
                result.append(_MappedCharacter("\n", source.source_start, source.source_end))
        result.extend(line)
        pending_newlines = [newline] if newline is not None else []
    return result, removed


def _collapse_inline_whitespace(line: list[_MappedCharacter]) -> list[_MappedCharacter]:
    collapsed: list[_MappedCharacter] = []
    whitespace_start: int | None = None
    whitespace_end: int | None = None
    for character in line:
        if character.value.isspace():
            whitespace_start = (
                character.source_start if whitespace_start is None else whitespace_start
            )
            whitespace_end = character.source_end
            continue
        if whitespace_start is not None and collapsed:
            collapsed.append(
                _MappedCharacter(" ", whitespace_start, whitespace_end or whitespace_start)
            )
        whitespace_start = None
        whitespace_end = None
        collapsed.append(character)
    return collapsed


def _segment_passages(
    *,
    candidate_id: UUID,
    mapped: list[_MappedCharacter],
    normalization_version: str,
    passage_schema_version: str,
    max_characters: int,
    min_characters: int,
) -> tuple[NormalizedPassage, ...]:
    text = "".join(character.value for character in mapped)
    passages: list[NormalizedPassage] = []
    start = 0
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text):
            break
        hard_end = min(start + max_characters, len(text))
        end = hard_end
        if hard_end < len(text):
            search_start = min(start + min_characters, hard_end)
            boundary = max(
                (
                    index
                    for index in range(search_start, hard_end)
                    if text[index] in _SPLIT_BOUNDARIES
                ),
                default=-1,
            )
            if boundary >= 0:
                end = boundary + 1
            else:
                open_marker = text.rfind("[", start, hard_end)
                close_marker = text.rfind("]", start, hard_end)
                if open_marker > close_marker and open_marker > start + min_characters:
                    end = open_marker
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start:
            end = hard_end
        passage_text = text[start:end]
        passage_hash = normalized_sha256(passage_text)
        ordinal = len(passages)
        passage_id = stable_passage_id(
            candidate_id,
            f"{normalization_version}:{passage_schema_version}",
            ordinal,
            passage_hash,
        )
        passages.append(
            NormalizedPassage(
                passage_id=passage_id,
                ordinal=ordinal,
                passage_hash=passage_hash,
                text=passage_text,
                source_start=mapped[start].source_start,
                source_end=mapped[end - 1].source_end,
            )
        )
        start = end
    return tuple(passages)
