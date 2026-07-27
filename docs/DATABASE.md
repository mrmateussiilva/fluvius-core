# Banco de dados

## Entidades

| Entidade | Papel | Escopo de tenant |
|---|---|---|
| `Tenant` | Conta/organização | É a raiz |
| `User` | Identidade global de login | Global |
| `TenantUser` | Membership e papel do usuário | `tenant_id` |
| `TenantUserChannel` | Canais permitidos para um atendente | `tenant_id` |
| `WhatsAppChannel` | Canal e provider configurado | `tenant_id` |
| `Contact` | Cliente identificado por telefone | `tenant_id` |
| `Conversation` | Atendimento de um contato em um canal | `tenant_id` |
| `ConversationRead` | Última leitura de uma conversa por usuário | `tenant_id` |
| `Message` | Mensagem recebida ou enviada | `tenant_id` |
| `MessageRevision` | Histórico técnico de edição de uma mensagem | `tenant_id` |
| `MessageAttachment` | Metadados do arquivo de uma mensagem | `tenant_id` |
| `MessageDelivery` | Outbox e estado da entrega outgoing | `tenant_id` |
| `QuickReply` | Texto reutilizável no atendimento | `tenant_id` |
| `ProviderEvent` | Evento bruto, deduplicação e diagnóstico | `tenant_id` |
| `ProviderCredential` | Credencial cifrada e estado do provisionamento | `tenant_id` |
| `SyncRun` | Execução e progresso de sincronização administrativa | `tenant_id` |
| `AuditLog` | Trilha de ações relevantes | `tenant_id` |

## Relacionamentos

- `Tenant 1—N TenantUser N—1 User`.
- `Tenant 1—N WhatsAppChannel` e `Tenant 1—N Contact`.
- `Conversation` pertence a tenant, canal e contato; pode apontar para um usuário responsável.
- `ConversationRead` relaciona conversa e usuário e é único por `(tenant_id, conversation_id, user_id)`.
- `TenantUser` usa os papéis `admin` e `agent`. A membership, não o cadastro global do usuário, controla se a pessoa pode acessar cada empresa.
- `TenantUserChannel` é único por `(tenant_id, user_id, channel_id)`. Administradores são irrestritos dentro do tenant; atendentes dependem dessas associações.
- `Message` pertence a tenant e conversa; mensagens outgoing podem apontar para o usuário remetente e qualquer mensagem pode referenciar outra mensagem da mesma conversa como resposta.
- `Message.sender_name` preserva o nome de exibição usado no envio, sem depender de alterações futuras no cadastro do usuário.
- `MessageRevision` pertence à mensagem, preserva o corpo anterior, o conteúdo
  novo quando disponível e o ID idempotente do evento externo.
- `MessageAttachment` pertence à mensagem, repete o tenant e guarda nome, MIME type, tamanho, chave de storage e URL pública controlada pelo Fluvius.
- `MessageDelivery` é único por mensagem e guarda somente estado da outbox, tentativas, próximo processamento e erro seguro.
- `ProviderEvent` pertence ao canal e guarda o payload bruto.
- `ProviderCredential` pertence a um canal e provider; guarda somente ciphertext autenticado, fingerprint, versão da cifra e estado seguro do provisionamento.
- `SyncRun` pertence ao tenant, canal e usuário solicitante; guarda somente estado, limites, contadores e erro seguro da execução.

Contatos são únicos por `(tenant_id, phone_number)`. Conversas são únicas por `(tenant_id, channel_id, contact_id)`, mantendo um histórico contínuo de WhatsApp por contato e canal. Além do nome operacional e telefone, contatos podem guardar o último retrato normalizado do WhatsApp (`push_name`, nome comercial/verificado, recado, foto, existência no WhatsApp e data/erro de sincronização). Esses campos são cache e podem ficar ausentes por privacidade; dados históricos continuam derivados da conversa e das mensagens. IDs externos de mensagem são únicos por `(tenant_id, provider_message_id)`. Eventos, quando têm ID externo, são únicos por `(channel_id, provider_event_id)`. Canais guardam o fingerprint da credencial resolvida, único por `(provider, credential_fingerprint)`; canais gerenciados guardam o token somente cifrado em `ProviderCredential`.

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
3. Mensagem outgoing é criada como `pending` junto de sua
   `MessageDelivery(queued)` na mesma transação, antes da chamada ao provider.
4. `sent` exige confirmação positiva e `provider_message_id`.
5. Falha confirmada ou resposta sem confirmação muda para `failed`; não mascarar como sucesso.
6. Canal diferente de `connected` bloqueia envio antes de criar a mensagem.
7. Atribuir ou liberar uma conversa bloqueia sua linha durante a transição. Atendentes podem assumir para si apenas conversas livres ou finalizadas; administradores também podem tomar uma conversa ativa, transferi-la para outro usuário ativo do mesmo tenant ou devolvê-la à fila `new`. Cada mudança registra estado anterior, novo responsável e autor em `AuditLog`.
8. Enviar texto/anexo, reenviar falha e finalizar exigem conversa `open` atribuída ao usuário autenticado.
9. Finalizar move a conversa para `closed`, mas não separa seu histórico. A próxima incoming reabre a mesma conversa como `new`, sem atendente; o operador precisa assumi-la novamente antes de responder.
10. Payload bruto de provider pode conter dado pessoal; produção precisa de retenção, mascaramento e controles LGPD.
11. A contagem de não lidas é individual por usuário e considera apenas mensagens `incoming` posteriores a `last_read_at`. Abrir ou atualizar o histórico não avança o marcador; a UI chama o endpoint de leitura somente com aba visível e final da conversa alcançado, informando a última incoming visível. A API valida essa mensagem no mesmo tenant/conversa e nunca regride `last_read_at`.
12. Perfil de contato é consultado sempre pelo provider do canal validado e nunca diretamente pelo frontend; ausência de foto/recado não é erro de cadastro.
13. `reply_to_message_id` deve apontar para uma mensagem do mesmo tenant e conversa; o ID externo citado é preservado para interoperabilidade com o provider.
14. `sent_at`, `delivered_at` e `read_at` registram fatos distintos. Horários ausentes permanecem nulos; um recibo `read` também confirma entrega, mas nenhum estado pode regredir.
15. Reenvio manual é permitido somente para mensagem outgoing em `failed`,
    reinicia sua outbox e volta a persistir `pending`; `attempt_count` incrementa
    apenas quando o worker inicia a chamada externa.
16. Para texto, `client_message_id` fornecido pelo frontend torna-se `Message.id`; repetir o mesmo ID, conteúdo e referência de resposta devolve a mensagem existente sem novo efeito externo.
17. Mídia recebida é decodificada pelo adapter e copiada para o storage do Fluvius antes da resposta ao webhook. O frontend nunca usa diretamente a URL criptografada do WhatsApp.
18. Uploads locais têm limite de 25 MB. Figurinhas usam WebP; vídeo e áudio preservam o MIME type para reprodução no navegador.
19. Somente administradores gerenciam memberships. Desativar um atendente libera suas conversas abertas para a fila `new`; um administrador não pode desativar ou rebaixar a si próprio.
20. Uma credencial de provider pode pertencer a somente um canal. O fingerprint sustenta a constraint global e o segredo gerenciado permanece cifrado com uma chave exclusiva do backend. A consulta ao cofre sempre filtra `tenant_id`, canal e provider; o frontend nunca recebe ciphertext ou token. Canais antigos ainda podem resolver o segredo pelo ambiente.
21. Edição atualiza a mensagem original e registra uma revisão; nunca cria uma
    segunda `Message`. A associação exige `tenant_id`, canal e
    `provider_message_id`. Reação não gera mensagem no MVP.
22. Texto e legenda outgoing são enviados ao WhatsApp com o prefixo em negrito
    `*sender_name:*\n`; o corpo persistido continua limpo. Retry reutiliza o mesmo
    snapshot de nome e conteúdo.
23. Somente administradores criam ou consultam `SyncRun`. Cada consulta valida
    tenant e canal; existe no máximo uma execução `queued` ou `running` por
    canal. Contatos são atualizados pelo provider somente com o canal conectado.
    A sincronização de mensagens processa apenas eventos recentes já
    persistidos e pendentes, sem importar histórico externo.
24. `MessageDelivery` é consultada sempre com `tenant_id` e `message_id`. Jobs
    duplicados não repetem o efeito porque a transição para `processing` usa
    bloqueio. Falhas de conexão claramente transitórias podem voltar para
    `retry_wait`; resultado ambíguo ou processamento interrompido vira `failed`
    para não duplicar o envio.
25. Somente administradores provisionam ou reconectam instâncias. O
    `provisioning_key` é único por tenant; timeout ou resposta ambígua só muda o
    provisionamento para `active` após confirmação positiva da instância.
26. Administradores acessam todos os canais do próprio tenant. Atendentes
    listam e operam somente canais associados em `TenantUserChannel`; conversa,
    contato, mensagem, atribuição e evento realtime repetem essa autorização.
    Remover um canal do atendente devolve suas conversas abertas naquele canal
    para a fila `new`.

## Migration inicial

`api/alembic/versions/20260721_0001_initial.py` cria as onze tabelas iniciais, enums, chaves estrangeiras, constraints de deduplicação e índices de tenant. `20260722_0002_conversation_reads.py` adiciona os marcadores de leitura por usuário. `20260722_0003_contact_profiles.py` adiciona o cache de perfil WhatsApp aos contatos. `20260722_0004_message_replies_delivery_times.py` adiciona citações, contagem de tentativas e timestamps de envio/entrega/leitura. `20260722_0005_single_conversation_per_contact.py` consolida conversas duplicadas sem apagar mensagens e impede novas duplicatas por contato/canal. `20260722_0006_video_and_sticker_messages.py` adiciona vídeo e figurinha ao enum. `20260724_0007_channel_credential_claims.py` adiciona o fingerprint e impede que uma credencial de provider seja reutilizada por outro canal. `20260726_0008_message_edits.py` adiciona revisões/estado de edição, remove mensagens artificiais geradas por edição/reação e sanitiza material criptográfico legado. `20260726_0009_attachment_integrity.py` adiciona o SHA-256 do conteúdo para validar a idempotência exata dos anexos novos. `20260726_0010_message_sender_name.py` preserva o nome de exibição do atendente em cada mensagem outgoing e preenche o histórico que ainda referencia um usuário. `20260727_0011_sync_runs.py` adiciona as execuções administrativas, seus contadores e a unicidade parcial que impede duas sincronizações ativas no mesmo canal. `20260727_0012_message_delivery_outbox.py` cria a outbox, recupera mensagens outgoing que já estavam `pending` e adiciona limites de tentativas. `20260727_0013_provider_credentials.py` cria o cofre cifrado, registra o estado do provisionamento e adiciona a chave idempotente dos canais gerenciados. `20260727_0014_tenant_user_channels.py` cria as permissões de canal dos atendentes e preserva o acesso existente preenchendo todos os canais atuais do mesmo tenant. Defaults de UUID e estados são aplicados pela camada ORM; integrações que escrevam SQL diretamente devem fornecê-los explicitamente.

A `20260722_0005` é uma migration de dados e consulta as conversas existentes para escolher e
consolidar registros. Por isso, a cadeia completa deve ser validada com `alembic upgrade head`
conectado ao PostgreSQL; a geração offline integral com `alembic upgrade head --sql` não é
suportada a partir dessa revisão.
