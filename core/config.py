"""Runtime settings, read from the environment (see README)."""

import os
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "ollama"            # "ollama" | "groq" | "none"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:8b"
    llm_timeout: float = 120.0
    # Development only: serve facts that a person has not verified yet. Off by default.
    allow_unverified_facts: bool = False
    top_k: int = 8
    max_evidence_chunks: int = 12
    max_evidence_chars: int = 9000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_provider=os.environ.get("LLM_PROVIDER", "ollama").strip().lower(),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            groq_model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
            llm_timeout=float(os.environ.get("LLM_TIMEOUT", "120")),
            allow_unverified_facts=_flag("ALLOW_UNVERIFIED_FACTS"),
            top_k=int(os.environ.get("TOP_K", "8")),
            max_evidence_chunks=int(os.environ.get("MAX_EVIDENCE_CHUNKS", "12")),
            max_evidence_chars=int(os.environ.get("MAX_EVIDENCE_CHARS", "9000")),
        )

    @property
    def model(self) -> str:
        return self.groq_model if self.llm_provider == "groq" else self.ollama_model
