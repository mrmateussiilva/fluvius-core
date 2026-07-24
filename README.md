# Fluvius Core

O Fluvius Core é um núcleo próprio, WhatsApp-first, para multiatendimento. Esta fundação substitui a dependência de um Chatwoot customizado por uma API, uma interface operacional e um contrato de gateway controlados pelo Fluvius.

Esta etapa entrega os pilares técnicos, não o produto completo.

## Stack

- API: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis e RQ.
- Realtime: WebSocket nativo do FastAPI.
- Web: Vue 3, Vite, TypeScript, Vue Router, Pinia, TailwindCSS e lucide-vue-next.
- Gateway padrão: Evolution Go, atrás do contrato `WhatsAppProvider`.
- Storage inicial: volume local, atrás do contrato `StorageProvider`.

## Rodando localmente

Requisitos: Docker e Docker Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

A migration roda automaticamente ao iniciar a API. Em outro terminal, crie o primeiro tenant e usuário administrador:

```bash
docker compose exec api python -m app.jobs.bootstrap \
  --tenant-name "Empresa local" \
  --tenant-slug "empresa-local" \
  --email "admin@example.com" \
  --name "Administrador" \
  --password "troque-esta-senha"
```

Serviços locais:

- Web: http://localhost:5173
- API e OpenAPI: http://localhost:8000/docs
- Healthcheck: http://localhost:8000/health
- Evolution Go/Manager: http://localhost:8080

Antes de usar o gateway, ajuste os segredos do `.env` e conclua a ativação exigida pela versão do Evolution Go. Na versão 0.7.2, `EVOLUTION_GO_GLOBAL_API_KEY` administra o gateway e `EVOLUTION_GO_API_KEY` deve receber o token da instância usada pelo Fluvius. O nome da instância continua registrado em `provider_config.instance_name` como referência não secreta.

## Comandos principais

```bash
docker compose up --build
docker compose down
docker compose logs -f api worker evolution-go
docker compose exec api alembic current
docker compose exec api alembic upgrade head
docker compose exec web npm run build
curl http://localhost:8000/health
```

Para desenvolvimento fora do Docker:

```bash
cd api && python -m venv .venv && .venv/bin/pip install -e '.[dev]'
cd web && npm install && npm run dev
```

## Escopo do MVP

O MVP cobre login, canais WhatsApp, filas de conversas, assumir/finalizar atendimento, mensagens de texto e anexos básicos, respostas rápidas, perfil operacional básico do contato, webhook, status/QR e realtime em uma única réplica da API.

Não entram agora: dashboard, CRM, IA, billing, campanhas, Meta Cloud completa, BSP completo, automações avançadas e arquitetura herdada do Chatwoot. Veja [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md).

## Arquitetura em uma frase

O navegador fala exclusivamente com o Fluvius Core; a API resolve o provider configurado no canal, valida tenant e estado do canal, e só então chama o gateway. Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Estado desta fundação

- Os endpoints iniciais existem e são tenant-scoped.
- A mensagem outgoing é persistida como `pending` antes da chamada externa.
- O provider precisa confirmar um ID para a mensagem virar `sent`; falhas viram `failed`.
- O composer e a API bloqueiam envio com o canal offline.
- O worker RQ está disponível, mas o envio ainda é síncrono para manter simples a confirmação nesta etapa.
- Payloads e rotas exatas do Evolution Go devem ser validados contra o Swagger da imagem escolhida antes de produção.
