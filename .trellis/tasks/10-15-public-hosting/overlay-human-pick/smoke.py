import importlib
importlib.import_module("app.api_main")
from app.api_main import app
from app.application.services.visitor_display import split_headline_hook_copy
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository

paths = app.openapi()["paths"]
for p in (
    "/api/v1/admin/human-picks",
    "/api/v1/admin/human-picks/{key}/review",
    "/api/v1/admin/human-picks/{key}/copy",
    "/api/v1/admin/human-picks/{key}/push",
):
    assert p in paths, p
assert hasattr(PostgresVisitorDisplayRepository, "load_human_pick_review")
parts = split_headline_hook_copy("🔎【小赛洞察】\n标题\n引导语\n新闻来源：某\n原文链接：https://example.org\n#科学思维")
assert parts["hook"] == "引导语" and parts["hashtags"] == ["#科学思维"], parts
print("human_pick_overlay_ok")
