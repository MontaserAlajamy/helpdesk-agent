# Deploying

| Option | Cost | Best for | Database | Notes |
|---|---|---|---|---|
| Hugging Face Space (Docker) | free | the public demo | SQLite in `/tmp` (resets on restart) | `DEMO_MODE=1`; sleeps when idle; secrets in Space settings |
| Any VM with Docker Compose, behind Cloudflare Tunnel | VM cost | persistent demo, real Postgres + pgvector | Postgres volume | no open inbound ports |
| AWS EC2 | free tier or small instance | the "real" deployment, IAM + CloudWatch (roadmap) | Postgres in Compose or RDS | most steps, most control |

## Hugging Face Space

1. Create a Space: SDK Docker, public.
2. Copy `deploy/huggingface/README.md` and `deploy/huggingface/Dockerfile` to the Space repo root; (the repo URL is already set in
   both with the GitHub account (the repo must be public, or add a token build secret).
3. Settings: secret `OPENAI_API_KEY` (an OpenRouter key with a small spend limit); variables
   `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=https://openrouter.ai/api/v1`, `LLM_MODEL=<free model id>`.
4. The Space builds and serves on port 8000. Put its URL in the main README as `DEMO_URL`.

## VM with Docker Compose + Cloudflare Tunnel

```bash
git clone https://github.com/MontaserAlajamy/helpdesk-agent && cd helpdesk-agent
cp .env.example .env   # model, key; add DEMO_MODE=1 for a public demo
docker compose up -d --build
cloudflared tunnel --url http://localhost:8000    # quick tunnel; use a named tunnel for a stable hostname
```

For a stable address create a named tunnel and route a hostname to `http://localhost:8000`. Keep port 8000 closed to
the internet.

## AWS EC2

1. Launch a small instance (Ubuntu), security group: SSH from your IP only, plus 80/443 if serving directly, or none
   with a tunnel.
2. Install Docker and the compose plugin, clone the repo, `cp .env.example .env`, `docker compose up -d --build`.
3. Keys: put them in AWS Systems Manager Parameter Store or Secrets Manager and read them with an instance role;
   do not bake them into the image.
4. CloudWatch metrics per run and results to S3 are on the roadmap, not implemented.
