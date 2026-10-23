# Matriz de Cobertura dos Recursos do FastAPI

Como a plataforma **consome** o FastAPI nativo. A coluna *Como a plataforma expõe* indica o
mecanismo concreto no código do Studio (ou `—` quando o recurso é provido pelo próprio
framework sem intervenção da plataforma).

Referências cruzadas no código: `studio/app/runtime/builder.py`,
`studio/app/runtime/registry.py`, `studio/app/runtime/executor.py`,
`studio/app/api/admin/*`, `studio/app/services/compiler.py`.

## 1. Roteamento e parâmetros

| Recurso do FastAPI | Uso na plataforma | Como a plataforma expõe |
|---|---|---|
| `APIRouter` | Sim | `runtime/builder.py` monta um `APIRouter` novo a cada rebuild e o inclui no app |
| `@router.get/post/put/patch/delete` | Sim | `router.add_api_route(...)` com o método vindo da definição visual |
| Path parameters | Sim | `fastapi.Path()` na assinatura gerada; tipo Pydantic derivado do campo do builder |
| Query parameters | Sim | `fastapi.Query()` com `default`, `ge/le`, `min_length/max_length`, `pattern`, `description` |
| Header parameters | Sim | `fastapi.Header(convert_underscores=False)` |
| Cookie parameters | Parcial | tipo suportado na matriz de tipos; exposto via `Cookie` no modo avançado |
| Body (modelo Pydantic) | Sim | `fastapi.Body()` com `create_model()` a partir do schema de entrada do builder |
| Body (múltiplos parâmetros) | Sim | um parâmetro `Body` por campo marcado como `body` |
| Form / UploadFile | Não na UI | disponível no modo avançado (código Python) |
| `Depends` / injeção de dependência | Sim | dependências de auth de runtime, rate limit e sessão de banco |
| `include_router(prefix=...)` | Sim | prefixo global `STUDIO_RUNTIME_PREFIX` + prefixo por endpoint |
| `APIRoute` customizado | Sim | `route_class` do runtime para métricas e logs por requisição |
| WebSockets | Não | fora do escopo declarado (APIs de dados HTTP) |
| `StreamingResponse` / SSE | Parcial | suportado no modo avançado; não exposto como opção visual |

## 2. Validação de dados e serialização

| Recurso do FastAPI | Uso na plataforma | Como a plataforma expõe |
|---|---|---|
| Pydantic v2 | Sim | modelos de entrada/saída gerados dinamicamente com `create_model` |
| `response_model` | Sim | schema de resposta montado pelo construtor visual |
| `response_model_exclude_unset` | Sim | opção por endpoint |
| Erros 422 padronizados | Sim | nativos, porque a rota é uma rota FastAPI normal |
| `Annotated` (metadados de parâmetro) | Sim | usado internamente na construção das anotações |
| Aliases de campo | Sim | `alias` por campo no builder |
| `jsonable_encoder` | Sim | usado no executor ao devolver `Row` do banco |
| Tipos: `datetime`, `date`, `UUID`, `float` (número JSON) | Sim | matriz de tipos em `services/types.py`; `number` usa `float` para sair como número no JSON |
| `Enum` (choices) | Sim | parâmetro `enum` no builder |

## 3. OpenAPI e documentação

| Recurso do FastAPI | Uso na plataforma | Como a plataforma expõe |
|---|---|---|
| `/openapi.json` gerado | Sim | aplicação de runtime montada com `FastAPI(...)` próprio |
| Swagger UI | Sim | `/api/v1/docs` (nativo) |
| ReDoc | Sim | `/api/v1/redoc` (nativo) |
| `title`/`version`/`description` do OpenAPI | Sim | derivados do projeto e da versão publicada |
| `tags` por endpoint | Sim | campo do construtor visual |
| `summary` / `description` | Sim | campos do construtor visual |
| `deprecated` | Sim | flag por endpoint |
| `responses` extras (ex.: 401/403/429) | Sim | `responses={...}` declarado no `add_api_route` |
| `openapi_tags` | Sim | metadados das tags do projeto |
| `servers` | Sim | configurável por projeto |

## 4. Segurança

| Recurso do FastAPI | Uso na plataforma | Como a plataforma expõe |
|---|---|---|
| `HTTPBearer` | Sim | auth de runtime por JWT |
| `APIKeyHeader` | Sim | auth de runtime por chave de API (`X-API-Key`) |
| `Security` com escopos | Sim | escopos exigidos por endpoint, verificados na dependência |
| `OAuth2PasswordBearer` | Não | o login administrativo é JSON puro (sem fluxo OAuth2 de terceiros) |
| `RequestValidationError` | — | nativo |
| `HTTPException` | Sim | tratamento de erros do executor e do guard de SQL |

## 5. Observabilidade e ciclo de vida

| Recurso do FastAPI | Uso na plataforma | Como a plataforma expõe |
|---|---|---|
| Middleware CORS | Sim | `CORSMiddleware` configurado por `STUDIO_CORS_ORIGINS` |
| Middleware GZip | Sim | habilitado quando o payload é grande |
| Middleware próprio | Sim | correlação de requisição (`X-Request-ID`) + métricas + rate limit |
| `lifespan` (startup/shutdown) | Sim | migrações, bootstrap do admin, carga do registry, criação do engine |
| Handlers de exceção globais | Sim | formato de erro uniforme e sanitização de mensagens de driver |
| `app.state` | Sim | registry de endpoints, engine de metadados, cache de introspecção |
| Logs por requisição | Sim | tabela `request_logs` + log estruturado em JSON |
| `background` tasks | Sim | gravação assíncrona de `request_logs` e de uso de API key |
| Healthcheck | Sim | `/healthz` (liveness) e `/readyz` (verifica metadados e registry) |

## 6. Testes

| Recurso do FastAPI | Uso na plataforma | Como a plataforma expõe |
|---|---|---|
| `TestClient` | Sim | toda a suíte de integração e ponta a ponta |
| `dependency_overrides` | Sim | injeção de banco de metadados temporário e de executor falso em testes unitários |
| App de teste isolado | Sim | `create_app(settings)` permite instanciar a aplicação com configuração de teste |

## 7. Itens deliberadamente fora do escopo

| Recurso | Motivo |
|---|---|
| WebSockets | A plataforma entrega APIs de dados HTTP; WS exigiria outro modelo de versionamento |
| GraphQL | Fora do escopo declarado pelo projeto |
| Templates HTML (Jinja2) no runtime | O runtime devolve JSON; o painel é servido como estático |
| Upload de arquivos pelo construtor visual | Requer política de armazenamento; disponível apenas no modo avançado |
| OAuth2 de terceiros | SSPs corporativos exigiriam decisão de negócio não inferível |
