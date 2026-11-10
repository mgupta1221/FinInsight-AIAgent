"""Central configuration.

Loads and validates every setting from `.env` in one place (see `.env.example`), so no other
module reads environment variables directly. Import the singleton `settings` anywhere:

    from finsight.config import settings
    client_url = settings.openai_base_url
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (src/finsight/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM endpoint ---
    openai_base_url: str = "https://103.42.50.41:1034/v1"
    openai_api_key: str = ""
    model_name: str = "Qwen/Qwen3-8B"
    openai_ca_cert: str = "./vm04-ca.crt"

    # --- Generation limits ---
    max_output_tokens: int = 1024
    token_budget: int = 12_000
    rate_limit_per_min: int = 60
    max_concurrency: int = 1
    qwen_disable_thinking: bool = True

    # --- Embeddings + reranker (local) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # --- Vector store ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "finsight"

    # --- Agent / memory ---
    memory_db: str = "./store/memory.sqlite"
    max_steps: int = 10

    # --- Tracing (optional) ---
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # --- Paths (derived) ---
    config_dir: Path = Field(default=REPO_ROOT / "config")
    data_dir: Path = Field(default=REPO_ROOT / "data")
    store_dir: Path = Field(default=REPO_ROOT / "store")

    @property
    def ca_cert_path(self) -> str:
        """Absolute path to the CA cert (resolved against the repo root if relative)."""
        p = Path(self.openai_ca_cert)
        return str(p if p.is_absolute() else REPO_ROOT / p)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


settings = Settings()
