# ruff: noqa: RUF001
"""Qwen3-VL chat through DashScope's OpenAI-compatible endpoint, with images as data URLs."""

from __future__ import annotations

import base64
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from PIL import Image

from evals.asset_labels.labels import LABEL_GUIDE, AssetLabels, InvalidLabels, parse_labels

ENV_FILE = Path("/root/projects/edu-ai-lead-agent/.env")


def image_data_url(path: Path, *, edge: int) -> str:
    """Downscale, flatten transparency on white and encode as a JPEG data URL."""

    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGBA")
    image.thumbnail((edge, edge))
    background = Image.new("RGB", image.size, (255, 255, 255))
    background.paste(image, mask=image.getchannel("A"))
    buffer = BytesIO()
    background.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float


class ChatModel(Protocol):
    name: str

    def complete(self, content: Sequence[Mapping[str, Any]]) -> ChatResult: ...


class DashScopeVL:
    """One OpenAI-compatible chat call per `complete`; the key never leaves this object."""

    def __init__(self, name: str, *, env_file: Path = ENV_FILE, timeout: float = 90.0) -> None:
        env = _read_env(env_file)
        host = urlsplit(env["VISUAL_EMBEDDING_ENDPOINT"]).netloc
        self.name = name
        self._url = f"https://{host}/compatible-mode/v1/chat/completions"
        self._key = env["VISUAL_EMBEDDING_API_KEY"]
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def complete(self, content: Sequence[Mapping[str, Any]]) -> ChatResult:
        started = time.monotonic()
        response = self._client.post(
            self._url,
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self.name,
                "messages": [{"role": "user", "content": list(content)}],
                "temperature": 0,
                "max_tokens": 400,
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        return ChatResult(
            text=str(body["choices"][0]["message"]["content"] or ""),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            seconds=time.monotonic() - started,
        )

    def close(self) -> None:
        self._client.close()


@dataclass(frozen=True, slots=True)
class LabelOutcome:
    labels: AssetLabels | None
    calls: int
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    error: str | None = None


def label_image(
    model: ChatModel,
    image: Path,
    *,
    references: Sequence[Path],
    edge: int = 1024,
    reference_edge: int = 512,
) -> LabelOutcome:
    """Ask once; on invalid output ask once more with the validation error."""

    content: list[dict[str, Any]] = []
    for reference in references:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_data_url(reference, edge=reference_edge)},
            }
        )
    content.append({"type": "image_url", "image_url": {"url": image_data_url(image, edge=edge)}})
    content.append({"type": "text", "text": LABEL_GUIDE})
    calls = prompt = completion = 0
    seconds = 0.0
    error: str | None = None
    for attempt in range(2):
        message = list(content)
        if attempt and error:
            message.append(
                {
                    "type": "text",
                    "text": f"上一次输出不合法（{error}）。"
                    "只能使用上面列出的取值，只输出 JSON 对象。",
                }
            )
        result = model.complete(message)
        calls += 1
        prompt += result.prompt_tokens
        completion += result.completion_tokens
        seconds += result.seconds
        try:
            return LabelOutcome(parse_labels(result.text), calls, prompt, completion, seconds)
        except InvalidLabels as invalid:
            error = str(invalid)
    return LabelOutcome(None, calls, prompt, completion, seconds, error)
