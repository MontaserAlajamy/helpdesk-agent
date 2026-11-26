# Hugging Face Docker Space. Build context is the Space repo, so the project is fetched from GitHub.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

ARG REPO_URL=https://github.com/OWNER/helpdesk-agent.git
ARG REPO_REF=main
RUN git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" . \
    && pip install --no-cache-dir -e .

# Demo mode, throw-away SQLite in /tmp, simulated services. Keys come from Space secrets/variables.
ENV DEMO_MODE=1 \
    DATABASE_URL=sqlite+aiosqlite:////tmp/helpdesk.db \
    PORT=8000
EXPOSE 8000
CMD ["uvicorn", "--factory", "helpdesk.api:app_factory", "--host", "0.0.0.0", "--port", "8000"]
