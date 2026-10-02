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

## Rodar local
`GUARDA_IDENTIDADE` ausente = identidade sintética só no `testar_guarda.py`; as outras baterias precisam da variável (sem ela a guarda barra tudo e o Conselho escala tudo). Dados: clonar o repo privado e ligar `redes/kit`, `redes/estoque`, `img/og` (no Windows, `mklink /J`).
