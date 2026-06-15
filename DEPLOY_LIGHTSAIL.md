# AWS Lightsail Deployment

This deploys WC2026 Opportunity Engine on one Ubuntu Lightsail instance with Docker Compose and Caddy.

## 1. Create the Lightsail instance

In AWS Lightsail:

- Platform: Linux/Unix
- Blueprint: Ubuntu 22.04 LTS or Ubuntu 24.04 LTS
- Size: 1 GB RAM is enough to start
- Create a static IP and attach it to the instance
- Networking: allow TCP `22`, `80`, and `443`

If you have a domain, create an `A` record pointing to the Lightsail static IP.

## 2. Upload the project

From your local machine:

```bash
cd /Users/neilsu/Desktop
tar --exclude='Cup/.env' \
    --exclude='Cup/__pycache__' \
    --exclude='Cup/data/*.db' \
    --exclude='Cup/data/latest_*.json' \
    -czf cup-release.tar.gz Cup

scp -i /path/to/LightsailDefaultKey-*.pem cup-release.tar.gz ubuntu@YOUR_STATIC_IP:/home/ubuntu/
```

On the Lightsail instance:

```bash
ssh -i /path/to/LightsailDefaultKey-*.pem ubuntu@YOUR_STATIC_IP
tar -xzf cup-release.tar.gz
cd Cup
```

## 3. Install Docker on the server

```bash
sudo bash deploy/lightsail/install_server.sh
sudo usermod -aG docker ubuntu
exit
```

Reconnect SSH so the Docker group is active:

```bash
ssh -i /path/to/LightsailDefaultKey-*.pem ubuntu@YOUR_STATIC_IP
cd Cup
```

## 4. Configure production env

```bash
cp deploy/lightsail/.env.lightsail.example .env
nano .env
```

Set:

```bash
ODDS_API_KEY=your_the_odds_api_key
POLL_INTERVAL=300
DONATION_URL=https://buymeacoffee.com/neilsuuu
SITE_ADDRESS=:80
```

Use `SITE_ADDRESS=:80` for IP-only testing.

After your domain points to the static IP, change:

```bash
SITE_ADDRESS=yourdomain.com
```

Caddy will automatically issue HTTPS certificates.

## 5. Start the app

```bash
docker compose -f docker-compose.lightsail.yml up -d --build
```

Open:

```text
http://YOUR_STATIC_IP
```

or after DNS:

```text
https://yourdomain.com
```

## 6. Operations

Logs:

```bash
docker compose -f docker-compose.lightsail.yml logs -f
```

Restart:

```bash
docker compose -f docker-compose.lightsail.yml restart
```

Stop:

```bash
docker compose -f docker-compose.lightsail.yml down
```

Update after uploading new code:

```bash
docker compose -f docker-compose.lightsail.yml up -d --build
```

Backup SQLite data:

```bash
tar -czf wc2026-data-backup-$(date +%F).tar.gz data
```

## 7. API usage warning

Production should start with:

```bash
POLL_INTERVAL=300
```

That is 5 minutes. Lower it only near match time. The app currently scans multiple regions, so 30-second polling consumes API credits quickly.
