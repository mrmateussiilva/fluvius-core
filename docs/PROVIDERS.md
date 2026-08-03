# Providers de WhatsApp

## Contrato

`WhatsAppProvider` isola todo comportamento específico de gateway em `api/app/providers`. A UI e os demais domínios não importam SDKs nem montam URLs do gateway.

Métodos obrigatórios:

- `send_text(channel, to, text, reply_to_*, idempotency_key) -> SendResult`
- `send_media(channel, to, file_url, caption=None) -> SendResult`
- `send_contact(channel, to, contact) -> SendResult`
- `get_status(channel) -> ChannelStatusResult`
- `get_qr_code(channel) -> QRCodeResult`
- `handle_webhook(payload) -> IncomingMessageResult`
- `handle_message_status(payload) -> MessageStatusUpdateResult | None`
- `get_contact_profile(channel, phone_number) -> ContactProfileResult`

Os DTOs normalizam confirmação de envio, status do canal, QR/pairing code e mensagem recebida. A factory seleciona o adapter a partir de `WhatsAppChannel.provider`.

## EvolutionGoProvider

É a implementação inicial. Usa `httpx`, `EVOLUTION_GO_BASE_URL` e uma credencial por instância. Canais novos são provisionados pela API com `POST /instance/create`: o Fluvius gera o identificador e o token, cifra o token em `provider_credentials` e usa `EVOLUTION_GO_GLOBAL_API_KEY` somente no cliente administrativo. `PROVIDER_CREDENTIALS_KEY` protege esse cofre; quando ausente, instalações existentes derivam a chave de `SECRET_KEY`. O segredo resolvido é enviado no header `apikey` e nunca aparece em logs ou respostas.

A mesma credencial não pode ser associada a canais diferentes. O banco guarda o ciphertext autenticado e o fingerprint SHA-256, aplicando unicidade por provider. Toda leitura de `provider_credentials` exige `tenant_id` e `channel_id`. `ChannelResponse` filtra `provider_config` e devolve somente `instance_name`.

`EVOLUTION_GO_INSTANCE_TOKENS` e `EVOLUTION_GO_API_KEY` permanecem como fallback compatível para canais antigos, sem obrigar uma migração imediata. Canais gerenciados não exigem novas variáveis de ambiente nem acesso ao Manager. A chave global continua sendo um segredo único da infraestrutura e deve ser entregue somente à API.

O cadastro recebe um `provisioning_key` gerado pelo navegador e é idempotente dentro do tenant. A instância usa o UUID persistido do canal; em timeout, conflito ou resposta ambígua, a API confirma sua existência com a credencial da instância antes de marcar o provisionamento como `active`. Sem confirmação positiva, o canal fica `failed`/`uncertain`, preservado para nova tentativa, e nunca é apagado automaticamente.

A imagem local padrão é `fluvius/evolution-go:0.7.2-edit-media-fix.2`, compilada pelo Compose a partir do commit oficial 0.7.2 fixado em `EVOLUTION_GO_SOURCE_REF`. Os patches mantidos junto ao provider chamam `DecryptSecretEncryptedMessage` para edições `MESSAGE_EDIT` e fazem o download de documentos recebidos dentro de `DocumentWithCaptionMessage`, formato que o gateway original encaminhava sem `base64`. Isso disponibiliza o texto editado, o ID original e os bytes de documentos envelopados à API; se uma edição não puder ser decifrada ou uma mídia não puder ser baixada, o evento continua registrado com erro seguro. O serviço usa os bancos locais `evogo_auth` e `evogo_users`. `EVOLUTION_GO_GLOBAL_API_KEY` é a chave administrativa do container; `EVOLUTION_GO_API_KEY` é o token da instância usado pelo adapter. A ativação/licença do gateway é externa ao Fluvius e exige um registro inicial. Na VPS, o Manager fica vinculado somente ao loopback em `127.0.0.1:18081` e o Caddy o publica com HTTPS em `evolution.finderbit.com.br`; depois da ativação persistida no `evogo_auth`, ele não participa da criação cotidiana de canais.

## Respostas confirmadas na versão 0.7.2

O status chega no envelope `{"message": "success", "data": {...}}`. Dentro de `data`, os campos `Connected` e `LoggedIn` indicam, respectivamente, conexão do socket e sessão autenticada. O adapter aceita também as variantes em camelCase. O QR usa o mesmo envelope e expõe `qrcode` e `code`.

Em uma sessão já autenticada, `GET /instance/qr` responde HTTP 400 com `{"error": "session already logged in"}`. Essa resposta específica confirma que não há QR a exibir e preserva o canal como `connected`; qualquer outro HTTP 400 continua sendo tratado como falha.

O token em `EVOLUTION_GO_API_KEY` deve ser o **Token da Instância** mostrado no Manager. Ele não é o nome `Pessoal` e também não é a chave administrativa `EVOLUTION_GO_GLOBAL_API_KEY`.

### Webhook Evolution Go 0.7.2

A instância é conectada com uma URL por canal e as assinaturas `MESSAGE`, `CONNECTION`, `QRCODE` e `READ_RECEIPT`. Em Docker local, a URL precisa usar o DNS interno da API, nunca `localhost`:

```text
http://api:8000/api/v1/webhooks/whatsapp/evolution_go/{channel_id}
```

Ao iniciar ou renovar o QR por `POST /api/v1/channels/{id}/connect`, o adapter reaplica essa configuração por meio de `/instance/connect`. A consulta periódica de status não reconfigura o webhook. Assim, uma instância apagada e recriada com o mesmo nome recupera webhook e assinaturas quando o operador abre novamente o assistente de conexão. A base interna é configurada por `EVOLUTION_GO_WEBHOOK_BASE_URL`; em Docker local, o padrão é `http://api:8000`.

### DNS no ambiente local

O Evolution Go precisa resolver e acessar `web.whatsapp.com` para obter a versão do cliente e abrir o WebSocket. O Compose define `DOCKER_DNS_PRIMARY` e `DOCKER_DNS_SECONDARY` para API, worker e gateway, usando `1.1.1.1` e `8.8.8.8` como padrões locais. Isso evita que containers antigos continuem encaminhando consultas para o DNS de uma rede Wi-Fi que já foi trocada.

Se a rede bloquear resolvedores públicos, configure esses valores no `.env` com os servidores permitidos pela infraestrutura. Erros contendo `lookup web.whatsapp.com on 127.0.0.11:53` indicam falha de DNS do Docker, não credencial ou número inválido.

Ao apagar manualmente uma instância legada, atualize seu token em `EVOLUTION_GO_INSTANCE_TOKENS` — ou em `EVOLUTION_GO_API_KEY` no modo de instância única — e reinicie a API. Instâncias gerenciadas devem ser recuperadas pelo fluxo administrativo do Fluvius.

Essa versão não envia header customizado no webhook. Ela inclui `instanceToken` no corpo; o adapter compara esse valor com `EVOLUTION_GO_API_KEY` em tempo constante. O token é removido do payload antes de gravar `provider_events`. O header `X-Webhook-Secret` continua aceito como alternativa para providers capazes de configurá-lo.

Eventos `Message` usam o envelope nativo do Go com `data.Info` e `data.Message`. Mensagens com `Info.IsFromMe=true` originadas no celular são persistidas como `outgoing/sent`; o contato é resolvido por `Info.RecipientAlt`, evitando armazenar LIDs como telefone. Eventos técnicos `SendMessage` são ignorados porque a chamada síncrona da API já persiste esse envio.

Grupos (`Info.IsGroup=true` ou `Chat` com sufixo `@g.us`) entram na mesma inbox operacional. A thread é o chat do grupo (`Chat`), não o participante; o autor da mensagem fica em `participant_phone`/`participant_name` (via `Sender`/`SenderAlt` + `PushName`). Quando `Sender` vier como `@lid`, o adapter só preenche `participant_phone` se existir `SenderAlt` com JID `@s.whatsapp.net`; sem esse alternativo, preserva o nome do participante e deixa o telefone vazio para não persistir LID como número real. Quando o payload informa o assunto/nome do grupo, o adapter preenche `chat_name` para evitar contatos provisórios como `Grupo 123456`. O envio usa o endereço `…@g.us` do grupo; respostas citadas exigem o JID do participante original em `quoted.participant`.

Menções em grupos são enviadas pelo contrato do Evolution Go em `/send/text` e `/send/media` com `mentionedJid`. Membros sincronizados com telefone real usam JIDs `@s.whatsapp.net`; grupos em modo LID podem expor participantes somente como `@lid`, então `contact.group_members` preserva também `provider_jid`. O frontend envia telefones e/ou JIDs dos membros sincronizados, a API valida ambos contra o grupo e o adapter normaliza o payload final. Não aceitar menção real para contato fora do grupo sincronizado. Quando a lista do provider vem sem nome e existe um contato direto do mesmo tenant com o mesmo telefone, `GET /contacts/{id}` usa o nome conhecido desse contato apenas na resposta para o picker; o payload final ao Evolution continua sendo baseado em JIDs.

Quando o atendente usa `@` para apontar outro contato do tenant que não é participante sincronizado do grupo, isso é uma referência interna do Fluvius, não uma menção do WhatsApp. O frontend envia `referenced_contact_ids`, a API valida tenant e permissões de canal e persiste snapshots em `messages.referenced_contacts`. O provider recebe somente `mentioned_phones`/`mentioned_jids`; referências internas nunca viram `mentionedJid`.

Edições observadas na 0.7.2 usam `Info.Edit=1` e apontam para a mensagem
original em `Message.secretEncryptedMessage.targetMessageKey.ID`. O adapter
também aceita a variante descriptografada
`protocolMessage.editedMessage`. Quando o gateway não fornece o novo texto, o
Fluvius marca a mensagem original como editada e indisponível, sem criar outra
bolha. `Info.Edit=7`/`Type=reaction` representa alteração de reação e é ignorado
no MVP. `encIV`, `encPayload` e metadados de chaves de dispositivos são
removidos antes de `provider_events`.

Respostas a botões legados podem gerar os eventos `ButtonClick` e `Message` para a mesma interação. O adapter ignora `ButtonClick` com sucesso HTTP e usa apenas `Message` como fonte canônica, evitando retries e duplicidade. Botões interativos continuam fora do escopo do MVP.

O envio de texto retorna `{"message": "success", "data": {...}}`; a confirmação positiva é o identificador em `data.Info.ID`. Sem esse campo, o Fluvius mantém a regra conservadora e marca o envio como `failed`. Na 0.7.2, respostas usam `quoted.messageId` e `quoted.participant`; o delivery worker também envia o UUID local em `id`, mantendo a mesma chave em todas as tentativas.

Mídia usa `/send/media` com `type` igual a `image`, `audio`, `video` ou `document`. Figurinhas são normalizadas como WebP 512×512 pelo composer, persistidas com `message_type=sticker`, enviadas sem legenda por `/send/sticker` no campo `sticker` e renderizadas sem o balão de mídia comum. WebP recebido do WhatsApp segue o mesmo tipo nativo e pode ser animado. A URL armazenada para o navegador é convertida para a URL interna da API antes da chamada ao gateway. Respostas citadas também são encaminhadas nos dois endpoints. O UUID criado pelo navegador acompanha o multipart como `client_message_id`, nasce como ID local `pending` e é reutilizado como chave idempotente no provider; o SHA-256 do conteúdo impede que o mesmo UUID seja aceito para outro arquivo.

Cartões de contato usam `/send/contact` na versão fixada do Evolution Go, com
`fullName`, `phone`, organização opcional e o UUID da mensagem como `id`. Cada
cartão outgoing é uma mensagem independente porque o provider não confirma
envio múltiplo em uma única chamada. Webhooks `ContactMessage` e
`ContactsArrayMessage` são normalizados para snapshots em
`message_contact_shares`; recebê-los nunca cadastra automaticamente um contato
na agenda do tenant.

Com `WEBHOOK_FILES=true`, mensagens de mídia chegam com o arquivo em `data.Message.base64` e metadados no objeto `imageMessage`, `audioMessage`, `videoMessage`, `documentMessage` ou `stickerMessage`. O adapter normaliza esses dados, a API valida a assinatura do arquivo, salva o conteúdo e seu SHA-256 em `MessageAttachment` e remove o base64 da cópia guardada em `provider_events`.

Recibos chegam como evento `Receipt`, com o estado em `state`, os IDs em `data.MessageIDs` e o instante em `data.Timestamp`. `Delivered` e `Read` avançam mensagens outgoing do mesmo tenant e canal, preenchem `delivered_at`/`read_at` e nunca regridem. `ReadSelf` é ignorado porque representa leitura local de uma mensagem recebida, não leitura pelo cliente. Se o recibo chegar antes da confirmação assíncrona do envio, ele permanece não processado em `provider_events` e é reconciliado assim que o worker persistir o ID do provider.

O adapter classifica como retryable somente falhas seguras antes de uma
confirmação: conexão recusada, timeout de conexão, timeout do pool e HTTP 429.
Timeout de resposta, falha de escrita e erro de protocolo têm resultado
ambíguo e bloqueiam retry automático para evitar uma segunda mensagem no
WhatsApp. Confirmar em sessão real que a Evolution deduplica o campo `id`
continua sendo requisito antes de ampliar essa política.

Timeouts de envio usam 12s (connect 5s); consultas de perfil/grupo usam 6s
(connect 3s). Chamadas de perfil passam por um circuit breaker em memória por
`base_url`: após falhas consecutivas o adapter deixa de consultar o gateway por
alguns segundos e devolve perfil parcial, evitando prender workers HTTP.
Recibos e edições que chegam antes da mensagem original ficam em
`provider_events` com erros canônicos e são reprocessados automaticamente pelo
loop de reconciliação da API e pela sincronização administrativa.

O perfil de contato combina, em paralelo, `/user/check`, `/user/info`, `/user/avatar` e `/user/contacts`. O adapter preserva separadamente `FullName`/`FirstName` da agenda, `PushName`, nome comercial/verificado, confirmação do número, recado e URL da foto. Um nome igual ao telefone, um JID ou um placeholder não é aceito como nome exibível. O nome operacional definido no Fluvius sempre tem prioridade e nunca é sobrescrito pelo webhook ou pela sincronização. Grupos usam `/group/info` e `/user/avatar`, normalizando assunto, descrição, foto, contagem de membros e lista parcial de participantes quando o provider disponibiliza esses campos. Cada fonte tem timeout independente e falha parcial não elimina os dados obtidos pelas demais; URLs de avatar fora de HTTP(S) são descartadas. O frontend acessa apenas `/api/v1/contacts/{id}` e solicita atualização pela API.

O adapter atual não possui um endpoint confirmado para listar ou importar o
histórico completo de mensagens. Por isso, a sincronização administrativa de
mensagens não chama uma rota presumida do gateway: ela reprocessa somente
edições e recibos recentes que o webhook já persistiu como pendentes em
`provider_events`. A sincronização de contatos atualiza contatos e grupos já
associados às conversas do canal. Para Evolution Go, ela também pode consultar
`/group/myall` ou `/group/list` para manter um cache auxiliar de grupos, mas
isso não cria conversas nem atendimento sem mensagem recebida.

## TODO de compatibilidade Evolution Go

A documentação pública e o Swagger da linha Evolution Go estão evoluindo. Antes do primeiro teste integrado/produção, confirmar contra o Swagger da imagem efetivamente fixada:

- compatibilidade das rotas ao trocar a imagem (0.7.2 usa `/send/text` e `/send/media`);
- validar rotação da chave mestra e exportação segura do cofre antes de produção;
- schema exato de confirmação de `SendMedia`;
- validade/cache das URLs de avatar e latência de `/user/info` em diferentes contas;
- eventos de falha de entrega e os códigos de erro associados (os recibos `Delivered`/`Read` estão confirmados);
- assinatura/autenticação nativa de webhook e estratégia de rotação;
- política de retries e idempotência aceita pelo gateway;
- exigência e ciclo de ativação da licença na versão implantada.

As fixtures sanitizadas de status conectado, QR solicitado durante sessão
autenticada, edição criptografada e remoção de reação ficam em
`api/tests/fixtures/evolution_go/0.7.2`. Envio de texto/mídia e demais itens
acima ainda dependem de captura real antes da liberação para produção. Falha de
HTTP ou resposta de envio sem ID nunca é tratada como envio bem-sucedido.

## MetaCloudProvider

Placeholder que implementa a interface e lança `NotImplementedError`. No futuro precisará tratar tokens por WABA/número, templates, mídia, assinatura de webhook e status oficiais. O fluxo de QR não se aplica da mesma forma.

## BspProvider

Placeholder até a escolha do BSP. A interface interna permanece a mesma; detalhes de autenticação, template, mídia e webhook ficam no adapter escolhido.

## Adicionando um provider

1. Implementar todos os métodos de `WhatsAppProvider` dentro de `api/app/providers`.
2. Acrescentar o enum e uma migration se for um provider novo.
3. Registrar na factory.
4. Criar fixtures/testes de respostas positivas, erros, timeout e webhooks duplicados.
5. Documentar estados externos e provar que nenhuma credencial chega ao frontend.
