# Banco de dados

## Entidades

| Entidade | Papel | Escopo de tenant |
|---|---|---|
| `Tenant` | Conta/organização | É a raiz |
| `User` | Identidade global de login | Global |
| `TenantUser` | Membership e papel do usuário | `tenant_id` |
| `WhatsAppChannel` | Canal e provider configurado | `tenant_id` |
| `Contact` | Cliente identificado por telefone | `tenant_id` |
| `Conversation` | Atendimento de um contato em um canal | `tenant_id` |
| `ConversationRead` | Última leitura de uma conversa por usuário | `tenant_id` |
| `Message` | Mensagem recebida ou enviada | `tenant_id` |
| `MessageAttachment` | Metadados do arquivo de uma mensagem | `tenant_id` |
| `QuickReply` | Texto reutilizável no atendimento | `tenant_id` |
| `ProviderEvent` | Evento bruto, deduplicação e diagnóstico | `tenant_id` |
| `AuditLog` | Trilha de ações relevantes | `tenant_id` |

## Relacionamentos

- `Tenant 1—N TenantUser N—1 User`.
- `Tenant 1—N WhatsAppChannel` e `Tenant 1—N Contact`.
- `Conversation` pertence a tenant, canal e contato; pode apontar para um usuário responsável.
- `ConversationRead` relaciona conversa e usuário e é único por `(tenant_id, conversation_id, user_id)`.
- `Message` pertence a tenant e conversa; mensagens outgoing podem apontar para o usuário remetente e qualquer mensagem pode referenciar outra mensagem da mesma conversa como resposta.
- `MessageAttachment` pertence à mensagem, repete o tenant e guarda nome, MIME type, tamanho, chave de storage e URL pública controlada pelo Fluvius.
- `ProviderEvent` pertence ao canal e guarda o payload bruto.

Contatos são únicos por `(tenant_id, phone_number)`. Conversas são únicas por `(tenant_id, channel_id, contact_id)`, mantendo um histórico contínuo de WhatsApp por contato e canal. Além do nome operacional e telefone, contatos podem guardar o último retrato normalizado do WhatsApp (`push_name`, nome comercial/verificado, recado, foto, existência no WhatsApp e data/erro de sincronização). Esses campos são cache e podem ficar ausentes por privacidade; dados históricos continuam derivados da conversa e das mensagens. IDs externos de mensagem são únicos por `(tenant_id, provider_message_id)`. Eventos, quando têm ID externo, são únicos por `(channel_id, provider_event_id)`.

## Enums

- `channel.provider`: `evolution_go`, `meta_cloud`, `bsp`.
- `channel.status`: `disconnected`, `connecting`, `connected`, `requires_qr`, `failed`.
- `conversation.status`: `new`, `open`, `closed`.
- `message.direction`: `incoming`, `outgoing`.
- `message.type`: `text`, `image`, `document`, `audio`, `video`, `sticker`.
- `message.status`: `pending`, `sent`, `delivered`, `read`, `failed`.

## Regras críticas

1. Toda query operacional deve ter condição explícita de `tenant_id`, mesmo quando o ID pareça globalmente único.
2. `tenant_id` do webhook é sempre derivado do canal persistido.
3. Mensagem outgoing é criada como `pending` antes da chamada ao provider.
4. `sent` exige confirmação positiva e `provider_message_id`.
5. Falha confirmada ou resposta sem confirmação muda para `failed`; não mascarar como sucesso.
6. Canal diferente de `connected` bloqueia envio antes de criar a mensagem.
7. Finalizar move a conversa para `closed`, mas não separa seu histórico. A próxima incoming reabre a mesma conversa como `new`, sem atendente; um envio explícito do operador a reabre como `open` e atribui o operador atual.
8. Payload bruto de provider pode conter dado pessoal; produção precisa de retenção, mascaramento e controles LGPD.
9. A contagem de não lidas é individual por usuário e considera apenas mensagens `incoming` posteriores a `last_read_at`.
10. Perfil de contato é consultado sempre pelo provider do canal validado e nunca diretamente pelo frontend; ausência de foto/recado não é erro de cadastro.
11. `reply_to_message_id` deve apontar para uma mensagem do mesmo tenant e conversa; o ID externo citado é preservado para interoperabilidade com o provider.
12. `sent_at`, `delivered_at` e `read_at` registram fatos distintos. Horários ausentes permanecem nulos; um recibo `read` também confirma entrega, mas nenhum estado pode regredir.
13. Reenvio manual é permitido somente para mensagem outgoing em `failed`, incrementa `attempt_count` e volta a persistir `pending` antes do efeito externo.
14. Mídia recebida é decodificada pelo adapter e copiada para o storage do Fluvius antes da resposta ao webhook. O frontend nunca usa diretamente a URL criptografada do WhatsApp.
15. Uploads locais têm limite de 25 MB. Figurinhas usam WebP; vídeo e áudio preservam o MIME type para reprodução no navegador.

## Migration inicial

`api/alembic/versions/20260721_0001_initial.py` cria as onze tabelas iniciais, enums, chaves estrangeiras, constraints de deduplicação e índices de tenant. `20260722_0002_conversation_reads.py` adiciona os marcadores de leitura por usuário. `20260722_0003_contact_profiles.py` adiciona o cache de perfil WhatsApp aos contatos. `20260722_0004_message_replies_delivery_times.py` adiciona citações, contagem de tentativas e timestamps de envio/entrega/leitura. `20260722_0005_single_conversation_per_contact.py` consolida conversas duplicadas sem apagar mensagens e impede novas duplicatas por contato/canal. `20260722_0006_video_and_sticker_messages.py` adiciona vídeo e figurinha ao enum. Defaults de UUID e estados são aplicados pela camada ORM; integrações que escrevam SQL diretamente devem fornecê-los explicitamente.

A `20260722_0005` é uma migration de dados e consulta as conversas existentes para escolher e
consolidar registros. Por isso, a cadeia completa deve ser validada com `alembic upgrade head`
conectado ao PostgreSQL; a geração offline integral com `alembic upgrade head --sql` não é
suportada a partir dessa revisão.
