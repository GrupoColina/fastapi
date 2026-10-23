# FastAPI Studio

Plataforma visual para construir, versionar, publicar e operar APIs de dados sobre o
**FastAPI nativo**.

O FastAPI não é reescrito nem bifurcado: os endpoints criados na interface são compilados em
rotas FastAPI reais (assinatura + `Path`/`Query`/`Header`/`Body` + `response_model`), de modo
que validação, OpenAPI, Swagger UI e ReDoc são os originais do framework.

- Documentação de arquitetura: [`../docs/architecture.md`](../docs/architecture.md)
- Plano de implementação: [`../docs/implementation-plan.md`](../docs/implementation-plan.md)
- Cobertura de recursos do FastAPI: [`../docs/fastapi-feature-matrix.md`](../docs/fastapi-feature-matrix.md)
- Backlog: [`../docs/backlog.md`](../docs/backlog.md)

## Início rápido (local)

```bash
cd studio
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev,mssql]"
copy .env.example .env          # Windows
# cp .env.example .env          # Linux/macOS
alembic upgrade head
uvicorn app.main:app --reload
```

Acesse `http://127.0.0.1:8000/` para o painel administrativo.

## Início rápido (Docker)

```bash
cd studio
cp .env.example .env
# edite o .env e defina STUDIO_SECRET_KEY
docker compose up --build
```

Painel: `http://localhost:8000/`
OpenAPI do runtime: `http://localhost:8000/api/v1/docs`

Consulte [`../docs/backlog.md`](../docs/backlog.md) para o estado atual da entrega e as
limitações conhecidas.
