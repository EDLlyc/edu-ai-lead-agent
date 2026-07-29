from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

TITLE_RELEVANCE_RULE_VERSION = "ai-title-v1"

_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)


@dataclass(frozen=True, slots=True)
class TitleRelevanceResult:
    is_relevant: bool
    matched_terms: tuple[str, ...]
    normalized_title: str
    rule_version: str = TITLE_RELEVANCE_RULE_VERSION


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKC", title).translate(_DASH_TRANSLATION).casefold()
    return " ".join(normalized.split())


def _ascii_term(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])")


_THEME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("人工智能", re.compile("人工智能")),
    ("ai", _ascii_term("ai")),
    ("aigc", _ascii_term("aigc")),
    ("大模型", re.compile("大模型")),
    ("语言模型", re.compile("语言模型")),
    ("language model", _ascii_term(r"language[\s-]+models?")),
    ("large language model", _ascii_term(r"large[\s-]+language[\s-]+models?")),
    ("foundation model", _ascii_term(r"foundation[\s-]+models?")),
    ("llm", _ascii_term("llms?")),
    ("gpt", _ascii_term(r"(?:chatgpt|gpt(?:[\s-]*\d+(?:\.\d+)?)?)")),
    ("deepseek", _ascii_term("deepseek")),
    ("生成式ai", re.compile(r"生成式\s*ai")),
    ("generative ai", _ascii_term(r"generative[\s-]+ai")),
    ("多模态", re.compile("多模态")),
    ("multimodal", _ascii_term(r"multi[\s-]*modal")),
    ("神经网络", re.compile("神经网络")),
    ("neural network", _ascii_term(r"neural[\s-]+networks?")),
    ("机器学习", re.compile("机器学习")),
    ("machine learning", _ascii_term(r"machine[\s-]+learning")),
    (
        "深度学习",
        re.compile(
            r"(?:人工智能|机器学习|神经网络|模型|算法|计算机视觉|图像|语音|自然语言|"
            r"训练|推理|芯片|算力).{0,12}深度学习|"
            r"深度学习.{0,12}(?:人工智能|机器学习|神经网络|模型|算法|计算机视觉|图像|"
            r"语音|自然语言|训练|推理|芯片|算力)"
        ),
    ),
    ("deep learning", _ascii_term(r"deep[\s-]+learning")),
    ("强化学习", re.compile("强化学习")),
    ("reinforcement learning", _ascii_term(r"reinforcement[\s-]+learning")),
    # Avoid education/health/lifestyle compounds such as 智能体育、智能体检、智能体脂秤.
    ("智能体", re.compile(r"智能体(?!育|系(?!统)|验|检|温|脂|制)")),
    (
        "agent",
        _ascii_term(r"(?:agentic(?:[\s-]+ai)?|(?:ai|intelligent|autonomous)[\s-]+agents?)"),
    ),
    ("算法", re.compile("算法")),
    ("algorithm", _ascii_term(r"algorithms?")),
    ("算力", re.compile("算力")),
    ("智算", re.compile("智算")),
    ("智能计算", re.compile("智能计算")),
    ("ai芯片", re.compile(r"ai\s*芯片")),
    ("智能芯片", re.compile("智能芯片")),
    ("ai chip", _ascii_term(r"ai[\s-]+chips?")),
    ("npu", _ascii_term("npus?")),
    ("计算机视觉", re.compile("计算机视觉")),
    ("机器视觉", re.compile("机器视觉")),
    ("computer vision", _ascii_term(r"computer[\s-]+vision")),
    ("machine vision", _ascii_term(r"machine[\s-]+vision")),
    ("语音识别", re.compile("语音识别")),
    ("语音合成", re.compile("语音合成")),
    ("speech recognition", _ascii_term(r"speech[\s-]+recognition")),
    ("speech synthesis", _ascii_term(r"speech[\s-]+synthesis")),
    ("自然语言处理", re.compile("自然语言处理")),
    (
        "natural language processing",
        _ascii_term(r"natural[\s-]+language[\s-]+processing"),
    ),
    ("nlp", _ascii_term("nlp")),
    ("chatbot", _ascii_term(r"chat[\s-]*bots?")),
    ("机器人", re.compile("机器人")),
    ("robot", _ascii_term(r"robots?|robotics")),
    ("具身智能", re.compile("具身智能")),
    ("embodied intelligence", _ascii_term(r"embodied[\s-]+(?:ai|intelligence)")),
    ("自动驾驶", re.compile("自动驾驶")),
    ("无人驾驶", re.compile("无人驾驶")),
    ("智能驾驶", re.compile("智能驾驶")),
    ("自主系统", re.compile("自主系统")),
    ("无人系统", re.compile("无人系统")),
    ("智能系统", re.compile("智能系统")),
    ("autonomous system", _ascii_term(r"autonomous[\s-]+systems?")),
    ("autonomous driving", _ascii_term(r"autonomous[\s-]+driving")),
    ("autonomous vehicle", _ascii_term(r"autonomous[\s-]+vehicles?")),
    ("intelligent system", _ascii_term(r"intelligent[\s-]+systems?")),
    ("无人机", re.compile("无人机")),
    ("drone", _ascii_term(r"drones?")),
    ("uav", _ascii_term("uavs?")),
    ("脑机接口", re.compile("脑机接口")),
    (
        "brain-computer interface",
        _ascii_term(r"brain[\s-]+computer[\s-]+interfaces?"),
    ),
)

_POLICY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("规划", re.compile("规划")),
    ("办法", re.compile("办法")),
    ("措施", re.compile("措施")),
    ("标准", re.compile("标准")),
    ("治理", re.compile("治理")),
    ("通知", re.compile("通知")),
    ("支持", re.compile("支持")),
    ("资助", re.compile("资助")),
    ("policy", _ascii_term(r"polic(?:y|ies)")),
    ("regulation", _ascii_term(r"regulations?")),
    ("governance", _ascii_term("governance")),
    ("standard", _ascii_term(r"standards?")),
    ("plan", _ascii_term(r"plans?")),
    ("notice", _ascii_term(r"notices?")),
    ("support", _ascii_term("support")),
    ("funding", _ascii_term("funding")),
)


def evaluate_title_relevance(title: str | None) -> TitleRelevanceResult:
    normalized = normalize_title(title)
    if not normalized:
        return TitleRelevanceResult(False, (), normalized)

    theme_terms = tuple(
        label for label, pattern in _THEME_PATTERNS if pattern.search(normalized) is not None
    )
    if not theme_terms:
        return TitleRelevanceResult(False, (), normalized)

    policy_terms = tuple(
        label for label, pattern in _POLICY_PATTERNS if pattern.search(normalized) is not None
    )
    return TitleRelevanceResult(True, (*theme_terms, *policy_terms), normalized)
