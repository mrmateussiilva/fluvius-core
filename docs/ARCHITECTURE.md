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

1. O frontend envia texto ou anexo à API com JWT.
2. A API extrai `user_id` e `tenant_id` do JWT e revalida o membership no banco.
3. A conversa, o contato e o canal são consultados com filtro de tenant.
4. A API exige que a conversa esteja `open` e atribuída ao usuário autenticado. Assumir usa bloqueio de linha no PostgreSQL, impedindo que dois agentes sobrescrevam a posse ativa.
5. Se `channel.status != connected`, a API retorna `409` com: “WhatsApp desconectado. Reconecte o canal antes de enviar mensagens.”
6. Para texto, o frontend gera `client_message_id`, mostra imediatamente a bolha `pending` e a API usa esse UUID como ID local e chave idempotente. Repetir o mesmo ID e conteúdo devolve a mensagem existente sem chamar novamente o provider.
7. A mensagem outgoing é persistida como `pending` antes do efeito externo.
8. A factory cria o adapter correspondente a `channel.provider`.
9. O adapter chama o gateway.
10. Apenas uma resposta positiva com ID do provider muda o status para `sent`. A API
   reaplica essa invariante mesmo que um adapter retorne um resultado contraditório. Falha ou
   resposta ambígua muda para `failed`.
11. A API emite `message.created` no tenant.

Depois do `sent`, webhooks `Receipt` podem avançar a mensagem para `delivered` e `read`. A atualização é monotônica, limitada a mensagens outgoing do mesmo tenant/canal e emite `message.updated`. Recibos que chegam antes do ID de envio ficam pendentes em `provider_events` para reconciliação após a resposta síncrona do gateway.

Uma resposta valida a mensagem citada no mesmo tenant/conversa, persiste a referência local e envia apenas os identificadores externos necessários pelo adapter. Webhooks recebidos extraem a referência de `ContextInfo.StanzaID`. O reenvio manual aceita somente outgoing em `failed`, reutiliza o UUID local como chave do provider, incrementa a tentativa e repete o ciclo `pending` antes da chamada externa.

Carregar ou receber mensagens por realtime não marca a conversa como lida. O frontend emite a leitura somente quando a aba está visível, o histórico terminou de carregar e o operador alcançou o final da conversa. A requisição informa a última mensagem incoming realmente visível; a API valida tenant e conversa e avança o marcador exatamente até o `created_at` dela. Fora do final, novas mensagens preservam a posição atual e aparecem em um indicador explícito.

Rascunhos de texto ficam somente no `localStorage`, sob chave composta por usuário e conversa. Eles não são enviados à API antes do envio, são removidos quando o composer fica vazio e não incluem arquivos selecionados.

O envio é síncrono nesta fundação. A evolução natural é enfileirar tentativas e retries no RQ com idempotency key, mantendo a mesma máquina de estados.

## Fluxo de recebimento

1. O gateway chama `/api/v1/webhooks/whatsapp/{provider}/{channel_id}`.
2. A API valida a credencial do webhook e encontra o canal; o tenant vem do canal, nunca do payload. No Evolution Go 0.7.2, o `instanceToken` do corpo é validado pelo adapter.
3. O payload sanitizado entra em `provider_events`, permitindo auditoria, deduplicação e reprocessamento futuro. Credenciais são removidas antes da persistência.
4. O adapter normaliza o evento em `IncomingMessageResult`.
5. A API deduplica pelo ID da mensagem, encontra/cria o contato e usa sua conversa única naquele canal. Se ela estava finalizada, é reaberta como `new`, sem perder o histórico e sem manter a atribuição anterior.
6. Para mídia, o adapter normaliza base64, MIME type e nome; a API valida o limite, grava o arquivo no storage e cria `MessageAttachment` no mesmo tenant.
7. A mensagem incoming é persistida e os eventos realtime são emitidos.

## Fluxo de status do canal

O status pode ser consultado pela API ou atualizado por webhook. Em ambos os casos, o valor externo é normalizado para `disconnected`, `connecting`, `connected`, `requires_qr` ou `failed`. A UI usa somente esse estado interno. Eventos de mudança emitem `channel.status.updated`.

O assistente de conexão chama `POST /api/v1/channels/{id}/connect`, recebe somente QR/código de pareamento e consulta `GET /status` até a sessão ficar conectada. A solicitação inicial reaplica o webhook; as consultas periódicas de status são somente leitura no provider. O frontend nunca recebe URL ou token da Evolution. `provider_config.instance_name` funciona como referência não secreta para `EVOLUTION_GO_INSTANCE_TOKENS`; a API compara fingerprints dos tokens e rejeita a associação da mesma credencial a mais de um canal.

O cadastro é idempotente por credencial dentro do tenant: se o usuário tentar criar novamente o canal que já possui aquele token, a API devolve o canal existente e a UI abre sua conexão. A constraint global continua bloqueando reutilização entre tenants sem revelar a qual conta a credencial pertence.

## Perfil do contato

O painel operacional lê o contato persistido em `GET /api/v1/contacts/{id}`. A atualização explícita usa `POST /api/v1/contacts/{id}/refresh`, valida tenant, vínculo entre contato e canal e status conectado antes de chamar `WhatsAppProvider.get_contact_profile`. O Evolution Go é consultado apenas pelo adapter e os resultados disponíveis são armazenados como cache; estatísticas de primeira/última interação e atendimentos são calculadas a partir dos dados do Fluvius.

## Storage de mídia

No ambiente local, arquivos ficam no volume `api_storage` e são servidos por `/storage`. A API retorna o endereço externo ao navegador; o adapter converte esse endereço para `http://api:8000/storage/...` ao enviar pela Evolution Go, pois `localhost` dentro do container apontaria para o próprio gateway. Imagens, áudios, vídeos, documentos e WebP são limitados a 25 MB nesta etapa. Produção deverá substituir o storage local por S3/MinIO e URLs assinadas.

## Realtime

`WS /ws?token=...` valida o JWT e o membership antes de registrar a conexão na sala em memória do tenant. Eventos planejados:

- `conversation.created`
- `conversation.updated`
- `message.created`
- `message.updated`
- `contact.updated`
- `channel.status.updated`

O gerenciador atual funciona em uma única réplica. Com duas ou mais réplicas da API, Redis Pub/Sub é obrigatório para propagar eventos entre processos; presença, replay e cursor continuam fora desta etapa.

O cliente trata o tipo e a conversa informados em cada evento. Mensagens da conversa selecionada
são conciliadas por ID, evitando duplicação entre a resposta HTTP e o WebSocket. A contagem de não
lidas só é zerada quando a aba está visível; ao voltar para a tela, a conversa selecionada é
sincronizada novamente.

## Fila

Redis e uma fila RQ chamada `fluvius` já sobem no Compose. O worker ainda não executa envio de mensagens. Futuros candidatos: retries de provider, download/processamento de mídia, reprocessamento de webhook e notificações. Jobs precisam receber IDs e reconsultar dados com `tenant_id`, em vez de serializar objetos ORM.

## Storage

`StorageProvider` define a fronteira. `LocalStorageProvider` grava em volume local e publica arquivos via API, suficiente para desenvolvimento. Produção deve implementar S3/MinIO, URLs assinadas, validação de MIME, antivírus e política de retenção. O gateway precisa conseguir acessar a URL entregue pela API.

## Limites atuais

- Um processo da API para realtime consistente.
- Sem retry automático de envio.
- Sem criptografia de `provider_config`; apenas configurações não secretas devem ser armazenadas ali.
- Storage local e upload de até 25 MB.
- Contrato webhook do Evolution Go ainda precisa de fixtures reais e testes de compatibilidade por versão.
