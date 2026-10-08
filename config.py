"""Settings read from environment variables (no secrets are hard-coded)."""
import os
from dataclasses import dataclass


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


@dataclass
class Settings:
    # Which provider to use first: auto | ollama | gemini | openai_compat
    # "auto" = Gemini if GEMINI_API_KEY is set, otherwise local Ollama
    # (this matches how the project behaved before).
    ai_provider: str = "auto"
    # Optional backup used only if the primary fails: none | ollama | gemini | openai_compat
    ai_fallback_provider: str = "none"

    # Local Ollama
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "gemma4:e2b"
    ollama_timeout: float = 120      # local models can be slow on CPU

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout: float = 25

    # Any OpenAI-compatible API (Groq, OpenRouter, ...) - good as a fallback
    openai_compat_api_key: str = ""
    openai_compat_base_url: str = ""   # e.g. https://api.groq.com/openai/v1
    openai_compat_model: str = ""
    openai_compat_timeout: float = 25

    # Limits and cost control
    max_text_length: int = 1000        # matches the 1000 limit in the UI
    cache_ttl_seconds: int = 600       # 0 disables the cache
    cache_max_entries: int = 200
    rate_limit_per_minute: int = 20    # per client IP, 0 disables

    @classmethod
    def from_env(cls):
        d = cls()
        return cls(
            ai_provider=os.getenv("AI_PROVIDER", d.ai_provider).strip().lower(),
            ai_fallback_provider=os.getenv("AI_FALLBACK_PROVIDER", d.ai_fallback_provider).strip().lower(),
            ollama_url=os.getenv("OLLAMA_URL", d.ollama_url),
            ollama_model=os.getenv("OLLAMA_MODEL", d.ollama_model),
            ollama_timeout=_float("OLLAMA_TIMEOUT", d.ollama_timeout),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", d.gemini_model),
            gemini_timeout=_float("GEMINI_TIMEOUT", d.gemini_timeout),
            openai_compat_api_key=os.getenv("OPENAI_COMPAT_API_KEY", "").strip(),
            openai_compat_base_url=os.getenv("OPENAI_COMPAT_BASE_URL", "").strip().rstrip("/"),
            openai_compat_model=os.getenv("OPENAI_COMPAT_MODEL", "").strip(),
            openai_compat_timeout=_float("OPENAI_COMPAT_TIMEOUT", d.openai_compat_timeout),
            max_text_length=_int("MAX_TEXT_LENGTH", d.max_text_length),
            cache_ttl_seconds=_int("CACHE_TTL_SECONDS", d.cache_ttl_seconds),
            cache_max_entries=_int("CACHE_MAX_ENTRIES", d.cache_max_entries),
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", d.rate_limit_per_minute),
        )

    def secrets(self):
        """Values that must never appear in logs."""
        return [s for s in (self.gemini_api_key, self.openai_compat_api_key) if s]
