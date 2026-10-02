# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco, sem e-mail real) de `redes/relatorio_mensal.py`:
(1) `fila_linkedin_aguardando_api` — mesma contagem de `redes/informe_comercial.py`, mas
    consultada SEM filtro de `mes_ref` (peça `aguardando_api` fica com `mes_ref=None` depois de
    `redes/publicar.py::_marcar_aguardando_api`, PLAYBOOK §7-V-8 — a query normal deste relatório,
    escopada por mês, nunca a veria);
(2) `montar` — a linha "N peças do LinkedIn em fila aguardando acesso à API" chega no HTML
    enviado por e-mail, com a contagem certa, em tom neutro.

Roda `python3 redes/testar_relatorio_mensal.py` a partir da raiz do repo; sai com código != 0 se
qualquer prova falhar (mesmo padrão dos demais testar_*.py do repo)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import relatorio_mensal  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %s (esperado %s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


def contem(nome, texto, sub, esperado=True):
    got = (sub in texto)
    print(("OK  " if got == esperado else "FALHA") + " - %s -> '%s' em texto? %s (esperado %s)" % (nome, sub, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


_select_original = relatorio_mensal.supa.select
_enviar_email_original = relatorio_mensal.supa.enviar_email

print("== fila_linkedin_aguardando_api — controle POSITIVO: 2 linhas no banco (mock), SEM filtro "
      "de mes_ref (peça na fila não pertence a nenhum mês) -> conta 2 ==")


def fake_select_2(tabela, query):
    if tabela == "ic_redes_publicacao" and "canal=eq.linkedin_pagina" in query and "calendario_status=eq.aguardando_api" in query:
        checar("query da fila NÃO filtra por mes_ref", "mes_ref" in query, False)
        return [{"peca_id": "p1"}, {"peca_id": "p2"}]
    return []


relatorio_mensal.supa.select = fake_select_2
try:
    n = relatorio_mensal.fila_linkedin_aguardando_api("innconta")
    checar("2 peças aguardando_api no banco -> conta 2", n, 2)
finally:
    relatorio_mensal.supa.select = _select_original

print("\n== fila_linkedin_aguardando_api — controle NEGATIVO: fila vazia -> conta 0 ==")
relatorio_mensal.supa.select = lambda *a, **k: []
try:
    n = relatorio_mensal.fila_linkedin_aguardando_api("innconta")
    checar("fila vazia -> conta 0", n, 0)
finally:
    relatorio_mensal.supa.select = _select_original

print("\n== montar() — a linha da fila do LinkedIn chega no HTML do relatório mensal, com a "
      "contagem certa, sem tocar rede real (supa.enviar_email mockado) ==")
FILA_MOCK = [{"peca_id": "p1"}, {"peca_id": "p2"}, {"peca_id": "p3"}, {"peca_id": "p4"}]


def fake_select_relatorio(tabela, query):
    if tabela == "ic_redes_publicacao":
        if "canal=eq.linkedin_pagina" in query and "calendario_status=eq.aguardando_api" in query:
            return list(FILA_MOCK)
        return []  # linhas do mês (publicadas/aguardando/expiradas) — vazio, fora do escopo deste teste
    return []  # tabelas de contatos por origem de rede


emails_enviados = []


def fake_enviar_email(assunto, para, html):
    emails_enviados.append({"assunto": assunto, "para": para, "html": html})
    return {"id": "mock-email"}


relatorio_mensal.supa.select = fake_select_relatorio
relatorio_mensal.supa.enviar_email = fake_enviar_email
try:
    r = relatorio_mensal.montar(marca="innconta", mes_ref="2026-08", destino_email="qa@example.com")
    checar("montar() devolve fila_linkedin=4 no resultado", r.get("fila_linkedin"), 4)
    checar("exatamente 1 e-mail mockado enviado (nunca rede real)", len(emails_enviados), 1)
    if emails_enviados:
        html = emails_enviados[0]["html"]
        contem("linha com contagem 4 presente no HTML enviado", html, "4 peças do LinkedIn em fila aguardando acesso à API.")
        contem("tom neutro — nunca menciona Roveda", html, "Roveda", esperado=False)
        contem("tom neutro — nunca pede ação (\"publique\")", html, "publique", esperado=False)
finally:
    relatorio_mensal.supa.select = _select_original
    relatorio_mensal.supa.enviar_email = _enviar_email_original

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (2 cenários de fila_linkedin_aguardando_api + 1 de montar()/HTML enviado).")
