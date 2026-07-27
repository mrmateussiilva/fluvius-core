# Arquitetura

## Visão geral

O Fluvius Core é um monólito modular simples nesta fase. A API FastAPI concentra autenticação, multi-tenancy, regras de atendimento e adaptação do gateway. O Vue é um cliente da API e não conhece detalhes do provider.

```text
Vue 3 ──HTTP/WS──> FastAPI ──SQLAlchemy──> PostgreSQL
                       │
                       ├──Redis/RQ──> worker
                       ├──StorageProvider──> volume local
                       └──WhatsAppProvider──> Evolution Go
                                             Meta Cloud (futuro)
                                             BSP (futuro)
```

Os módulos em `api/app` são separados pelo domínio de negócio. Não há repository/service layer genérica: routers consultam os modelos diretamente enquanto a complexidade ainda é baixa.

## Fluxo de envio

1. O frontend envia texto ou anexo à API com a sessão em cookie `HttpOnly`.
2. A API valida o JWT do cookie, extrai `user_id` e `tenant_id` e revalida o membership no banco. O header Bearer permanece compatível para integrações controladas, mas o navegador não persiste o token em `localStorage`.
3. A conversa, o contato e o canal são consultados com filtro de tenant.
4. A API exige que a conversa esteja `open` e atribuída ao usuário autenticado. Atribuir usa bloqueio de linha no PostgreSQL: atendentes não sobrescrevem uma posse ativa, enquanto administradores podem assumir ou transferir para outro usuário ativo do mesmo tenant. Toda alteração efetiva de responsável gera `conversation.assigned` em `audit_logs`.
5. Se `channel.status != connected`, a API retorna `409` com: “WhatsApp desconectado. Reconecte o canal antes de enviar mensagens.”
6. Para texto, o frontend gera `client_message_id`, mostra imediatamente a bolha `pending` e a API usa esse UUID como ID local e chave idempotente. Repetir o mesmo ID e conteúdo devolve a mensagem existente sem chamar novamente o provider.
7. A API persiste `Message(pending)` e `MessageDelivery(queued)` na mesma
   transação. A resposta HTTP `202` não depende da latência do gateway.
8. A API emite `message.created`; o dispatcher encontra a outbox persistida e
   envia somente `delivery_id` e `tenant_id` à fila `fluvius-delivery`.
9. O delivery worker bloqueia a entrega, reconsulta mensagem, conversa, canal e
   contato com filtro de tenant e preserva a ordem das mensagens da conversa.
10. O worker registra a tentativa antes do efeito externo, resolve o adapter
    correspondente a `channel.provider` e chama o gateway com o UUID da mensagem
    como chave idempotente.
11. Apenas uma resposta positiva com ID do provider muda a mensagem para
    `sent`. Falha confirmada ou resposta ambígua muda para `failed`.
12. O worker persiste o resultado e publica `message.updated` pelo Redis; a API
    repassa o evento ao WebSocket do tenant.

Depois do `sent`, webhooks `Receipt` podem avançar a mensagem para `delivered` e `read`. A atualização é monotônica, limitada a mensagens outgoing do mesmo tenant/canal e emite `message.updated`. Recibos que chegam antes do ID de envio ficam pendentes em `provider_events` para reconciliação após a confirmação do gateway.

Uma resposta valida a mensagem citada no mesmo tenant/conversa, persiste a referência local e envia apenas os identificadores externos necessários pelo adapter. Webhooks recebidos extraem a referência de `ContextInfo.StanzaID`. O reenvio manual aceita somente outgoing em `failed`, reinicia a outbox e reutiliza o UUID local; `attempt_count` avança somente quando o worker realmente inicia outra chamada.

Falhas claramente anteriores à aceitação pelo provider — conexão recusada,
timeout de conexão, falta de conexão no pool ou HTTP 429 — usam backoff de 5,
30 e 120 segundos, até quatro tentativas. Timeout de resposta, erro de protocolo
ou worker interrompido durante a chamada são ambíguos e nunca geram retry
automático: a mensagem vira `failed` para evitar envio duplicado.

Carregar ou receber mensagens por realtime não marca a conversa como lida. O frontend emite a leitura somente quando a aba está visível, o histórico terminou de carregar e o operador alcançou o final da conversa. A requisição informa a última mensagem incoming realmente visível; a API valida tenant e conversa e avança o marcador exatamente até o `created_at` dela. Fora do final, novas mensagens preservam a posição atual e aparecem em um indicador explícito.

Rascunhos de texto ficam somente no `localStorage`, sob chave composta por usuário e conversa. Eles não são enviados à API antes do envio, são removidos quando o composer fica vazio e não incluem arquivos selecionados. Anexos recebem um UUID no navegador, aparecem imediatamente como `pending` e reutilizam esse identificador no multipart e no provider. Repetir o mesmo UUID e o mesmo SHA-256 devolve a mensagem existente sem duplicar o envio; reutilizá-lo com outro conteúdo retorna conflito.

Se Redis estiver indisponível depois do commit, a entrega permanece `queued` no
PostgreSQL e o dispatcher tenta novamente. Um job RQ duplicado é inofensivo
porque somente uma transição bloqueada da outbox pode chegar ao provider.

## Fluxo de recebimento

1. O gateway chama `/api/v1/webhooks/whatsapp/{provider}/{channel_id}`.
2. A API valida a credencial do webhook e encontra o canal; o tenant vem do canal, nunca do payload. No Evolution Go 0.7.2, o `instanceToken` do corpo é validado pelo adapter.
3. O payload sanitizado entra em `provider_events`, permitindo auditoria, deduplicação e reprocessamento futuro. Credenciais são removidas antes da persistência.
4. O adapter normaliza o evento como mensagem nova ou edição. Reações são
   reconhecidas e ignoradas no MVP, sem gerar bolhas artificiais.
5. A API deduplica pelo ID da mensagem, encontra/cria o contato e usa sua conversa única naquele canal. Se ela estava finalizada, é reaberta como `new`, sem perder o histórico e sem manter a atribuição anterior.
6. Para mídia, o adapter normaliza base64, MIME type e nome; a API valida limite, assinatura binária e coerência entre conteúdo/MIME/extensão, grava o arquivo no storage e cria `MessageAttachment` com SHA-256 no mesmo tenant.
7. A mensagem incoming é persistida e os eventos realtime são emitidos.

Uma edição localiza a mensagem original pelo ID externo dentro do mesmo tenant
e canal, grava uma `MessageRevision`, atualiza a mesma linha e emite
`message.updated`. Se a edição chegar antes da mensagem, o `ProviderEvent` fica
pendente e é reconciliado depois. Na Evolution Go 0.7.2, algumas edições chegam
como `secretEncryptedMessage` sem o novo texto; nesse caso a mensagem é marcada
como editada e a UI informa que o conteúdo atualizado não foi disponibilizado.
Material criptográfico do envelope não é persistido.

## Fluxo de status do canal

O status pode ser consultado pela API ou atualizado por webhook. Em ambos os casos, o valor externo é normalizado para `disconnected`, `connecting`, `connected`, `requires_qr` ou `failed`. A UI usa somente esse estado interno. Eventos de mudança emitem `channel.status.updated`.

Somente administradores criam ou reconectam canais. `POST /api/v1/channels` reserva o canal com uma chave idempotente, gera sua credencial, cria a instância por meio do cliente administrativo em `api/app/providers` e persiste somente o segredo cifrado. O assistente chama `POST /api/v1/channels/{id}/connect`, recebe somente QR/código de pareamento e consulta `GET /status` até a sessão ficar conectada. A solicitação inicial reaplica o webhook; as consultas periódicas de status são somente leitura. O frontend nunca recebe URL ou token da Evolution.

O cadastro gerenciado é idempotente por `provisioning_key` dentro do tenant. Repetir uma solicitação recupera o mesmo canal e a mesma instância; uma resposta ambígua do gateway só vira sucesso após consulta positiva pela credencial da instância. Canais legados ainda resolvem referências de `EVOLUTION_GO_INSTANCE_TOKENS`, e a constraint global continua bloqueando reutilização de credenciais entre canais.

## Perfil do contato

O painel operacional lê o contato persistido em `GET /api/v1/contacts/{id}`. A atualização explícita usa `POST /api/v1/contacts/{id}/refresh`, valida tenant, vínculo entre contato e canal e status conectado antes de chamar `WhatsAppProvider.get_contact_profile`. O Evolution Go é consultado apenas pelo adapter e os resultados disponíveis são armazenados como cache; estatísticas de primeira/última interação e atendimentos são calculadas a partir dos dados do Fluvius.

## Sincronização administrativa

A tela **Sincronização**, disponível apenas para administradores, cria execuções em
`/api/v1/admin/sync-runs`. A API valida o canal dentro do tenant, persiste a
execução como `queued`, registra auditoria e envia ao RQ somente os IDs da
execução e do tenant. O worker reconsulta todos os dados com filtro explícito de
`tenant_id`, mantém contadores de progresso e conclui como `completed`,
`partial` ou `failed`. Apenas uma execução `queued` ou `running` pode existir por
canal.

A sincronização de contatos atualiza, no máximo, os 50 contatos conhecidos mais
recentes por meio do provider do canal e exige conexão ativa. A opção de
mensagens examina até 500 eventos dos últimos 1 a 30 dias que já estão
persistidos como recibos ou edições pendentes e tenta reconciliá-los com as
mensagens locais. Ela não consulta nem importa todo o histórico do WhatsApp,
porque esse contrato não existe no adapter atual. O frontend consulta
periodicamente o estado persistido da execução; o worker não depende do
gerenciador WebSocket em memória da API.

## Usuários da empresa

`TenantUser` é a autorização entre uma identidade global e uma empresa. A gestão usa `/api/v1/users`, exige papel `admin` e filtra explicitamente cada listagem ou alteração pelo `tenant_id` autenticado. `TenantUserChannel` limita cada atendente aos canais escolhidos pelo administrador; administradores continuam irrestritos dentro da própria empresa. A mesma regra é aplicada à listagem e operação de canais, conversas, mensagens e contatos. Não existe acesso direto do usuário ao gateway. E-mails novos são únicos, senhas são persistidas apenas como hash e nenhuma resposta expõe credenciais.

Desativar uma membership invalida imediatamente o acesso porque toda requisição e WebSocket revalidam a associação ativa. Alterar papel ou canais também encerra os WebSockets desse usuário para que a nova autorização seja carregada na reconexão. O realtime entrega ao atendente somente eventos que carregam um `channel_id` autorizado. Conversas `open` atribuídas ao usuário desativado voltam para `new`; ao remover apenas um canal, somente as conversas abertas desse canal são liberadas. O próprio administrador não pode remover seu papel administrativo nem desativar seu acesso.

O quadro operacional e `/api/v1/users/active` exigem papel `admin`. O endpoint expõe somente ID, nome, papel e canais dos usuários ativos do tenant autenticado, sem e-mail ou dados de acesso. Conversas e quadro oferecem seletor de canal; somente o administrador recebe a opção consolidada “Todos os canais”. As colunas são calculadas no navegador a partir das conversas existentes e uma conversa só pode ser atribuída a um atendente autorizado para seu canal. Drag-and-drop e o seletor dos cards chamam exclusivamente os endpoints tenant-scoped de atribuição ou liberação. Liberar move uma conversa `open` para `new`, remove o responsável e registra `conversation.released` em `audit_logs`.

## Administração da plataforma

`User.is_platform_admin` é uma autorização global distinta do papel `admin` de
uma membership. Somente ela libera `/api/v1/platform`: a área lista empresas,
mostra usuários e canais, cria tenant com seu primeiro administrador e
ativa/suspende a operação. Suspender um tenant invalida imediatamente login,
requisições e WebSockets porque todos revalidam `Tenant.is_active`.

O acesso de suporte não ignora as regras operacionais. A API cria ou reativa uma
`TenantUser` administrativa para o operador da plataforma, troca o cookie para
o tenant escolhido e grava `platform.support_access` no `AuditLog` dessa
empresa. A conta global da plataforma não pode ter nome, senha, papel ou estado
alterados pela gestão de usuários de uma empresa. Usuários com memberships
ativas em mais de um tenant podem trocar de empresa pelo seletor; cada novo
cookie continua representando exatamente um tenant.

Mensagens criadas pela API guardam uma cópia de `User.name` em
`Message.sender_name`. O corpo interno permanece sem decoração, enquanto o
conteúdo entregue ao WhatsApp recebe `*Nome do atendente:*\n` antes do texto ou
da legenda existente. A cópia torna retries determinísticos e preserva a
autoria histórica mesmo após renomear ou desativar o usuário. Figurinhas e
mídias sem suporte a legenda não geram uma segunda mensagem apenas para
assinatura.

## Storage de mídia

No ambiente local, arquivos ficam no volume `api_storage`. Na VPS, o mesmo contrato usa `/srv/fluvius/media`, montado em `/app/storage`; o Caddy bloqueia acesso público direto a `/storage`. O navegador recebe `/api/v1/attachments/{id}/content`, e a API valida sessão, tenant e canal antes de entregar o arquivo. O adapter converte o endereço persistido para `http://api:8000/storage/...` ao enviar pela Evolution Go, mantendo essa leitura restrita à rede Docker. Imagens JPEG/PNG/GIF, WebP, áudios AAC/FLAC/M4A/MP3/OGG/WAV/WebM, vídeos MP4/MOV/WebM e documentos PDF/Office/texto/CSV/ZIP são limitados a 25 MB nesta etapa. Ao escolher a categoria figurinha, o navegador converte PNG/JPG para WebP 512×512 com fundo transparente; WebP recebido ou selecionado é preservado. A API valida o WebP e o persiste como `sticker`, sem legenda. A leitura do upload também é limitada a 25 MB + 1 byte, evitando aceitar corpos arbitrariamente grandes.

## Realtime

`WS /ws` recebe o cookie de sessão no navegador; o subprotocolo
`fluvius-auth` permanece compatível para clientes controlados. Em produção, o
endpoint também valida `Origin`, JWT, membership e canais antes de registrar a
conexão na sala em memória do tenant. Eventos planejados:

- `conversation.created`
- `conversation.updated`
- `message.created`
- `message.updated`
- `contact.updated`
- `channel.status.updated`

Eventos produzidos pelo delivery worker atravessam Redis Pub/Sub até a API. Os
demais eventos ainda usam o gerenciador em memória; portanto, duas ou mais
réplicas da API exigem migrar toda a emissão para o broker. Presença, replay e
cursor continuam fora desta etapa.

O cliente trata o tipo e a conversa informados em cada evento. Mensagens da conversa selecionada
são conciliadas por ID, evitando duplicação entre a resposta HTTP e o WebSocket. A contagem de não
lidas só é zerada quando a aba está visível; ao voltar para a tela, a conversa selecionada é
sincronizada novamente.

## Fila

Redis e duas filas RQ sobem no Compose. `fluvius-delivery` tem um
`delivery-worker` exclusivo para texto e mídia; `fluvius-maintenance` mantém
sincronizações administrativas fora do caminho crítico. Os jobs recebem IDs e
reconsultam dados com `tenant_id`, em vez de serializar objetos ORM. A outbox no
PostgreSQL é a fonte da verdade; Redis apenas transporta a execução.

## Storage

`StorageProvider` define a fronteira. `LocalStorageProvider` grava em volume local e publica arquivos via API, suficiente para desenvolvimento. Produção deve implementar S3/MinIO, URLs assinadas, validação de MIME, antivírus e política de retenção. O gateway precisa conseguir acessar a URL entregue pela API.

## Limites atuais

- Um processo da API para realtime consistente.
- Retry automático conservador apenas para falhas comprovadamente transitórias;
  respostas ambíguas exigem reenvio manual.
- Sem criptografia de `provider_config`; apenas configurações não secretas devem ser armazenadas ali.
- Storage local e upload de até 25 MB.
- Contrato webhook do Evolution Go ainda precisa de fixtures reais e testes de compatibilidade por versão.
