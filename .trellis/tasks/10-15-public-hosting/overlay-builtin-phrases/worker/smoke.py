from pathlib import Path

from app.domain.builtin_phrases import DEFAULT_ANXIETY, LOCKED_PHRASE_LISTS
from app.infrastructure.db.builtin_phrases import phrases_for_copy_run
from app.infrastructure.db.models import BuiltinPhraseVersionModel, ContentSlotRunModel

assert "输在起跑线" in DEFAULT_ANXIETY
assert LOCKED_PHRASE_LISTS
assert BuiltinPhraseVersionModel.__tablename__ == "builtin_phrase_versions"
assert hasattr(ContentSlotRunModel, "builtin_phrase_version_id")
assert phrases_for_copy_run is not None
slots = Path("/app/app/infrastructure/db/content_slots.py").read_text()
copy = Path("/app/app/infrastructure/db/copy_generation.py").read_text()
picks = Path("/app/app/infrastructure/db/content_slot_human_picks.py").read_text()
assert "load_active_builtin_phrase_row" in slots
assert "phrases_for_copy_run" in copy
assert "builtin_phrase_version_id" in picks
print("builtin_phrases_worker_ok")
