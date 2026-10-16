from app.api_main import app
from app.domain.builtin_phrases import DEFAULT_MARKETING, LOCKED_PHRASE_LISTS
from app.infrastructure.db.models import BuiltinPhraseVersionModel, ContentSlotRunModel

assert "/api/v1/admin/builtin-phrases" in app.openapi()["paths"]
assert "保证提分" in DEFAULT_MARKETING
assert LOCKED_PHRASE_LISTS
assert BuiltinPhraseVersionModel.__tablename__ == "builtin_phrase_versions"
assert hasattr(ContentSlotRunModel, "builtin_phrase_version_id")
print("builtin_phrases_api_ok")
