"""Narrow read-only and private receipt ports for explicitly invoked manual drafts."""

from typing import Any, Protocol


class ManualDraftError(ValueError):
    """Only constant, secret-free codes may cross the CLI boundary."""


class ManualDraftJournal(Protocol):
    """Caller holds the account lock for the entire local/network operation."""

    def read(self, name: str) -> dict[str, Any] | None: ...

    def write(self, name: str, payload: dict[str, Any]) -> None: ...


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ManualDraftError(code)
