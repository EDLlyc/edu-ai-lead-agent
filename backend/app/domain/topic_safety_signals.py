"""Deterministic `.14` topic signals: unsuitable negative incidents and national industrial tech."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.editorial_relevance import normalize_editorial_text

NEGATIVE_INCIDENT_RULE_VERSION = "negative-incident-v1"
INDUSTRIAL_TECHNOLOGY_RULE_VERSION = "industrial-technology-v1"
_TEXT_LIMIT = 6_000

# Criminal/legal enforcement and rumour cases are never brand-suitable, wherever they appear.
_LEGAL_INCIDENT_PATTERN = re.compile(
    r"刑事拘留|刑拘|行政拘留|被拘|被捕|逮捕|批捕|提起公诉|判处|判刑|获刑|犯罪嫌疑人|"
    r"涉嫌(?:犯罪|诈骗|违法)|立案侦查|警情通报|造谣|编造.{0,12}谣言|传播谣言|诈骗|"
    r"落马|双开|严重违纪违法"
)
# Casualty words are only decisive in the headline, and bare 死亡 must refer to people: science
# headlines use it for cells, stars or species ("细胞程序性死亡").
_CASUALTY_HEADLINE_PATTERN = re.compile(
    r"\d+\s*(?:人|名)[^。]{0,4}(?:死亡|遇难|受伤|伤亡)|(?:致|造成|导致)[^。]{0,6}(?:死亡|伤亡)|"
    r"身亡|遇难|丧生|坠亡|溺亡|自杀|车祸|火灾|爆炸事故|安全事故|死亡事故"
)
# Debunking and fraud-prevention education are constructive science/safety communication.
_CONSTRUCTIVE_PATTERN = re.compile(r"辟谣|谣言粉碎|反诈|防诈|防骗")

_INDUSTRIAL_TECH_HEADLINE_PATTERN = re.compile(
    r"新型工业化|智能制造|智能工厂|先进制造业|工业互联网|制造强国|未来产业|新质生产力|"
    r"低空经济|战略性新兴产业|高端装备|工业母机|集成电路产业|数字化转型"
)
_NATIONAL_TECH_ISSUER_PATTERN = re.compile(
    r"国务院|国新办|中共中央|工业和信息化部|工信部|国家发展改革委|科技部|国家数据局|"
    r"国家标准委|全国人大"
)


@dataclass(frozen=True, slots=True)
class TopicSignal:
    matched: bool
    reason_code: str


def _normalize(value: str | None) -> str:
    return normalize_editorial_text((value or "")[:_TEXT_LIMIT])


def evaluate_negative_incident(title: str | None, summary: str | None) -> TopicSignal:
    headline = _normalize(title)
    text = f"{headline}\n{_normalize(summary)}"
    if _CONSTRUCTIVE_PATTERN.search(text):
        return TopicSignal(False, "negative_incident_constructive_context")
    if _LEGAL_INCIDENT_PATTERN.search(text):
        return TopicSignal(True, "negative_incident_legal_or_rumour")
    if _CASUALTY_HEADLINE_PATTERN.search(headline):
        return TopicSignal(True, "negative_incident_casualty_headline")
    return TopicSignal(False, "negative_incident_not_found")


def evaluate_industrial_technology(title: str | None, summary: str | None) -> TopicSignal:
    """A national industrial-technology direction, e.g. 国新办发布会谈新型工业化."""

    headline = _normalize(title)
    if not _INDUSTRIAL_TECH_HEADLINE_PATTERN.search(headline):
        return TopicSignal(False, "industrial_technology_not_headline")
    if not _NATIONAL_TECH_ISSUER_PATTERN.search(f"{headline}\n{_normalize(summary)}"):
        return TopicSignal(False, "industrial_technology_issuer_missing")
    return TopicSignal(True, "industrial_technology_national")


def is_industrial_technology_title(title: str | None) -> bool:
    """Lenient headline check used only to order which listing items get a detail fetch."""

    return _INDUSTRIAL_TECH_HEADLINE_PATTERN.search(_normalize(title)) is not None
