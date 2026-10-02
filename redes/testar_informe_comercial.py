# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco, sem e-mail real) de `redes/informe_comercial.py`:
(1) `fila_linkedin_aguardando_api` — contagem real de peças `linkedin_pagina` com
    `calendario_status='aguardando_api'` (devolvidas à fila por `redes/publicar.py`, PLAYBOOK
    §7-V-8);
(2) `montar_html` — a linha "N peças do LinkedIn em fila aguardando acesso à API" aparece no
    informe, em tom NEUTRO (sem culpar ninguém, sem pedir ação ao Roveda — ele é Diretor
    Comercial, só recebe informe, não opera redes: memória da casa,
    `feedback-roveda-diretor-comercial-nao-opera-redes.md`).

Roda `python3 redes/testar_informe_comercial.py` a partir da raiz do repo; sai com código != 0 se
qualquer prova falhar (mesmo padrão dos demais testar_*.py do repo)."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import informe_comercial  # noqa: E402

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


_select_original = informe_comercial.supa.select

print("== fila_linkedin_aguardando_api — controle POSITIVO: 3 linhas no banco (mock) -> conta 3 ==")


def fake_select_3(tabela, query):
    if tabela == "ic_redes_publicacao" and "canal=eq.linkedin_pagina" in query and "calendario_status=eq.aguardando_api" in query:
        return [{"peca_id": "p1"}, {"peca_id": "p2"}, {"peca_id": "p3"}]
    return []


informe_comercial.supa.select = fake_select_3
try:
    n = informe_comercial.fila_linkedin_aguardando_api("innconta")
    checar("3 peças aguardando_api no banco -> conta 3", n, 3)
finally:
    informe_comercial.supa.select = _select_original

print("\n== fila_linkedin_aguardando_api — controle NEGATIVO: fila vazia -> conta 0 ==")
informe_comercial.supa.select = lambda *a, **k: []
try:
    n = informe_comercial.fila_linkedin_aguardando_api("innconta")
    checar("fila vazia -> conta 0", n, 0)
finally:
    informe_comercial.supa.select = _select_original

print("\n== fila_linkedin_aguardando_api — controle NEGATIVO: erro de rede/banco não derruba o "
      "informe (devolve 0, mesma defesa das outras contagens deste arquivo) ==")


def fake_select_erro(tabela, query):
    raise RuntimeError("mock: banco indisponível")


informe_comercial.supa.select = fake_select_erro
try:
    n = informe_comercial.fila_linkedin_aguardando_api("innconta")
    checar("erro no select -> conta 0 (não propaga exceção)", n, 0)
finally:
    informe_comercial.supa.select = _select_original

print("\n== montar_html — a linha da fila do LinkedIn aparece com a contagem certa, em tom neutro ==")
hoje = datetime.date(2026, 9, 23)
inicio, fim = informe_comercial.semana_de(hoje)
html = informe_comercial.montar_html(inicio, fim, [], [], {}, 0, [], fila_linkedin=5)
contem("linha com contagem 5 presente", html, "5 peças do LinkedIn em fila aguardando acesso à API.")
contem("tom neutro — nunca menciona Roveda nesta linha/informe inteiro", html, "Roveda", esperado=False)
contem("tom neutro — nunca pede ação (\"publique\")", html, "publique", esperado=False)
contem("tom neutro — nunca pede ação (\"urgente\")", html, "urgente", esperado=False)

print("\n== montar_html — contagem 0 também aparece (controle negativo: nunca omite a linha) ==")
html0 = informe_comercial.montar_html(inicio, fim, [], [], {}, 0, [], fila_linkedin=0)
contem("linha com contagem 0 presente mesmo sem pendência", html0, "0 peças do LinkedIn em fila aguardando acesso à API.")

# ══ Prospecção (Consultor SDR, passo 2 — 25/09/2026) ═══════════════════════════════════════════
_rpc_original = informe_comercial.supa.rpc

print("\n== categoria_dor — mapeia a frase (com valor variável) pra um rótulo estável de contagem ==")
checar("dívida ativa com valor em R$ vira categoria fixa",
       informe_comercial.categoria_dor("Dívida ativa da União acima de R$ 1 milhão (R$ 2.500.000,00)"),
       "Dívida ativa da União")
checar("Lucro Real mapeia pra si mesmo", informe_comercial.categoria_dor("Lucro Real"), "Lucro Real")
checar("sanção vigente mapeia pro rótulo genérico (sem o nome da base)",
       informe_comercial.categoria_dor("Sanção vigente: embargo do IBAMA"), "Sanção vigente")
checar("frase sem prefixo conhecido usa a própria frase (nunca descarta a dor)",
       informe_comercial.categoria_dor("frase nunca vista antes"), "frase nunca vista antes")

print("\n== dores_e_contato_das_entradas — agrega por categoria, conta contato, ignora fora_do_perfil na dor ==")


def fake_rpc_dor(nome, corpo=None):
    if nome != "ic_radar_dor":
        raise RuntimeError("mock: RPC inesperada " + nome)
    cnpj = corpo["p_cnpj"]
    if cnpj == "cnpj_divida":
        return {"pontos": 40, "dores": ["Dívida ativa da União acima de R$ 1 milhão (R$ 2.500.000,00)"], "faixa": "alta"}
    if cnpj == "cnpj_lucro_real":
        return {"pontos": 25, "dores": ["Lucro Real", "Sem registro nos cadastros de sanções em 24/09/2026"], "faixa": "média"}
    return {"pontos": 0, "dores": [], "faixa": "sem dado"}


linhas_semana = [
    {"cnpj": "cnpj_divida", "estado": "na_fila", "email": None, "telefone": "4730000000"},
    {"cnpj": "cnpj_lucro_real", "estado": "em_contato", "email": "nao@deve.aparecer", "telefone": None},
    {"cnpj": "cnpj_fora", "estado": "fora_do_perfil", "email": None, "telefone": "4730000001"},  # tem contato, mas dor não conta (fora do perfil)
    {"cnpj": "cnpj_novo", "estado": "novo", "email": None, "telefone": None},  # nem enriquecido ainda: fora da dor
]
informe_comercial.supa.rpc = fake_rpc_dor
try:
    contagem, com_contato = informe_comercial.dores_e_contato_das_entradas(linhas_semana)
    checar("dívida ativa contada 1x (categoria, não frase inteira)", contagem.get("Dívida ativa da União"), 1)
    checar("Lucro Real contado 1x", contagem.get("Lucro Real"), 1)
    checar("sem registro de sanções contado 1x", contagem.get("Sem registro nos cadastros de sanções"), 1)
    checar("fora_do_perfil e novo NÃO entram na contagem de dor (só 2 chamadas geram dor)", sum(contagem.values()), 3)
    checar("com_contato conta TODAS as linhas com email/telefone, mesmo fora do perfil (3: divida+lucro_real+fora)", com_contato, 3)
finally:
    informe_comercial.supa.rpc = _rpc_original

print("\n== dores_e_contato_das_entradas — controle NEGATIVO: erro numa RPC não derruba as outras ==")


def fake_rpc_erra_uma(nome, corpo=None):
    if corpo["p_cnpj"] == "cnpj_quebra":
        raise RuntimeError("mock: RPC falhou pra este CNPJ")
    return {"pontos": 15, "dores": ["Lucro Presumido"], "faixa": "baixa"}


informe_comercial.supa.rpc = fake_rpc_erra_uma
try:
    contagem, _ = informe_comercial.dores_e_contato_das_entradas([
        {"cnpj": "cnpj_quebra", "estado": "na_fila", "email": None, "telefone": None},
        {"cnpj": "cnpj_ok", "estado": "na_fila", "email": None, "telefone": None},
    ])
    checar("a linha que não quebrou ainda soma normalmente", contagem.get("Lucro Presumido"), 1)
finally:
    informe_comercial.supa.rpc = _rpc_original

print("\n== movimentacao_radar_semana / originadores_novos_semana — contam por estado/tabela, 0 em erro ==")


def fake_select_mov(tabela, query):
    if tabela == "ic_radar" and "estado=eq.em_contato" in query:
        return [{"id": 1}, {"id": 2}]
    if tabela == "ic_radar" and "estado=eq.virou_lead" in query:
        return [{"id": 3}]
    if tabela == "ic_radar_pessoa":
        return [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    return []


informe_comercial.supa.select = fake_select_mov
try:
    mov = informe_comercial.movimentacao_radar_semana(inicio, fim)
    checar("2 moveram pra em_contato na semana", mov["em_contato"], 2)
    checar("1 virou lead na semana", mov["virou_lead"], 1)
    checar("3 originadores novos na semana", informe_comercial.originadores_novos_semana(inicio, fim), 3)
finally:
    informe_comercial.supa.select = _select_original

informe_comercial.supa.select = fake_select_erro
try:
    mov0 = informe_comercial.movimentacao_radar_semana(inicio, fim)
    checar("erro no select -> em_contato 0 (não propaga)", mov0["em_contato"], 0)
    checar("erro no select -> originadores 0 (não propaga)", informe_comercial.originadores_novos_semana(inicio, fim), 0)
finally:
    informe_comercial.supa.select = _select_original

print("\n== montar_html — seção Prospecção com movimento: dores, contato (só contagem), movimentação, link ==")
prospeccao_cheia = {
    "entradas": 5, "na_fila": 4, "fora_do_perfil": 1,
    "dores": {"Dívida ativa da União": 2, "Lucro Real": 1},
    "com_contato": 3, "em_contato_semana": 2, "virou_lead_semana": 1,
    "originadores_novos": 2, "link_crm": "https://crm.innconta.com.br/",
}
html_prosp = informe_comercial.montar_html(inicio, fim, [], [], {}, 0, [], fila_linkedin=0, prospeccao=prospeccao_cheia)
contem("título da seção presente", html_prosp, "<h3>Prospecção</h3>")
contem("contagem de entradas presente", html_prosp, "5 empresa(s) nova(s) na fila do radar")
contem("dores mais frequentes, por categoria", html_prosp, "Dívida ativa da União: 2, Lucro Real: 1")
contem("contato é SÓ contagem", html_prosp, "3</b> com contato corporativo encontrado")
contem("nunca o contato em si (nenhum e-mail/telefone aparece na seção)", html_prosp, "@", esperado=False)
contem("movimentação da equipe", html_prosp, "2 em contato, 1 viraram lead")
contem("originadores novos", html_prosp, "2</b> originador(es) novo(s)")
contem("link para a fila do CRM sempre presente", html_prosp, 'href="https://crm.innconta.com.br/"')
contem("tom positivo — nunca 'falha'", html_prosp, "falha", esperado=False)
contem("tom positivo — nunca 'erro'", html_prosp, "erro", esperado=False)
contem("nunca pede ação (\"publique\")", html_prosp, "publique", esperado=False)

print("\n== montar_html — semana sem NENHUM movimento: frase positiva, nunca 'nada aconteceu' ==")
html_vazio = informe_comercial.montar_html(inicio, fim, [], [], {}, 0, [], fila_linkedin=0, prospeccao=None)
contem("frase positiva de fila pronta", html_vazio, "A fila está pronta para a próxima semana.")
contem("nunca a frase negativa 'nada aconteceu'", html_vazio, "nada aconteceu", esperado=False)
contem("link do CRM aparece mesmo sem movimento", html_vazio, 'href="https://crm.innconta.com.br/"')

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM.")
