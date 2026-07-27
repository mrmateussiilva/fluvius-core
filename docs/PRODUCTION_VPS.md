# Produção na VPS

Este ambiente foi dimensionado para a primeira implantação em:

- Ubuntu;
- 8 vCPU e 8 GB de RAM;
- SSD de 400 GB expansível;
- domínio `fluvius.finderbit.com.br`;
- Caddy como único serviço exposto;
- dados e mídias persistidos em `/srv/fluvius`.

## Topologia

Somente Caddy publica `80/tcp`, `443/tcp` e `443/udp`. API, PostgreSQL, Redis,
workers e Evolution Go usam redes Docker privadas, sem portas no host. O Caddy
serve o frontend compilado, termina HTTPS, encaminha `/api`, `/health` e `/ws`,
e não encaminha `/storage`.

Os anexos são entregues por
`GET /api/v1/attachments/{id}/content`. A API revalida sessão, tenant e canal
antes de usar `FileResponse`. A Evolution Go continua lendo `/storage` apenas
pela rede interna, durante o envio da mídia.

## Primeira instalação

Clone o repositório em uma localização estável, por exemplo
`/opt/fluvius-core`. Não mova o diretório depois de instalar o timer de backup,
pois os links operacionais apontam para ele.

```bash
cd /opt/fluvius-core
sudo ./deploy/scripts/install-ubuntu.sh
./deploy/scripts/generate-production-env.sh
nano .env.production
./deploy/scripts/production-deploy.sh
```

O instalador não ativa o firewall automaticamente para evitar interromper uma
sessão SSH que use porta não padrão. Depois de confirmar `SSH_PORT`:

```bash
sudo SSH_PORT=22 ./deploy/scripts/install-ubuntu.sh --enable-firewall
sudo ufw status verbose
```

O gerador cria segredos URL-safe independentes e protege
`.env.production` com modo `0600`. Antes do deploy, conferir:

- `APP_DOMAIN=fluvius.finderbit.com.br`;
- um e-mail válido em `ACME_EMAIL`;
- nenhuma chave vazia fora dos campos legados;
- DNS `A` apontando para o IPv4 da VPS;
- portas 80 e 443 liberadas no firewall do provedor.

Em `production`, a API recusa iniciar com segredo curto/reutilizado, URL HTTP,
CORS de localhost, cookie inseguro, rate limit desligado, storage relativo,
banco com senha padrão ou Redis sem autenticação.

## Primeiro administrador

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
  --password "defina-uma-senha-forte"
```

O navegador usa cookie `HttpOnly`, `Secure` e `SameSite=Strict`; o JWT não fica
persistido em `localStorage`. O login é limitado por conta e IP usando Redis.

## Operação

```bash
# Estado
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl -fsS https://fluvius.finderbit.com.br/health/live
curl -fsS https://fluvius.finderbit.com.br/health/ready

# Logs
docker compose --env-file .env.production -f docker-compose.prod.yml \
  logs -f api worker delivery-worker evolution-go caddy

# Migration
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec api alembic current

# Atualização depois de revisar o commit
git pull --ff-only
./deploy/scripts/production-deploy.sh
```

O endpoint `/health/live` confirma o processo. `/health/ready` exige conexão
positiva com PostgreSQL e Redis. Os containers usam `restart: unless-stopped`,
healthchecks, limites de recursos, limite de PIDs e rotação do log local.

Para rollback de código, voltar ao commit anterior de forma não destrutiva,
reconstruir e subir novamente. Migration de banco só pode ser revertida após
analisar se houve escrita no schema novo; na dúvida, restaurar em ambiente
separado antes.

## Dados e capacidade

Diretórios persistentes:

```text
/srv/fluvius/postgres
/srv/fluvius/redis
/srv/fluvius/media
/srv/fluvius/caddy/data
/srv/fluvius/caddy/config
/srv/fluvius/backups
```

Monitorar ocupação do SSD e alertar a partir de 70%. Mídias são o principal
vetor de crescimento; o limite por upload continua em 25 MB.

## Backup local

O timer `fluvius-backup.timer` executa diariamente por volta de 02:30, com
atraso aleatório de até 15 minutos. Ele:

1. cria `pg_dumpall` dos bancos Fluvius e Evolution;
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

A restauração para produção para API, workers, Evolution e Caddy, substitui
banco e mídias e depois sobe a stack:

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
