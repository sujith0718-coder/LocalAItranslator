# LocalTranslate – Local AI Translator

A small Flask web app that translates text between **Tamil, English, Hindi, Malayalam and Telugu** using an AI model.

It runs in two modes:

| Mode | Flow | Where your text goes |
|------|------|----------------------|
| **Local** | Browser → Flask → Ollama → Gemma 4 E2B | Stays on your computer |
| **Public (Render)** | Browser → Flask on Render → Gemini API (+ optional backup AI) | Sent to the hosted AI provider |

This is a student project for demos and small hackathons. It is **not** built for large traffic – see [Limitations](#limitations).

## Project structure

```
app.py            Flask routes, validation, error handling, security headers
translator.py     translate_text logic: cache, duplicate protection, fallback, friendly errors
providers.py      OllamaProvider, GeminiProvider, OpenAICompatProvider (+ shared prompt)
config.py         Reads settings from environment variables
templates/        index.html
static/           style.css, script.js
tests/            Automated tests (fake providers, no real API calls)
```

Adding another AI service = add one small class in `providers.py` with a `translate(text, language)` method and register it in `build_provider()`.

## Run locally (Ollama + Gemma 4 E2B)

1. Install [Ollama](https://ollama.com) and download the model:
   ```bash
   ollama pull gemma4:e2b
   ```
   Make sure Ollama is running (`ollama serve`, or the desktop app).
2. Set up Python:
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Start the app (do **not** set `GEMINI_API_KEY` for pure local mode):
   ```bash
   python app.py
   ```
4. Open http://localhost:5000

With no `GEMINI_API_KEY`, the app automatically uses Ollama, so your local setup works as before.

## Deploy on Render

1. Push the repo to GitHub (never commit `.env` or any key).
2. Render → **New → Web Service** → connect the repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 1 --threads 4 --timeout 60`
   - **Health Check Path:** `/health`
4. **Environment** variables (set in the Render dashboard, not in code):

   | Variable | Required | Example / default | Meaning |
   |----------|----------|-------------------|---------|
   | `AI_PROVIDER` | recommended | `gemini` | `auto`, `ollama`, `gemini`, `openai_compat` |
   | `GEMINI_API_KEY` | yes (for Gemini) | *(your key)* | Server-side only. Never sent to the browser |
   | `GEMINI_MODEL` | no | `gemini-3.8-flash` | Change this if you want a model with a more generous free quota |
   | `AI_FALLBACK_PROVIDER` | no | `openai_compat` | Backup if the primary is rate-limited or down |
   | `OPENAI_COMPAT_API_KEY` | for fallback | *(your key)* | e.g. a Groq free-tier key |
   | `OPENAI_COMPAT_BASE_URL` | for fallback | `https://api.groq.com/openai/v1` | Must be `https://` |
   | `OPENAI_COMPAT_MODEL` | for fallback | *(a model from that provider)* | |
   | `MAX_TEXT_LENGTH` | no | `1000` | Max characters per request |
   | `CACHE_TTL_SECONDS` | no | `600` | `0` disables the cache |
   | `RATE_LIMIT_PER_MINUTE` | no | `20` | Per visitor IP, `0` disables |
   | `LOG_LEVEL` | no | `INFO` | |

   Render sets `PORT` itself; Gunicorn binds to it automatically. Ollama is **not** needed on Render.

Why `--workers 1 --threads 4`? Translation is mostly waiting for the AI API, so threads handle a few visitors at once, and a single process means the cache and duplicate protection are shared. It also fits the small free-tier memory.

## How provider fallback works

```
request → cache hit? → return immediately
        → primary provider (e.g. Gemini)
              ├─ success → return
              └─ rate limit / timeout / error → fallback provider (only if fully configured)
                          ├─ success → return
                          └─ fails → friendly error message
```

- A fallback is used **only if its key/URL/model are all set**. Otherwise the app logs a warning and runs without one.
- Identical requests arriving at the same moment share one AI call.

## Error handling

| Situation | HTTP | User sees |
|-----------|------|-----------|
| Empty text / missing or unsupported language / too long | 400 | A specific, simple message |
| Request body too large | 413 | "That request is too large." |
| Provider rate limit / quota | 429 | "Translation service is temporarily busy…" (+ short countdown on the button) |
| You send too many requests | 429 | "You are sending requests too quickly…" |
| Provider timeout | 504 | "The translation took too long…" |
| Provider down, bad key, bad model, no config | 503 | Generic "unavailable / not set up" message |
| Malformed provider reply | 502 | "The AI returned an unusable answer…" |
| Real bug in the app | 500 | Generic message. Details only in server logs |

Tracebacks, keys, paths and provider internals are never shown to users.

## Security notes

- API keys come only from environment variables, are never put in HTML/JS, and are redacted from logs.
- `.env` is git-ignored. If a key was ever committed, **revoke it** and create a new one – deleting the file is not enough.
- User text is wrapped in tags and the prompt tells the model to treat it as text only (reduces, but cannot fully remove, prompt-injection risk for a translator).
- Input length is limited (server side too), request bodies are capped, and per-IP rate limiting protects your quota.
- No CORS is enabled (the page and API are same-origin). Strict Content-Security-Policy and other security headers are set.
- Flask debug mode is off. The AI provider URLs come only from server config, never from user input (no SSRF).
- Logs record provider, timing and text **length**, not the text.

## Testing

No real API calls are made; AI providers are replaced with fakes.

```bash
python -m unittest discover -s tests -v
```

## Troubleshooting

| Problem | Likely cause |
|---------|--------------|
| "temporarily unavailable" locally | Ollama isn't running, or `gemma4:e2b` isn't pulled (`ollama list`) |
| "temporarily unavailable" on Render | Wrong `GEMINI_MODEL`, bad key, or Ollama selected on Render. Check the Render logs (they show the reason, e.g. `HTTP 404`) |
| "not set up correctly" | Missing/invalid `GEMINI_API_KEY` |
| "busy" often | Free-tier quota reached – wait, switch to a higher-quota model, or configure a fallback |
| First request very slow on Render | Free instances sleep after inactivity and take a while to wake |

## Limitations

- Free AI tiers have request-per-minute and per-day limits. A fallback and caching reduce the problem but **cannot remove it**.
- Render's free instance sleeps when idle; the first visit can be slow. The UI shows a "waking up" hint, but the delay is a hosting limit.
- The cache, rate limiter and duplicate protection live in memory: they reset on restart and aren't shared if you run several instances.
- Translation quality depends on the AI model, especially for long or specialised text.
- This is a small demo app, not a production-scale service.
