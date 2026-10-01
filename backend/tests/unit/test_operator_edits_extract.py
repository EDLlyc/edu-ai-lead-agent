# ruff: noqa: RUF001

from __future__ import annotations

from app.schemas.copy_generation import render_headline_hook_copy
from evals.operator_edits.extract import example_from_snapshot, summarize

TITLE = "机器人世界模型取得新进展"


def _copy(hook: str, tags: str = "#赛先生科学 #人工智能") -> str:
    return render_headline_hook_copy(
        f"{hook}\n{tags}", title=TITLE, source_name="科技日报", source_url="https://example.test/a"
    )


def test_an_edited_package_becomes_one_before_after_example() -> None:
    model = _copy("机器人开始理解世界，和孩子聊聊观察🔭")
    middle = _copy("机器人学会看世界了，和孩子聊聊我们怎么观察🔍")
    final = _copy("机器人学会看世界了，和孩子聊聊我们怎么观察🔍", "#赛先生科学 #机器人")
    snapshot = {
        "operator_edits": [
            {
                "copy_run_id": "r1",
                "draft_version_id": "d1",
                "edited_at": "2026-10-02T10:00:00+08:00",
                "model_copywriting": model,
                "previous_copywriting": model,
                "copywriting": middle,
                "rule_issue_codes": [],
            },
            {
                "copy_run_id": "r1",
                "draft_version_id": "d1",
                "edited_at": "2026-10-02T10:05:00+08:00",
                "model_copywriting": model,
                "previous_copywriting": middle,
                "copywriting": final,
                "rule_issue_codes": ["copy_fluency"],
            },
        ],
        "operator_push": {
            "pushed_at": "2026-10-02T10:06:00+08:00",
            "edited": True,
            "copywriting": final,
        },
    }

    example = example_from_snapshot(snapshot, title=TITLE)

    assert example is not None
    assert example["edit_count"] == 2
    assert example["model_hook"] == "机器人开始理解世界，和孩子聊聊观察🔭"
    assert example["final_hook"] == "机器人学会看世界了，和孩子聊聊我们怎么观察🔍"
    assert example["hook_changed"] and example["hashtags_changed"]
    assert example["pushed"] and example["pushed_text_matches_final"]
    assert example["rule_warnings"] == ["copy_fluency"]
    assert example_from_snapshot({"operator_push": {}}, title=TITLE) is None
    assert "改了引导语 1 份" in summarize([example])
    assert "还没有" in summarize([])
