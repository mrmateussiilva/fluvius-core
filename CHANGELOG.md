# Changelog

Formato inspirado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Versionamento semântico a partir do MVP (`0.0.x`).

## [0.0.4] — 2026-07-30

Foco: **confiabilidade da Evolution Go / webhooks** e capacidade da API em produção.

### Added

- Loop automático de reconciliação de webhooks pendentes (recibos e edições
  aguardando a mensagem correspondente), com eleição de líder via Redis
  (`api/app/providers/reconcile.py`).
- Constantes canônicas de erro pendente em `api/app/providers/pending_events.py`.
- Circuit breaker em memória para consultas de perfil/grupo da Evolution
  (`api/app/providers/evolution_circuit.py`).
- Métricas de webhook na saúde operacional:
  - `pending_provider_events`, `failed_provider_events`, `oldest_pending_event_at`
  - `stale_connected_channels`
  - por canal: `pending_events`, `failed_events`, `webhook_stale`
- Cards e detalhes de webhook na tela **Saúde operacional**.
- Migration `20260730_0018`: índices em `provider_events` para health/reconcile
  (`tenant_id/processed/created_at`, `channel_id/processed/created_at`).
- Backup com dumps dedicados de `evogo_auth` (licença) e `evogo_users` (instâncias).
- Variáveis de produção `UVICORN_WORKERS`, `UVICORN_LIMIT_CONCURRENCY`,
  `UVICORN_BACKLOG` (padrão 4 / 200 / 2048).

### Changed

- API de produção sobe com **múltiplos workers uvicorn** (padrão 4), backlog e
  limite de concorrência maiores; container com até 2 GB RAM e 3 CPUs.
- Pool SQLAlchemy limitado (`pool_size=5`, `max_overflow=5`) por processo.
- Dispatcher de entregas usa lock Redis (um líder entre workers da API).
- Timeouts Evolution Go: envio ~12s (connect 5s); perfil/grupo ~6s (connect 3s).
- Decode de mídia base64 no webhook fora do event loop (`asyncio.to_thread`).
- Health considera crítico webhook pendente há mais de 15 minutos.
- Documentação: `ARCHITECTURE.md`, `PROVIDERS.md`, `PRODUCTION_VPS.md`.

### Fixed

- Risco de a API travar o accept TCP sob carga de webhooks/mídia (workers +
  timeouts + circuit breaker).
- Eventos de recibo/edição “à espera da mensagem” deixam de depender só da
  sincronização administrativa manual.

### Files touched (resumo)

| Área | Arquivos |
|------|----------|
| API core | `main.py`, `database.py`, `delivery/dispatcher.py`, `attachments/service.py` |
| Providers | `evolution_go.py`, `webhook_router.py`, `reconcile.py`, `pending_events.py`, `evolution_circuit.py` |
| Ops | `operations/router.py`, `operations/schemas.py` |
| Sync | `sync/tasks.py` (usa constantes compartilhadas) |
| DB | `alembic/versions/20260730_0018_*.py` |
| Web | `OperationalHealthPage.vue`, `api/types.ts`, `config/app.ts` |
| Deploy | `docker-compose.prod.yml`, `backup.sh`, `.env.production.example`, `generate-production-env.sh` |
| Docs/tests | `ARCHITECTURE.md`, `PROVIDERS.md`, `PRODUCTION_VPS.md`, testes de health/invariants |

### Upgrade notes (VPS)

1. Deploy da tag/release `v0.0.4` (ou build da API+web após pull).
2. Migration sobe sozinha no fluxo de deploy (`20260730_0018`).
3. Opcional em `.env.production`: `UVICORN_WORKERS=4`.
4. Após subir a API, se webhooks falharem com IP antigo: `restart evolution-go`.
5. Conferir: `curl -fsS http://127.0.0.1:18000/health/ready` e tela Saúde operacional.

## [0.0.3] — 2026-07-30

- Bump de versão do pacote web/API.
- Deploy por release tags, melhorias de produção e fluxo Evolution/canais
  (ver histórico Git a partir de `ae04745`).

## [0.0.2] — anterior

- Polimento da UI de login e bump de versão.

## [0.0.1] — inicial

- MVP inicial do Fluvius Core.
