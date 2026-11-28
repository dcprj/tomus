# PLANO DE ACAO — Purga de Historico: Google API Key (REAL, REVOGADA)

**Status:** Preparado, aguardando autorizacao expressa do Chefe.
**Pré-requisito pendente:** fixture segura do Sentinela entrar no commit de correcao (antes de qualquer execucao).
**Alerta GitHub:** #1 — estado alvo: `resolved`, resolucao `revoked` (chave ja revogada pelo Dario).

---

## 0. Antes de executar (gates obrigatorios)

1. Fixture segura do Sentinela commitada (commit de correcao).
2. Autorizacao expressa do Chefe para reescrever historico e force push.
3. Nenhuma build/release em andamento.

---

## 1. Comandos exatos — git filter-repo

Executar num clone espelho temporário (NUNCA no worktree de desenvolvimento).

### 1.1 Backup mirror
```bash
cd /tmp
git clone --mirror https://github.com/dcprj/tomus.git tomus-purge-mirror
cd tomus-purge-mirror
git bundle create /tmp/tomus-full-backup.bundle --all
```

### 1.2 Instalar git-filter-repo
```bash
pip install git-filter-repo
```

### 1.3 Arquivo de substituicao de texto
Criar `/tmp/replace-expressions.txt`:
```
<STRING_DA_API_KEY_REAL>==>[REDACTED_GOOGLE_API_KEY]
```
*Substituir `<STRING_DA_API_KEY_REAL>` pela string exata da chave Google exposta (fornecida pelo Sentinela/Forja no inventário).*

### 1.4 Executar filtro (reescreve todos os commits de todos os refs)
```bash
cd /tmp/tomus-purge-mirror
git filter-repo --replace-text /tmp/replace-expressions.txt --force
```

### 1.5 Verificar que a string nao existe mais em nenhum commit
```bash
git log --all --oneline
git rev-list --all | while read sha; do
  if git show "$sha" | grep -q "<STRING_DA_API_KEY_REAL>"; then
    echo "AINDA PRESENTE em $sha"
  fi
done
echo "Verificacao concluida"
```

---

## 2. Sequencia exata de force push

Ordem: **develop → stage → main**, depois tags.

```bash
cd /tmp/tomus-purge-mirror
# Adicionar remote se nao existir
git remote add origin https://github.com/dcprj/tomus.git

# 1. develop
git push origin --force develop

# 2. stage
git push origin --force stage

# 3. main
git push origin --force main

# 4. Tags: deletar antigas e recriar nos novos SHAs
# Listar tags atuais
git tag -l 'v*'

# Deletar tags locais e remotas (exemplos; ajustar conforme tag -l)
git tag -d v1.4.0 v1.4.1 v1.4.2 v1.4.3
git push origin --delete v1.4.0 v1.4.1 v1.4.2 v1.4.3

# Recriar tags nos NOVOS SHAs correspondentes (obter shas com git log --all --oneline)
git tag v1.4.0 <NOVO_SHA_1_4_0>
git tag v1.4.1 <NOVO_SHA_1_4_1>
git tag v1.4.2 <NOVO_SHA_1_4_2>
git tag v1.4.3 <NOVO_SHA_1_4_3>

# Enviar tags recriadas
git push origin v1.4.0 v1.4.1 v1.4.2 v1.4.3
```

*Aviso: cada force push invalida clones locais existentes. Desenvolvedores precisarão de `git fetch --all --force` ou `git clone` fresco, e rebasear branches de feature nos novos SHAs.*

---

## 3. Fechar alerta GitHub #1 como revogado

```bash
# 1. Confirmar que o alerta 1 existe
gh api repos/dcprj/tomus/secret-scanning/alerts/1

# 2. Fechar como revogado (chave ja revogada pelo Dario)
gh api -X PATCH repos/dcprj/tomus/secret-scanning/alerts/1 \
  -f state=resolved \
  -f resolution=revoked
```

---

## 4. O que NAO fazer

- Não executar sem autorizacao expressa do Chefe.
- Não executar sem a fixture do Sentinela commitada primeiro.
- Não force push sem backup mirror validado.
- Não criar tag v1.4.3 antes da purga (apontaria para commits com a chave exposta).
- Não fazer `git push --force --all` de uma vez; seguir a sequencia por branch.

---

**Responsavel:** Farol (plano apenas). Execução depende de: fixture do Sentinela commitada + autorizacao expressa do Chefe.
