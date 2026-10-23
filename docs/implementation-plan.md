# FastAPI Studio — Plano de Implementação

Documento de execução. Cada onda (W) só é marcada como concluída quando **todos os seus
critérios de aceitação passam em teste executado**. O status vivo fica em
[backlog.md](./backlog.md); este arquivo descreve o *como*.

---

## Onda 0 — Auditoria e fundação documental

| Item | Entrega |
|---|---|
| Auditoria do repositório | Estado do git, runtime disponível, ausência de trabalho prévio |
| `docs/architecture.md` | Desenho arquitetural completo |
| `docs/implementation-plan.md` | Este documento |
| `docs/fastapi-feature-matrix.md` | Matriz de cobertura dos recursos do FastAPI |
| `docs/backlog.md` | Backlog com prioridade, dependência, critério de aceitação e status |

Critério de aceitação: os quatro documentos existem, são coerentes entre si e a matriz cita
recursos verificáveis do framework.

---

## Onda 1 — Scaffold e dependências verificadas

- `studio/pyproject.toml` com dependências fixadas por faixa.
- Ambiente virtual isolado e instalação comprovada (`pip install -e .[dev,mssql]`).
- `studio/.env.example` completo e comentado.
- `pytest` executando (mesmo sem testes ainda, deve coletar 0 e sair com código 0).

Critério de aceitação: `python -c "import fastapi, sqlalchemy, alembic, jwt, pwdlib, cryptography"`
retorna sem erro e `pytest` coleta sem falha de importação.

---

## Onda 2 — Core e banco de metadados

- `app/core/config.py`: `Settings` via `pydantic-settings`, com validação de produção
  (recusa subir em `STUDIO_ENV=production` com `SECRET_KEY` padrão).
- `app/core/logging.py`: logging estruturado em JSON + `PIIRedactor` aplicado ao formatter.
- `app/core/security.py`: Argon2id, emissão/validação de JWT, geração e hash de API keys,
  cifra Fernet de segredos.
- `app/db/models.py`: todas as tabelas de §3 da arquitetura.
- `alembic/` com migração inicial `0001_initial` **gerada a partir dos modelos** e revisada.

Critério de aceitação: `alembic upgrade head` cria o schema em banco vazio; um teste confere
a presença de todas as tabelas e colunas-chave.

---

## Onda 3 — Admin API de fundação

Routers: `auth`, `users`, `projects`, `apikeys`, `logs`, `system`.

Critério de aceitação: bootstrap do admin ocorre uma única vez (idempotente); login devolve
`access`+`refresh`; refresh rotaciona; usuário inativo é recusado; toda tentativa de login
falha gera log de auditoria; ações administrativas exigem papel adequado (403 caso contrário).

---

## Onda 4 — Data sources

- CRUD de conexões com senha cifrada; a senha **nunca** é devolvida pela API.
- `POST /datasources/{id}/test`: abre conexão real, mede latência, guarda o resultado.
- `POST /datasources/{id}/introspect`: descobre tabelas, views, colunas, procedures e seus
  parâmetros; persiste em `datasource_objects` com `allowed=false`.
- `PATCH /datasources/{id}/objects/{oid}`: autoriza/desautoriza objeto.
- Adaptadores: `sqlserver` (pyodbc, fallback python-tds) e `sqlite` (testes/dev).

Critério de aceitação: teste de integração com SQLite real (arquivo temporário) descobre
tabelas/views/colunas; objeto não autorizado é recusado com 403 na criação e na execução de
endpoint; falha de conexão devolve erro tratado (não 500 cru).

---

## Onda 5 — Construtor, versionamento e publicação

- CRUD de endpoints e versões (`draft`).
- `POST /endpoints/{id}/versions` cria nova versão a partir da anterior.
- `POST /versions/{id}/validate`: valida a definição (parâmetros, SQL contra allow-list,
  tipos, coerência de path).
- `POST /versions/{id}/publish`: publica; versão anterior vai para `archived`; incrementa
  `semver`; invalida o registry.
- `POST /endpoints/{id}/rollback/{version}`: republica uma versão anterior como nova.
- Diff entre versões.

Critério de aceitação: publicar duas versões mantém histórico íntegro; rollback restaura o
comportamento observável; versão publicada não aceita `PATCH`; endpoint referenciando objeto
não autorizado não publica (409/403 com motivo).

---

## Onda 6 — Runtime dinâmico

- `runtime/registry.py`: carrega specs publicados para a memória, com rebuild atômico.
- `runtime/builder.py`: compila spec → rota FastAPI com assinatura real.
- `runtime/executor.py`: executa SQL parametrizado / stored procedure, mapeia resposta,
  aplica paginação e limite de linhas.
- `runtime/auth.py`: dependência de autenticação de runtime (`none` / `api_key` / `jwt`),
  com verificação de escopo e registro de uso da chave.
- `runtime/ratelimit.py`: janela deslizante por chave/IP.
- OpenAPI do runtime em `/api/v1/openapi.json` + Swagger UI + ReDoc (nativos do FastAPI).

Critério de aceitação: após publicar, `GET {prefix}/...` responde com dados reais do banco
alvo; `/api/v1/openapi.json` descreve parâmetros e schema; tipo inválido retorna 422 do
FastAPI; sem credencial retorna 401; escopo insuficiente retorna 403; excedente de rate
limit retorna 429.

---

## Onda 7 — Modo avançado

- `app/advanced/validator.py`: análise AST com allow-list.
- `app/advanced/runner.py`: execução em subprocesso isolado com timeout e JSON puro.
- Endpoint de *dry-run* na Admin API para testar o código antes de publicar.

Critério de aceitação: código com `import os` é recusado na validação (na API e na
publicação); laço infinito estoura o timeout e devolve 504 tratado, sem derrubar o processo
principal; caso válido executa e retorna o JSON esperado.

---

## Onda 8 — Frontend

SPA servida pelo próprio FastAPI em `/` (arquivos estáticos). Telas funcionais, todas
consumindo a API real: login, projetos, data sources (+ testar/introspectar/autorizar),
construtor de endpoint (parâmetros, tipos, SQL, resposta, auth), versões/diff/publicar,
API keys, usuários, logs, playground de requisição e links para Swagger/ReDoc/OpenAPI.

Critério de aceitação: nenhum botão decorativo; fluxo completo executável pelo navegador
contra o backend real; o smoke test HTTP confirma que `/` entrega o HTML e que os assets
respondem 200.

---

## Onda 9 — Empacotamento, testes e validação

- `Dockerfile` + `docker-compose.yml` + `docker-compose.mssql.yml`.
- Suíte de testes: `unit`, `integration`, `e2e`, `security`, `mssql` (marcados).
- Validação real de `docker build` e subida do compose com healthcheck.

Critério de aceitação: `docker build` conclui; `docker compose up` leva o serviço a `healthy`;
a suíte passa integralmente em `TZ=UTC` e no fuso local; testes que exigem SQL Server real
ficam explicitamente marcados e reportados como não executados quando a infraestrutura
não está disponível — sem serem apresentados como aprovados.

---

## Riscos e decisões de contorno

| Risco | Contorno adotado |
|---|---|
| Ausência de SQL Server real no ambiente | Adaptador `sqlite` exercita todo o pipeline; testes MSSQL ficam marcados e gated por `STUDIO_TEST_MSSQL_DSN` |
| `pyodbc` exige driver ODBC no host | `python-tds` (puro Python) como fallback; a imagem Docker instala o driver 18 |
| Dinamismo de rotas vs. tipagem do FastAPI | Assinatura real construída com `inspect.Signature` + `fastapi.params`; nada de `**kwargs` sem anotação |
| Segredos em log | Redator central aplicado ao formatter, com teste dedicado |
| Frontend com build pesado | SPA em JS puro servida pelo próprio FastAPI, sem toolchain Node |
