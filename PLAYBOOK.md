# PLAYBOOK · consultor-redes

Como este código funciona e onde ele morde. Toda entrada leva data e sessão de origem.

## Origem
- 02/10/2026 (sessão vigia-cotas-fornecedores): extraído de `zarkatus/innconta-site@2d83cb51` porque o Actions do repositório privado estourava a franquia (innconta-site 350 de 518 min em 1-2/10; o Conselho passa ~24 min esperando IA gratuita). Repositório público = minutos do Actions sem custo. O PLAYBOOK histórico (§7-V e seguintes) segue no innconta-site; as referências "PLAYBOOK §x" nos comentários apontam para lá.

## Regras deste repositório público
- **Nenhum dado pessoal ou sigiloso no código.** Identidade do dono (nomes, domínio pessoal, amostras) só no Secret `GUARDA_IDENTIDADE` (JSON); e-mail e WhatsApp do CVO só nos Secrets `CVO_EMAIL` e `CVO_WA`. Sem `GUARDA_IDENTIDADE`, `guarda.checar` barra toda peça (falha fechada); `testar_guarda.py` usa identidade sintética quando o Secret não existe e exige ≥2 amostras quando existe.
- **Log do Actions é público.** Todo passo que roda Python passa por `python redes/quieto.py <rótulo> -- <comando>`: no log só "exit N, L linhas"; em falha (ou input `log_central=true`) a cauda (150 linhas) vai à central pela RPC `ic_email`. Passo novo sem `quieto.py` vaza texto de peça, motivo do Conselho e nome de cliente barrado.
- **Motivo da guarda nunca leva o padrão** ("variante N de GUARDA_IDENTIDADE"); a bateria reprova se o padrão aparecer no motivo.
- **Dados no repo privado `consultor-redes-dados`** (deploy key de escrita no Secret `DADOS_DEPLOY_KEY`): o workflow faz checkout em `_dados/` e liga `redes/kit`, `redes/estoque`, `img/og` por symlink. A reposição do vigia commita em `_dados` (branch `main`), não aqui.
- **Inputs do workflow entram por env** (`TAREFA`, `IN_QA`, `IN_MES_REF`, `IN_PECA_ID`, `IN_LOTE_JSON`, `IN_MARCA`) em `redes/rodar_tarefa.sh`; nunca interpolar `${{ }}` dentro de script (injeção).

## Armadilhas
- 02/10/2026 (vigia-cotas-fornecedores): `gh secret set` no Windows com `subprocess.run(..., input=str, text=True)` grava `\r\n` (pipe em modo texto). Chave SSH com CRLF dá `Load key ...: error` e `Permission denied (publickey)` no checkout. Passar **bytes** (`input=valor.encode()`, sem `text=True`).
- 02/10/2026: o cofre local recusa valor multilinha; a deploy key está lá em base64 de 1 linha (`github-deploy-key-consultor-redes-dados-02out2026.txt`).
- 02/10/2026: GET na API de um repositório público dá 200 com qualquer token; para provar que um PAT dispara, só o POST `dispatches` (204 x 403).
- 02/10/2026 (virada): `redes/vigia.py` (`gh_runs`) lê só os runs do PRÓPRIO repo (`GITHUB_REPOSITORY`). No dia em que o Consultor mudou de repo, a 1ª vigia real não achou os runs do dia (estavam no innconta-site) e re-disparou `metricas` e `conselho_diario`, que já tinham rodado. Em nova mudança de repo, faça a virada depois da última tarefa do dia, ou rode a 1ª vigia real só no dia seguinte. Runs em QA não re-disparam nada.
- 02/10/2026: a reserva GitLab é `zarkatus-mirror/consultor-redes` (id 87183546, `.gitlab-ci.yml` deste repo, tópico `reserva-ci`). Repo novo só entra no espelho da VM depois de ganhar a chave de deploy da VM (`garantir_chaves_vm` do `espelho-gitlab.py`). Identidade da guarda vai como `GUARDA_IDENTIDADE_B64`, porque o GitLab não mascara JSON. `CONSELHO_ECONOMICO=1` só no passo da tarefa: se for global, quebra a bateria do Conselho. Para rodar as baterias local, encaixe os dados por junção (`redes/kit`, `redes/estoque`, `img/og` → repo de dados) e remova com `rmdir` (só o link).
- 02/10/2026: o pg_cron (`sql/redes-disparo-pg-cron.sql`) só aciona este repo depois que o PAT do disparo (`github_pat_redes_dispatch`, fine-grained) o inclui em Repository access. Editar o PAT pede "Confirm access" (sudo) do dono da conta. O valor do token não muda, então vault e cofre continuam iguais.

## Rodar local
`GUARDA_IDENTIDADE` ausente = identidade sintética só no `testar_guarda.py`; as outras baterias precisam da variável (sem ela a guarda barra tudo e o Conselho escala tudo). Dados: clonar o repo privado e ligar `redes/kit`, `redes/estoque`, `img/og` (no Windows, `mklink /J`).
