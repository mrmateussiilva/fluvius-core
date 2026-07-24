# AGENTS.md — Fluvius Core

Estas regras valem para todo o repositório.

## Limites de produto

- Não recriar Chatwoot nem importar sua arquitetura ou código.
- Não criar CRM, dashboard, IA, billing ou campanhas agora.
- Não implementar Meta Cloud API ou BSP completos sem autorização.
- Não criar feature fora do escopo do MVP sem autorização explícita.
- Priorizar a operação de atendimento: receber, assumir, responder e finalizar.

## Providers e mensagens

- Todo código específico de gateway deve ficar em `api/app/providers`.
- O frontend nunca chama Evolution Go, Meta Cloud ou BSP diretamente.
- A API sempre resolve o provider a partir do canal persistido.
- Não hardcodar URL, token, cliente, tenant ou nome de instância.
- Não registrar API keys, tokens ou payloads contendo segredos.
- Não tratar erro, timeout ou resposta ambígua do gateway como sucesso.
- Mensagem outgoing nasce como `pending`.
- Não marcar mensagem como `sent` sem confirmação positiva e identificador do provider.
- Em falha confirmada do provider, marcar a mensagem como `failed` e preservar o erro seguro.
- Bloquear envio na API e na UI quando o canal não estiver `connected`.

## Multi-tenancy e segurança

- Toda consulta a dados operacionais deve conter filtro explícito por `tenant_id`.
- IDs recebidos na URL não provam pertencimento ao tenant.
- Validar associação de usuários, canais, contatos e conversas ao tenant autenticado.
- Webhooks devem resolver o tenant pelo canal persistido; nunca aceitar `tenant_id` do payload externo.
- WebSockets devem validar token e membership antes de entrar na sala do tenant.
- Segredos pertencem ao ambiente ou a um cofre futuro, nunca ao repositório ou ao frontend.

## Banco e migrations

- Toda alteração de schema exige migration Alembic revisável.
- Preservar os enums e as transições descritas em `docs/DATABASE.md`.
- Webhooks e IDs externos devem ser idempotentes sempre que o provider oferecer identificador.
- Não apagar migration aplicada; criar uma nova migration corretiva.

## Qualidade

- Manter módulos organizados por domínio e evitar camadas genéricas sem necessidade atual.
- Atualizar documentação quando um contrato, fluxo ou risco mudar.
- Rodar, no mínimo, compilação/import da API, validação Alembic, build TypeScript e `docker compose config` quando essas áreas forem alteradas.
- Preferir mudanças pequenas, rastreáveis e compatíveis com o escopo em `docs/MVP_SCOPE.md`.
