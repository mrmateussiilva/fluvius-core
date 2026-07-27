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

Antes de usar o gateway, ajuste os segredos do `.env` e conclua a ativação exigida pela versão do Evolution Go. O Compose compila uma imagem derivada do Evolution Go 0.7.2, fixada no commit oficial `9337afc47e10b86cc896a6f432240e40fee95dd1`, com o patch mínimo que decripta edições `SecretEncryptedMessage` antes do webhook. Na versão 0.7.2, `EVOLUTION_GO_GLOBAL_API_KEY` administra o gateway e `EVOLUTION_GO_API_KEY` recebe o token no modo compatível de instância única. Para múltiplas instâncias, `EVOLUTION_GO_INSTANCE_TOKENS` contém um mapa JSON entre o nome não secreto usado pelo canal e seu token. A tela **Canais do WhatsApp** inicia a conexão, exibe QR/código de pareamento e acompanha o status sem enviar credenciais ao navegador.

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

O MVP cobre login, canais WhatsApp, filas de conversas, quadro operacional da equipe, assumir/finalizar atendimento, mensagens de texto e anexos básicos, respostas rápidas, perfil operacional básico do contato, webhook, status/QR e realtime em uma única réplica da API.

Não entram agora: dashboard, CRM, IA, billing, campanhas, Meta Cloud completa, BSP completo, automações avançadas e arquitetura herdada do Chatwoot. Veja [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md).

## Arquitetura em uma frase

O navegador fala exclusivamente com o Fluvius Core; a API resolve o provider configurado no canal, valida tenant e estado do canal, e só então chama o gateway. Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Estado desta fundação

- Os endpoints iniciais existem e são tenant-scoped.
- Assumir uma conversa é atômico; atendentes não podem sobrescrever a atribuição ativa. Administradores podem assumir ou transferir o atendimento para outro usuário ativo da própria empresa, com registro em auditoria.
- O **Quadro da equipe** organiza a fila aguardando e os atendimentos de cada usuário ativo. Todos podem acompanhar a distribuição; administradores arrastam os cards, usam o seletor para transferir ou devolvem uma conversa à fila, sempre pela API auditada.
- Responder, reenviar e finalizar exigem que a conversa esteja atribuída ao agente autenticado.
- A mensagem outgoing é persistida como `pending` antes da chamada externa.
- Em texto e anexo, o navegador cria o UUID exibido na bolha otimista e a API reutiliza esse UUID como chave idempotente. Anexos também validam a assinatura real do arquivo e guardam seu SHA-256.
- O provider precisa confirmar um ID para a mensagem virar `sent`; falhas viram `failed`.
- Administradores gerenciam a equipe da própria empresa em **Usuários**: criam acessos individuais, definem administrador/atendente, redefinem senha e desativam memberships sem atravessar tenants. Os números disponíveis continuam sendo exclusivamente os canais cadastrados naquela empresa.
- Textos e legendas enviados pelo número compartilhado recebem automaticamente `*Nome do atendente:*` em negrito no WhatsApp. O nome usado fica preservado na mensagem para auditoria e retries.
- Edições atualizam a mensagem original, aparecem como `editada` e nunca criam
  uma bolha `[text]`; reações ficam fora do MVP.
- O composer e a API bloqueiam envio com o canal offline.
- O chat preserva rascunho e posição por conversa, não força a rolagem de quem lê o histórico e só marca leitura quando o final está visível. A interface agrupa mensagens consecutivas, oferece ações contextuais, visualização ampliada de mídia, seletor de emojis, botão dedicado para figurinha e um menu de anexos separado em fotos/vídeos, documentos e áudio, além de colagem e arrastar e soltar. PNG/JPG escolhidos como figurinha são convertidos para WebP 512×512 e enviados pelo fluxo nativo de sticker, sem legenda. Áudios usam player próprio com progresso e velocidades `1x`, `1,5x` e `2x`.
- O worker RQ está disponível, mas o envio ainda é síncrono para manter simples a confirmação nesta etapa.
- Payloads e rotas exatas do Evolution Go devem ser validados contra o Swagger da imagem escolhida antes de produção.
