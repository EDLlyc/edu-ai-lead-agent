import importlib, os
importlib.import_module("app.api_main")
from app.core.config import Settings
from app.api.v1.routes import admin
os.environ.pop("ADMIN_SESSION_COOKIE_DOMAIN", None)
assert Settings(_env_file=None).admin_session_cookie_domain is None
os.environ["ADMIN_SESSION_COOKIE_DOMAIN"] = ""
s = Settings(_env_file=None); assert s.admin_session_cookie_domain is None
assert admin._cookie_path(s) == "/api/v1/admin"
os.environ["ADMIN_SESSION_COOKIE_DOMAIN"] = "xiaosaiai.com"
s = Settings(_env_file=None); assert s.admin_session_cookie_domain == "xiaosaiai.com"
assert admin._cookie_path(s) == "/"
print("cookie_domain_overlay_ok")
