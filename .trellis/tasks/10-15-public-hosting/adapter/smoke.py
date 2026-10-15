import importlib, pathlib
import app
assert pathlib.Path(app.__file__).resolve().as_posix().startswith("/opt/visitor-display/backend/app/"), app.__file__
main = importlib.import_module("app.visitor_display_main")
import os
for key in ("DATABASE_URL", "MINIO_ENDPOINT", "VISITOR_DISPLAY_ENABLED"):
    os.environ.pop(key, None)
settings = main.load_settings({})
assert settings.visitor_display_enabled is False
assert not settings.visitor_review_enabled and not settings.visitor_human_pick_enabled
routes = {getattr(r, "path", "") for r in main.create_app(settings).routes}
for banned in ("/api/v1/visitor-display/operator/session", "/api/v1/visitor-display/news-reviews", "/api/v1/visitor-display/human-picks"):
    assert banned not in routes, banned
print("adapter_import_and_no_operator_routes_ok")
