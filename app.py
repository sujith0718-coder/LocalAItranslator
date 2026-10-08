"""Local AI Translator - Flask app.

Local:   Browser -> Flask -> Ollama (Gemma 4 E2B)
Public:  Browser -> Flask on Render -> Gemini (optionally a backup provider)
"""
import logging
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Settings
from translator import RateLimiter, TranslationError, build_translator

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("translator.app")

# Same languages as the dropdown in the UI.
LANGUAGES = ["Tamil", "English", "Hindi", "Malayalam", "Telugu"]


def create_app(settings=None, translator=None):
    app = Flask(__name__)
    settings = settings or Settings.from_env()
    translator = translator or build_translator(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024   # reject huge request bodies
    # Render sits behind a proxy; trust one hop so we see the real client IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

    primary = translator.primary
    is_local = bool(primary and primary.is_local)
    page_info = {
        "languages": LANGUAGES,
        "max_len": settings.max_text_length,
        "is_local": is_local,
        "provider_label": primary.label if primary else "AI",
        # browser gives up slightly after the server's own timeout
        "client_timeout_ms": int((sum(p.timeout for p in translator.providers) + 10) * 1000),
    }

    # -------------------------------------------------------------- helpers

    def validate(text, language):
        if not isinstance(text, str) or not text.strip():
            raise TranslationError(400, "empty_text", "Please enter some text.")
        if len(text) > settings.max_text_length:
            raise TranslationError(400, "text_too_long",
                                   f"Text is too long. Please keep it under {settings.max_text_length} characters.")
        if not isinstance(language, str) or not language.strip():
            raise TranslationError(400, "missing_language", "Please select a target language.")
        if language.strip() not in LANGUAGES:
            raise TranslationError(400, "unsupported_language", "That language is not supported.")
        return text.strip(), language.strip()

    def run_translation(text, language):
        text, language = validate(text, language)
        wait = limiter.check(request.remote_addr or "unknown")
        if wait:
            log.warning("client rate limited")
            raise TranslationError(429, "too_many_requests",
                                   "You are sending requests too quickly. Please wait a moment.", retry_after=wait)
        return translator.translate(text, language), language

    def page(**kw):
        return render_template("index.html", **page_info,
                               translation=kw.get("translation", ""), error=kw.get("error", ""),
                               text=kw.get("text", ""), selected=kw.get("selected", "Tamil"),
                               result_provider=kw.get("result_provider", page_info["provider_label"]))

    def wants_json():
        return request.path == "/translate"

    # --------------------------------------------------------------- routes

    @app.get("/health")
    def health():
        # Cheap on purpose: never calls an AI provider.
        return jsonify(status="ok")

    @app.route("/", methods=["GET", "POST"])
    def home():
        # POST here is the no-JavaScript fallback; the normal path is /translate.
        if request.method == "GET":
            return page()
        text = request.form.get("text", "")
        language = request.form.get("language", "")
        try:
            result, language = run_translation(text, language)
            return page(translation=result.text, text=text, selected=language,
                        result_provider=result.provider)
        except TranslationError as e:
            return page(error=e.message, text=text, selected=language or "Tamil"), e.status

    @app.post("/translate")
    def translate():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise TranslationError(400, "bad_request", "Invalid request.")
        result, _ = run_translation(data.get("text"), data.get("language"))
        return jsonify(translation=result.text, provider=result.provider, cached=result.cached)

    # --------------------------------------------------------------- errors

    def error_response(status, code, message, retry_after=None):
        if wants_json():
            resp = jsonify(error=message, code=code)
            resp.status_code = status
        else:
            resp = app.make_response((page(error=message), status))
        if retry_after:
            resp.headers["Retry-After"] = str(retry_after)
        return resp

    @app.errorhandler(TranslationError)
    def handle_translation_error(e):
        return error_response(e.status, e.code, e.message, e.retry_after)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(e):
        return error_response(413, "too_large", "That request is too large.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):   # 404, 405... keep Flask's normal behaviour
            return e
        log.exception("unexpected server error")   # details stay in the server log
        return error_response(500, "internal_error", "Something went wrong on our side. Please try again.")

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if request.path in ("/translate", "/health"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


# Gunicorn imports this:  gunicorn app:app
app = create_app()

if __name__ == "__main__":
    # Local development only. Debug mode stays OFF.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
