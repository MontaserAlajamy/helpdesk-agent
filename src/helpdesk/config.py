"""Settings read from the environment (no extra dependency, validated by Pydantic)."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


def parse_services(raw: str) -> dict[str, str]:
    """'api=http://x/healthz,db=tcp://h:5432' -> {'api': 'http://x/healthz', 'db': 'tcp://h:5432'}"""
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, url = part.partition("=")
        if not url:
            raise ValueError(f"SERVICES entry needs name=url, got {part!r}")
        out[name.strip()] = url.strip()
    return out


class Settings(BaseModel):
    database_url: str = "sqlite+aiosqlite:///./helpdesk.db"
    llm_provider: str = "anthropic"
    llm_model: str = ""
    openai_base_url: str | None = None
    max_steps: int = Field(default=6, ge=1, le=20)
    services: dict[str, str] = Field(default_factory=dict)
    embed_dim: int = 256
    check_timeout_s: float = 3.0
    demo_mode: bool = False  # public demo: simulated services, per-visitor isolation, abuse limits

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL", cls.model_fields["database_url"].default),
            llm_provider=env.get("LLM_PROVIDER", "anthropic"),
            llm_model=env.get("LLM_MODEL", ""),
            openai_base_url=env.get("OPENAI_BASE_URL") or None,
            max_steps=int(env.get("MAX_STEPS", "6")),
            services=parse_services(env.get("SERVICES", "")),
            demo_mode=env.get("DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"},
        )
