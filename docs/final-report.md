# Relatório final — FastAPI Studio

Data da última verificação: 2026-10-23
Ambiente de verificação: Windows local (Python 3.12) + Docker Desktop (engine 29.7.2,
Compose v5.4.0).

Este relatório descreve **apenas o que foi executado e verificado**. Nada aqui foi
declarado aprovado sem execução; os itens não executados estão explicitamente listados em
[Limitações e impedimentos](#8-limitações-conhecidas-e-impedimentos).

---

## 1. Funcionalidades realmente implementadas

### 1.1 Painel administrativo (SPA)
Painel servido pela própria aplicação em `/` (rota "cauda"), escrito em ES modules
nativos — sem bundler e sem CDN. Telas implementadas e ligadas à API real:

| Tela | Arquivo | Função |
|---|---|---|
| Login/sessão | `app/web/session.js`, `app/web/api.js` | autentica, guarda tokens e renova o access token automaticamente |
| Dashboard | `app/web/views/dashboard.js` | indicadores de `GET /api/admin/logs/stats` |
| Projetos | `app/web/views/projects.js` | CRUD |
| Fontes de dados | `app/web/views/datasources.js` | cadastro, teste de conexão, descoberta e autorização de objetos |
| Endpoints | `app/web/views/endpoints.js`, `endpoint-detail.js` | versões, validação, publicação, rollback e playground |
| Construtor visual | `app/web/definition-editor.js` | parâmetros, fonte, schema de resposta e auth, com alternância para JSON |
| API keys | `app/web/views/apikeys.js` | criar, revogar, remover |
| Usuários | `app/web/views/users.js` | CRUD com papéis |
| Logs | `app/web/views/logs.js` | telemetria de requisições e trilha de auditoria |
| Documentação | `app/web/views/docs.js` | abre OpenAPI/Swagger/ReDoc do runtime |

A interface segue o **Design System Colina Core** (padrão visual obrigatório do Grupo
Colina): tema claro único, tokens da paleta declarados em `:root` no `styles.css` e
componentes (botões, inputs, cards, tabelas, modais e toasts) construídos sobre as cores
oficiais `#1e3a8a` / `#e5e7eb` / `#374151` / `#64748b`. O logo oficial do Grupo Colina
(`app/web/logo-colina.png`) aparece no topo da sidebar e no cartão de login.

### 1.2 API administrativa (`/api/admin`)
52 rotas em 7 routers (`auth`, `users`, `projects`, `datasources`, `endpoints`,
`api_keys`, `logs`). Inclui:

- autenticação (login, refresh, logout, `me`, troca de senha) e **bootstrap do admin**;
- RBAC (`admin`/`editor`/`operator`/`viewer`) aplicado por `require_role`;
- CRUD de projetos, usuários, fontes de dados, endpoints e API keys;
- `POST /datasources/{id}/test`, `POST /datasources/{id}/discover`,
  `GET /datasources/{id}/objects`, `POST /datasources/{id}/objects/authorize`;
- ciclo de versão: `validate`, `publish`, `rollback`, `versions`, `versions/{v}`;
- `GET /logs/requests`, `GET /logs/audit`, `GET /logs/stats`, `GET|POST /logs/runtime*`.

### 1.3 Descoberta e segurança de acesso ao banco alvo
- Introspecção de **tabelas, views e procedures** (colunas, tipos nativos, PKs e
  parâmetros de procedure), traduzidos para a matriz de tipos canônica.
- **Allow-list explícita com deny-by-default**: objetos descobertos entram com
  `allowed=false`; a autorização é conferida **na publicação e na execução** (cache TTL).
- Adaptadores plugáveis sobre SQLAlchemy Engine: `SqlServerAdapter`
  (pyodbc → fallback python-tds) e `SqliteAdapter` (ambiente de teste/dev).
- Senha da fonte cifrada com Fernet; a API nunca devolve a senha (expõe `has_password`).

### 1.4 Construtor visual → rota FastAPI nativa
- A definição visual (`EndpointDefinition`, `extra="forbid"`) é **compilada em uma rota
  FastAPI real**: `inspect.Signature` + `Path`/`Query`/`Header`/`Body` + `response_model`.
- Consequência: validação Pydantic e **422 nativo**, `requestBody` e parâmetros no
  OpenAPI, Swagger UI e ReDoc — sem reimplementar o framework.
- `fastapi/` não foi modificado em nenhum momento.

### 1.5 Runtime dinâmico
- Registry em memória que carrega versões `published`, compila e **instala/desinstala
  rotas sem reiniciar o processo**, invalidando o cache do OpenAPI.
- Autenticação de runtime por **API key** e/ou JWT, com escopos; sem credencial → 401,
  escopo insuficiente → 403. Rate limit por endpoint (429) e telemetria por requisição.

### 1.6 Modo avançado (código Python personalizado)
- Validador AST **deny-by-default** (imports e builtins perigosos recusados) +
  execução em subprocesso isolado (`python -I`), com timeout → 504.
- Endpoint de playground para testar o rascunho sem publicar.

### 1.7 Segurança
Argon2id (`pwdlib`) para senhas; JWT HS256 com claims `typ`/`jti`/`iss`; API keys
`sk_<env>_<hex4>_<segredo>` das quais só o hash SHA-256 é persistido; Fernet para
segredos de datasource; rate limit em janela deslizante; bloqueio progressivo de login;
redação de PII nos logs de auditoria; `X-Request-ID` correlacionado.

### 1.8 Versionamento e publicação
Versões imutáveis (`draft`/`published`/`archived`); rollback **cria uma nova versão** (não
muta a publicada); diff entre versões; publicação só passa se a validação semântica
(caminho × parâmetros, allow-list e bind params) aprovar.

### 1.9 Entrega e operação
`Dockerfile` multi-stage (usuário não-root, ODBC Driver 18 opcional, healthcheck),
`docker-compose.yml` (app + Postgres), `docker-compose.mssql.yml` (com SQL Server 2022),
migração Alembic `40c543ad0fe0`, `.env.example`, `README.md` e
`docs/deployment-easypanel.md`.

---

## 2. Arquitetura final

```
Navegador
  └─ SPA (ES modules)  ──HTTP──►  FastAPI (app/main.py)
                                   ├─ /api/admin/*      API administrativa (JWT + RBAC)
                                   ├─ /api/v1/<proj>/<path>   rotas publicadas (dinâmicas)
                                   ├─ /api/v1/docs|openapi.json|redoc   docs do runtime
                                   ├─ /health
                                   └─ /{full_path:path}  rota-cauda da SPA
                                             │
                  ┌──────────────────────────┼───────────────────────────┐
                  ▼                          ▼                           ▼
     Banco de metadados           Runtime (registry)             Banco alvo (ERP)
     SQLAlchemy 2.0 + Alembic     compila a definição em         SqlServerAdapter
     (Postgres no Docker)         APIRoute nativa                SqliteAdapter
```

Decisões estruturais:

- **Produto em `studio/`; framework em `fastapi/` intocado.** O Studio configura o
  FastAPI programaticamente (`APIRouter.add_api_route`, `inspect.Signature`,
  `create_model`) em vez de reescrever o framework.
- **Single Source of Truth**: o banco de metadados relacional define projetos, fontes,
  objetos autorizados, endpoints, versões, API keys, usuários, auditoria e telemetria.
- **Deny-by-default** em dois pontos (publicação e execução) via cache TTL de allow-list.
- **Versionamento imutável** com rollback por nova versão.

Detalhamento completo em [`architecture.md`](architecture.md); matriz de recursos do
FastAPI em [`fastapi-feature-matrix.md`](fastapi-feature-matrix.md).

---

## 3. Tarefas concluídas e pendentes

Fonte: [`backlog.md`](backlog.md).

| Onda | Escopo | Estado |
|---|---|---|
| W0 | Auditoria, arquitetura, plano, matriz, backlog | concluída |
| W1 | Scaffold, `pyproject.toml`, Alembic, `.env.example` | concluída |
| W2 | Config, segurança, banco, logging, erros, rate limit | concluída |
| W3 | API administrativa (auth, RBAC, projetos, auditoria) | concluída |
| W4 | Fontes de dados (CRUD, teste, introspecção, allow-list, adaptadores) | concluída |
| W5 | Construtor de endpoints (contrato, guarda SQL, compilador, versionamento) | concluída |
| W6 | Runtime dinâmico (estado, executor, auth, builder, registry, rate limit) | concluída |
| W7 | Modo avançado (validador AST, runner isolado, playground) | concluída |
| W8 | Painel SPA (login, projetos, fontes, builder, versões, keys, logs) | concluída |
| W9 | Entrega (testes, Docker, compose, docs, relatório) | concluída |
| W10 | Correções pós-verificação (4 defeitos) | concluída |

**Pendências declaradas:**

| Item | Motivo |
|---|---|
| Execução de `test_mssql_adapter.py` (6 casos) contra SQL Server real | sem instância acessível; requer `STUDIO_TEST_MSSQL_DSN` |
| Cadastro e teste de uma **conexão SQL Server real** pelo painel | mesma dependência externa acima |

Nenhuma outra pendência de escopo.

---

## 4. Testes executados e resultados

### 4.1 Suíte automatizada

| Execução | Comando | Resultado |
|---|---|---|
| Local | `.\.venv\Scripts\python.exe -m pytest -p no:warnings --tb=line` | **166 passed, 7 skipped** |
| TZ=UTC | `$env:TZ='UTC'; pytest -p no:warnings --tb=line` | **166 passed, 7 skipped** |
| Local + Docker | `$env:STUDIO_TEST_DOCKER='1'; pytest -p no:warnings --tb=line` | **167 passed, 6 skipped** |
| TZ=UTC + Docker | `$env:STUDIO_TEST_DOCKER='1'; $env:TZ='UTC'; pytest -p no:warnings --tb=line` | **167 passed, 6 skipped** |

Cobertura por arquivo: `test_config`, `test_security`, `test_logging_redaction`,
`test_errors`, `test_rate_limit`, `test_migrations`, `test_datasources`, `test_sql_guard`,
`test_compiler`, `test_advanced`, `test_admin_api`, `test_e2e_flow`, `test_docker_smoke`
(marcado), `test_mssql_adapter` (marcado).

### 4.2 Testes que dependem de infraestrutura externa

| Teste | Marca | Dependência | Situação |
|---|---|---|---|
| `tests/test_docker_smoke.py` (1) | `pytest.mark.docker` | Docker + compose | **executado**: 1 passed (`docker compose config --quiet` → exit 0) |
| `tests/test_mssql_adapter.py` (6) | `pytest.mark.mssql` | SQL Server real + ODBC 18 | **não executado**; requer `STUDIO_TEST_MSSQL_DSN=... pytest -m mssql` |

Os 6 `skipped` (`test_mssql_adapter.py`) **não** foram declarados aprovados.

### 4.3 Migrações

`alembic upgrade head` → revisão `40c543ad0fe0`; `alembic check` → *"No new upgrade
operations detected"* (modelos ORM e schema em sincronia).

### 4.4 Docker — build e inicialização

| Verificação | Resultado |
|---|---|
| `docker build -t fastapi-studio:latest .` | exit 0; camadas exportadas |
| `docker compose config --quiet` (ambos os arquivos) | exit 0 |
| `docker compose up -d --build` | `studio-app-1` e `studio-db-1` ambos `healthy` |
| `GET /health` | 200 |
| `GET /` (painel) | 200 `text/html` |
| `GET /app.js`, `/styles.css`, `/views/dashboard.js` | 200 (`text/javascript`, `text/css`) |
| `GET /api/v1/openapi.json` | 200 |
| `POST /api/admin/auth/login` | 200, `access_token` de 304 caracteres |
| `GET /api/rota-que-nao-existe` | **404 com envelope JSON** (`not_found`) |

### 4.5 Teste ponta a ponta dentro do container

Executado por script `httpx` enviado a `docker compose exec app python -`, contra o
servidor real (`127.0.0.1:8000`), com metadados em **Postgres** e o banco alvo em
**SQLite** (ambiente de teste, conforme permitido):

```
login ok
projeto ok 1
datasource ok 1
teste de conexao ok: SQLite 3.40.1
descoberta ok: 2 objetos
autorizacao ok: {'updated': 2}
endpoint ok 1 versao 1
validacao ok
publicacao ok
api key ok: sk_live_f2 ...
consumo ok: [{'id': 1, 'nome': 'Ana', 'saldo': 100.0}, {'id': 2, 'nome': 'Bruno', 'saldo': 200.0}]
validacao de tipo ok (422)
openapi ok
telemetria ok: 1 registros
DOCKER E2E: TUDO OK
```

Observado no mesmo fluxo: `GET` sem credencial → 401; `limite=abc` → 422; o caminho
publicado aparece em `/api/openapi.json`; o consumo gera telemetria consultável.

### 4.6 Defeitos encontrados e corrigidos nesta rodada

| # | Defeito | Correção | Evidência |
|---|---|---|---|
| 1 | Campo `number` era serializado como **string** no JSON (Pydantic v2 serializa `Decimal` como string), divergindo do tipo declarado e do contrato | `TYPE_NUMBER` passou a `float`; `json_schema_for` usa `format: double` | `saldo` = `100.0` no Docker; asserção nova em `test_e2e_flow.py` |
| 2 | A rota-cauda da SPA devolvia **HTML 200** para caminhos de API inexistentes | rota-cauda passa a recusar `/api/*` (e o prefixo do runtime) com `NotFoundError` | `GET /api/rota-que-nao-existe` → 404 JSON; `test_errors.py` cobre |
| 3 | `HTTP_422_UNPROCESSABLE_ENTITY` depreciado no Starlette | trocado por `HTTP_422_UNPROCESSABLE_CONTENT` | sem `StarletteDeprecationWarning` de 422 |
| 4 | Atribuição não utilizada em `admin/endpoints.py` | removida | — |

---

## 5. Comandos de instalação e implantação

### 5.1 Local (desenvolvimento)

```bash
cd studio
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev,mssql]"
copy .env.example .env            # Linux/macOS: cp .env.example .env
# edite .env e defina STUDIO_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

### 5.2 Docker Compose

```bash
cd studio
cp .env.example .env
# edite .env: STUDIO_SECRET_KEY (obrigatório) e, de preferência, STUDIO_ENCRYPTION_KEY
docker compose up --build -d
```

Painel: `http://localhost:8000/` — OpenAPI do runtime: `http://localhost:8000/api/v1/docs`

### 5.3 Docker Compose com SQL Server de teste

```bash
docker compose -f docker-compose.mssql.yml up -d --build
```

### 5.4 Easypanel

Passo a passo completo (banco, app, domínio, variáveis, healthcheck, rede) em
[`deployment-easypanel.md`](deployment-easypanel.md). Resumo:

1. Crie um serviço **Postgres** (fornece `STUDIO_DATABASE_URL`).
2. Crie um **App** a partir do repositório, *build path* `studio`, Dockerfile `studio/Dockerfile`.
3. Defina as variáveis `STUDIO_ENV=production`, `STUDIO_SECRET_KEY`, `STUDIO_ENCRYPTION_KEY`,
   `STUDIO_DATABASE_URL`, `STUDIO_BOOTSTRAP_ADMIN_*` e exponha a porta `8000`.
4. Healthcheck: `GET /health`.

---

## 6. Procedimento: cadastrar a conexão SQL Server e publicar a primeira API

Pré-requisito: a aplicação no ar e o administrador do bootstrap autenticado.

1. **Autenticar** no painel (`/`) com `STUDIO_BOOTSTRAP_ADMIN_EMAIL` e
   `STUDIO_BOOTSTRAP_ADMIN_PASSWORD`. Troque a senha no primeiro acesso.
2. **Criar um projeto** (ex.: `vendas`) — o *slug* vira o primeiro segmento do caminho público.
3. **Cadastrar a fonte de dados**: tipo **SQL Server**, informando host, porta, banco,
   usuário e senha. A senha é cifrada (Fernet) e não é devolvida pela API.
4. **Testar a conexão** — o painel chama `POST /api/admin/datasources/{id}/test` e exibe
   latência e versão do servidor.
5. **Descobrir objetos** — `discover` grava tabelas/views/procedures com colunas e
   parâmetros. Todos entram como **não autorizados**.
6. **Autorizar** os objetos que a API poderá tocar (allow-list). Sem isso, a publicação é
   recusada.
7. **Criar o endpoint** no construtor visual: método, caminho, parâmetros (query/path/
   header/body, com tipo, obrigatoriedade e validações), a consulta SQL com bind params
   (`:parametro`) e o schema de resposta (envelope `object`, `list` ou `paginated`).
8. **Configurar autenticação/permissões** do endpoint (API key e/ou JWT) e, se necessário,
   o rate limit.
9. **Validar** a versão (`validate`): confere caminho × parâmetros, bind params e a
   allow-list dos objetos usados.
10. **Publicar** (`publish`): a rota é compilada e instalada no runtime imediatamente,
    sem reiniciar a aplicação.
11. **Criar uma API key** no painel (o valor em claro aparece **uma única vez**).
12. **Consumir**:

```bash
curl -H "X-API-Key: sk_live_..." "https://SEU-DOMINIO/api/v1/vendas/clientes?limite=10"
```

13. **Conferir** a documentação (`/api/v1/docs`) e os **logs** no painel
    (telemetria de requisições + trilha de auditoria).

---

## 7. Critérios de conclusão

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Construir e iniciar a aplicação em Docker | **verificado** | §4.4 |
| 2 | Acessar o painel e autenticar o administrador | **verificado** | §4.4 (`/` = 200; login = 200) |
| 3 | Cadastrar e testar uma conexão **SQL Server** | **não verificado** | `test` executado com SQLite; requer instância SQL Server real (§8) |
| 4 | Descobrir os objetos autorizados do banco | **verificado** | §4.5 (descoberta + autorização + deny-by-default) |
| 5 | Criar visualmente um endpoint com parâmetros e schemas | **verificado** | §4.5 (endpoint com parâmetro `limite` e schema de resposta) |
| 6 | Configurar autenticação e permissões | **verificado** | §4.5 (401/403, API key) |
| 7 | Testar e publicar a API | **verificado** | §4.5 (`validate` + `publish`) |
| 8 | Consumir o endpoint por HTTP | **verificado** | §4.5 (200/422/401) |
| 9 | Consultar a documentação OpenAPI e os logs | **verificado** | §4.4 e §4.5 |
| 10 | Executar os testes relevantes e corrigir defeitos críticos | **verificado** | §4.1 e §4.6 |

O critério 3 é o único não verificado, por ausência de uma instância SQL Server acessível
neste ambiente. **O produto não é declarado pronto contra SQL Server real** — o caminho do
adaptador está implementado, a imagem embute ODBC Driver 18 e pyodbc, e há fallback
python-tds, mas a execução contra um servidor real depende de infraestrutura externa.

---

## 8. Limitações conhecidas e impedimentos

### 8.1 Impedimento externo
- **SQL Server real não disponível.** `tests/test_mssql_adapter.py` (6 casos) e o critério
  de conclusão nº 3 não foram executados. Para validar: `STUDIO_TEST_MSSQL_DSN="mssql+pyodbc://..."`
  + `pytest -m mssql`, e cadastrar a conexão pelo painel.

### 8.2 Limitações de projeto (conscientes)
- **Rate limit e bloqueio de login são em memória, por processo.** O limite efetivo é
  `limite × número de workers`. A imagem roda um único worker por padrão; escalar
  horizontalmente exige um contador compartilhado (ex.: Redis). Documentado no próprio
  módulo `app/core/rate_limit.py`.
- **O registry do runtime é por processo.** Publicar uma versão recarrega as rotas no
  processo que atendeu a requisição; com múltiplos workers seria necessário um sinal
  compartilhado (o endpoint `POST /api/admin/logs/runtime/rebuild` permite forçar).
- **Modo avançado é sandbox de aplicação, não jail de SO.** A defesa é o validador AST
  deny-by-default somado ao subprocesso isolado (`python -I`) com timeout. Não substitui
  isolamento de contêiner/usuário para código não confiável.
- **`number` é serializado como `float`** (precisão de double, ~15–17 dígitos
  significativos). Para decimais de altíssima precisão, declare o campo como `string` e
  faça a conversão no consumidor.
- **SPA sem bundler** (ES modules nativos): exige navegador moderno.
- **Rota-cauda da SPA**: caminhos fora de `/api` e do prefixo do runtime devolvem o
  `index.html` (comportamento normal de SPA); a partir desta rodada, caminhos sob `/api`
  devolvem 404 JSON.

### 8.3 Não verificado
- `tests/test_mssql_adapter.py` (marca `mssql`) não foi executado — depende de SQL Server real.
- Não foram executados testes de carga, de penetração externa nem auditoria de
  dependências; os testes de segurança cobrem os controles implementados (hash de senha,
  JWT, API keys, cifra, escopos, rate limit, redação de PII).
