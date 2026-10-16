"""Stratified samples for owner labelling: 120 headlines and ~100 same-topic pairs."""

import hashlib
import json
import random
import re
import sys
from datetime import date
from pathlib import Path

from app.domain.content_slots import _SAME_TOPIC_TITLE_OVERLAP, _share_title_phrase

rows = [json.loads(l) for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
out_dir = Path(sys.argv[2])
existing_titles = set()
for path in (Path("evals/topic_golden/cases.v1.jsonl"),):
    for line in path.read_text(encoding="utf-8").splitlines():
        existing_titles.add(json.loads(line)["title"])
existing_pairs = set()
for line in Path("evals/same_topic_golden/pairs.v1.jsonl").read_text(encoding="utf-8").splitlines():
    pair = json.loads(line)
    existing_pairs.add(frozenset((pair["left"], pair["right"])))

rng = random.Random(20260930)
norm = lambda t: re.sub(r"\W+", "", t)
seen, pool = set(), []
for row in sorted(rows, key=lambda r: (r["business_date"], r["event_id"])):
    key = norm(row["title"])
    if key in seen or row["title"] in existing_titles or not row["summary"]:
        continue
    seen.add(key)
    pool.append(row)


def spread(items, n):
    """Round-robin over sources so one busy source cannot dominate a stratum."""
    by_source = {}
    for item in rng.sample(items, len(items)):
        by_source.setdefault((item["source_slugs"] or ["?"])[0], []).append(item)
    picked = []
    while len(picked) < n and any(by_source.values()):
        for source in sorted(by_source):
            if by_source[source] and len(picked) < n:
                picked.append(by_source[source].pop())
    return picked


delivered = [r for r in pool if r["delivered"]]
eligible = sorted(
    (r for r in pool if not r["delivered"] and r["rule_eligible"]), key=lambda r: -r["total"]
)
rejected = [r for r in pool if not r["rule_eligible"]]
strata = {
    "ai_pushed": spread(delivered, 50),
    "near_miss": spread(eligible[: len(eligible) // 3], 30),
    "low_rank": spread(eligible[len(eligible) // 3 :], 20),
    "rule_rejected": spread(rejected, 20),
}
topics = []
for stratum, items in strata.items():
    for row in items:
        digest = hashlib.sha256(row["event_id"].encode()).hexdigest()[:8]
        topics.append(
            {
                "item_id": f"t-{digest}",
                "stratum": stratum,
                "event_id": row["event_id"],
                "business_date": row["business_date"],
                "title": row["title"],
                "summary": row["summary"],
                "facts": row["facts"],
                "categories": row["categories"],
                "source_slugs": row["source_slugs"],
                "source_tiers": row["source_tiers"],
                "source_url": row["source_url"],
                "topic_priority_policy": row["topic_priority_policy"],
                "ai_delivered": row["delivered"],
                "rule_eligible": row["rule_eligible"],
                "rule_total": row["total"],
            }
        )
rng.shuffle(topics)

# Same-topic candidate pairs: titles within 14 days of each other.
dated = [(date.fromisoformat(r["business_date"]), r["title"]) for r in pool]
candidates = []
for i, (left_day, left) in enumerate(dated):
    for right_day, right in dated[i + 1 :]:
        if abs((left_day - right_day).days) > 14 or frozenset((left, right)) in existing_pairs:
            continue
        a, b = set(zip(norm(left), norm(left)[1:])), set(zip(norm(right), norm(right)[1:]))
        jaccard = len(a & b) / len(a | b) if a | b else 0.0
        v2 = _share_title_phrase(left, right, _SAME_TOPIC_TITLE_OVERLAP)
        v3 = _share_title_phrase(left, right, _SAME_TOPIC_TITLE_OVERLAP, strict=True)
        if v2 or v3 or jaccard >= 0.12:
            candidates.append((jaccard, v2, v3, left, right))
flagged = [c for c in candidates if c[1] or c[2]]
similar = sorted((c for c in candidates if not (c[1] or c[2])), key=lambda c: -c[0])
pairs_raw = rng.sample(flagged, min(60, len(flagged))) + similar[:40]
pairs = []
for jaccard, v2, v3, left, right in pairs_raw:
    digest = hashlib.sha256((left + "|" + right).encode()).hexdigest()[:8]
    pairs.append(
        {"item_id": f"p-{digest}", "left": left, "right": right, "rule_v2": v2, "rule_v3": v3,
         "title_jaccard": round(jaccard, 3)}
    )
rng.shuffle(pairs)
(out_dir / "topics-to-label.json").write_text(json.dumps(topics, ensure_ascii=False, indent=1), encoding="utf-8")
(out_dir / "pairs-to-label.json").write_text(json.dumps(pairs, ensure_ascii=False, indent=1), encoding="utf-8")
print("topics", len(topics), {k: len(v) for k, v in strata.items()})
print("pair candidates", len(candidates), "flagged", len(flagged), "picked", len(pairs))
