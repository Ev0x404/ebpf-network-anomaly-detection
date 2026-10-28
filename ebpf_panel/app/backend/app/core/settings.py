from pathlib import Path
from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Resolved relative to this file so it works regardless of launch directory.
    # settings.py → core/ → app/ → backend/ → app/ → ebpf_panel/ → project_root
    project_root: Path = DEFAULT_PROJECT_ROOT
    reports_dir: Path | None = None
    logs_dir: Path | None = None
    detections_file: Path | None = None

    # Convert empty strings from .env to None so the fallback logic works correctly.
    @field_validator("reports_dir", "logs_dir", "detections_file", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v

    @field_validator("project_root", mode="before")
    @classmethod
    def _default_project_root(cls, v: Any) -> Any:
        if v == "" or v is None:
            return DEFAULT_PROJECT_ROOT
        return v

    n8n_url: str = "http://localhost:5678"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_container: str = "ollama"

    @property
    def resolved_reports_dir(self) -> Path:
        if self.reports_dir:
            return self._resolve_project_path(self.reports_dir)

        configured = self.project_root / "rapports"
        if configured.exists():
            return configured

        # Keeps the panel useful if a copied .env still points PROJECT_ROOT to
        # an old absolute path while the current checkout contains rapports/.
        local = DEFAULT_PROJECT_ROOT / "rapports"
        return local if local.exists() else configured

    @property
    def resolved_logs_dir(self) -> Path:
        if self.logs_dir:
            return self._resolve_project_path(self.logs_dir)

        configured = self.project_root / "logs"
        if configured.exists():
            return configured

        local = DEFAULT_PROJECT_ROOT / "logs"
        return local if local.exists() else configured

    @property
    def resolved_detections_file(self) -> Path:
        if self.detections_file:
            return self._resolve_project_path(self.detections_file)

        # Le detecteur principal persiste ses alertes dans alerts_local.jsonl.
        # detections.jsonl etait une cible prevue cote panel, mais il n'est pas
        # produit par le pipeline actuel.
        return self.resolved_logs_dir / "alerts_local.jsonl"

    def _resolve_project_path(self, path: Path) -> Path:
        return path if path.is_absolute() else self.project_root / path


settings = Settings()
