# GitHub Actions

O workflow `.github/workflows/pipeline.yml` executa CI em pull requests, pushes
na `main` e execuções manuais. Ele roda migrations/testes da API, build do
frontend e validação dos arquivos Compose. Push na `main` não faz deploy de
produção.

O deploy de produção fica em `.github/workflows/production-deploy.yml` e só é
acionado por:

- publicação de uma GitHub Release;
- execução manual com `workflow_dispatch`, informando uma tag existente.

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
  'cd /opt/apps/fluvius-core && git fetch origin --tags --dry-run && docker compose version'
```

O repositório precisa permanecer sem alterações rastreadas na VPS. O arquivo
`.env.production` é ignorado pelo Git e continua existindo somente no servidor.

## Secrets

Em **Settings -> Secrets and variables -> Actions**, criar estes repository
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

O job usa o environment `production`. Ele pode receber uma regra de aprovação
manual em **Settings -> Environments -> production** sem alterar o workflow.

## Publicar uma versão

Crie uma tag anotada a partir da `main` revisada:

```bash
git switch main
git pull --ff-only
git tag -a v0.1.0 -m "Fluvius v0.1.0"
git push origin v0.1.0
```

Depois publique a Release:

```text
GitHub -> Releases -> Draft a new release -> selecionar a tag -> Publish release
```

Ao publicar a Release, o workflow **Production deploy** valida a tag, faz
checkout do commit exato, roda testes/build/Compose nessa tag e envia a mesma
tag para a VPS. A VPS executa:

```bash
./deploy/scripts/production-deploy.sh v0.1.0
```

O servidor busca tags, entra em detached HEAD na tag informada, confirma o SHA,
faz build das imagens e só então atualiza os containers.

## Rollback manual

Para voltar o código para uma versão anterior:

```text
GitHub -> Actions -> Production deploy -> Run workflow
```

Informe a tag anterior, por exemplo:

```text
v0.1.0
```

O rollback não altera o histórico Git e não faz `git pull origin main`. A VPS
fica no commit associado à tag informada.

## Conferir versão implantada

Na VPS:

```bash
cd /opt/apps/fluvius-core
git describe --tags --exact-match HEAD
git rev-parse HEAD
cat .deploy-state/last-successful-tag
cat .deploy-state/last-successful-sha
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Logs da aplicação:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  logs -f api worker delivery-worker evolution-go web
```

Logs do último deploy pelo GitHub ficam em
**GitHub -> Actions -> Production deploy**.

## Comportamento do deploy

O workflow executa `deploy/scripts/production-deploy.sh` na VPS com a tag
obrigatória. Esse script não deve ser substituído por um `docker compose up`
genérico, porque ele preserva garantias operacionais:

- valida a tag e confirma o SHA antes de implantar;
- valida o Compose e constrói as imagens antes de tocar nos containers ativos;
- mantém Postgres, Redis e Evolution Go separados da troca cotidiana de código;
- roda `alembic upgrade head` em um container temporário antes de reiniciar a
  API;
- inicia a API sem rodar migration no boot;
- atualiza API, workers e frontend em etapas;
- verifica containers esperados e healthchecks internos/público;
- grava a tag e o SHA publicados em `.deploy-state/` somente depois dos
  healthchecks passarem.

Um erro de build interrompe o deploy antes da troca de API, workers e frontend.
Migrations não sofrem rollback automático.

## Migrations e rollback

Rollback de código para uma tag anterior pode falhar se uma versão mais nova já
aplicou migrations incompatíveis com o código antigo. Não implemente rollback
automático de banco no deploy de produção.

Migrations futuras devem, sempre que possível, ser compatíveis com versões
anteriores: adicionar colunas/tabelas antes de exigir uso, evitar remoções
imediatas e separar mudanças destrutivas em versões posteriores após o código
antigo deixar de ser necessário.
