# Plano de Purga de Histórico — Google API Key Exposta (PREPARADO, NÃO EXECUTADO)

**Status:** Preparado, aguardando autorização expressa do Chefe e veredito do Sentinela sobre se a chave é real.
**Incidente:** Google API key exposta em fixtures de teste, presente no commit ba2e186 (raiz do histórico).
**Risco:** Purgar reescreve o histórico — afeta branches, tags, CI, PRs abertos e todos os clones.

---

## 1. Procedimento com git filter-repo (apenas preparação, não executar)

### 1.1 Backup completo antes de qualquer coisa
```bash
# Clone espelho (mirror) para backup seguro fora do repo de trabalho
git clone --mirror https://github.com/dcprj/tomus.git /tmp/tomus-backup-mirror
# Ou usar bundle para incluir todos os refs
git bundle create /tmp/tomus-full-backup.bundle --all
```

### 1.2 Instalar git-filter-repo
```bash
pip install git-filter-repo
```
*Nota: git filter-repo exige que o repositório não tenha worktree sujo e que seja um clone fresco (ou use --force).*

### 1.3 Arquivo de expressões para remoção da API key
Criar `/tmp/expressions.txt`:
```
<STRING_DA_API_KEY>==>
```
*(substituir `<STRING_DA_API_KEY>` pela string exata da chave Google exposta)*

Ou, para substituir por marcador seguro:
```
<STRING_DA_API_KEY>==>[REDACTED_GOOGLE_API_KEY]
```

### 1.4 Executar filtro em clone espelho (não no worktree de desenvolvimento)
```bash
cd /tmp/tomus-purga-work
git filter-repo --replace-text /tmp/expressions.txt --force
```
Isso reescreve todos os commits em todos os refs (branches + tags), alterando SHAs.

### 1.5 Verificar remoção
```bash
git log --all --oneline | head -50
git rev-list --all | xargs -I{} sh -c 'git show {} --stat | grep -q "<STRING_DA_API_KEY>" && echo "AINDA PRESENTE em {}"'
git grep -r "<STRING_DA_API_KEY>" $(git rev-list --all) 2>/dev/null || echo "Nenhuma ocorrencia encontrada no historico reescrito"
```

---

## 2. Impacto no CI, PRs abertos e clones

### CI (GitHub Actions)
- Todos os workflows disparados por `push` ou `pull_request` em branches afetadas serão reavaliados contra os novos SHAs.
- O workflow `release.yml` é disparado por `push: tags: 'v*'`. Como as tags serão reescritas (novos SHAs), qualquer tag existente `v*` precisará ser deletada e recriada.
- PRs abertos contra `develop`/`stage`/`main` terão histórico divergente (branches de feature baseadas em commits antigos). Os PRs precisarão ser rebaseados nos novos SHAs ou recriados.

### Clones locais
- Todo desenvolvedor com clone local terá histórico desatualizado.
- `git pull` falhará ou criará merge estranho porque os SHAs mudaram.
- Solução para cada desenvolvedor: `git fetch --all --force` ou `git clone` fresco. Branches locais de feature precisarão de `git rebase --onto <novo-sha> <velho-sha> <branch-feature>`.

### Tags
- Tags existentes apontarão para commits antigos (que serão órfãos ou removidos pelo filter-repo com `--prune-empty auto`).
- Precisam ser deletadas e recriadas apontando para os novos SHAs correspondentes.

---

## 3. Sequência exata de force push por branch

Ordem recomendada: **develop → stage → main**, depois tags.

```bash
# No repo principal (após filter-repo concluído localmente):

# 1. develop
git push origin --force develop

# 2. stage
git push origin --force stage

# 3. main
git push origin --force main

# 4. Tags (deletar antigas e recriar apontando para novos SHAs)
git tag -d v1.4.0 v1.4.1 v1.4.2 v1.4.3  # exemplos
git push origin --delete v1.4.0 v1.4.1 v1.4.2 v1.4.3
# Recriar tags nos novos SHAs correspondentes
git tag v1.4.2 <novo-sha-1.4.2>
git tag v1.4.3 <novo-sha-1.4.3>
git push origin v1.4.2 v1.4.3  # etc.
```

**Aviso:** Nenhum push deve acontecer sem autorização explícita do Chefe. Cada force push invalida clones existentes.

---

## 4. Fechar alerta do GitHub (Secret Scanning)

O GitHub gera um alerta de Secret Scanning para a API key exposta. Após a purga e o force push, fechar o alerta via API:

```bash
# Obter número do alerta
gh api repos/dcprj/tomus/secret-scanning/alerts --jq '.[] | select(.secret_type == "google_api_key") | .number'

# Fechar o alerta (conforme veredito do Sentinela)
# Opção A: Chave revogada -> estado "resolved"
gh api -X PATCH repos/dcprj/tomus/secret-scanning/alerts/{NUMERO_ALERTA} \
  -f state=resolved \
  -f resolution=revoked

# Opção B: Falso positivo -> estado "dismissed"
gh api -X PATCH repos/dcprj/tomus/secret-scanning/alerts/{NUMERO_ALERTA} \
  -f state=dismissed \
  -f resolution=false_positive \
  -f dismissed_reason="Chave nao e valida / e falso positivo"
```

**A decisão entre `revoked` e `false_positive` depende exclusivamente do veredito do Sentinela.**

---

## 5. Pré-requisitos antes de executar (quando autorizado)

1. [ ] Sentinela confirma se a Google API key é real ou falso positivo.
2. [ ] Chefe dá autorização expressa para reescrever histórico e force push.
3. [ ] Todos os PRs abertos em develop/stage/main são mesclados, fechados ou rebaseados antes da purga.
4. [ ] Todos os desenvolvedores são avisados para fazer push de trabalho pendente (branches locais serão invalidados).
5. [ ] Backup mirror criado e validado.
6. [ ] Nenhuma build/release em andamento.

---

## 6. O que NÃO fazer

- Não executar `git filter-repo` sem backup mirror validado.
- Não force push sem autorização explícita do Chefe.
- Não criar tag `v1.4.3` antes da purga (se a chave estiver em histórico anterior, a tag ainda apontaria para commits expostos).
- Não fazer `git push --force --all` de uma vez sem revisar cada branch.

---

**Responsável:** Farol (preparação do plano apenas). Execução depende de: veredito do Sentinela + autorização explícita do Chefe.
