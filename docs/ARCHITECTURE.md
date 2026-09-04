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
    repassa o evento ao WebSocket do tenant. Depois de um resultado terminal,
    o worker enfileira imediatamente a próxima mensagem pendente da mesma
    conversa; a varredura periódica permanece como mecanismo de recuperação.

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

## Agente de IA e transbordo humano

O Agente de IA é um módulo opcional pós-MVP, desativado por padrão, cuja
configuração é isolada por `(tenant_id, channel_id)` em
`channel_ai_configs`. Somente administradores podem consultar ou alterar essa
configuração e usar o simulador. A chave do provedor é cifrada no backend e
nunca é devolvida ao frontend.

Quando habilitado, o worker de inbox agenda um turno somente para mensagens
diretas recebidas em canal conectado, em conversa `new`, sem atendente
atribuído e com `is_bot_active=true`. Grupos nunca ativam o bot. Antes de
persistir a resposta, o serviço confirma novamente o tenant, a conversa, o
canal, a atribuição e o estado do bot, para descartar uma resposta caso um
atendente tenha assumido o atendimento durante a chamada ao LLM.

A decisão de responder passa por duas camadas. Primeiro, regras determinísticas
interrompem o turno do LLM quando a mensagem pede explicitamente uma pessoa ou
apresenta sinais objetivos de reclamação (por exemplo, Procon, fraude ou
advogado). Nesses casos, o sistema envia o aviso padrão, registra o motivo e
desativa o bot. Para as demais mensagens, a política de triagem é enviada ao
LLM junto do contexto: ele só deve responder quando tiver escopo e informação
suficiente; fora do escopo, com dúvida relevante ou baixa confiança, deve usar
a ferramenta de transbordo humano. Assim a triagem não depende apenas de uma
resposta textual livre do modelo.

O `bot_name` configurado por canal também é incluído na identidade enviada ao
LLM. Assim, se o cliente escrever “Sofia, preciso de ajuda”, por exemplo, o
agente reconhece que está sendo chamado e responde normalmente. A menção ao
nome é contextual e não obrigatória: o bot continua atendendo as mensagens
elegíveis mesmo quando o cliente não usa o nome.

Após uma resposta válida, a API persiste na mesma transação a mensagem
outgoing como `pending` e sua `MessageDelivery` como `queued`, sempre com
`tenant_id`. Em seguida, envia somente `delivery_id` e `tenant_id` ao
dispatcher; o delivery worker resolve o provider pelo canal persistido e
aplica as mesmas regras de confirmação, idempotência e falha do envio manual.
Assim, a IA não marca mensagens como `sent` diretamente.

O agente dispõe da ferramenta de transbordo humano. Quando acionada, a
conversa registra `bot_handoff_at` e `bot_handoff_reason`, desativa
`is_bot_active` e envia a mensagem de aviso pela mesma outbox. Ativar ou
desativar o bot manualmente usa
`POST /api/v1/conversations/{conversation_id}/toggle-bot`.

As atualizações são publicadas pelos eventos realtime existentes
`message.created` e `conversation.updated`, sempre incluindo `channel_id`
para respeitar sockets restritos a canais. O turno assíncrono abre e fecha sua
própria sessão SQLAlchemy e é aguardado pelo worker que processa o webhook;
assim, ele não é cancelado junto com o `asyncio.run()` do job. Falhas do
provedor não são tratadas como sucesso e interrompem o turno sem criar uma
mensagem falsa como `sent`.

## Fluxo de recebimento

1. O gateway chama `/api/v1/webhooks/whatsapp/{provider}/{channel_id}`.
2. A API valida a credencial do webhook e encontra o canal; o tenant vem do canal, nunca do payload. No Evolution Go 0.7.2, o `instanceToken` do corpo é validado pelo adapter.
3. O adapter normaliza `Message` como mensagem nova ou edição. Reações são
   reconhecidas e ignoradas no MVP, sem gerar bolhas artificiais. O payload
   sanitizado não preserva credenciais, base64 ou material criptográfico.
4. A API valida e grava a mídia no storage antes do aceite. Na mesma transação,
   persiste `ProviderEvent` e `ProviderEventInbox(queued)` com o conteúdo
   normalizado, hash e referência do arquivo. Só então responde `202`; falha de
   storage retorna `503`, permitindo nova entrega pelo gateway.
5. O enqueue imediato usa `fluvius-webhooks`. Se Redis estiver indisponível, a
   inbox continua no PostgreSQL e o dispatcher tenta novamente. Jobs
   interrompidos retornam a `retry_wait`; após oito tentativas ficam `failed` e
   podem ser reiniciados pelo reconciliador administrativo.
6. O webhook worker deduplica pelo ID real da mensagem e adquire um lock por
   tenant, canal e conversa. Webhooks de conversas diferentes continuam em
   paralelo, mas mensagens simultâneas do mesmo atendimento não disputam a
   criação do contato, da conversa ou da mensagem entre workers. Em seguida, o
   worker encontra/cria o contato e usa sua conversa única naquele canal. Se ela
   estava finalizada, é reaberta como `new`, sem perder o histórico e sem manter
   a atribuição anterior.
7. O worker verifica novamente tamanho e SHA-256 da mídia staged, cria o
   `MessageAttachment`, persiste a mensagem e conclui inbox e evento na mesma
   transação. Depois do commit, publica os eventos realtime.

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

Para contatos diretos, `name` é reservado ao nome operacional informado pelo atendente. Dados descobertos no provider permanecem separados e o nome exibido é resolvido de forma centralizada na ordem: nome operacional, verificado, comercial, agenda, `PushName` válido e telefone. Webhooks e sincronizações descartam números, JIDs e placeholders usados como nome.

A agenda operacional usa `GET /api/v1/contacts` para listar contatos diretos
do tenant com paginação e busca por nome ou telefone. `POST /api/v1/contacts`
cria contato manual com telefone normalizado e reaproveita de forma idempotente
um contato direto já existente no mesmo tenant. `PATCH /api/v1/contacts/{id}`
altera somente o nome operacional. Atendentes restritos a canais veem contatos
com conversa em seus canais ou contatos ainda sem conversa; contatos vinculados
apenas a canais sem acesso não ficam disponíveis por listagem, edição ou abertura
de conversa.

Administradores podem iniciar a sincronização de contatos diretamente na agenda.
O botão usa o canal conectado selecionado, reaproveita o fluxo assíncrono de
`POST /api/v1/admin/sync-runs` com `sync_type=contacts`, acompanha uma execução
já ativa e atualiza a listagem quando ela termina.

O início de atendimento ativo usa `POST
/api/v1/contacts/{id}/conversations`, sempre com `channel_id` persistido. A API
valida tenant, acesso ao canal e `channel.status=connected`, cria ou reutiliza a
conversa única `(tenant_id, channel_id, contact_id)` e reabre conversas
`closed` como `new` sem atribuição automática. O envio da primeira mensagem
continua passando pelo composer normal, portanto ainda exige assumir a conversa
antes de sair pelo provider.

Para grupos, a resposta de contato expõe `group_members` como o conjunto de
participantes sincronizados pelo provider. Quando o provider retorna apenas o
telefone do participante, a API enriquece o nome exibido com um contato direto
já conhecido do mesmo tenant e mesmo telefone. Isso melhora o texto inserido
pelo picker de menções sem alterar o dado bruto salvo em `contact.group_members`
e sem aceitar menção de participantes fora do grupo sincronizado.

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

Qualquer usuário autenticado pode alterar o próprio nome de exibição e senha em `PATCH /api/v1/auth/me`. A troca de senha exige a senha atual, persiste somente o novo hash e registra `profile.updated` em auditoria com a lista de campos alterados, sem valores sensíveis. Tema e som de novas mensagens são preferências da interface salvas somente no `localStorage` do navegador; não alteram autorização, membership ou dados de outros usuários.

Desativar uma membership invalida imediatamente o acesso porque toda requisição e WebSocket revalidam a associação ativa. Alterar papel ou canais também encerra os WebSockets desse usuário para que a nova autorização seja carregada na reconexão. O realtime entrega ao atendente somente eventos que carregam um `channel_id` autorizado. Conversas `open` atribuídas ao usuário desativado voltam para `new`; ao remover apenas um canal, somente as conversas abertas desse canal são liberadas. O próprio administrador não pode remover seu papel administrativo nem desativar seu acesso.

O quadro operacional e `/api/v1/users/active` exigem papel `admin`. O endpoint expõe somente ID, nome, papel e canais dos usuários ativos do tenant autenticado, sem e-mail ou dados de acesso. Conversas e quadro oferecem seletor de canal; somente o administrador recebe a opção consolidada “Todos os canais”. As colunas são calculadas no navegador a partir das conversas existentes e uma conversa só pode ser atribuída a um atendente autorizado para seu canal. Drag-and-drop e o seletor dos cards chamam exclusivamente os endpoints tenant-scoped de atribuição ou liberação. Liberar move uma conversa `open` para `new`, remove o responsável e registra `conversation.released` em `audit_logs`.

`GET /api/v1/operations/health` também exige papel `admin`. Ele combina o
registro de workers ativos do RQ com contagens tenant-scoped da outbox, dos
canais e dos webhooks (`provider_events` pendentes, com erro e canais
conectados sem nenhum evento). Uma entrega `pending` há mais de dois minutos é
considerada atrasada; falhas de entrega são contadas numa janela de 24 horas.
Eventos de webhook aguardando reconciliação há mais de 15 minutos elevam o
status a crítico. A resposta também expõe o heartbeat e o último lote do
reconciliador automático de webhooks, sem incluir payloads externos. A resposta
nunca contém jobs ou dados de outros tenants, mesmo que Redis e os workers sejam
compartilhados. O frontend consulta esse retrato a cada 30 segundos enquanto a
aba está visível e mostra um alerta global quando a operação exige atenção.

A API também mantém um loop de reconciliação de webhooks pendentes (mensagens
recebidas cujo processamento foi interrompido, recibos e edições aguardando a
mensagem correspondente), com eleição de líder via Redis, para não depender só
da sincronização administrativa manual. Administradores
podem acionar `POST /api/v1/operations/webhooks/reconcile` para reprocessar, de
forma tenant-scoped e auditada, eventos pendentes do tenant ou de um canal
específico.

Além disso, um reconciliador de histórico roda a cada cinco minutos para canais
Evolution Go conectados. Ele escolhe conversas recentes com mensagem externa
conhecida, respeita cooldown por conversa no Redis e chama `/chat/history-sync`
a partir dessa âncora. Quando o gateway devolve eventos `HistorySync`, a API
normaliza cada mensagem recuperada e a coloca na mesma `ProviderEventInbox` dos
webhooks comuns, preservando deduplicação por `provider_message_id`, staging de
mídia e broadcasts realtime. Administradores podem acionar
`POST /api/v1/operations/history-sync/request`; o endpoint é tenant-scoped,
auditado e apenas solicita o histórico ao provider, pois a entrega das mensagens
recuperadas continua assíncrona pelo webhook.

## Administração da plataforma

`User.is_platform_admin` é uma autorização global distinta do papel `admin` de
uma membership. Somente ela libera `/api/v1/platform`: a área lista empresas,
mostra usuários e canais, cria tenant com seu primeiro administrador e
ativa/suspende a operação. Suspender um tenant invalida imediatamente login,
requisições e WebSockets porque todos revalidam `Tenant.is_active`.

Cada tenant ativo possui o endereço `/login/{slug}`. A tela consulta somente
nome e slug públicos e envia `tenant_slug` junto das credenciais; a API exige
uma membership ativa exatamente nessa empresa antes de emitir a sessão. Na
criação, o frontend exibe link, e-mail e senha inicial uma única vez, mantendo a
senha apenas em memória. Um e-mail existente só pode ser reaproveitado quando
não é administrador da plataforma e não possui nenhuma membership ativa; as
associações antigas permanecem inativas.

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

No ambiente local, arquivos ficam no volume `api_storage`. Na VPS, o mesmo contrato usa `/srv/fluvius/media`, montado em `/app/storage`; o Caddy do host bloqueia acesso público direto a `/storage`. API e frontend ficam disponíveis ao proxy somente em portas de loopback. O navegador recebe `/api/v1/attachments/{id}/content`, e a API valida sessão, tenant e canal antes de entregar o arquivo. O adapter converte o endereço persistido para o base interno de `EVOLUTION_GO_MEDIA_BASE_URL` (`http://api:8000/storage/...` na VPS) ao enviar pela Evolution Go, mantendo essa leitura restrita à rede Docker — o base do webhook permanece público porque o registro de webhook do gateway passa pelo Caddy. GIF é entregue como `document` porque o gateway só aceita JPEG/PNG/WebP como `image`. Ao receber, a imagem customizada do gateway também desembrulha `DocumentWithCaptionMessage`, baixa os bytes do WhatsApp e os inclui no webhook para que a API copie o documento ao storage antes de responder. Imagens JPEG/PNG/GIF, WebP, áudios AAC/FLAC/M4A/MP3/OGG/WAV/WebM, vídeos MP4/MOV/WebM e documentos PDF/Office/HTML/JSON/XML/texto/CSV/ZIP são limitados a 25 MB nesta etapa. Documentos são entregues com `Content-Disposition: attachment` e `nosniff`; HTML nunca é renderizado dentro da aplicação. O compositor aceita até dez arquivos por lote, cria uma mensagem idempotente para cada item e os envia sequencialmente na ordem escolhida; legenda, menções e referências ficam no primeiro arquivo compatível, e resposta/citação fica no primeiro item. Ao escolher a categoria figurinha, o navegador converte PNG/JPG para WebP 512×512 com fundo transparente; WebP recebido ou selecionado é preservado. A API valida o WebP e o persiste como `sticker`, sem legenda. A leitura do upload também é limitada a 25 MB + 1 byte, evitando aceitar corpos arbitrariamente grandes.

O compositor também grava áudio pelo `MediaRecorder`, escolhendo WebM/Opus ou
MP4 conforme o navegador, com pausa, cancelamento, prévia e limites de dez
minutos e 25 MB. A gravação final entra na mesma validação e outbox dos uploads
de áudio; nenhum stream de microfone sai diretamente do navegador para o
provider.

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

Todos os eventos produzidos pela API, pelos webhooks e pelos workers atravessam
o canal Redis Pub/Sub `fluvius:realtime`. Cada processo uvicorn mantém seu
próprio listener e faz somente o fan-out local para os WebSockets conectados
naquele processo. Invalidações de usuário e tenant usam o mesmo canal, garantindo
que alteração de acesso encerre conexões em todos os workers. Se a publicação no
Redis falhar, o processo emissor ainda tenta a entrega local, mas registra a
degradação sem tratar o fan-out como concluído. Presença, replay e cursor
continuam fora desta etapa.

O cliente trata o tipo e a conversa informados em cada evento, agrupando eventos
próximos em uma única atualização para não multiplicar leituras durante rajadas.
Mensagens da conversa selecionada são conciliadas por ID, evitando duplicação
entre a resposta HTTP e o WebSocket. O navegador envia `ping` a cada 20 segundos
e exige `pong` em até oito segundos; conexão sem resposta é encerrada e refeita
com backoff. Ao reconectar, voltar para a aba ou recuperar a rede, a lista e a
conversa selecionada são sincronizadas novamente, cobrindo eventos ocorridos
durante a interrupção. A contagem de não lidas só é zerada quando a aba está
visível.

## Fila

Redis e duas filas RQ sobem no Compose. `fluvius-delivery` tem um
`delivery-worker` exclusivo para texto e mídia, executado por um pool de dois
processos por padrão (`DELIVERY_WORKER_PROCESSES`); `fluvius-maintenance` mantém
sincronizações administrativas fora do caminho crítico. Os jobs recebem IDs e
reconsultam dados com `tenant_id`, em vez de serializar objetos ORM. A outbox no
PostgreSQL é a fonte da verdade; Redis apenas transporta a execução. Cada job
carrega todos os modelos antes de abrir a sessão, pois os processos RQ não
passam pelo bootstrap da API e precisam resolver as chaves estrangeiras no
próprio metadata SQLAlchemy. O dispatcher consulta o estado do job no RQ para
recuperar rapidamente entregas que falharam antes do efeito externo e só
enfileira a mensagem pendente mais antiga de cada conversa; o worker repete a
mesma validação antes de chamar o provider. Se uma exceção interna escapar do
processamento, o worker tenta persistir a falha segura e relança a exceção para
que o próprio RQ registre o job como falho. Processos diferentes podem enviar
conversas distintas em paralelo, enquanto a verificação de predecessora mantém
uma única entrega ativa por conversa e preserva sua ordem.

## Storage

`StorageProvider` define a fronteira. `LocalStorageProvider` grava em volume local e publica arquivos via API, suficiente para desenvolvimento. Produção deve implementar S3/MinIO, URLs assinadas, validação de MIME, antivírus e política de retenção. O gateway precisa conseguir acessar a URL entregue pela API.

## Limites atuais

- Um processo da API para realtime consistente.
- Retry automático conservador apenas para falhas comprovadamente transitórias;
  respostas ambíguas exigem reenvio manual.
- Sem criptografia de `provider_config`; apenas configurações não secretas devem ser armazenadas ali.
- Storage local e upload de até 25 MB.
- Contrato webhook do Evolution Go ainda precisa de fixtures reais e testes de compatibilidade por versão.
