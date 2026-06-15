# Docker Deployment

## 1. Prepare env

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ODDS_API_KEY=your_the_odds_api_key
POLL_INTERVAL=300
DONATION_URL=https://buymeacoffee.com/neilsuuu
```

For production, start with `POLL_INTERVAL=300` or higher to control API usage. Lower it only close to match time.

## 2. Run with Docker Compose

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8000
```

Stop:

```bash
docker compose down
```

View logs:

```bash
docker compose logs -f
```

## 3. Run with Docker only

```bash
docker build -t wc2026-opportunity-engine .
docker run -d \
  --name wc2026-opportunity-engine \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  wc2026-opportunity-engine
```

## 4. Production notes

- Put Nginx or Caddy in front for HTTPS.
- Make sure WebSocket proxying is enabled.
- Keep `./data` mounted so SQLite history and snapshots survive container restarts.
- Do not bake `.env` or API keys into the image.
- This app does not process payments; donation links open Buy Me a Coffee externally.

For AWS Lightsail, use:

```bash
docker compose -f docker-compose.lightsail.yml up -d --build
```

Full Lightsail guide: `DEPLOY_LIGHTSAIL.md`.
