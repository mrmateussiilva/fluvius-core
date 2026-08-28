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

A migration roda automaticamente ao iniciar a API. Em outro terminal, crie o
primeiro tenant e o administrador da plataforma:

```bash
docker compose exec api python -m app.jobs.bootstrap \
  --tenant-name "Empresa local" \
  --tenant-slug "empresa-local" \
  --email "admin@example.com" \
  --name "Administrador" \
  --password "troque-esta-senha" \
  --platform-admin
```

Serviços locais:

- Web: http://localhost:5173
- API e OpenAPI: http://localhost:8000/docs
- Healthcheck: http://localhost:8000/health
- Evolution Go/Manager: http://localhost:8080

## Produção na VPS

A implantação de produção usa Ubuntu, o Caddy do host para HTTPS/WSS, frontend
estático em loopback, serviços internos e dados persistentes sob
`/srv/fluvius`. O domínio preparado é `fluvius.finderbit.com.br`.

```bash
sudo ./deploy/scripts/install-ubuntu.sh
./deploy/scripts/generate-production-env.sh
# Instale deploy/Caddyfile.host no Caddy já executado pelo Ubuntu.
./deploy/scripts/production-deploy.sh
```

O pipeline de GitHub Actions valida API, frontend e Compose antes de publicar o
SHA aprovado na VPS por SSH. A configuração dos secrets, da chave do host e da
trava de ativação está em [docs/GITHUB_ACTIONS.md](docs/GITHUB_ACTIONS.md).
O deploy publicado na VPS roda em etapas pelo script
`deploy/scripts/production-deploy.sh`: migrations em container temporário,
troca da API sem migration no boot, workers depois da API e frontend por
último. Não substitua esse fluxo por `docker compose up` genérico em produção.

Use `docker-compose.prod.yml`; o Compose local continua destinado ao
desenvolvimento. Instalação, firewall, backups, restauração e operação estão em
[docs/PRODUCTION_VPS.md](docs/PRODUCTION_VPS.md).

Antes de usar o gateway, ajuste os segredos únicos da instalação no `.env` e
conclua a ativação única exigida pela versão do Evolution Go. Em produção, o
Manager fica vinculado a `127.0.0.1:18081` e o Caddy o disponibiliza com HTTPS
em `evolution.finderbit.com.br`, conforme
[docs/PRODUCTION_VPS.md](docs/PRODUCTION_VPS.md). O Compose
compila uma imagem derivada do Evolution Go 0.7.2, fixada no commit oficial
`9337afc47e10b86cc896a6f432240e40fee95dd1`, com o patch mínimo que decripta
edições `SecretEncryptedMessage` antes do webhook.
`EVOLUTION_GO_GLOBAL_API_KEY` permite que somente a API crie instâncias e
`PROVIDER_CREDENTIALS_KEY` cifra seus tokens no banco. Depois da ativação
inicial, administradores criam o canal e recebem o QR pela tela **Canais do
WhatsApp**, sem editar o `.env` por número ou acessar o Manager.
`EVOLUTION_GO_API_KEY` e `EVOLUTION_GO_INSTANCE_TOKENS` permanecem apenas para
canais legados.

O módulo opcional **Agente de IA** está disponível a partir da release
`v0.0.56`. Ele fica desativado por padrão, é configurado por canal por um
administrador e usa a mesma outbox de mensagens do atendimento humano. O fluxo
completo, incluindo transbordo e limites de segurança, está em
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Comandos principais

```bash
docker compose up --build
docker compose down
docker compose logs -f api delivery-worker webhook-worker worker evolution-go
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

## Testes

Os testes unitários da API podem ser executados no ambiente Python de desenvolvimento:

```bash
cd api
python -m unittest discover -s tests -v
```

A suíte completa usa um PostgreSQL temporário, aplica todas as migrations e inclui os testes de
isolamento entre tenants e do ciclo de atendimento:

```bash
./scripts/test-integration.sh
```

O Compose de testes usa um projeto isolado chamado `fluvius-core-test`. O script encerra os
containers e remove os volumes temporários mesmo quando algum teste falha; ele não utiliza o banco
de desenvolvimento.

## Escopo do MVP

O MVP cobre login, canais WhatsApp, filas de conversas, quadro operacional da equipe, sincronização operacional administrativa, assumir/finalizar atendimento, mensagens de texto e anexos básicos, respostas rápidas, perfil operacional básico do contato, webhook, status/QR e realtime em uma única réplica da API.

Não entram agora: dashboard, CRM, IA, billing, campanhas, Meta Cloud completa, BSP completo, automações avançadas e arquitetura herdada do Chatwoot. Veja [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md).

## Arquitetura em uma frase

O navegador fala exclusivamente com o Fluvius Core; a API valida tenant, canal e atendimento, persiste a outbox e o delivery worker resolve o provider antes de chamar o gateway. Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Estado desta fundação

- Os endpoints iniciais existem e são tenant-scoped.
- Assumir uma conversa é atômico; atendentes não podem sobrescrever a atribuição ativa. Administradores podem assumir ou transferir o atendimento para outro usuário ativo da própria empresa, com registro em auditoria.
- O **Quadro da equipe** é exclusivo para administradores e organiza a fila aguardando e os atendimentos de cada usuário ativo. O admin arrasta os cards, usa o seletor para transferir ou devolve uma conversa à fila, sempre pela API auditada.
- A tela **Sincronização** é exclusiva para administradores e executa no worker a atualização de até 50 contatos conhecidos, a reconciliação de até 500 edições/recibos recentes já persistidos ou ambas. Ela mostra progresso auditável por canal e não promete importar o histórico completo do WhatsApp.
- A tela **Saúde operacional** é exclusiva para administradores da empresa e
  acompanha Redis, presença dos dois workers, entregas pendentes ou atrasadas,
  falhas recentes e conexão dos canais. Situações de atenção ou críticas também
  aparecem no topo da área autenticada, com atualização automática.
- Responder, reenviar e finalizar exigem que a conversa esteja atribuída ao agente autenticado.
- A mensagem outgoing e sua outbox são persistidas juntas antes da chamada externa. A API responde `202/pending`, e um delivery worker exclusivo processa a fila sem concorrer com sincronizações administrativas.
- Em texto e anexo, o navegador cria o UUID exibido na bolha otimista e a API reutiliza esse UUID como chave idempotente. Anexos também validam a assinatura real do arquivo e guardam seu SHA-256.
- O provider precisa confirmar um ID para a mensagem virar `sent`; falhas viram `failed`.
- O Agente de IA, quando habilitado, também cria mensagens `pending` na outbox;
  não envia diretamente ao provider, não opera em grupos e desativa o bot ao
  solicitar transbordo humano.
- Administradores gerenciam a equipe da própria empresa em **Usuários**: criam acessos individuais, definem administrador/atendente, atribuem os canais permitidos, redefinem senha e desativam memberships sem atravessar tenants. Conversas e quadro podem ser filtrados por canal; a visão consolidada é exclusiva de administradores.
- O administrador da plataforma usa **Administração Fluvius** para criar,
  inspecionar, ativar ou suspender empresas. Cada empresa recebe um link
  `/login/{slug}` que restringe a autenticação àquela membership; na criação, o
  link, o e-mail e a senha inicial aparecem uma única vez para envio ao cliente.
  Entrar em uma empresa para suporte cria uma membership administrativa e
  registra a ação no log auditável do tenant; administradores comuns nunca
  acessam essa área.
- Textos e legendas enviados pelo número compartilhado recebem automaticamente `*Nome do atendente:*` em negrito no WhatsApp. O nome usado fica preservado na mensagem para auditoria e retries.
- Edições atualizam a mensagem original, aparecem como `editada` e nunca criam
  uma bolha `[text]`; reações ficam fora do MVP.
- O composer e a API bloqueiam envio com o canal offline.
- O chat preserva rascunho e posição por conversa, não força a rolagem de quem lê o histórico e só marca leitura quando o final está visível. A interface agrupa mensagens consecutivas, oferece ações contextuais, visualização ampliada de mídia, seletor de emojis, botão dedicado para figurinha e um menu de anexos separado em fotos/vídeos, documentos e áudio, além de colagem e arrastar e soltar. PNG/JPG escolhidos como figurinha são convertidos para WebP 512×512 e enviados pelo fluxo nativo de sticker, sem legenda. Áudios usam player próprio com progresso e velocidades `1x`, `1,5x` e `2x`.
- Redis possui filas separadas de entrega e manutenção. O PostgreSQL recupera
  uma entrega que não chegou ao Redis, preserva a ordem por conversa e limita
  retries automáticos a falhas comprovadamente transitórias. Exceções internas
  dos workers também encerram o job como falha no RQ, sem produzir um falso
  `Job OK` nos logs.
- Payloads e rotas exatas do Evolution Go devem ser validados contra o Swagger da imagem escolhida antes de produção.
