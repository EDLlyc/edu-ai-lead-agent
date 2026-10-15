import importlib
importlib.import_module("app.api_main")
from app.domain.admin_auth import AdminInputError, check_new_password
from app.schemas.admin import AdminAccountCreateRequest, AdminAccountResetRequest, AdminAccountWithPasswordResponse

for ok in ("a8f3k2m9", "19900101", "my own words 7"):
    check_new_password(ok, username="liyuchen")
for bad in ("short", "12345678", "Password123", "aaaaaaaaaa", "LiYuChen", " a8f3k2m9", "x" * 129):
    try:
        check_new_password(bad, username="liyuchen")
    except AdminInputError:
        continue
    raise SystemExit(f"accepted {bad!r}")
assert AdminAccountCreateRequest(username="a", display_name="b", role="editor").password is None
assert AdminAccountResetRequest().password is None
assert AdminAccountWithPasswordResponse.model_fields["initial_password"].default is None
print("account_password_overlay_ok")
