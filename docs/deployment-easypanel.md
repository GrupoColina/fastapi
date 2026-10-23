# Implantação e operação — FastAPI Studio

Este documento cobre instalação local, execução em Docker, implantação no **Easypanel** e o
procedimento operacional para cadastrar o SQL Server e publicar a primeira API.

Deployar é feito a partir do diretório `studio/`, que contém `Dockerfile`,
`docker-compose.yml`, `docker-compose.mssql.yml`, `alembic/` e o painel em `app/web/`.

---

## 1. Pré-requisitos

| Item | Versão/observação |
|---|---|
| Python (execução local) | 3.10+ (o ambiente validado usa 3.12 no container e 3.14 no host) |
| Docker | engine 29.x + `docker compose` v2+ (validado com Docker 29.7.2 / Compose v5.4.0) |
| Banco de metadados | SQLite (desenvolvimento) ou PostgreSQL 16 (produção) |
| Banco alvo | SQL Server 2016+ com autenticação SQL, acessível pela rede do container |
| Driver | ODBC Driver 18 (instalado na imagem) ou `python-tds` (puro Python, fallback) |

---

## 2. Execução local (sem Docker)

```powershell
cd studio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,mssql]"
Copy-Item .env.example .env
```

Edite o `.env` e defina no mínimo `STUDIO_SECRET_KEY`. Gere os segredos:

```powershell
python -c "import secrets;print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

Aplique as migrações e suba a aplicação:

```powershell
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- Painel: <http://127.0.0.1:8000/>
- Swagger das APIs publicadas: <http://127.0.0.1:8000/api/v1/docs>
- OpenAPI: <http://127.0.0.1:8000/api/v1/openapi.json>
- Healthcheck: <http://127.0.0.1:8000/health>

---

## 3. Execução com Docker Compose

```bash
cd studio
cp .env.example .env
# edite o .env: STUDIO_SECRET_KEY (obrigatório) e, de preferência, STUDIO_ENCRYPTION_KEY

docker compose up --build -d
docker compose ps           # o serviço `app` deve ficar `healthy`
docker compose logs -f app
```

A composição padrão sobe **dois serviços**:

| Serviço | Imagem | Papel |
|---|---|---|
| `db` | `postgres:16-alpine` | banco de metadados (usuários, projetos, endpoints, logs) |
| `app` | construída de `./Dockerfile` | painel + runtime das APIs publicadas, na porta 8000 |

O SQL Server (banco alvo) **não** faz parte desta composição — em produção ele é o servidor
corporativo, cadastrado pelo painel.

### 3.1 Variáveis de ambiente relevantes

| Variável | Padrão | Observação |
|---|---|---|
| `STUDIO_ENV` | `production` no compose | em `production` a aplicação **recusa** subir com `STUDIO_SECRET_KEY` fraca |
| `STUDIO_SECRET_KEY` | chave de exemplo | **obrigatório trocar**; assina JWT |
| `STUDIO_ENCRYPTION_KEY` | derivada da anterior | chave Fernet que cifra a senha das conexões de banco |
| `STUDIO_DATABASE_URL` | `postgresql+psycopg://…@db:5432/studio` | banco de metadados |
| `STUDIO_RUN_MIGRATIONS_ON_STARTUP` | `true` | aplica `alembic upgrade head` no start |
| `STUDIO_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | `admin@example.com` / `TroqueEstaSenha123!` | usados **apenas** quando a tabela de usuários está vazia |
| `STUDIO_RUNTIME_PREFIX` | `/api/v1` | prefixo de todas as APIs publicadas |
| `STUDIO_RATE_LIMIT_PER_MINUTE` | `120` | limite por chave/IP (janela deslizante, em memória) |
| `STUDIO_CORS_ORIGINS` | `*` | use a lista explícita em produção |
| `STUDIO_ALLOW_WRITE_OPERATIONS` | `false` | trava global; escrita exige também `allow_write` na fonte |
| `STUDIO_MSSQL_DRIVER` | `ODBC Driver 18 for SQL Server` | nome do driver ODBC na imagem |
| `STUDIO_QUERY_TIMEOUT` | `30` | segundos |
| `STUDIO_MAX_ROWS` | `1000` | teto de linhas devolvidas por requisição |

Lista completa e comentada: [`../studio/.env.example`](../studio/.env.example).

### 3.2 Imagem sem o driver ODBC

Se o repositório da Microsoft não estiver acessível no build:

```bash
docker compose build --build-arg INSTALL_MSSQL_ODBC=false
```

A aplicação continua funcionando contra SQL Server via `python-tds` (puro Python). O
`docker-compose.mssql.yml` **exige** `INSTALL_MSSQL_ODBC=true`.

### 3.3 Compose com SQL Server de teste

Sobe também um SQL Server 2022 (Developer) como banco alvo:

```bash
docker compose -f docker-compose.mssql.yml up --build -d
```

Depois cadastre, no painel, a fonte apontando para `mssql:1433` (ver seção 5).

> Essa composição é para validação/homologação. Não exponha a porta 1433 na internet.

---

## 4. Implantação no Easypanel

O Easypanel constrói a imagem a partir do repositório Git. Passo a passo:

1. **Banco de metadados** — em *Create Service → Postgres*, crie um serviço chamado `db`
   (usuário/senha/base `studio`). Anote o hostname interno (ex.: `db` ou o nome completo do
   serviço interno, como `studio_db`).
2. **Aplicação** — em *Create Service → App*, aponte para o repositório Git e configure:
   - **Source → Build Path**: `/studio`. **Este campo é obrigatório.** O Build Path é, ao
     mesmo tempo, a raiz de detecção e o **contexto do `docker build`**; o caminho do
     Dockerfile é resolvido a partir dele e um `COPY` não consegue sair do contexto.
     Deixá-lo em `/` faz o build falhar com
     `failed to calculate checksum ... "/app": not found`.
   - **Build**: Dockerfile, com o caminho padrão `Dockerfile` (resolvido como
     `/studio/Dockerfile`). O `.dockerignore` de `studio/` é o que vale.
   - **Porta**: `8000`.
   - **Volumes**: monte um volume persistente em `/srv/studio/data`.
   - **Domínio**: informe o domínio (o Easypanel/Traefik emite o TLS). A aplicação respeita
     `X-Forwarded-*` (o container roda uvicorn com `--proxy-headers`).
3. **Variáveis de ambiente** do serviço (aba *Environment*):

```env
STUDIO_ENV=production
STUDIO_SECRET_KEY=<token_urlsafe(48) gerado>
STUDIO_ENCRYPTION_KEY=<chave Fernet gerada>
STUDIO_DATABASE_URL=postgresql+psycopg://studio:<senha>@<host-do-postgres>:5432/studio
STUDIO_RUN_MIGRATIONS_ON_STARTUP=true
STUDIO_BOOTSTRAP_ADMIN_EMAIL=seu.email@empresa.com
STUDIO_BOOTSTRAP_ADMIN_PASSWORD=<senha forte>
STUDIO_RUNTIME_PREFIX=/api/v1
STUDIO_CORS_ORIGINS=https://seu-dominio.exemplo
STUDIO_MSSQL_DRIVER=ODBC Driver 18 for SQL Server
```

> **`STUDIO_DATABASE_URL` exige o driver explícito.** Use `postgresql+psycopg://`. A imagem
> instala `psycopg` 3 (`.[postgres]`), não `psycopg2`; colar a URL crua do Easypanel
> (`postgresql://…`) faz o SQLAlchemy procurar `psycopg2` e falhar no start com
> `ModuleNotFoundError`. O host é o hostname interno do serviço Postgres do Easypanel.

4. **Deploy**. No start, a aplicação aplica as migrações, cria o administrador inicial (se a
   tabela estiver vazia) e instala as rotas publicadas.
5. **Healthcheck** — use `GET /health`. Resposta esperada:

```json
{"status":"ok","database":true,"metadata_engine":"postgresql","runtime_endpoints":0}
```

6. **Rede** — garanta que o container alcança o SQL Server corporativo (VPN/peering/firewall).
   Se o SQL Server exigir TLS com certificado interno, use nas opções da fonte
   `encrypt=true` e, para certificado autoassinado, `trust_server_certificate=true`.

### 4.1 Atualização

Publique uma nova revisão no Easypanel. Na inicialização, `alembic upgrade head` aplica
apenas as migrações pendentes; as versões publicadas e a allow-list permanecem intactas.

### 4.2 Backup

- Banco de metadados: backup do serviço Postgres (contém projetos, endpoints, versões, logs).
- `STUDIO_ENCRYPTION_KEY`: sem ela as senhas das conexões salvas **não** podem ser
  decifradas. Guarde-a em cofre de segredos e faça parte do plano de recuperação.

---

## 5. Operação — cadastrar a conexão SQL Server e publicar a primeira API

Todo o procedimento abaixo é feito **pelo painel** (a mesma sequência existe na API
administrativa, em `/api/admin`).

### 5.1 Autenticar

1. Acesse `https://<seu-dominio>/` e faça login com
   `STUDIO_BOOTSTRAP_ADMIN_EMAIL` / `STUDIO_BOOTSTRAP_ADMIN_PASSWORD`.
2. Troque a senha no primeiro acesso (o painel oferece a troca quando
   `must_change_password = true`).

### 5.2 Criar o projeto

Menu **Projetos → Novo**. Informe:
`slug` (ex.: `comercial`), `name`, `description` e `openapi_version`.
O `slug` define o prefixo da API: `…/api/v1/<slug>/…`.

### 5.3 Cadastrar e testar a conexão SQL Server

Menu **Fontes de dados → Nova**:

| Campo | Exemplo |
|---|---|
| `kind` | `sqlserver` |
| `host` | `sqlserver.interno.local` (ou `mssql` no compose de teste) |
| `port` | `1433` |
| `database` | `ERP` |
| `username` | `usuario_leitura` |
| `password` | *(a senha é cifrada com Fernet e nunca é devolvida pela API)* |
| `options` | `{"encrypt": true, "trust_server_certificate": false}` |
| `allow_write` | `false` (mantenha leitura; escrita exige a trava global habilitada) |
| `discover_schemas` | `["dbo"]` (vazio = todos os schemas visíveis) |

Clique em **Testar conexão**. O painel mostra `ok`, latência, versão do servidor e driver
usados. Em caso de falha, a mensagem do driver é exibida com usuário/senha já mascarados.

### 5.4 Descobrir e autorizar objetos

1. **Descobrir objetos** — lê tabelas, views, colunas e procedures do banco alvo.
2. A lista aparece com a marcação `allowed = false` para **todos** (deny-by-default).
3. Selecione os objetos que a API pode usar e clique em **Autorizar**. Só objetos
   autorizados podem ser referenciados — a validação e a execução recusam o resto.

### 5.5 Criar o endpoint no construtor visual

Menu **Endpoints → Novo**:

- `http_method`: `GET`
- `path`: `/clientes`
- `slug`: `clientes`
- `datasource_id`: a fonte criada
- **Construtor visual**:
  - *Parâmetros*: `limite` — `location=query`, `type=integer`, `required=false`,
    `default=10`.
  - *Fonte*: modo `sql` com bind param nomeado:
    `SELECT id, nome, saldo FROM dbo.clientes ORDER BY id OFFSET 0 ROWS FETCH NEXT :limite ROWS ONLY`
  - *Resposta*: envelope `list`; campos `id` (integer), `nome` (string), `saldo` (number).
    O botão de preencher a partir das colunas da tabela autorizada já faz isso.
  - *Autenticação*: `api_key`.
- Para casos não cobertos pelos campos visuais use o **modo avançado** (JSON da definição
  ou código Python com `handle(ctx)`).

### 5.6 Validar, testar e publicar

1. **Validar** — confere parâmetros × SQL, allow-list e bind params.
2. **Playground** — execute sem publicar e confira o `payload`, `rows` e `duration_ms`.
3. **Publicar** — a versão passa a `published` e a rota é instalada no runtime **sem
   reiniciar** a aplicação. O caminho final aparece no endpoint, por exemplo
   `/api/v1/comercial/clientes`.
4. Alterações posteriores geram uma **nova versão** (a publicada é imutável). O *rollback*
   republica o conteúdo de uma versão anterior como uma nova versão.

### 5.7 Criar a API key e consumir

Menu **API keys → Nova** (`name`, `project_id`, ambiente `live`, escopos). O segredo em
claro (`sk_live_…`) é mostrado **uma única vez** — copie e guarde.

```bash
curl -H "X-API-Key: sk_live_xxxxxxxxxxxxxxxx" \
     "https://<seu-dominio>/api/v1/comercial/clientes?limite=5"
```

| Situação | Resposta |
|---|---|
| sem credencial | `401` |
| chave revogada/inexistente | `401` |
| parâmetro com tipo inválido (`?limite=abc`) | `422` (validação nativa do FastAPI) |
| escopo insuficiente | `403` |
| limite de requisições excedido | `429` |
| sucesso | `200` com o JSON do envelope |

### 5.8 Documentação e observabilidade

- Swagger das APIs publicadas: `/api/v1/docs` · ReDoc: `/api/v1/redoc` ·
  OpenAPI: `/api/v1/openapi.json`
- Documentação do painel: `/api/docs`
- No painel: **Logs** traz a telemetria de requisições (método, caminho, status, duração,
  linhas) e a **trilha de auditoria** (quem fez o quê, com PII redigida). O **Painel**
  mostra os indicadores e o estado do runtime, com botão para reconstruí-lo.

---

## 6. Diagnóstico rápido

| Sintoma | Verifique |
|---|---|
| App reinicia no start com erro de `SECRET_KEY` | `STUDIO_SECRET_KEY` fraca/ausente em `STUDIO_ENV=production` |
| `database: false` no `/health` | `STUDIO_DATABASE_URL` e o serviço de banco |
| Teste de conexão falha com "driver não encontrado" | `STUDIO_MSSQL_DRIVER` e se a imagem tem o driver 18 (ou use o fallback python-tds) |
| Endpoint publicado responde `404` | a rota só existe após **publicar** uma versão válida e com `is_active=true` |
| Publicação recusada | objeto não autorizado na allow-list ou `SQL` sem bind param |
| `429` constante | `STUDIO_RATE_LIMIT_PER_MINUTE` (o limite é por processo; com várias réplicas o teto efetivo é multiplicado) |

---

## 7. Limitações conhecidas

1. **Rate limit e bloqueio de login em memória** — não são compartilhados entre réplicas;
   com N réplicas o limite efetivo é `N ×` o configurado.
2. **Modo avançado** (código Python) roda em subprocesso isolado com timeout, mas é um
   sandbox **de camada de aplicação**, não uma jaula de sistema operacional.
3. **Rota-cauda da SPA** — a rota-cauda serve o `index.html` para caminhos de navegação
   (o painel usa rotas de hash) e arquivos reais quando existem. Os prefixos reservados
   (`api` e o `STUDIO_RUNTIME_PREFIX`) são excluídos: um caminho de API grafado errado
   responde **404 com envelope JSON**, nunca HTML 200 (corrigido em W10.2).
4. **`alembic check` / migrações** — validados contra SQLite; o schema é compatível com
   PostgreSQL, mas o caminho MSSQL de metadados não é usado (o metadados é sempre
   Postgres/SQLite).
5. **Testes com infraestrutura externa** — o teste de fumaça do Docker foi **executado**
   (`STUDIO_TEST_DOCKER=1`, 1 passed); o marcado `mssql` permanece pulado por ausência de
   SQL Server real no ambiente de desenvolvimento; veja o relatório final.
