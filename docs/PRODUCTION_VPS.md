# Produção na VPS

Este ambiente foi dimensionado para a primeira implantação em:

- Ubuntu;
- 8 vCPU e 8 GB de RAM;
- SSD de 400 GB expansível;
- domínio `fluvius.finderbit.com.br`;
- domínio administrativo `evolution.finderbit.com.br`;
- Caddy instalado no host como único serviço exposto;
- dados e mídias persistidos em `/srv/fluvius`.

## Topologia

Somente o serviço Caddy do Ubuntu publica `80/tcp`, `443/tcp` e `443/udp`. A
API, o servidor estático e o Manager da Evolution são vinculados pelo Docker
apenas em `127.0.0.1:18000`, `127.0.0.1:18080` e `127.0.0.1:18081`;
nunca ficam acessíveis diretamente pela interface pública. O Caddy encaminha
`evolution.finderbit.com.br` para a porta `18081` com HTTPS; o Manager exige a
chave administrativa forte da instalação. PostgreSQL, Redis e workers
permanecem somente nas redes Docker privadas.

O Caddy do host termina HTTPS/WSS, encaminha `/api`, `/health` e `/ws` para a
API, encaminha o restante para o frontend e bloqueia `/storage`. O container
`web` usa Caddy apenas como servidor estático HTTP interno, sem certificado e
sem ocupar 80/443.

Os anexos são entregues por
`GET /api/v1/attachments/{id}/content`. A API revalida sessão, tenant e canal
antes de usar `FileResponse`. A Evolution Go continua lendo `/storage` apenas
pela rede interna, durante o envio da mídia.

## Primeira instalação

Clone o repositório em uma localização estável, por exemplo
`/opt/apps/fluvius-core`. Não mova o diretório depois de instalar o timer de
backup, pois os links operacionais apontam para ele.

```bash
cd /opt/apps/fluvius-core
sudo ./deploy/scripts/install-ubuntu.sh
./deploy/scripts/generate-production-env.sh
nano .env.production
sudo cp deploy/Caddyfile.host /etc/caddy/fluvius.caddy
# Adicione uma única vez ao /etc/caddy/Caddyfile:
# import /etc/caddy/*.caddy
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
git fetch origin --tags --force
./deploy/scripts/production-deploy.sh v0.1.0
```

Se `fluvius.finderbit.com.br` já existir no Caddy, substitua o bloco antigo
pelo conteúdo de `deploy/Caddyfile.host` em vez de adicionar um segundo bloco
com o mesmo endereço. Depois, sempre valide antes de recarregar.

O instalador não ativa o firewall automaticamente para evitar interromper uma
sessão SSH que use porta não padrão. Depois de confirmar `SSH_PORT`:

```bash
sudo SSH_PORT=22 ./deploy/scripts/install-ubuntu.sh --enable-firewall
sudo ufw status verbose
```

O gerador cria segredos URL-safe independentes e protege
`.env.production` com modo `0600`. Antes do deploy, conferir:

- `APP_DOMAIN=fluvius.finderbit.com.br`;
- `FLUVIUS_API_PORT=18000`, `FLUVIUS_WEB_PORT=18080` e
  `EVOLUTION_GO_MANAGER_PORT=18081` livres no loopback;
- nenhuma chave vazia fora dos campos legados;
- DNS `A` apontando para o IPv4 da VPS;
- DNS `A` de `evolution.finderbit.com.br` apontando para o mesmo IPv4;
- portas 80 e 443 liberadas no firewall do provedor.

Em `production`, a API recusa iniciar com segredo curto/reutilizado, URL HTTP,
CORS de localhost, cookie inseguro, rate limit desligado, storage relativo,
banco com senha padrão ou Redis sem autenticação.

## Ativação única da Evolution Go

A versão fixada da Evolution Go exige uma licença da Evolution Foundation.
Antes da ativação, o container fica no ar, mas responde `503 LICENSE_REQUIRED`
para criação de instâncias. Isso é diferente da chave administrativa
`EVOLUTION_GO_GLOBAL_API_KEY`, que protege as chamadas entre Fluvius e
Evolution.

O Manager não publica uma porta própria no firewall. Ele é acessado por HTTPS
através do Caddy em `https://evolution.finderbit.com.br`. Depois de subir a
stack, confirme o estado na VPS:

```bash
curl -fsS http://127.0.0.1:18081/license/status
```

Abra `https://evolution.finderbit.com.br/manager/login`, use
`https://evolution.finderbit.com.br` como URL da API e informe a
`EVOLUTION_GO_GLOBAL_API_KEY` guardada na `.env.production`. Não envie essa
chave por chat nem a coloque em histórico de comandos. Conclua o registro
solicitado pela Evolution Foundation e valide novamente:

```bash
curl -fsS http://127.0.0.1:18081/license/status
```

O resultado deve conter `"status":"active"`. A licença fica persistida no banco
`evogo_auth`; reiniciar ou recriar o container não exige novo registro. Feche o
navegador ao terminar. A partir daí, empresas criam e reconectam suas
instâncias somente pela tela **Canais do WhatsApp**, sem acessar o Manager.

## Primeiro administrador da plataforma

Depois do healthcheck ficar verde:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.prod.yml \
  exec api python -m app.jobs.bootstrap \
  --tenant-name "Finderbit" \
  --tenant-slug "finderbit" \
  --email "admin@finderbit.com.br" \
  --name "Administrador" \
  --password "defina-uma-senha-forte" \
  --platform-admin
```

O navegador usa cookie `HttpOnly`, `Secure` e `SameSite=Strict`; o JWT não fica
persistido em `localStorage`. O login é limitado por conta e IP usando Redis.
Depois do login, o ícone **Administração Fluvius** permite criar as empresas e
seus primeiros administradores sem shell. Ao criar, copie o cartão de acesso
antes de fechá-lo: ele contém `https://SEU_DOMINIO/login/{slug}`, o e-mail e a
senha inicial, que não fica disponível para consulta posterior. O cliente deve
usar esse link para que a autenticação seja limitada à empresa dele. Se o
primeiro usuário já existia antes desta migration, promova a conta existente
sem alterar sua senha:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.prod.yml \
  exec api python -m app.jobs.promote_platform_admin \
  --email "admin@finderbit.com.br"
```

## Operação

O deploy de produção é versionado por GitHub Release e tag Git. Push na `main`
não faz deploy. O workflow **Production deploy** roda quando uma Release é
publicada ou quando uma execução manual informa uma tag anterior para rollback.

O deploy em si é feito em etapas pelo script
`deploy/scripts/production-deploy.sh vX.Y.Z`: primeiro busca tags, valida que a
tag existe, faz checkout detached no commit da tag, confirma o SHA e constrói as
imagens. Só depois garante Postgres/Redis/Evolution Go, roda as migrations em um
container temporário, troca a API já sem executar migration no boot, atualiza os
workers e por último o frontend. Esse fluxo reduz a janela de 502 do Caddy
durante publicação. Zero downtime completo exigirá blue/green com duas
instâncias ativas ou troca atômica de upstream.

A API de produção sobe com vários processos uvicorn (`UVICORN_WORKERS`, padrão
4) para absorver webhooks paralelos da Evolution Go sem bloquear o accept TCP.
O dispatcher de entregas elege um líder via Redis; o listener realtime roda em
cada worker para fan-out local dos WebSockets. Em VPS de 8 GB, o container da
API fica limitado a 2 GB de RAM.

O serviço `delivery-worker` usa `rq worker-pool` com dois processos por padrão,
configuráveis por `DELIVERY_WORKER_PROCESSES`. Conversas distintas podem ser
processadas em paralelo, mas mensagens da mesma conversa continuam ordenadas e
são encadeadas imediatamente após a confirmação terminal da anterior. O loop de
dois segundos do dispatcher é mantido para recuperar entregas que não puderam
ser enfileiradas diretamente.

O serviço `webhook-worker` consome `fluvius-webhooks` com um processo por
padrão, configurável por `WEBHOOK_WORKER_PROCESSES`. A API confirma o webhook
somente depois de persistir inbox e staging; o worker cria contato, conversa,
mensagem e anexo. O dispatcher recupera itens não enfileirados e jobs
interrompidos. Para preservar o teto de memória da VPS, `worker` e
`webhook-worker` usam 384 MB cada por padrão.

Não troque esse script por `docker compose up -d --build` em produção. O fluxo
genérico recria serviços em bloco, pode deixar o Caddy sem upstream por mais
tempo e volta a acoplar migration ao boot da API.

```bash
# Estado
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl -fsS https://fluvius.finderbit.com.br/health/live
curl -fsS https://fluvius.finderbit.com.br/health/ready

# Logs
docker compose --env-file .env.production -f docker-compose.prod.yml \
  logs -f api worker delivery-worker webhook-worker evolution-go web

# Proxy do host
sudo systemctl status caddy
sudo journalctl -u caddy --since "10 minutes ago"
sudo caddy validate --config /etc/caddy/Caddyfile

# Migration
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec api alembic current

# Versão implantada
git describe --tags --exact-match HEAD
git rev-parse HEAD
cat .deploy-state/last-successful-tag
cat .deploy-state/last-successful-sha
```

Em operação normal, esse fluxo é executado automaticamente pelo GitHub Actions
após uma GitHub Release publicada. Para rollback, execute manualmente o workflow
**Production deploy** e informe uma tag anterior, por exemplo `v0.1.0`. A VPS
nunca deve executar `git pull origin main`, `git checkout main` ou
`git reset --hard origin/main` durante o deploy. Consulte
[GITHUB_ACTIONS.md](GITHUB_ACTIONS.md) para cadastrar a chave SSH, os secrets,
publicar versões e operar rollback.

Depois de um deploy, valide:

```bash
curl -fsS https://fluvius.finderbit.com.br/health/ready
cat .deploy-state/last-successful-tag
cat .deploy-state/last-successful-sha
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

O endpoint `/health/live` confirma o processo. `/health/ready` exige conexão
positiva com PostgreSQL e Redis. Os containers usam `restart: unless-stopped`,
healthchecks, limites de recursos, limite de PIDs e rotação do log local.

Administradores de cada empresa também possuem **Saúde operacional** no menu.
A tela verifica a cada 30 segundos a presença dos workers de entrega,
recebimento e manutenção, entregas e inbox aguardando há mais de dois minutos,
falhas nas últimas 24 horas e o estado/último evento dos canais daquele tenant. Alertas amarelos
indicam degradação; alertas vermelhos indicam risco direto para o envio. Durante
um deploy, o aviso de worker offline pode aparecer transitoriamente até o novo
processo registrar seu heartbeat no RQ.

Rollback de código deve ser feito pela execução manual do workflow de produção,
informando uma tag anterior. Isso não altera o histórico Git e deixa a VPS no
commit associado à tag. Migration de banco não sofre rollback automático: voltar
o código para uma tag anterior pode falhar se uma versão mais nova já aplicou
migrations incompatíveis. Migrations futuras devem, sempre que possível, ser
compatíveis com versões anteriores e separar mudanças destrutivas em etapas.

## Dados e capacidade

Diretórios persistentes:

```text
/srv/fluvius/postgres
/srv/fluvius/redis
/srv/fluvius/media
/srv/fluvius/backups
```

Monitorar ocupação do SSD e alertar a partir de 70%. Mídias são o principal
vetor de crescimento; o limite por upload continua em 25 MB.

## Backup local

O timer `fluvius-backup.timer` executa diariamente por volta de 02:30, com
atraso aleatório de até 15 minutos. Ele:

  1. cria `pg_dumpall` dos bancos Fluvius e Evolution, mais dumps dedicados
     de `evogo_auth` (licença) e `evogo_users` (instâncias);
2. salva dump e `/srv/fluvius/media` em um repositório Restic deduplicado;
3. mantém 7 diários, 4 semanais e 3 mensais;
4. remove dados que saíram da retenção.

Comandos:

```bash
sudo systemctl status fluvius-backup.timer
sudo systemctl start fluvius-backup.service
sudo journalctl -u fluvius-backup.service
sudo fluvius-verify-backup
```

Esse backup protege contra exclusão acidental e regressão lógica, mas permanece
no mesmo domínio de falha da VPS. Perda do SSD ou da VPS pode eliminar dados e
backup juntos. O próximo passo operacional obrigatório é copiar o repositório
Restic para outro servidor ou object storage.

## Restauração

Primeiro listar e verificar snapshots:

```bash
sudo fluvius-verify-backup
sudo RESTIC_REPOSITORY=/srv/fluvius/backups/restic \
  RESTIC_PASSWORD_FILE=/etc/fluvius/restic-password restic snapshots
```

A restauração para API, workers, Evolution e servidor web substitui banco e
mídias e depois sobe a stack. O Caddy do host permanece ativo:

```bash
sudo CONFIRM_RESTORE=YES \
  ./deploy/scripts/restore-backup.sh latest
```

Após restaurar, validar login, canais, mensagem incoming, envio, arquivo,
edição, recibos e reconexão. Sempre que possível, ensaiar a restauração em uma
VPS temporária antes de alterar produção.

## Liberação

Antes do primeiro cliente real, completar a matriz de homologação descrita em
`docs/PROVIDERS.md`: texto, mídias, figurinha, edição, recibos, timeout,
reinício, QR, licença e idempotência na imagem Evolution fixada.
