import importlib
importlib.import_module("app.api_main")
from app.api_main import app
from app.infrastructure.db.models import Base, NewsReviewModel
from app.infrastructure.db.news_reviews import PostgresNewsReviewStore
from alembic.config import Config
from alembic.script import ScriptDirectory

assert "/api/v1/admin/news-reviews" in app.openapi()["paths"]
assert "news_reviews" in Base.metadata.tables and NewsReviewModel.__tablename__ == "news_reviews"
heads = ScriptDirectory.from_config(Config("/app/alembic.ini")).get_heads()
assert heads == ["20261015_0062"], heads
assert PostgresNewsReviewStore is not None
print("news_review_overlay_ok")
