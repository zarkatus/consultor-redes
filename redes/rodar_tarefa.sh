#!/usr/bin/env bash
# Tarefa do Consultor de redes (passo "Rodar" do workflow). Saiu do YAML em 02/10/2026 para rodar dentro de
# redes/quieto.py (repositório público: a saída não pode ir ao log aberto). Os inputs chegam por variável de
# ambiente, nunca interpolados no script: TAREFA, IN_QA, IN_MES_REF, IN_PECA_ID, IN_LOTE_JSON, IN_MARCA.
set -euo pipefail

MES_QUE_VEM="${IN_MES_REF:-}"
if [ -z "$MES_QUE_VEM" ]; then
  MES_QUE_VEM=$(date -u -d "+1 month" +%Y-%m 2>/dev/null || python3 -c "import datetime;h=datetime.date.today();m=h.month+1;a=h.year+(m>12);m=1 if m>12 else m;print('%04d-%02d'%(a,m))")
fi
QA_FLAG=()
if [ "${IN_QA:-false}" = "true" ]; then QA_FLAG=(--qa); fi
PECA_ID_FLAG=()
if [ -n "${IN_PECA_ID:-}" ]; then PECA_ID_FLAG=(--peca-id "$IN_PECA_ID"); fi

case "${TAREFA:-lote}" in
  lote) python redes/lote_aprovacao.py "${QA_FLAG[@]}" "${PECA_ID_FLAG[@]}" ;;
  calendario) python redes/calendario.py --mes-ref "$MES_QUE_VEM" ;;
  relatorio) python redes/relatorio_mensal.py ;;
  informe) python redes/informe_comercial.py "${QA_FLAG[@]}"; python redes/conselho/avisos.py resumo "${QA_FLAG[@]}"; python redes/alcance.py collab-semana "${QA_FLAG[@]}" ;;
  publicar) python redes/publicar.py "${QA_FLAG[@]}" "${PECA_ID_FLAG[@]}" ;;
  renovar_ig) python redes/ig_renovar_token.py "${QA_FLAG[@]}" ;;
  metricas) python redes/alcance.py coletar; python redes/alcance.py relatorio ;;
  video) python redes/lote_aprovacao.py --somente-video "${QA_FLAG[@]}" ;;
  arte) python redes/arte_sob_demanda.py "${PECA_ID_FLAG[@]}" ;;
  # prova ponta a ponta do artigo como fonte (linhas qa=true; recusa sem --qa; nada publicado, nada commitado)
  artigos) python redes/artigos.py provar "${QA_FLAG[@]}" --marcas "${IN_MARCA:-}" ;;
  ensaio) python redes/ensaio_geral.py --marca "${IN_MARCA:-innconta}" --mes-ref "$MES_QUE_VEM" "${QA_FLAG[@]}" "${PECA_ID_FLAG[@]}" ;;
  # depois do Conselho, a peça recém-aprovada ganha data no mês corrente (sem isso esperava o calendário do dia 5)
  conselho_diario) python redes/lote_aprovacao.py --escaladas-se-novas; python redes/calendario.py --mes-ref "$(TZ=America/Sao_Paulo date +%Y-%m)" --diario ;;
  conselho)
    if [ -n "${IN_LOTE_JSON:-}" ]; then
      python redes/conselho/conselho.py --avaliar "$IN_LOTE_JSON"
    else
      python redes/lote_aprovacao.py "${QA_FLAG[@]}"
    fi ;;
  *) echo "tarefa desconhecida: ${TAREFA:-}"; exit 1 ;;
esac
