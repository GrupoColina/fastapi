# Backlog — FastAPI Studio

Backlog vivo do projeto. Estados: `todo`, `doing`, `done`, `blocked`.
Critérios de aceitação são verificáveis por comando ou por uso do produto.

Produto vive em `studio/`; o framework em `fastapi/` **não é modificado**.

> **Regra de marcação**: nenhum item recebe `done` sem que o critério de aceitação tenha
> sido executado. As evidências da última rodada estão na seção
> [Registro de verificação](#registro-de-verificação) ao final deste documento.

---

## Convenções

- **ID**: `W<onda>.<n>`.
- **Depende de**: IDs que precisam estar `done`.
- **Evidência**: comando/arquivo que comprova o critério de aceitação.

---

## W0 — Auditoria, plano e documentação

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W0.1 | Auditoria do repositório e decisão de escopo | — | `docs/architecture.md` §1 registra a decisão (produto em `studio/`, zero alteração em `fastapi/`) | done |
| W0.2 | Arquitetura | W0.1 | `docs/architecture.md` publicado | done |
| W0.3 | Plano de implementação | W0.2 | `docs/implementation-plan.md` publicado | done |
| W0.4 | Matriz de recursos do FastAPI | W0.2 | `docs/fastapi-feature-matrix.md` publicado | done |
| W0.5 | Backlog | W0.3 | este arquivo, com todos os itens e critérios | done |

## W1 — Scaffold e dependências

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W1.1 | Estrutura `studio/` + `pyproject.toml` | W0.3 | `pip install -e ".[dev,mssql]"` conclui sem erro | done |
| W1.2 | Pacotes `__init__.py` completos | W1.1 | `python -c "import app"` funciona | done |
| W1.3 | Alembic configurado | W1.1 | `alembic upgrade head` cria o schema | done |
| W1.4 | `.env.example` documentado | W1.1 | arquivo presente, em português, com comandos de geração de chaves | done |

## W2 — Núcleo (config, segurança, banco, logging)

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W2.1 | Configuração tipada | W1.3 | `Settings` rejeita segredo inseguro em produção | done |
| W2.2 | Modelos ORM + migração inicial | W2.1 | `alembic check` sem divergências | done |
| W2.3 | Senhas (Argon2id) e JWT (HS256, `typ`) | W2.1 | `tests/test_security.py` verde | done |
| W2.4 | API keys (`sk_…`, hash SHA-256) | W2.3 | `tests/test_security.py` verde | done |
| W2.5 | Cifra Fernet de segredos | W2.3 | `tests/test_security.py` verde | done |
| W2.6 | Redação de PII em logs | W2.1 | `tests/test_logging_redaction.py` verde | done |
| W2.7 | Erros de domínio e handlers | W2.1 | `tests/test_errors.py` verde | done |
| W2.8 | Rate limit e bloqueio de login | W2.1 | `tests/test_rate_limit.py` verde | done |
| W2.9 | Contexto de requisição + middleware | W2.7 | `X-Request-ID` ecoado nas respostas | done |

## W3 — API administrativa

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W3.1 | Login/refresh/logout/me + bootstrap do admin | W2.9 | `POST /api/admin/auth/login` devolve tokens; `GET /me` devolve o usuário | done |
| W3.2 | CRUD de usuários e papéis (RBAC) | W3.1 | `viewer` recebe 403 em `POST /api/admin/users` | done |
| W3.3 | CRUD de projetos | W3.1 | projeto criado aparece em `GET /api/admin/projects` | done |
| W3.4 | Trilha de auditoria | W3.2 | cada ação grava `audit_logs` com PII redigida | done |

## W4 — Fontes de dados

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W4.1 | CRUD de conexões | W3.3 | senha cifrada em `password_enc`; nunca devolvida pela API | done |
| W4.2 | Teste de conexão | W4.1 | `POST /…/test` grava `last_test_ok` e latência | done |
| W4.3 | Introspecção e persistência de objetos | W4.2 | tabelas/views/procedures gravados com colunas e parâmetros | done |
| W4.4 | Autorização (allow-list) de objetos | W4.3 | objetos descobertos entram como `allowed=false` e só ficam visíveis ao runtime quando autorizados | done |
| W4.5 | Adaptador SQLite (dev/teste) | W4.2 | mesmo contrato; `tests/test_datasources.py` verde | done |
| W4.6 | Adaptador SQL Server (pyodbc → python-tds) | W4.2 | `tests/test_mssql_adapter.py` (marcado `mssql`) documenta dependência externa | done |

## W5 — Construtor de endpoints

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W5.1 | Contrato da definição (`EndpointDefinition`) | W1.1 | `extra="forbid"`; valida modo × campos | done |
| W5.2 | Guarda de SQL | W1.1 | `tests/test_sql_guard.py` verde | done |
| W5.3 | Validação semântica do compilador | W5.2 | caminho × parâmetros, allow-list e bind params conferidos | done |
| W5.4 | Materiais de compilação (tipos, modelo de resposta) | W5.3 | `tests/test_compiler.py` verde | done |
| W5.5 | Versionamento imutável + publish/rollback/diff | W5.4 | versão publicada nunca é mutada; rollback gera nova versão | done |

## W6 — Runtime dinâmico

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W6.1 | Estado compartilhado (runtime, cache de allow-list) | W4.4 | `allowed_objects()` reflete autorizações | done |
| W6.2 | Executor parametrizado | W6.1 | bind params; erro de driver vira erro de domínio | done |
| W6.3 | Autenticação de runtime (API key/JWT/escopos) | W6.2 | sem credencial → 401; escopo insuficiente → 403 | done |
| W6.4 | Builder de rota (assinatura nativa) | W6.3 | OpenAPI descreve parâmetros; tipo inválido → 422 | done |
| W6.5 | Registry + instalação de rotas + rebuild | W6.4 | publicar nova versão recarrega a rota sem reiniciar | done |
| W6.6 | Rate limit por endpoint | W6.3 | excedente → 429 | done |
| W6.7 | Fábrica da aplicação (`create_app`) + lifespan | W6.5 | `uvicorn app.main:app` sobe e responde | done |

## W7 — Modo avançado

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W7.1 | Validador AST (deny-by-default) | W5.3 | `tests/test_advanced.py` verde | done |
| W7.2 | Runner isolado em subprocesso | W7.1 | `print`/`import os` rejeitados; timeout → 504 | done |
| W7.3 | Endpoint de execução em rascunho (playground) | W7.2 | executa sem publicar | done |

## W8 — Painel (SPA)

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W8.1 | Login e sessão | W3.1 | autentica e mantém sessão com refresh | done |
| W8.2 | Projetos e fontes de dados | W4.4 | cadastra, testa e descobre objetos pela UI | done |
| W8.3 | Autorização de objetos | W4.4 | alterna `allowed` pela UI e reflete no runtime | done |
| W8.4 | Construtor visual | W5.5 | cria endpoint com parâmetros e schema de resposta | done |
| W8.5 | Versões, validação, publicação e rollback | W5.5 | publica e consome pelo playground | done |
| W8.6 | API keys e logs | W3.4 | cria/revoga chave; consulta logs de requisição | done |

## W9 — Entrega

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W9.1 | Suíte de testes (unitário, integração, segurança, e2e) | W6.7 | `pytest` verde (167 passed, 6 skipped); testes de infra externa marcados | done |
| W9.2 | Dockerfile multi-stage | W9.1 | `docker build` conclui (imagem `fastapi-studio:latest`) | done |
| W9.3 | Docker Compose (app + Postgres) e variante MSSQL | W9.2 | `docker compose up` sobe, `/health` responde 200, login do admin responde 200 e o fluxo vertical roda dentro do container | done |
| W9.4 | Documentação de instalação/operação (Easypanel) | W9.3 | `docs/deployment-easypanel.md` publicada | done |
| W9.5 | Relatório final | W9.1 | `docs/final-report.md` com evidências de testes e limitações declaradas | done |

## W10 — Correções pós-verificação (defeitos encontrados na validação Docker)

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W10.1 | `number` serializado como string no JSON | W6.4 | campo `number` volta como número JSON (`saldo` = `100.0`); `tests/test_e2e_flow.py` cobre | done |
| W10.2 | Rota-cauda da SPA mascarava 404 de API | W6.7 | `GET /api/<inexistente>` devolve 404 com envelope JSON, não HTML 200 | done |
| W10.3 | Constante HTTP 422 depreciada no Starlette | W2.7 | sem `StarletteDeprecationWarning` de 422 nas execuções | done |
| W10.4 | Variável morta em `admin/endpoints.py` | W3.x | sem atribuição não utilizada na criação de endpoint | done |
| W10.5 | `Build Path` do Easypanel no contexto errado | W9.4 | build falhava com `failed to calculate checksum ... "/app": not found`; corrigido com `Build Path = /studio` e documentado em `docs/deployment-easypanel.md` §4 | done |

## W11 — Identidade visual (Design System Colina Core)

| ID | Tarefa | Depende de | Critério de aceitação | Estado |
|----|--------|-----------|----------------------|--------|
| W11.1 | Tokens e componentes do Colina Core em `styles.css` | W8.6 | tema claro único; cores oficiais (`#1e3a8a`/`#e5e7eb`/`#374151`/`#64748b`) em `:root`; raio 8px (12px em modal/login); sem gradientes nem sombras pesadas | done |
| W11.2 | Logo oficial na sidebar e no login | W11.1 | `app/web/logo-colina.png` servido com 200 e renderizado (243×80, com alfa) nas duas telas | done |
| W11.3 | Sidebar em drawer abaixo de 768px | W11.1 | a 600px de largura a sidebar entra em off-canvas com backdrop e fecha por `Esc` | done |
| W11.4 | Verificação de renderização real do painel | W11.2 | valores computados (`getComputedStyle`) de login, sidebar, topbar, cards, botões, tabelas e pills conferem com a especificação | done |

---

## Testes que dependem de infraestrutura externa

| Teste | Marca | Dependência | Execução |
|-------|-------|-------------|----------|
| `tests/test_mssql_adapter.py` | `pytest.mark.mssql` | SQL Server real + driver ODBC 18 | `STUDIO_TEST_MSSQL_DSN=... pytest -m mssql` |
| `tests/test_docker_smoke.py` | `pytest.mark.docker` | Docker + compose | **executado**: `STUDIO_TEST_DOCKER=1 pytest tests/test_docker_smoke.py` → 1 passed |

Quando a infraestrutura não está disponível, os testes são **coletados mas não executados**
(skip automático por ausência de variável de ambiente), e isso é informado no relatório.
O `test_docker_smoke.py` já foi executado com sucesso no ambiente local (Docker disponível).

---

## Registro de verificação

Execuções efetuadas no ambiente Windows local (Python 3.12, venv do projeto) e no Docker
Desktop (engine 29.7.2, Compose v5.4.0).

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `.\.venv\Scripts\python.exe -m pytest -p no:warnings --tb=line` | `166 passed, 7 skipped` |
| 2 | `$env:TZ='UTC'; pytest -p no:warnings --tb=line` | `166 passed, 7 skipped` |
| 3 | `alembic upgrade head` + `alembic check` | revisão `40c543ad0fe0`; "No new upgrade operations detected" |
| 4 | `docker build -t fastapi-studio:latest .` | exit 0; imagem exportada |
| 5 | `docker compose config --quiet` (ambos os compose) | exit 0 |
| 6 | `docker compose up -d --build` | `studio-app-1` e `studio-db-1` ambos `healthy` |
| 7 | `GET /health` | 200 |
| 8 | `GET /` (painel) | 200 `text/html` |
| 9 | `GET /api/v1/openapi.json` | 200 |
| 10 | `POST /api/admin/auth/login` (admin do bootstrap) | 200, `access_token` de 304 chars |
| 11 | E2E dentro do container (script piped em `docker compose exec`) | login → projeto → datasource → test → discover → authorize → endpoint → validate → publish → API key → consumo (200/401/422) → OpenAPI → telemetria: `TUDO OK` |
| 12 | `$env:STUDIO_TEST_DOCKER='1'; pytest tests/test_docker_smoke.py` | `1 passed` |
| 13 | `$env:STUDIO_TEST_DOCKER='1'; pytest -p no:warnings` (+ variante `TZ=UTC`) | `167 passed, 6 skipped` |
| 14 | `GET /` · `/styles.css` · `/logo-colina.png` · `/app.js` | 200 (`text/html` 618 B · CSS 16813 B · PNG 14749 B · JS 9459 B) |
| 15 | Renderização real no navegador (Chrome DevTools, painel em `127.0.0.1:8011`) com `getComputedStyle` | login: card 420px/rai 12px, `h1` `rgb(30,58,138)` 24px, logo 243×56; sidebar branca com borda 1px `rgb(229,231,235)` e item ativo `rgb(238,242,251)`/`rgb(30,58,138)` peso 600; topbar branca sem sombra; card raio 8px e sombra `rgba(15,23,42,0.04)`; botão primário `rgb(30,58,138)` raio 8px; `th` 11px/600 maiúsculas; pills `rgb(236,253,245)`/`rgb(4,120,87)`; a 600px a sidebar vira drawer (`left:-264` → `0`, backdrop visível) e fecha por `Esc` |

Os 6 testes `skipped` são de `tests/test_mssql_adapter.py` (falta `STUDIO_TEST_MSSQL_DSN`).
Nenhum deles foi declarado aprovado.

