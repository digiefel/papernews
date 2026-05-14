# Papernews

A lightweight, server-rendered website for research discussion. Django + SQLite, no
frontend framework. See [PLAN.md](PLAN.md) for the product spec.

## Local development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run manage.py migrate
uv run manage.py runserver
```

Visit http://127.0.0.1:8000. Local runs use `config.settings.dev` automatically — no
`.env` needed.

Useful checks:

```sh
uv run manage.py check
uv run manage.py check --deploy --settings=config.settings.prod
```

## Production

Stack: **Caddy** (TLS + reverse proxy) → **gunicorn** (WSGI) → Django, managed by
**systemd**. 

### One-time server setup
1. **Install dependencies:**

   ```sh
   apt update && apt install -y git caddy
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Create the service user and directories:**
   ```sh
   sudo useradd --system --create-home --shell /bin/bash papernews
   sudo mkdir -p /var/lib/papernews
   sudo chown papernews:papernews /var/lib/papernews
   ```

3. **Clone the repo**
   ```sh
   sudo -u papernews -i
   git clone https://github.com/digiefel/papernews /opt/papernews
   cd /opt/papernews
   ```

4. **Create `/opt/papernews/.env`** (copy `.env.example`, fill in real values):

   ```sh
   cp .env.example .env
   # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, DJANGO_DB_PATH
   ```

   Generate a secret key:

   ```sh
   uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

5. **Initialize the app:**

   ```sh
   set -a; source .env; set +a
   uv sync --frozen
   uv run manage.py migrate
   uv run manage.py collectstatic --noinput
   exit   # back to your sudo-capable user
   ```

6. **Install the systemd service:**

   ```sh
   sudo cp /opt/papernews/deploy/papernews.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now papernews
   sudo systemctl status papernews
   ```

7. **Configure Caddy** — put the contents of `deploy/Caddyfile` into
   `/etc/caddy/Caddyfile` (edit the domain), then:

   ```sh
   sudo systemctl reload caddy
   ```

`sudo` for `systemctl restart papernews` is needed by `deploy.sh`. Allow it without a
password by adding a sudoers rule:

```sh
echo 'papernews ALL=(root) NOPASSWD: /usr/bin/systemctl restart papernews' | sudo tee /etc/sudoers.d/papernews
```

### Ongoing deploys

Push locally, then on the server:

```sh
ssh papernews@your-server 'cd /opt/papernews && ./deploy/deploy.sh'
```

`deploy.sh` pulls, syncs deps, migrates, collects static files, and restarts the service.
