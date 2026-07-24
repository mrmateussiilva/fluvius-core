# Providers de WhatsApp

## Contrato

`WhatsAppProvider` isola todo comportamento específico de gateway em `api/app/providers`. A UI e os demais domínios não importam SDKs nem montam URLs do gateway.

Métodos obrigatórios:

- `send_text(channel, to, text, reply_to_*, idempotency_key) -> SendResult`
- `send_media(channel, to, file_url, caption=None) -> SendResult`
- `get_status(channel) -> ChannelStatusResult`
- `get_qr_code(channel) -> QRCodeResult`
- `handle_webhook(payload) -> IncomingMessageResult`
- `handle_message_status(payload) -> MessageStatusUpdateResult | None`
- `get_contact_profile(channel, phone_number) -> ContactProfileResult`

Os DTOs normalizam confirmação de envio, status do canal, QR/pairing code e mensagem recebida. A factory seleciona o adapter a partir de `WhatsAppChannel.provider`.

## EvolutionGoProvider

É a implementação inicial. Usa `httpx`, `EVOLUTION_GO_BASE_URL` e `EVOLUTION_GO_API_KEY`. A chave é enviada no header `apikey` e nunca deve aparecer em logs. Na versão 0.7.2, as rotas de dados confirmadas são `/send/text`, `/send/media`, `/instance/status` e `/instance/qr`; o middleware resolve a instância pelo token do header. Cada canal informa `provider_config.instance_name` somente como referência não secreta.

A imagem local padrão é `evoapicloud/evolution-go:0.7.2`, substituível por `EVOLUTION_GO_IMAGE`. O serviço usa os bancos locais `evogo_auth` e `evogo_users`. `EVOLUTION_GO_GLOBAL_API_KEY` é a chave administrativa do container; `EVOLUTION_GO_API_KEY` é o token da instância usado pelo adapter. A ativação/licença do gateway é externa ao Fluvius e pode exigir `EVOLUTION_OPERATOR_EMAIL` ou ativação pelo Manager.

## Respostas confirmadas na versão 0.7.2

O status chega no envelope `{"message": "success", "data": {...}}`. Dentro de `data`, os campos `Connected` e `LoggedIn` indicam, respectivamente, conexão do socket e sessão autenticada. O adapter aceita também as variantes em camelCase. O QR usa o mesmo envelope e expõe `qrcode` e `code`.

Em uma sessão já autenticada, `GET /instance/qr` responde HTTP 400 com `{"error": "session already logged in"}`. Essa resposta específica confirma que não há QR a exibir e preserva o canal como `connected`; qualquer outro HTTP 400 continua sendo tratado como falha.

O token em `EVOLUTION_GO_API_KEY` deve ser o **Token da Instância** mostrado no Manager. Ele não é o nome `Pessoal` e também não é a chave administrativa `EVOLUTION_GO_GLOBAL_API_KEY`.

### Webhook Evolution Go 0.7.2

A instância é conectada com uma URL por canal e as assinaturas `MESSAGE`, `CONNECTION`, `QRCODE` e `READ_RECEIPT`. Em Docker local, a URL precisa usar o DNS interno da API, nunca `localhost`:

```text
http://api:8000/api/v1/webhooks/whatsapp/evolution_go/{channel_id}
```

Ao consultar status ou QR pela API, o adapter reaplica essa configuração por meio de `/instance/connect`. Assim, uma instância apagada e recriada com o mesmo nome recupera webhook e assinaturas quando o operador usa **Reconectar WhatsApp**. A base interna é configurada por `EVOLUTION_GO_WEBHOOK_BASE_URL`; em Docker local, o padrão é `http://api:8000`.

### DNS no ambiente local

O Evolution Go precisa resolver e acessar `web.whatsapp.com` para obter a versão do cliente e abrir o WebSocket. O Compose define `DOCKER_DNS_PRIMARY` e `DOCKER_DNS_SECONDARY` para API, worker e gateway, usando `1.1.1.1` e `8.8.8.8` como padrões locais. Isso evita que containers antigos continuem encaminhando consultas para o DNS de uma rede Wi-Fi que já foi trocada.

Se a rede bloquear resolvedores públicos, configure esses valores no `.env` com os servidores permitidos pela infraestrutura. Erros contendo `lookup web.whatsapp.com on 127.0.0.11:53` indicam falha de DNS do Docker, não credencial ou número inválido.

Ao apagar e recriar uma instância, atualize `EVOLUTION_GO_API_KEY` com o novo token e reinicie a API. O `provider_config.instance_name` do canal também deve coincidir exatamente com o nome da nova instância.

Essa versão não envia header customizado no webhook. Ela inclui `instanceToken` no corpo; o adapter compara esse valor com `EVOLUTION_GO_API_KEY` em tempo constante. O token é removido do payload antes de gravar `provider_events`. O header `X-Webhook-Secret` continua aceito como alternativa para providers capazes de configurá-lo.

Eventos `Message` usam o envelope nativo do Go com `data.Info` e `data.Message`. Mensagens com `Info.IsFromMe=true` originadas no celular são persistidas como `outgoing/sent`; o contato é resolvido por `Info.RecipientAlt`, evitando armazenar LIDs como telefone. Eventos técnicos `SendMessage` são ignorados porque a chamada síncrona da API já persiste esse envio. Grupos continuam fora do MVP.

Respostas a botões legados podem gerar os eventos `ButtonClick` e `Message` para a mesma interação. O adapter ignora `ButtonClick` com sucesso HTTP e usa apenas `Message` como fonte canônica, evitando retries e duplicidade. Botões interativos continuam fora do escopo do MVP.

O envio de texto retorna `{"message": "success", "data": {...}}`; a confirmação positiva é o identificador em `data.Info.ID`. Sem esse campo, o Fluvius mantém a regra conservadora e marca o envio como `failed`. Na 0.7.2, respostas usam `quoted.messageId` e `quoted.participant`; o adapter também envia o UUID local em `id`, mantendo a mesma chave em uma tentativa manual de reenvio.

Mídia usa `/send/media` com `type` igual a `image`, `audio`, `video` ou `document`. WebP usa `/send/sticker` e o campo `sticker`. A URL armazenada para o navegador é convertida para a URL interna da API antes da chamada ao gateway. Respostas citadas também são encaminhadas nos dois endpoints.

Com `WEBHOOK_FILES=true`, mensagens de mídia chegam com o arquivo em `data.Message.base64` e metadados no objeto `imageMessage`, `audioMessage`, `videoMessage`, `documentMessage` ou `stickerMessage`. O adapter normaliza esses dados, a API salva o arquivo em `MessageAttachment` e remove o base64 da cópia guardada em `provider_events`.

Recibos chegam como evento `Receipt`, com o estado em `state`, os IDs em `data.MessageIDs` e o instante em `data.Timestamp`. `Delivered` e `Read` avançam mensagens outgoing do mesmo tenant e canal, preenchem `delivered_at`/`read_at` e nunca regridem. `ReadSelf` é ignorado porque representa leitura local de uma mensagem recebida, não leitura pelo cliente. Se o recibo chegar antes da confirmação síncrona do envio, ele permanece não processado em `provider_events` e é reconciliado assim que o ID do provider for persistido.

O perfil de contato combina, em paralelo, `/user/check`, `/user/info`, `/user/avatar` e `/user/contacts`. O adapter normaliza confirmação do número, nome exibido/comercial/verificado, recado e URL da foto. Cada fonte tem timeout independente e falha parcial não elimina os dados obtidos pelas demais; URLs de avatar fora de HTTP(S) são descartadas. O frontend acessa apenas `/api/v1/contacts/{id}` e solicita atualização pela API.

## TODO de compatibilidade Evolution Go

A documentação pública e o Swagger da linha Evolution Go estão evoluindo. Antes do primeiro teste integrado/produção, confirmar contra o Swagger da imagem efetivamente fixada:

- compatibilidade das rotas ao trocar a imagem (0.7.2 usa `/send/text` e `/send/media`);
- armazenamento seguro de um token por canal para suportar múltiplas instâncias; o environment atual atende uma instância por processo;
- schema exato de confirmação de `SendMedia`;
- validade/cache das URLs de avatar e latência de `/user/info` em diferentes contas;
- eventos de falha de entrega e os códigos de erro associados (os recibos `Delivered`/`Read` estão confirmados);
- assinatura/autenticação nativa de webhook e estratégia de rotação;
- política de retries e idempotência aceita pelo gateway;
- exigência e ciclo de ativação da licença na versão implantada.

As fixtures sanitizadas de status conectado e QR solicitado durante sessão autenticada ficam em `api/tests/fixtures/evolution_go/0.7.2`. Envio de texto/mídia e demais itens acima ainda dependem de captura real antes da liberação para produção. Falha de HTTP ou resposta de envio sem ID nunca é tratada como envio bem-sucedido.

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
