# Changelog

Formato inspirado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Versionamento semântico a partir do MVP (`0.0.x`).

## [0.0.66] — 2026-09-01

Foco: **recuperação e estabilidade da integração com Evolution Go**.

### Added

- Contrato executável das rotas Evolution Go 0.7.2, snapshot curado do
  Swagger, certificador sanitizado e diagnóstico administrativo por canal.
- Indicadores de versão do gateway, último envio confirmado e eventos fora do
  contrato na saúde operacional tenant-scoped.

### Fixed

- Canais legados copiam a credencial resolvida para o cofre cifrado na primeira
  operação autenticada, eliminando a dependência contínua da variável legada.
- A imagem `0.7.2-connection-pool-fix.3` fecha o `sqlstore.Container`
  substituído em reconexões, impedindo o acúmulo de conexões ociosas em
  `evogo_auth` e a saturação do PostgreSQL.
- Falhas HTTP, de rede e respostas inválidas na consulta de status retornam
  erros seguros e nunca são tratadas como conexão bem-sucedida.

### Validation

- 188 testes de API e integração aprovados com PostgreSQL e Alembic sem drift.
- Pacotes Go afetados, imagem Evolution Go completa, build Vue/TypeScript,
  configurações Compose e scripts de deploy aprovados.

## [0.0.65] — 2026-08-31

Foco: **conclusão segura do rollout blue/green**.

### Fixed

- O job de reconfiguração de webhooks agora roda após a pausa dos workers e
  antes da API candidata, evitando disputar conexões com os pools dos dois
  slots simultaneamente.
- A API candidata permanece validada antes da troca de tráfego, preservando o
  rollback automático e a continuidade do slot ativo.

### Validation

- Sintaxe Bash, compilação da API e configurações Compose aprovadas; a ordem foi
  ajustada com base no log completo do rollout anterior.

## [0.0.64] — 2026-08-31

Foco: **correção do boot do slot blue/green**.

### Fixed

- Os workers do slot ativo agora liberam conexões antes do início da API
  candidata, evitando que a verificação de saúde expire durante a sobreposição
  temporária das duas APIs.
- Em caso de falha no boot, o candidato é parado e a frota anterior volta a
  processar as filas persistentes.

### Validation

- Sintaxe Bash, compilação da API e configurações Compose aprovadas após o
  ajuste da ordem operacional.

## [0.0.63] — 2026-08-31

Foco: **publicação corretiva da personalização do posto de atendimento**.

### Fixed

- O rollout blue/green limpa candidatos abandonados e pausa os workers antigos
  antes do job de reconfiguração, mantendo o uso de conexões dentro do limite do
  PostgreSQL.
- Falhas antes ou depois da troca de tráfego restauram o slot e os workers
  anteriores sem tratar uma implantação incompleta como sucesso.

### Validation

- Sintaxe do script de produção, compilação da API e configurações Compose de
  desenvolvimento, produção e blue/green aprovadas.

## [0.0.62] — 2026-08-31

Foco: **personalização segura do posto de atendimento**.

### Added

- Nova área **Minha conta** para qualquer usuário alterar o próprio nome de
  exibição e trocar a senha mediante confirmação da senha atual.
- Preferências locais de tema e som de novas mensagens, com teste de áudio e
  persistência somente no navegador.
- Endpoint autenticado `PATCH /api/v1/auth/me`, com validação, hash da nova
  senha e auditoria sem valores sensíveis.
- Sistema visual reutilizável em `.interface-design/system.md`.

### Changed

- O avatar no desktop e o menu mobile passam a oferecer acesso direto às
  configurações da conta.
- O aviso de reconexão participa do fluxo no mobile e deixa de cobrir títulos
  ou controles.

### Validation

- 180 testes de API e integração aprovados com PostgreSQL.
- Build Vue/TypeScript, Alembic sem drift e configurações Compose aprovados.

## [0.0.59] — 2026-08-28

Foco: **execução do Agente de IA nas conversas reais**.

### Fixed

- O worker de webhook agora aguarda o turno da IA antes de encerrar o
  `asyncio.run()`, evitando que a tarefa seja cancelada antes de chamar o LLM
  e criar a resposta pela outbox.
- A documentação registra o ciclo de vida correto da sessão e do turno de IA.

## [0.0.58] — 2026-08-28

Foco: **correção do gate de testes da release do Agente de IA**.

### Fixed

- O teste de HistorySync usa uma data relativa segura e não falha quando o
  relógio do CI ultrapassa o limite exato de 30 dias.
- A funcionalidade de triagem e o reconhecimento do nome do agente da release
  `v0.0.57` ficam preservados nesta release corrigida.

## [0.0.57] — 2026-08-28

Foco: **triagem do Agente de IA e identidade configurável do bot**.

### Added

- O nome configurado do agente passa a ser incluído na identidade enviada ao
  LLM. O cliente pode chamar o bot pelo nome sem que isso seja obrigatório
  para receber uma resposta.
- Triagem determinística para pedidos explícitos de atendente e sinais
  objetivos de reclamação, com transbordo sem chamar o LLM.
- Política de triagem no contexto do LLM para evitar respostas fora do escopo,
  sem informação suficiente ou com baixa confiança.
- Testes de reconhecimento do nome do agente e do transbordo determinístico.

## [0.0.56] — 2026-08-28

Foco: **integração confiável do Agente de IA com a outbox de mensagens**.

### Fixed

- Respostas automáticas da IA agora criam `Message(pending)` e
  `MessageDelivery(queued)` com `tenant_id` antes de serem enviadas ao worker
  de entrega.
- O dispatcher recebe o tenant explicitamente e o worker continua responsável
  por resolver o canal/provider e confirmar o ID externo antes de marcar a
  mensagem como `sent`.
- Eventos realtime da IA usam os contratos existentes (`message.created` e
  `conversation.updated`) e incluem `channel_id`, permitindo atualização dos
  sockets com escopo de canal.
- O turno assíncrono da IA fecha sua sessão SQLAlchemy após o processamento,
  evitando esgotamento do pool de conexões.
- Teste de regressão cobre outbox tenant-scoped, dispatcher e eventos realtime.

### Notes

- O Agente de IA é um módulo opcional pós-MVP e permanece desativado por
  padrão. Sua configuração é por canal; somente administradores podem
  configurar/testar o agente, e a chave do provedor fica cifrada no backend.
- Mensagens de grupos não ativam o bot. Solicitações de atendimento humano
  desativam o bot na conversa e preservam o motivo do transbordo.

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
