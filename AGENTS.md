# AGENTS.md — Fluvius Core

Estas regras valem para todo o repositório.

## Limites de produto

- Não recriar Chatwoot nem importar sua arquitetura ou código.
- Não criar CRM, dashboard, IA, billing ou campanhas agora.
- Não implementar Meta Cloud API ou BSP completos sem autorização.
- Não criar feature fora do escopo do MVP sem autorização explícita.
- Priorizar a operação de atendimento: receber, assumir, responder e finalizar.
- Na fila `Não atendidas`, priorizar conversas novas sem atendente e atendimentos assumidos cuja última mensagem seja do cliente.

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

## Release e deploy

- Mudanças que precisam aparecer em produção exigem nova versão e nova tag semver.
- O deploy de produção usa tag, não apenas o `main`; após commit funcional, atualizar `api/pyproject.toml`, `web/package.json`, `web/package-lock.json`, `web/src/config/app.ts` e `web/index.html`, criar commit de release, criar tag `vX.Y.Z`, fazer push da branch e da tag, e disparar o workflow `Production deploy` com `version=vX.Y.Z`.
- Não considerar uma mudança disponível para teste em produção enquanto o HTML público não refletir a nova versão e `/health/ready` não responder `ready`.

<!-- ai-memory:start -->
## Long-term memory (ai-memory)

This project uses [ai-memory](https://github.com/akitaonrails/ai-memory)
for cross-session continuity.

**Default to the current project - always.** Every ai-memory tool
auto-scopes to the project resolved from your session's working
directory. **Do NOT pass `project`, `workspace`, or `cwd` arguments unless
the user explicitly references a *different* project by name** (e.g. "what
did we decide in the `other-app` project?"). Phrases like "this project",
"here", "we", "our work", and "where did we leave off" all mean the
*current* project, so call tools with no scoping args.

This default assumes the MCP client can identify the current agent
session. Static MCP clients in parallel sessions for the same user cannot
forward the real agent session id automatically; pass explicit
`workspace` + `project` / `scopes`, or use a session-aware bridge that
forwards the lifecycle-hook session id on MCP calls.

**Lifecycle hooks already capture sanitized, bounded prompt and tool-lifecycle
observations automatically.** They are not complete native transcripts;
managed `ai-memory run` launches add the portable visible-event ledger. Do not
manually write routine notes. Only write durable memory when the user explicitly asks
to remember or annotate something permanently.

### Use the installed ai-memory Agent Skills

Detailed tool-routing guidance lives in the installed ai-memory Agent
Skills. When a task matches an installed ai-memory Agent Skill, load and
follow that skill before calling ai-memory tools. The skills cover memory
retrieval, handoffs, durable pages, learning maintenance, and routing
install or refresh work.

### When you write a project rule, write it here

If you're about to write a durable project rule ("always X", "never
Y", "all PRs must ..."), write it in the project's canonical agent instruction file.
Many projects use CLAUDE.md for Claude Code and
AGENTS.md for Codex / OpenCode / Cursor / Gemini CLI / Grok Build CLI / Kimi Code,
but if the project says one file is canonical, use that file.

If the rule is a standing *user/team* preference that should apply to
every project (tech choices, code style, personal conventions), save it
to ai-memory's reserved global scope instead — the durable-pages skill
covers how. Default memory reads surface global-scope pages in every
project automatically.

### Refreshing this snippet

This block is maintained by ai-memory. Two ways to refresh it with the
latest binary's recommended copy:

- **From the agent** (no terminal needed): ask "refresh the ai-memory
  routing in this project". The agent calls `memory_install_self_routing`,
  picks the right filename for itself (Claude Code -> `CLAUDE.md`; Codex /
  OpenCode / Cursor / Gemini / Grok -> `AGENTS.md`; Kimi Code -> `AGENTS.md`),
  uses its Write / Edit tool to replace or append the returned
  `markered_block` while preserving
  non-ai-memory user content, then writes or updates each returned
  `managed_skills` item under the selected skill root from `target_hints`
  using its `relative_path`.
- **From the CLI**: `ai-memory install-instructions` (defaults to
  `CLAUDE.md`; pass `--target AGENTS.md` for non-Claude agents or projects
  that use `AGENTS.md` as the canonical instruction file).

Both are idempotent: re-runs replace the block delimited by the ai-memory
start/end HTML-comment markers, without disturbing the rest of the file.
<!-- ai-memory:end -->
