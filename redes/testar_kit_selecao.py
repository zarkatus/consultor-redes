# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco, sem forjar data em produção) da regra de
elegibilidade para PUBLICAR (redes/publicar.py::elegivel_para_publicar).

23/09/2026 (diretriz do CVO — Roveda é Diretor Comercial, não operador de redes; publicar é
tarefa do consultor): este arquivo testava a seleção do extinto "kit de 1 clique ao Roveda"
(kit_roveda.py::elegivel_para_kit — data <= amanhã E kit_enviado_em nulo). Vira a prova da
seleção do passo diário 'publicar' (redes/publicar.py), regra mais estrita: `data_publicacao
<= HOJE` (nunca amanhã — publicar não adianta a data agendada) E `publicado_em` nulo. Roda
`python3 redes/testar_kit_selecao.py` a partir da raiz do repo; sai com código != 0 se qualquer
prova falhar (mesmo padrão de redes/testar_guarda.py — gate real, não decorativo)."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publicar  # noqa: E402

FALHAS = []
HOJE = datetime.date(2026, 9, 23)  # data fixa — teste determinístico, não depende do relógio
ONTEM = (HOJE - datetime.timedelta(days=1)).isoformat()
AMANHA = (HOJE + datetime.timedelta(days=1)).isoformat()
DEPOIS = "2026-10-07"  # mesma data real das peças de outubro já aprovadas, bem no futuro


def checar(nome, row, esperado):
    got = publicar.elegivel_para_publicar(row, hoje=HOJE)
    print(("OK  " if got == esperado else "FALHA") + " - %s -> elegivel=%s (esperado=%s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


print("== controle POSITIVO: peça aprovada, data = hoje, nunca publicada -> ENTRA ==")
checar("data=hoje, publicado_em=null", {
    "status": "aprovado", "data_publicacao": HOJE.isoformat(), "publicado_em": None,
}, True)

print("\n== controle POSITIVO: data = ontem (atrasada, ainda não publicada) -> ENTRA ==")
checar("data=ontem, publicado_em=null", {
    "status": "aprovado", "data_publicacao": ONTEM, "publicado_em": None,
}, True)

print("\n== controle NEGATIVO: data = amanhã (agendada, mas o dia ainda não chegou) -> NÃO "
      "ENTRA (diferente do antigo kit, que saía na véspera — publicar não adianta a data) ==")
checar("data=amanha, publicado_em=null", {
    "status": "aprovado", "data_publicacao": AMANHA, "publicado_em": None,
}, False)

print("\n== controle NEGATIVO: peça aprovada, data em 07/10 (bem no futuro) -> NÃO ENTRA "
      "(exatamente o caso real das peças de outubro já aprovadas) ==")
checar("data=2026-10-07, publicado_em=null", {
    "status": "aprovado", "data_publicacao": DEPOIS, "publicado_em": None,
}, False)

print("\n== controle NEGATIVO: peça aprovada, SEM data (calendário ainda não rodou) -> NÃO ENTRA ==")
checar("data=null", {
    "status": "aprovado", "data_publicacao": None, "publicado_em": None,
}, False)

print("\n== controle NEGATIVO: data = hoje MAS já foi publicada -> NÃO ENTRA de novo "
      "(idempotência: uma peça publicada nunca é publicada 2x) ==")
checar("data=hoje, publicado_em já preenchido", {
    "status": "aprovado", "data_publicacao": HOJE.isoformat(), "publicado_em": "2026-09-23T09:00:00Z",
}, False)

print("\n== controle NEGATIVO: data = hoje mas status ainda não é 'aprovado' -> NÃO ENTRA ==")
checar("status=aguardando, data=hoje", {
    "status": "aguardando", "data_publicacao": HOJE.isoformat(), "publicado_em": None,
}, False)

print("\n== reprodução do cenário real de 23/09/2026 (12 peças aprovadas, todas com data de "
      "outubro) -> NENHUMA entra hoje (é exatamente por isso que a rodada de hoje publica 0) ==")
pecas_reais_hoje = [
    {"status": "aprovado", "data_publicacao": DEPOIS, "publicado_em": None}
    for _ in range(12)
]
elegiveis = [p for p in pecas_reais_hoje if publicar.elegivel_para_publicar(p, hoje=HOJE)]
print(("OK  " if len(elegiveis) == 0 else "FALHA") + " - 12 peças de outubro -> %d elegíveis (esperado 0)" % len(elegiveis))
if len(elegiveis) != 0:
    FALHAS.append("cenário real das 12 peças de outubro deveria dar 0 elegíveis")

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (2 positivas, 5 negativas + reprodução do cenário real das 12 peças de outubro).")
