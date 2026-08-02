# Plano de contatos

## Contexto atual

O Fluvius cria contatos principalmente a partir de mensagens recebidas. O painel
de contato mostra o perfil persistido, permite atualização via provider e usa
esse cache para conversas, grupos e menções. Na versão `v0.0.16`, membros de
grupo sem nome vindo do provider passaram a usar, na resposta da API, o nome de
um contato direto já conhecido no mesmo tenant e telefone. Isso melhora o picker
de `@` sem mudar o contrato de envio ao WhatsApp.

Já existe uma agenda operacional inicial com listagem, busca, criação manual,
edição de nome e abertura/reabertura de conversa por canal conectado. Ainda não
existe envio de cartão de contato entre conversas.

## Objetivo

Permitir que um atendente autorizado encontre, crie e use contatos do tenant
dentro do fluxo de atendimento:

- iniciar uma conversa com um contato novo pelo Fluvius;
- manter uma lista operacional de contatos diretos do tenant;
- compartilhar um contato em uma conversa, parecido com o envio de contato do
  WhatsApp;
- preservar tenant, canal e provider sempre resolvidos pela API.

## Fase 1: agenda operacional mínima

Estado: implementada como primeira versão. A tela de contatos é simples, sem
CRM, e cobre:

- listagem paginada tenant-scoped de contatos diretos;
- busca por nome e telefone;
- criação manual de contato com nome e telefone;
- edição mínima de nome operacional;
- validação de telefone normalizado e unicidade por `(tenant_id, phone_number)`;
- ação para abrir conversa em canal conectado.

Essa fase não deve criar campos comerciais, funil, tags, empresas, campanhas ou
histórico analítico.

## Fase 2: iniciar conversa com contato novo

Estado: implementada no fluxo básico. O atendimento ativo segue:

1. O usuário escolhe um canal conectado ao qual tem acesso.
2. A API valida membership, acesso ao canal e `channel.status=connected`.
3. A API cria ou reutiliza o contato direto pelo telefone normalizado.
4. A API cria ou reutiliza a conversa única `(tenant_id, channel_id, contact_id)`.
5. Se a conversa estiver `closed`, ela volta para `new` sem atribuição
   automática.
6. A UI abre a conversa no composer; o envio continua seguindo o fluxo normal
   de mensagem `pending` e outbox.

Decisão atual: para reduzir erro operacional, o primeiro envio continua exigindo
que o atendente assuma a conversa antes de mandar mensagem, mantendo a regra
atual de atendimento.

## Fase 3: compartilhar contato em conversa

Modelar o envio de contato como um novo tipo de mensagem, não como texto solto:

- adicionar `contact` ao enum `message_type`;
- criar `MessageContactShare` ou payload JSON estruturado com snapshots:
  `display_name`, `phone_number` e, futuramente, `organization`;
- permitir selecionar contato existente ou informar nome/telefone manualmente;
- persistir o snapshot para que o histórico não mude se o contato for editado;
- renderizar bolha específica no frontend com nome, telefone e ação de abrir ou
  salvar contato no Fluvius.

No provider, a primeira implementação deve confirmar o contrato real da
Evolution Go para vCard/contact message. Se a rota nativa não estiver confirmada
na versão fixada, usar fallback temporário como texto formatado somente com
autorização explícita, porque isso não é equivalente ao cartão do WhatsApp.

## Fase 4: recebimento de cartões de contato

Quando o webhook trouxer mensagem de contato/vCard:

- normalizar o payload no adapter;
- persistir como `message_type=contact`;
- guardar snapshot do contato compartilhado;
- oferecer ação na UI para criar ou vincular esse contato ao tenant;
- manter idempotência pelo ID da mensagem do provider.

## Segurança e limites

- Toda listagem, criação, atualização e conversa deve filtrar `tenant_id`.
- IDs vindos da URL não provam pertencimento ao tenant.
- O frontend nunca chama Evolution Go diretamente.
- O canal usado para iniciar conversa precisa ser persistido e autorizado.
- Não enviar mensagem se o canal não estiver `connected`.
- Não usar contato compartilhado para criar conversa sem confirmação do usuário.
- Não importar agenda completa do WhatsApp sem contrato confirmado do provider.

## Testes esperados

- isolamento entre tenants para listagem, criação e abertura de conversa;
- acesso por canal para atendentes sem permissão global;
- criação idempotente de contato por telefone;
- abertura/reabertura de conversa por canal;
- bloqueio quando canal desconectado;
- envio e retry de mensagem de contato quando houver contrato provider;
- parsing de webhook de contato recebido com fixture sanitizada.
