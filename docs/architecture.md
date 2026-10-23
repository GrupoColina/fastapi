# FastAPI Studio — Arquitetura

> Produto: **FastAPI Studio** — plataforma visual para construir, versionar, publicar e operar
> APIs de dados sobre o **FastAPI nativo**.
> Localização do código: `c:\Projetos\fastapi\studio\`

---

## 1. Princípio arquitetural central

O Studio **não reimplementa** o FastAPI. Ele é um consumidor do framework:

- O motor HTTP, a injeção de dependências, a validação via Pydantic v2, o roteamento
  (Starlette), a geração de OpenAPI e o Swagger UI/ReDoc são **os originais do FastAPI**.
- O que o Studio acrescenta é uma **camada de metadados + compilação**: o administrador
  descreve um endpoint na interface visual; o Studio persiste essa descrição, **compila** a
  descrição em uma assinatura Python real e a **injeta como rota em um `APIRouter` do FastAPI**
  em tempo de execução.
- Consequência direta: o OpenAPI, a validação de tipos, os códigos 422, a documentação
  interativa e o `TestClient` funcionam nos endpoints publicados **sem nenhum código
  específico do Studio** — porque para o FastAPI eles são rotas normais.

Regra de ouro: **nenhum arquivo dentro de `fastapi/` é modificado.**

---

## 2. Visão de componentes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NAVEGADOR (SPA)                                │
│  Painel administrativo em JavaScript puro (sem etapa de build)              │
│  Login · Projetos · Data Sources · Construtor Visual · Versões ·            │
│  Publicação · API Keys · Usuários · Logs · Playground · Docs OpenAPI        │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ HTTPS / JSON  (JWT Bearer ou X-API-Key)
┌───────────────▼─────────────────────────────────────────────────────────────┐
│                        APLICAÇÃO FASTAPI (studio/app)                       │
│                                                                             │
│  ┌──────────────────────────┐        ┌──────────────────────────────────┐   │
│  │  ADMIN API  /admin/api   │        │  RUNTIME API  /api/v1            │   │
│  │  (metadados do Studio)   │        │  (endpoints publicados)          │   │
│  │  auth, users, projects,  │        │  rotas geradas dinamicamente     │   │
│  │  datasources, endpoints, │        │  auth de runtime (API key/JWT),  │   │
│  │  versions, apikeys, logs │        │  rate limit, executor SQL        │   │
│  └───────────┬──────────────┘        └───────────────┬──────────────────┘   │
│              │                                       │                      │
│  ┌───────────▼──────────────┐        ┌───────────────▼──────────────────┐   │
│  │  SERVICES                │        │  RUNTIME                         │   │
│  │  auth, audit, datasource │        │  registry (specs publicados)     │   │
│  │  introspection, compiler │───────▶│  builder (spec -> rota FastAPI)  │   │
│  │  publisher, executor     │        │  executor (SQL parametrizado)    │   │
│  │  sandbox (modo avançado) │        │  openapi (nativo do FastAPI)     │   │
│  └───────────┬──────────────┘        └───────────────┬──────────────────┘   │
│              │                                       │                      │
│              │ SQLAlchemy 2.0                        │ drivers SQL          │
└──────────────┼───────────────────────────────────────┼──────────────────────┘
               │                                       │
      ┌────────▼─────────┐                  ┌──────────▼───────────────────┐
      │ BANCO DE          │                  │ BANCOS ALVO                  │
      │ METADADOS         │                  │ SQL Server (ERP) via pyodbc  │
      │ SQLite (dev) ou   │                  │ / python-tds (fallback)      │
      │ Postgres (prod)   │                  │ SQLite (dev/testes)          │
      └───────────────────┘                  └──────────────────────────────┘
```

---

## 3. Banco de metadados (Single Source of Truth)

Implementado com **SQLAlchemy 2.0 (ORM declarativo tipado)** + **Alembic** para migrações.

| Tabela | Responsabilidade |
|---|---|
| `users` | Administradores/operadores, hash Argon2id, estado ativo, papel |
| `roles` / `user_roles` | RBAC: `admin`, `editor`, `operator`, `viewer` e escopos finos |
| `projects` | Agrupador lógico e **detentor do escopo de acesso** (`slug` único) |
| `datasources` | Conexões de banco alvo. Senha **cifrada em repouso** (Fernet) |
| `datasource_objects` | Catálogo de objetos descobertos e **explícitamente autorizados** |
| `endpoints` | Identidade do endpoint (nome, método, caminho, projeto). Não versionado |
| `endpoint_versions` | **Snapshot imutável** da definição. `draft` / `published` / `archived` |
| `api_keys` | Chaves de consumo, **hash SHA-256** armazenado, escopos, expiração, uso |
| `request_logs` | Telemetria de execução por requisição (latência, linhas, status) |
| `audit_logs` | Trilha de auditoria de ações administrativas (**PII redigida**) |
| `settings` | Configurações em runtime sobrescrevendo variáveis de ambiente |

Invariante de versionamento: **uma versão publicada nunca é mutada de volta**. Alterar um
endpoint publicado cria uma nova versão `draft` a partir dela. Rollback = publicar uma versão
anterior, criando um novo registro de publicação.

---

## 4. Descoberta e autorização de objetos

1. O administrador cadastra um `datasource` (SQL Server) e clica em **Testar conexão**.
2. O Studio faz a introspecção via catálogo do próprio banco:
   - SQL Server: `sys.tables`, `sys.views`, `sys.columns`, `sys.procedures`,
     `sys.parameters`, `sys.types`, `INFORMATION_SCHEMA`.
   - SQLite (dev/testes): `sqlite_master` + `PRAGMA table_info` / `PRAGMA function_list`.
3. O catálogo é **persistido** em `datasource_objects` com `allowed = false` por padrão.
4. Só objetos com `allowed = true` podem ser referenciados por um endpoint publicado.
   A validação é **reavaliada na publicação** e **na execução**, não apenas na interface.

Isso implementa um *allow-list* explícito — o oposto de permitir SQL arbitrário contra o ERP.

---

## 5. Construtor visual e compilação do endpoint

O administrador monta, na interface:

- método HTTP, caminho (`/clientes/{contrato}`), resumo, descrição, tags;
- **parâmetros** com local (`path`, `query`, `header`, `body`), nome, tipo, obrigatoriedade,
  default, descrição, validações (`min/max`, `min_length/max_length`, regex, `enum`);
- **schemas de resposta** (campos tipados inline) que geram o `response_model`;
- **fonte de dados**: SQL parametrizado (nomeado `:param`) ou *stored procedure*
  (com mapeamento dos parâmetros de entrada);
- **mapeamento de resposta**: direto, envelope paginado ou projeção de colunas;
- **auth de runtime**: `none` / `api_key` / `jwt`, escopos exigidos, rate limit próprio;
- **modo avançado**: código Python próprio (ver §7).

Na publicação, `compiler.py` transforma a definição em um `EndpointSpec` executável, e
`runtime/builder.py` materializa a rota:

```python
# Biblioteca padrão: a assinatura é construída dinamicamente.
params = [
    inspect.Parameter("contrato", inspect.Parameter.KEYWORD_ONLY,
                      default=Path(description=...), annotation=int),
    inspect.Parameter("ativo", inspect.Parameter.KEYWORD_ONLY,
                      default=Query(None, description=...), annotation=bool | None),
]

async def handler(**kwargs):  # kwargs preenchidos e validados pelo FastAPI
    return await execute(spec, kwargs)

handler.__signature__ = inspect.Signature(params)
router.add_api_route(path, handler, methods=["GET"], response_model=ClienteOut)
```

Porque os parâmetros usam `fastapi.params.Path/Query/Header/Body` e a anotação é um tipo
Pydantic válido, **o FastAPI trata a rota como se tivesse sido escrita à mão**: gera o
`requestBody`, valida, devolve 422 com detalhes e publica tudo no `/openapi.json`.

### Tipos suportados
`string`, `integer`, `number`, `boolean`, `date`, `datetime`, `uuid`, `array<T>`, `object`,
`enum`. O mapeamento tipológico canônico vive em `app/services/types.py`.

Nota de serialização: `number` é anotado como `float`, **não** `Decimal`. O Pydantic v2
serializa `Decimal` como *string* no JSON, o que contradiria o tipo declarado no construtor
visual e o contrato OpenAPI; com `float` a resposta sai como número JSON real (ex.: `100.0`).

---

## 6. Execução segura contra o banco alvo

`app/services/executor.py`:

- Compila a query uma única vez com `sqlalchemy.text()`, obtendo um statement com
  **bind parameters** — nunca interpolação de string.
- Além disso, um **validador de SQL** (`app/services/sql_guard.py`) recusa qualquer comando de
  escrita quando `STUDIO_ALLOW_WRITE_OPERATIONS=false`: bloqueio por palavra-chave em
  posição de comando e por AST de tokenização simples.
- Aplica `LIMIT`/`TOP` derivado de `STUDIO_MAX_ROWS` para impedir varredura ilimitada.
- Timeout de statement (`STUDIO_QUERY_TIMEOUT`) propagado ao driver.
- Erros do driver são sanitizados: a mensagem original vai para o log interno; o cliente
  recebe um identificador de correlação, nunca o stack trace ou a DSN.

---

## 7. Modo avançado (código Python personalizado)

Quando a configuração visual não cobre o caso, o operador escreve código Python.

Barreiras implementadas, em camadas:

1. **Validação por AST** (`app/advanced/sandbox.py`): a árvore sintática é inspecionada e
   qualquer `Import`/`ImportFrom` fora de uma allow-list, `__import__`, `eval`, `exec`,
   `open`, acesso a `__globals__`/`__subclasses__`/`__builtins__`, `global`/`nonlocal`,
   `with` sobre I/O e atributos iniciados por `__` são **rejeitados antes da execução**.
2. **Processo isolado**: o código roda em um subprocesso `sys.executable -I -S -c` com
   diretório de trabalho temporário vazio.
3. **Contrato estrito**: `handle(ctx: dict) -> dict`. Entrada e saída transitam apenas como
   **JSON serializado por stdin/stdout**, sem objetos compartilhados.
4. **Timeout** por processo (`STUDIO_ADVANCED_TIMEOUT_SECONDS`) e limite de tamanho do código.

> Limitação declarada: isto **não** é uma jail de segurança endurecida (sem seccomp/namespaces).
> É um sandbox defensivo de camada de aplicação. Para produção multi-inquilino hostil, o passo
> seguinte é executar o subprocesso em container separado com `--network none --read-only`.
> Essa limitação está registrada no relatório final.

---

## 8. Segurança

| Vetor | Controle |
|---|---|
| Senhas | Argon2id (`pwdlib`), política de tamanho mínimo, `must_change_password` |
| Sessão | JWT HS256, `access` (curto) + `refresh` (longo), `jti` e revogação de refresh |
| API keys de runtime | Prefixo público + segredo; **apenas o hash SHA-256 é armazenado** |
| Segredos de datasource | Cifrados com Fernet (`STUDIO_ENCRYPTION_KEY`) |
| Autorização | RBAC por papel + escopo de projeto + allow-list de objetos |
| Enumeração | Mensagens de login genéricas; *timing-safe* no caminho de comparação |
| Força bruta | Rate limit por IP na rota de login + bloqueio progressivo |
| Injeção SQL | Bind parameters obrigatórios + validador de comando |
| Vazamento em log | `PIIRedactor` remove/mascara senhas, tokens, `Authorization`, DSN |
| CORS | Origem configurável; `*` apenas quando explicitamente definido |
| Trabalho excessivo | `STUDIO_MAX_ROWS`, timeouts, limite de payload |

Todas as ações administrativas relevantes geram registro em `audit_logs` contendo
**apenas chaves e comprimentos** para campos sensíveis (nunca o valor).

---

## 9. Empacotamento e implantação

- `Dockerfile` multi-stage, usuário não-root, instala o driver ODBC 18 da Microsoft,
  healthcheck em `/healthz`, `uvicorn` com múltiplos workers.
- `docker-compose.yml`: `app` + `db` (Postgres) + `mssql` em *profile* opcional para
  desenvolvimento e testes de integração reais.
- Migrações Alembic executadas na entrada do container
  (`STUDIO_RUN_MIGRATIONS_ON_STARTUP=true`) ou manualmente.
- No Easypanel: dois serviços (aplicação e Postgres), variáveis do `.env.example`,
  volume persistente para dados do Studio, healthcheck HTTP em `/healthz`.

---

## 10. Mapa de diretórios

```
studio/
├── alembic/                     migrações do banco de metadados
├── app/
│   ├── main.py                  fábrica da aplicação (admin + runtime + SPA)
│   ├── core/                    config, logging, segurança, erros, rate limit
│   ├── db/                      engine, sessão e modelos ORM
│   ├── schemas/                 contratos Pydantic da Admin API
│   ├── services/                regras de negócio (auth, datasource, compiler…)
│   ├── services/datasources/    adaptadores de introspecção (SQL Server, SQLite)
│   ├── runtime/                 registry, builder de rotas, executor, auth runtime
│   ├── api/admin/               routers da API administrativa
│   ├── advanced/                sandbox do modo avançado
│   └── web/                     SPA (HTML/CSS/JS, sem etapa de build)
├── tests/                       unitários, integração, ponta a ponta, segurança
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```
