# syntax=docker/dockerfile:1
#
# FastAPI Studio - imagem de producao.
#
# Dois estagios:
#   1. builder: cria o virtualenv e compila as dependencias (inclui pyodbc, que precisa
#      de compilador e dos cabecalhos do unixODBC);
#   2. runtime: copia apenas o virtualenv e o codigo, roda como usuario nao-root e
#      declara um HEALTHCHECK apontando para /health.
#
# Observacao sobre o PYTHONPATH: o pacote `app` tambem e instalado no virtualenv pelo
# `pip install .`, mas o processo roda com WORKDIR=/srv/studio e, para `python -m`,
# o diretorio atual tem precedencia no sys.path. O RUN de verificacao logo abaixo falha
# o build caso o import resolva para outro lugar (garantindo `app/web` para a SPA).

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------------------
# Estagio 1 - builder
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Metadados e codigo necessarios para resolver e instalar o pacote.
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip wheel \
    && /opt/venv/bin/pip install ".[postgres,mssql]"

# ---------------------------------------------------------------------------
# Estagio 2 - runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# O driver ODBC 18 permite o uso de pyodbc contra o SQL Server. Quando o repositorio da
# Microsoft nao estiver acessivel no build, use --build-arg INSTALL_MSSQL_ODBC=false:
# o adaptador cai automaticamente para python-tds (puro Python, ja instalado).
ARG INSTALL_MSSQL_ODBC=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    STUDIO_ENV=production \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=8000 \
    STUDIO_LOG_LEVEL=INFO \
    STUDIO_DATABASE_URL=sqlite:////srv/studio/data/studio.db \
    STUDIO_RUN_MIGRATIONS_ON_STARTUP=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && if [ "$INSTALL_MSSQL_ODBC" = "true" ]; then \
         curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
           | gpg --dearmor > /usr/share/keyrings/microsoft-prod.gpg \
         && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
              > /etc/apt/sources.list.d/mssql-release.list \
         && apt-get update \
         && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18; \
       fi \
    && apt-get install -y --no-install-recommends unixodbc \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system studio \
    && useradd --system --gid studio --home-dir /srv/studio --shell /usr/sbin/nologin studio

WORKDIR /srv/studio

COPY --from=builder /opt/venv /opt/venv
COPY --chown=studio:studio app ./app
COPY --chown=studio:studio alembic ./alembic
COPY --chown=studio:studio alembic.ini pyproject.toml README.md ./

RUN mkdir -p /srv/studio/data \
    && chown -R studio:studio /srv/studio \
    && python -c "import pathlib, app; p = pathlib.Path(app.__file__).resolve(); assert str(p).startswith('/srv/studio/'), p; print('app ->', p)" \
    && python -c "from app.core.config import BASE_DIR, Settings; assert str(BASE_DIR) == '/srv/studio', BASE_DIR; assert Settings().web_dir.joinpath('index.html').exists(), 'painel ausente'; print('painel ->', Settings().web_dir)"

USER studio

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
