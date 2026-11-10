"""Smoke test: the package imports and config loads with defaults."""
def test_import_and_config():
    from finsight.config import settings
    assert settings.model_name  # default is set even without a .env
    from finsight import schemas
    assert schemas.Intent.fact.value == "fact"
