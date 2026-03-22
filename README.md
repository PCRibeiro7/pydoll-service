# pydoll-service

HTTP service wrapping [pydoll](https://github.com/autoscrape-labs/pydoll) — an async Chromium automation library that connects via Chrome DevTools Protocol.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `POST` | `/scrape` | Navigate to a URL and return page HTML (or a CSS/XPath-selected element's text) |
| `POST` | `/screenshot` | Take a PNG screenshot and return it as base64 |
| `POST` | `/pdf` | Generate a PDF of the page and return it as base64 |

### Authentication

Set the `API_KEY` environment variable. Requests must include the header `X-API-Key: <your-key>`. If `API_KEY` is not set, all requests are accepted.

### Example requests

```bash
# Scrape
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret" \
  -d '{"url": "https://example.com"}'

# Screenshot
curl -X POST http://localhost:8000/screenshot \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret" \
  -d '{"url": "https://example.com", "full_page": true}'

# PDF
curl -X POST http://localhost:8000/pdf \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret" \
  -d '{"url": "https://example.com", "landscape": false}'
```

## Why not Netlify?

Pydoll requires a running Chromium browser process. Netlify only offers serverless functions (AWS Lambda) and static hosting — neither provides a persistent runtime or lets you install Chrome. This project uses Docker instead.

## Run locally

```bash
docker build -t pydoll-service .
docker run -p 8000:8000 -e API_KEY=secret pydoll-service
```

Then open http://localhost:8000/docs for the interactive Swagger UI.

## Deploy

Any Docker-capable platform works. Here are the simplest options:

### Railway

```bash
# Install the Railway CLI, then:
railway login
railway init
railway up
```

Set `API_KEY` in the Railway dashboard under **Variables**.

### Render

1. Push this repo to GitHub.
2. Create a new **Web Service** on [render.com](https://render.com) and connect the repo.
3. Render auto-detects the Dockerfile.
4. Add `API_KEY` in the **Environment** tab.

### Fly.io

```bash
fly launch          # creates fly.toml automatically from the Dockerfile
fly secrets set API_KEY=secret
fly deploy
```

## License

MIT
