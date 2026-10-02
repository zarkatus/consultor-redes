# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco) de `redes/calendario.py::montar` — o ponto que
decide se uma peça do LinkedIn devolvida à fila (`calendario_status='aguardando_api'`, ver
`redes/publicar.py::_marcar_aguardando_api`, PLAYBOOK §7-V-8) volta a competir por vaga no
calendário do mês seguinte.

Confirmado por LEITURA do código (não presumido) antes deste teste: peça `status='aprovado'` com
`data_publicacao is null` já era varrida pela query de `candidatas` em `montar()` independente do
motivo pelo qual a data está vazia — esse comportamento não precisou de mudança nova. O que FALTAVA
(e este arquivo prova) é o gate específico do LinkedIn: sem `ic_segredo.linkedin_token`, uma peça
`aguardando_api` do canal `linkedin_pagina` fica de fora (senão reagendaria todo mês sem nunca
poder publicar de fato); com o token presente, ela volta a competir normalmente.

Roda `python3 redes/testar_calendario.py` a partir da raiz do repo; sai com código != 0 se
qualquer prova falhar (mesmo padrão de redes/testar_kit_selecao.py e redes/testar_publicar_linkedin.py)."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import calendario  # noqa: E402

FALHAS = []
chamadas_itens = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %s (esperado %s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


MES_REF = "2026-10"

ROW_LINKEDIN_AGUARDANDO = {
    "id": "row-li-1", "peca_id": "peca-linkedin-fila", "canal": "linkedin_pagina",
    "status": "aprovado", "data_publicacao": None, "mes_ref": None,
    "calendario_status": "aguardando_api", "criado_em": "2026-09-01T00:00:00Z",
}


def _instalar_mocks(candidatas_imagem, token_presente):
    """Substitui supa.select/patch/segredo/enviar_email e email_lote.montar
    por mocks — nenhuma chamada de rede real sai daqui. Devolve os registros de chamada."""
    chamadas_patch = []
    chamadas_email = []
    chamadas_itens.clear()

    def fake_select(tabela, query):
        if "peca_id=eq." in query and "video-vaga-" in query:
            # checagem de placeholder de vídeo já reservado — devolve "já existe" pra nunca cair
            # no POST cru via urllib (esse caminho não é mockável por aqui, e não é o que este
            # teste prova; testar_calendario.py cobre só o despacho de imagem/texto do LinkedIn).
            return [{"id": "placeholder-ja-existe"}]
        if "tipo=eq.video" in query:
            return []  # sem vídeo aprovado pendente neste cenário
        if "tipo=neq.video" in query:
            return list(candidatas_imagem)
        return []

    def fake_patch(tabela, filtro, corpo):
        chamadas_patch.append((tabela, filtro, corpo))
        return [{}]

    def fake_segredo(chave):
        return "TOKEN-MOCK" if (chave == "linkedin_token" and token_presente) else None

    def fake_enviar_email(assunto, destino, html):
        chamadas_email.append((assunto, destino))
        return {"id": "mock-email"}

    calendario.supa.select = fake_select
    calendario.supa.patch = fake_patch
    calendario.supa.segredo = fake_segredo
    calendario.supa.enviar_email = fake_enviar_email
    calendario.email_lote.montar = lambda titulo, intro, itens, **k: (chamadas_itens.extend(itens) or "<html>mock</html>")
    # relógio fixo antes de MES_REF: o filtro de dia passado (30/09/2026) não pode depender da data em que o teste roda
    calendario.primeiro_dia_agendavel = lambda agora=None: _primeiro_dia_original(agora or _AGORA_FIXO)
    return chamadas_patch, chamadas_email


_select_original = calendario.supa.select
_patch_original = calendario.supa.patch
_segredo_original = calendario.supa.segredo
_enviar_email_original = calendario.supa.enviar_email
_email_lote_original = calendario.email_lote.montar
_primeiro_dia_original = calendario.primeiro_dia_agendavel
_BRT = datetime.timezone(datetime.timedelta(hours=-3))
_AGORA_FIXO = datetime.datetime(2026, 9, 30, 10, 0, tzinfo=_BRT)


def _restaurar():
    calendario.supa.select = _select_original
    calendario.supa.patch = _patch_original
    calendario.supa.segredo = _segredo_original
    calendario.supa.enviar_email = _enviar_email_original
    calendario.email_lote.montar = _email_lote_original
    calendario.primeiro_dia_agendavel = _primeiro_dia_original


print("== controle NEGATIVO: peça LinkedIn 'aguardando_api' SEM linkedin_token -> NÃO reagendada "
      "(fica de fora da vaga, sem PATCH nenhum para ela — evita o ciclo 'nova data -> falha de "
      "novo' todo mês) ==")
chamadas_patch, chamadas_email = _instalar_mocks([ROW_LINKEDIN_AGUARDANDO], token_presente=False)
try:
    r = calendario.montar("innconta", MES_REF)
    checar("sem token -> 0 peças agendadas", r["agendadas"], 0)
    checar("sem token -> nenhum PATCH na peça aguardando_api", len(chamadas_patch) == 0, True)
    checar("sem token -> nenhum e-mail de calendário enviado (nada novo para aprovar)", len(chamadas_email), 0)
finally:
    _restaurar()

print("\n== controle POSITIVO: peça LinkedIn 'aguardando_api' COM linkedin_token -> reagendada "
      "(mesmo tratamento que peça 'aprovado' sem data já recebia) ==")
chamadas_patch, chamadas_email = _instalar_mocks([ROW_LINKEDIN_AGUARDANDO], token_presente=True)
try:
    r = calendario.montar("innconta", MES_REF)
    checar("com token -> 1 peça agendada", r["agendadas"], 1)
    checar("com token -> 1 PATCH na peça (nova data)", len(chamadas_patch) == 1, True)
    if chamadas_patch:
        tabela, filtro, corpo = chamadas_patch[0]
        checar("PATCH na linha certa", filtro, "id=eq.%s" % ROW_LINKEDIN_AGUARDANDO["id"])
        checar("PATCH grava mes_ref novo", corpo.get("mes_ref"), MES_REF)
        checar("PATCH grava data_publicacao (não fica None)", corpo.get("data_publicacao") is not None, True)
        checar("PATCH devolve calendario_status para 'aguardando' (sai de aguardando_api)", corpo.get("calendario_status"), "aguardando")
    checar("com token -> 1 e-mail de calendário enviado", len(chamadas_email), 1)
    checar("CVO 30/09: e-mail vai à central, nunca à caixa pessoal", [d for _, d in chamadas_email], ["central@innconta.com.br"])
    checar("CVO 30/09: sem links de aprovação (itens só informativos)", [it.get("botoes") for it in chamadas_itens], [[]])
finally:
    _restaurar()

print("\n== controle NEGATIVO (canal diferente): peça 'aguardando_api' de OUTRO canal continua "
      "sendo varrida normalmente mesmo sem linkedin_token — o gate é só para linkedin_pagina ==")
ROW_INSTAGRAM_AGUARDANDO = dict(ROW_LINKEDIN_AGUARDANDO, id="row-ig-1", peca_id="peca-instagram-fila",
                                 canal="instagram")
chamadas_patch, chamadas_email = _instalar_mocks([ROW_INSTAGRAM_AGUARDANDO], token_presente=False)
try:
    r = calendario.montar("innconta", MES_REF)
    checar("instagram aguardando_api, sem linkedin_token -> ainda assim 1 agendada", r["agendadas"], 1)
    checar("instagram aguardando_api -> 1 PATCH (gate não se aplica a outro canal)", len(chamadas_patch) == 1, True)
finally:
    _restaurar()

print("\n== primeiro_dia_agendavel: nunca dia passado; depois das 17h BRT (publicar encerrado) é amanhã ==")
checar("15/10 10:00 -> 15/10", _primeiro_dia_original(datetime.datetime(2026, 10, 15, 10, 0, tzinfo=_BRT)), datetime.date(2026, 10, 15))
checar("15/10 21:20 -> 16/10", _primeiro_dia_original(datetime.datetime(2026, 10, 15, 21, 20, tzinfo=_BRT)), datetime.date(2026, 10, 16))

ROWS_IG = [{"id": "ig-%d" % i, "peca_id": "peca-ig-%d" % i, "canal": "instagram", "status": "aprovado",
            "data_publicacao": None, "mes_ref": None, "calendario_status": None, "criado_em": "2026-10-01T00:00:00Z"}
           for i in range(3)]

print("\n== diário no meio do mês (15/10 21:20): 3 peças do Instagram ganham 16, 17, 18/10 — nenhuma data passada, "
      "sem e-mail e sem vaga de vídeo ==")
chamadas_patch, chamadas_email = _instalar_mocks(ROWS_IG, token_presente=False)
try:
    r = calendario.montar("innconta", MES_REF, diario=True, agora=datetime.datetime(2026, 10, 15, 21, 20, tzinfo=_BRT))
    datas = [c[2]["data_publicacao"] for c in chamadas_patch]
    checar("3 agendadas", r["agendadas"], 3)
    checar("datas 16, 17 e 18/10", datas, ["2026-10-16", "2026-10-17", "2026-10-18"])
    checar("diário não manda e-mail", len(chamadas_email), 0)
finally:
    _restaurar()

print("\n== controle NEGATIVO: sem o filtro (agora antes do mês), as mesmas peças caem em 01, 02 e 03/10 ==")
chamadas_patch, chamadas_email = _instalar_mocks(ROWS_IG, token_presente=False)
try:
    calendario.montar("innconta", MES_REF, diario=True, agora=datetime.datetime(2026, 9, 30, 10, 0, tzinfo=_BRT))
    checar("datas 01, 02 e 03/10", [c[2]["data_publicacao"] for c in chamadas_patch], ["2026-10-01", "2026-10-02", "2026-10-03"])
finally:
    _restaurar()

print("\n== fim do mês (31/10 21:20): nenhuma vaga sobra no mês -> nada agendado (a rodada de 01/11 agenda em novembro) ==")
chamadas_patch, chamadas_email = _instalar_mocks(ROWS_IG, token_presente=False)
try:
    r = calendario.montar("innconta", MES_REF, diario=True, agora=datetime.datetime(2026, 10, 31, 21, 20, tzinfo=_BRT))
    checar("0 agendadas, 0 PATCH", (r["agendadas"], len(chamadas_patch)), (0, 0))
finally:
    _restaurar()

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (3 cenários: sem token não reagenda LinkedIn, com token reagenda, "
      "outro canal não é afetado pelo gate).")
