from __future__ import annotations

import json
import re

_PROVIDER_JSON_MAX_CHARACTERS = 32_768
_PROVIDER_JSON_MAX_AFFIX_CHARACTERS = 512
_JSON_PRIMITIVE = re.compile(
    r'(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|"(?:[^"\\]|\\.)*")',
    re.DOTALL,
)


class ProviderJsonEnvelopeError(ValueError):
    __slots__ = ("validation_type",)

    def __init__(self, validation_type: str) -> None:
        super().__init__("provider JSON envelope is invalid")
        self.validation_type = validation_type


def extract_provider_json_object(
    content: str,
    *,
    max_characters: int = _PROVIDER_JSON_MAX_CHARACTERS,
    max_affix_characters: int = _PROVIDER_JSON_MAX_AFFIX_CHARACTERS,
) -> str:
    """Extract one bounded top-level JSON object without interpreting surrounding prose."""

    if max_characters < 2 or max_affix_characters < 0:
        raise ValueError("provider JSON extraction limits are invalid")
    if len(content) > max_characters:
        raise ProviderJsonEnvelopeError("json_too_long")
    stripped = content.strip()
    if not stripped:
        raise ProviderJsonEnvelopeError("json_invalid")
    if stripped.startswith("```") or stripped.endswith("```"):
        lines = stripped.splitlines()
        if (
            len(lines) < 3
            or lines[0].strip().casefold() != "```json"
            or lines[-1].strip() != "```"
            or stripped.count("```") != 2
        ):
            raise ProviderJsonEnvelopeError("json_invalid")
        return _extract_unique_json_object(
            "\n".join(lines[1:-1]).strip(),
            max_affix_characters=0,
        )
    if "```" in stripped:
        raise ProviderJsonEnvelopeError("json_invalid")
    return _extract_unique_json_object(
        stripped,
        max_affix_characters=max_affix_characters,
    )


def _extract_unique_json_object(content: str, *, max_affix_characters: int) -> str:
    if content.lstrip().startswith("["):
        raise ProviderJsonEnvelopeError("json_array_root")
    start = content.find("{")
    if start < 0:
        raise ProviderJsonEnvelopeError("json_invalid")
    prefix = content[:start].strip()
    if len(prefix) > max_affix_characters:
        raise ProviderJsonEnvelopeError("json_affix_too_long")
    if _contains_competing_json_structure(prefix):
        raise ProviderJsonEnvelopeError("json_multiple_structures")

    depth = 0
    in_string = False
    escaped = False
    end: int | None = None
    for index in range(start, len(content)):
        character = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise ProviderJsonEnvelopeError("json_invalid")
            if depth == 0:
                end = index
                break
    if end is None:
        raise ProviderJsonEnvelopeError("json_unclosed")

    suffix = content[end + 1 :].strip()
    if len(suffix) > max_affix_characters:
        raise ProviderJsonEnvelopeError("json_affix_too_long")
    if _contains_competing_json_structure(suffix):
        raise ProviderJsonEnvelopeError("json_multiple_structures")
    candidate = content[start : end + 1]
    try:
        parsed: object = json.loads(candidate, parse_constant=_reject_non_json_constant)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ProviderJsonEnvelopeError("json_invalid") from None
    if not isinstance(parsed, dict):
        raise ProviderJsonEnvelopeError("json_array_root")
    return candidate


def _contains_competing_json_structure(value: str) -> bool:
    if not value:
        return False
    if any(character in value for character in "{}[]"):
        return True
    return _JSON_PRIMITIVE.fullmatch(value) is not None


def _reject_non_json_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")
