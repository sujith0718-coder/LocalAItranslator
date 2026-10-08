"""translate_text(): cache -> primary provider -> optional fallback -> friendly error."""
import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from providers import (AUTH, BAD_RESPONSE, RATE_LIMIT, TIMEOUT, UNAVAILABLE,
                       ProviderError, build_provider)

log = logging.getLogger("translator")


class TranslationError(Exception):
    """An error that is safe to show to the user."""

    def __init__(self, status, code, message, retry_after=None):
        super().__init__(message)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


@dataclass
class Result:
    text: str
    provider: str       # label shown in the UI, e.g. "Gemini"
    cached: bool = False


class TTLCache:
    """Tiny in-memory cache. Lives in one process only and is lost on restart."""

    def __init__(self, ttl, max_entries):
        self.ttl, self.max = ttl, max_entries
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        if self.ttl <= 0:
            return None
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            if item[0] < time.monotonic():
                del self._data[key]
                return None
            return item[1]

    def set(self, key, value):
        if self.ttl <= 0:
            return
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max:
                self._data.popitem(last=False)


class RateLimiter:
    """Allow `limit` requests per 60 seconds for each client key (IP)."""

    def __init__(self, limit):
        self.limit = limit
        self._hits = {}
        self._lock = threading.Lock()

    def check(self, key):
        """Returns 0 if allowed, otherwise seconds to wait."""
        if self.limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 5000:   # keep memory bounded
                self._hits.clear()
            q = self._hits.setdefault(key, deque())
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(60 - (now - q[0])) + 1)
            q.append(now)
            return 0


class _InFlight:
    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.error = None


class Translator:
    def __init__(self, primary, fallback=None, cache_ttl=0, cache_max=200):
        self.primary, self.fallback = primary, fallback
        self.cache = TTLCache(cache_ttl, cache_max)
        self._inflight = {}
        self._lock = threading.Lock()

    @property
    def providers(self):
        return [p for p in (self.primary, self.fallback) if p]

    def translate(self, text, language):
        key = (language, text)

        cached = self.cache.get(key)
        if cached:
            log.info("cache hit")
            return Result(cached.text, cached.provider, cached=True)

        # If someone else is already translating the exact same text, wait for
        # that answer instead of spending another API call.
        with self._lock:
            flight = self._inflight.get(key)
            leader = flight is None
            if leader:
                flight = self._inflight[key] = _InFlight()
        if not leader:
            flight.event.wait(timeout=130)
            if flight.result:
                return Result(flight.result.text, flight.result.provider, cached=True)
            raise flight.error or TranslationError(503, "unavailable", MESSAGES["unavailable"])

        try:
            flight.result = self._call_providers(text, language)
            self.cache.set(key, flight.result)
            return flight.result
        except TranslationError as e:
            flight.error = e
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            flight.event.set()

    def _call_providers(self, text, language):
        if not self.providers:
            log.error("no AI provider is configured")
            raise TranslationError(503, "not_configured", MESSAGES["not_configured"])

        errors = []
        for i, provider in enumerate(self.providers):
            started = time.monotonic()
            log.info("request started provider=%s chars=%d", provider.name, len(text))
            try:
                out = provider.translate(text, language)
                log.info("request succeeded provider=%s seconds=%.1f%s", provider.name,
                         time.monotonic() - started, " (fallback)" if i else "")
                return Result(out, provider.label)
            except ProviderError as e:
                log.warning("provider failed provider=%s kind=%s seconds=%.1f detail=%s",
                            e.provider, e.kind, time.monotonic() - started, e.detail)
                errors.append(e)
                if i + 1 < len(self.providers):
                    log.info("trying fallback provider")
        raise _to_user_error(errors)


MESSAGES = {
    "busy": "Translation service is temporarily busy. Please wait a moment and try again.",
    "timeout": "The translation took too long. Please try again, or try shorter text.",
    "unavailable": "Translation service is temporarily unavailable. Please try again soon.",
    "not_configured": "Translation service is not set up correctly. Please contact the site owner.",
    "bad_response": "The AI returned an unusable answer. Please try again.",
}


def _to_user_error(errors):
    kinds = {e.kind for e in errors}
    if RATE_LIMIT in kinds:
        return TranslationError(429, "rate_limited", MESSAGES["busy"], retry_after=30)
    if TIMEOUT in kinds:
        return TranslationError(504, "timeout", MESSAGES["timeout"])
    if kinds == {AUTH}:
        return TranslationError(503, "not_configured", MESSAGES["not_configured"])
    if kinds == {BAD_RESPONSE}:
        return TranslationError(502, "bad_response", MESSAGES["bad_response"])
    return TranslationError(503, "unavailable", MESSAGES["unavailable"])


def build_translator(settings, log_=log):
    """Choose primary and fallback providers from the settings."""
    name = settings.ai_provider
    if name == "auto":
        name = "gemini" if settings.gemini_api_key else "ollama"

    primary = build_provider(name, settings)
    if primary is None:
        log_.error("primary provider '%s' is not configured (missing key/settings)", name)

    fallback = None
    fb_name = settings.ai_fallback_provider
    if fb_name not in ("", "none"):
        if fb_name == name:
            log_.warning("fallback provider is the same as primary; ignoring it")
        else:
            fallback = build_provider(fb_name, settings)
            if fallback is None:
                log_.warning("fallback '%s' requested but not configured; running without fallback", fb_name)

    log_.info("providers: primary=%s fallback=%s cache_ttl=%ss",
              primary.name if primary else None, fallback.name if fallback else None,
              settings.cache_ttl_seconds)
    return Translator(primary, fallback, settings.cache_ttl_seconds, settings.cache_max_entries)
