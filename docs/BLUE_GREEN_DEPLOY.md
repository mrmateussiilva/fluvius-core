# Deploy blue/green

O Fluvius usa blue/green na camada de aplicação para trocar API e frontend sem
deixar o Caddy sem upstream. PostgreSQL, Redis, Evolution Go e o volume de
mídias permanecem únicos e compartilhados; eles não são duplicados por slot.

```text
Caddy -> upstream ativo -> API + Web do slot ativo
                       \-> PostgreSQL / Redis / Evolution Go
```

Os slots usam projetos Compose separados e portas locais distintas:

| Slot | API | Web |
| --- | ---: | ---: |
| legado | 18000 | 18080 |
| blue | 18100 | 18180 |
| green | 18200 | 18280 |

O slot ativo fica em `.deploy-state/active-slot`. Na ausência desse arquivo,
o deploy considera o stack antigo ativo e faz a primeira migração para Blue.

## Preparação única da VPS

O host precisa usar o include dinâmico do Caddy e permitir que o usuário de
deploy valide/recarregue o serviço sem senha:

```bash
cd /opt/apps/fluvius-core
sudo cp deploy/Caddyfile.host /etc/caddy/fluvius.caddy
sudo install -d -o deploy -g deploy -m 0755 .deploy-state
sudo install -o deploy -g deploy -m 0644 \
  deploy/Caddyfile.upstreams .deploy-state/active-upstreams.caddy
```

Confirme que o `/etc/caddy/Caddyfile` importa `/etc/caddy/*.caddy` e valide:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Crie uma regra sudoers equivalente, ajustando os caminhos se a distribuição
usar locais diferentes:

```text
deploy ALL=(root) NOPASSWD: /usr/bin/caddy validate --config /etc/caddy/Caddyfile, /usr/bin/systemctl reload caddy
```

O arquivo `.env.production` deve conter, além dos segredos existentes:

```text
EVOLUTION_GO_WEBHOOK_BASE_URL=https://fluvius.finderbit.com.br
FLUVIUS_FRONTEND_NETWORK=fluvius-core-prod_frontend
FLUVIUS_BACKEND_NETWORK=fluvius-core-prod_backend
```

Para outro domínio, substitua o valor pelo domínio público real. O endereço
de webhook precisa ser público porque o gateway pode manter uma URL antiga
como `http://api:8000`; o primeiro deploy blue/green reaplica o endereço para
todos os canais antes da troca de tráfego.

## Fluxo de publicação

`deploy/scripts/production-deploy.sh` executa as etapas abaixo:

1. valida tag e SHA;
2. identifica o slot ativo e escolhe o inativo;
3. garante PostgreSQL, Redis, Evolution Go e as redes compartilhadas;
4. constrói somente o slot inativo;
5. executa migrations compatíveis;
6. sobe API e frontend do slot inativo;
7. verifica `/health/ready`, `/health/version` e os serviços locais;
8. reaplica webhooks do Evolution Go;
9. atualiza os upstreams do Caddy e faz reload gracioso;
10. valida o domínio público e a identidade do slot;
11. sobe os workers novos, drena os antigos e registra o slot ativo.

Se a troca ou a validação pública falhar, o script tenta restaurar o upstream
anterior. O slot antigo só é parado depois que o novo worker estiver saudável.

O endpoint `/health/version` retorna `slot` e `version` e nunca deve ser
protegido por autenticação, pois é usado pelo deploy localmente e pelo Caddy.

## Workers e migrations

Durante a troca, apenas a frota de workers do novo slot deve processar as filas.
Os jobs continuam protegidos pelas garantias de idempotência do Fluvius.

Migrations devem seguir expand/contract: primeiro adicionar estrutura compatível
com a versão antiga, depois publicar o código, e somente em release posterior
remover o que ficou obsoleto. O banco nunca sofre rollback automático.

## Rollback

Um rollback normal executa o workflow com uma tag que já contenha o suporte a
blue/green. O script prepara o slot oposto e faz a troca para ele; o banco
permanece no estado atual.

A primeira release blue/green é uma fronteira operacional. Voltar diretamente
para uma tag anterior a essa mudança exige o procedimento legado e não deve ser
feito pelo script novo sem validar compatibilidade de migrations e webhooks.

## Verificação manual

```bash
curl -fsS https://fluvius.finderbit.com.br/health/live
curl -fsS https://fluvius.finderbit.com.br/health/ready
curl -fsS https://fluvius.finderbit.com.br/health/version
cat .deploy-state/active-slot
cat .deploy-state/last-successful-tag
docker compose --project-name fluvius-blue --env-file .env.production \
  -f docker-compose.prod.slot.yml ps
docker compose --project-name fluvius-green --env-file .env.production \
  -f docker-compose.prod.slot.yml ps
```

Blue/green evita indisponibilidade causada pela publicação da aplicação em uma
VPS saudável. Não substitui alta disponibilidade da própria VPS, PostgreSQL,
Redis, disco ou Caddy.
