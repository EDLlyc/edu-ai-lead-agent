"""Zhipu chat completions with tool calls for the copy repair agent.

It reuses the copy client's endpoint, key, timeouts, concurrency and retry policy, and only adds
the `tools` payload and a bounded parse of the returned tool calls.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.services.copy_repair_agent import ChatToolCall, ChatTurn
from app.core.errors import InvalidProviderOutputError
from app.infrastructure.ai.copy_generation import _ZhipuStructuredCopyClient
from app.infrastructure.ai.zhipu import _post_json_with_retries

_MAX_TOOL_CALLS_PER_TURN = 4
_MAX_ARGUMENT_CHARACTERS = 4_000


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Function(_Model):
    name: str = Field(min_length=1, max_length=64)
    arguments: str = Field(max_length=_MAX_ARGUMENT_CHARACTERS)


class _ToolCall(_Model):
    id: str = Field(min_length=1, max_length=120)
    function: _Function


class _Message(_Model):
    content: str | None = None
    tool_calls: tuple[_ToolCall, ...] | None = Field(
        default=None, max_length=_MAX_TOOL_CALLS_PER_TURN
    )


class _Choice(_Model):
    message: _Message


class _Usage(_Model):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class _Completion(_Model):
    choices: tuple[_Choice, ...] = Field(min_length=1)
    usage: _Usage


class ZhipuRepairChatModel:
    def __init__(self, client: _ZhipuStructuredCopyClient, *, max_output_tokens: int = 1_024):
        self._client = client
        self._max_output_tokens = min(max_output_tokens, client.max_output_tokens)

    async def complete(
        self, messages: Sequence[Mapping[str, object]], tools: Sequence[Mapping[str, object]]
    ) -> ChatTurn:
        payload: dict[str, Any] = {
            "model": self._client.model,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "max_tokens": self._max_output_tokens,
        }
        if len(json.dumps(payload, ensure_ascii=False)) > self._client.max_input_characters:
            raise InvalidProviderOutputError(("input_limit_exceeded",))
        response = await _post_json_with_retries(
            client=self._client.client,
            url=self._client.url,
            api_key=self._client.api_key,
            http_timeout=self._client.timeout,
            total_timeout_seconds=self._client.total_timeout_seconds,
            semaphore=self._client.semaphore,
            max_attempts=self._client.max_attempts,
            sleep=asyncio.sleep,
            payload=payload,
            max_response_bytes=max(16_384, self._max_output_tokens * 16),
        )
        try:
            completion = _Completion.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise InvalidProviderOutputError(("invalid_schema",)) from None
        message = completion.choices[0].message
        return ChatTurn(
            content=message.content,
            tool_calls=tuple(
                ChatToolCall(
                    call_id=call.id, name=call.function.name, arguments_json=call.function.arguments
                )
                for call in message.tool_calls or ()
            ),
            prompt_tokens=completion.usage.prompt_tokens,
            completion_tokens=completion.usage.completion_tokens,
        )
