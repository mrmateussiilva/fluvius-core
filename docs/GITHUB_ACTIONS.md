# GitHub Actions

O workflow `.github/workflows/pipeline.yml` executa migrations/testes da API,
build do frontend e validação dos arquivos Compose em pull requests, pushes na
`main` e execuções manuais. O deploy só ocorre depois dos três jobs passarem e
somente quando a variável de repositório `PRODUCTION_DEPLOY_ENABLED` vale
`true`.

## Preparar o acesso da VPS

A VPS deve possuir o usuário `deploy`, acesso pela chave pública correspondente,
permissão para executar Docker e propriedade do repositório:

```bash
usermod -aG docker deploy
chown -R deploy:deploy /opt/apps/fluvius-core
```

Antes de ativar o workflow, testar da máquina local:

```bash
ssh -i ~/.ssh/fluvius_deploy -p 22022 deploy@129.121.38.224 \
  'cd /opt/apps/fluvius-core && git fetch --dry-run origin main && docker compose version'
```

O repositório precisa permanecer sem alterações rastreadas na VPS. O arquivo
`.env.production` é ignorado pelo Git e continua existindo somente no servidor.

## Secrets e variável

Em **Settings → Secrets and variables → Actions**, criar estes repository
secrets:

- `VPS_HOST`: `129.121.38.224`
- `VPS_PORT`: `22022`
- `VPS_USER`: `deploy`
- `VPS_SSH_PRIVATE_KEY`: conteúdo completo de
  `~/.ssh/fluvius_deploy`, incluindo cabeçalho e rodapé
- `VPS_KNOWN_HOSTS`: chave pública do host SSH no formato abaixo

Como o SSH usa uma porta não padrão, gerar `VPS_KNOWN_HOSTS` na própria VPS:

```bash
awk '{print "[129.121.38.224]:22022 "$1" "$2}' \
  /etc/ssh/ssh_host_ed25519_key.pub
```

A chave privada nunca deve ser enviada para a VPS, adicionada ao repositório ou
exibida nos logs.

Depois de criar todos os secrets, ainda em
**Secrets and variables → Actions → Variables**, criar:

```text
PRODUCTION_DEPLOY_ENABLED=true
```

O job usa o environment `production`. Ele pode receber uma regra de aprovação
manual em **Settings → Environments → production** sem alterar o workflow.

## Primeiro deploy e operação

Após cadastrar os secrets e a variável:

1. abrir **Actions → CI and production deploy**;
2. escolher **Run workflow** na branch `main`;
3. confirmar os três jobs de validação;
4. acompanhar `Deploy production`.

O servidor aceita somente o SHA exato da `main` que passou no mesmo workflow.
Se outro commit avançar a branch enquanto um pipeline antigo estiver rodando, o
deploy antigo para e o pipeline novo assume. Um lock com `flock` impede duas
execuções simultâneas na VPS.

O SHA implantado fica em `.deploy-state/last-successful-sha`. Em falha, o
workflow mantém os containers e logs para diagnóstico; migrations não sofrem
rollback automático.

## Comportamento do deploy

O workflow executa `deploy/scripts/production-deploy.sh` na VPS. Esse script
não deve ser substituído por um `docker compose up` genérico, porque ele
preserva algumas garantias operacionais:

- valida o Compose e constrói as imagens antes de tocar nos containers ativos;
- mantém Postgres, Redis e Evolution Go separados da troca cotidiana de código;
- roda `alembic upgrade head` em um container temporário antes de reiniciar a
  API;
- inicia a API sem rodar migration no boot;
- atualiza API, workers e frontend em etapas;
- grava o SHA publicado em `.deploy-state/last-successful-sha` somente depois
  dos healthchecks passarem.

Esse fluxo reduz a janela em que o Caddy pode retornar 502 durante deploys.
Ainda não é zero downtime absoluto: a produção possui uma única API e um único
container `web` atrás do Caddy do host. Para eliminar a troca curta restante,
implementar blue/green com duas instâncias ativas e troca atômica de upstream.
