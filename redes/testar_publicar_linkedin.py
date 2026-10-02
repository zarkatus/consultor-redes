# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco) de `redes/publicar.py`:
(1) `publicar_via_linkedin` — o ponto onde o consultor decide entre publicar de verdade no
    LinkedIn (Community Management API) ou marcar `aguardando_api`/deixar para a próxima rodada;
(2) `rodar` — o DESPACHO por canal (linkedin_pagina tenta publicar; qualquer outro canal marca
    `aguardando_api` direto, sem tentar ler estoque nem falar com a rede).

23/09/2026 (diretriz do CVO — publicar é tarefa do consultor, não do kit ao Roveda): este
arquivo testava `kit_roveda.py::tentar_publicar_automatico`; migrado para `redes/publicar.py`
depois do rename/redesenho (ex-kit_roveda.py agora é redes/informe_comercial.py, SÓ informe).
Roda `python3 redes/testar_publicar_linkedin.py` a partir da raiz do repo; sai com código != 0
se qualquer prova falhar (mesmo padrão de redes/testar_guarda.py e redes/testar_kit_selecao.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import publicar  # noqa: E402
import publicar_linkedin  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %s (esperado %s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


ROW_LINKEDIN = {"id": "qa-id-1", "peca_id": "qa-adversario-nao-publica-de-verdade", "canal": "linkedin_pagina"}
# 23/09/2026: 'instagram' ganhou conector próprio (redes/publicar_instagram.py,
# redes/testar_publicar_instagram.py) — deixou de ser um canal "sem conector"; este arquivo usa
# 'threads' pra continuar provando o despacho genérico (qualquer canal fora de
# CANAIS_AUTOMATICOS marca aguardando_api direto, sem ler estoque).
ROW_OUTRO_CANAL = {"id": "qa-id-2", "peca_id": "qa-adversario-nao-publica-de-verdade", "canal": "threads"}

print("== publicar_via_linkedin — controle NEGATIVO: sem token (TokenAusente) -> "
      "'aguardando_api', marca calendario_status via PATCH E LIMPA data_publicacao/mes_ref "
      "(peça volta pra fila, não fica datada no passado — PLAYBOOK §7-V-8), nunca chama "
      "redes_decidir ==")
_ler_original = publicar.estoque.ler
_publicar_original = publicar_linkedin.publicar
_patch_original = publicar.supa.patch
_rpc_original = publicar.supa.rpc
chamadas_patch, chamadas_rpc = [], []
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": None}
publicar_linkedin.publicar = lambda *a, **k: (_ for _ in ()).throw(publicar_linkedin.TokenAusente("mock"))
publicar.supa.patch = lambda tabela, filtro, corpo: (chamadas_patch.append((tabela, filtro, corpo)) or [{}])
publicar.supa.rpc = lambda *a, **k: (chamadas_rpc.append((a, k)) or {"ok": True})
try:
    r = publicar.publicar_via_linkedin("innconta", ROW_LINKEDIN)
    checar("sem token -> 'aguardando_api'", r, "aguardando_api")
    checar("marcou calendario_status via PATCH 1x", len(chamadas_patch) == 1, True)
    if chamadas_patch:
        checar("PATCH com calendario_status=aguardando_api", chamadas_patch[0][2].get("calendario_status"), "aguardando_api")
        checar("PATCH limpa data_publicacao (None) — não fica datada no passado", "data_publicacao" in chamadas_patch[0][2] and chamadas_patch[0][2]["data_publicacao"] is None, True)
        checar("PATCH limpa mes_ref (None) — sai do mês, volta pra fila geral", "mes_ref" in chamadas_patch[0][2] and chamadas_patch[0][2]["mes_ref"] is None, True)
    checar("sem token -> nunca chama redes_decidir", len(chamadas_rpc) == 0, True)
finally:
    publicar.estoque.ler = _ler_original
    publicar_linkedin.publicar = _publicar_original
    publicar.supa.patch = _patch_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_linkedin — controle NEGATIVO: publicação real falha (PublicacaoFalhou) "
      "-> 'falhou', nunca marca aguardando_api, nunca chama redes_decidir (tenta de novo depois) ==")
chamadas_patch, chamadas_rpc = [], []
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": None}
publicar_linkedin.publicar = lambda *a, **k: (_ for _ in ()).throw(publicar_linkedin.PublicacaoFalhou("mock 500"))
publicar.supa.patch = lambda tabela, filtro, corpo: (chamadas_patch.append((tabela, filtro, corpo)) or [{}])
publicar.supa.rpc = lambda *a, **k: (chamadas_rpc.append((a, k)) or {"ok": True})
try:
    r = publicar.publicar_via_linkedin("innconta", ROW_LINKEDIN)
    checar("publicação falhou -> 'falhou'", r, "falhou")
    checar("publicação falhou -> nunca marcou aguardando_api", len(chamadas_patch) == 0, True)
    checar("publicação falhou -> nunca chamou redes_decidir", len(chamadas_rpc) == 0, True)
finally:
    publicar.estoque.ler = _ler_original
    publicar_linkedin.publicar = _publicar_original
    publicar.supa.patch = _patch_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_linkedin — controle POSITIVO: publica com sucesso + redes_decidir "
      "confirma -> 'publicado', com os argumentos certos (p_por='consultor') ==")
chamadas_rpc = []
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": None}
publicar_linkedin.publicar = lambda *a, **k: {"ok": True, "url_post": "https://www.linkedin.com/feed/update/share:123", "post_id": "urn:li:share:123"}
publicar.supa.rpc = lambda nome, corpo: (chamadas_rpc.append((nome, corpo)) or {"ok": True, "status": "publicado"})
try:
    r = publicar.publicar_via_linkedin("innconta", ROW_LINKEDIN)
    checar("publicou com sucesso -> 'publicado'", r, "publicado")
    checar("chamou redes_decidir exatamente 1x", len(chamadas_rpc) == 1, True)
    if chamadas_rpc:
        nome, corpo = chamadas_rpc[0]
        checar("RPC correta", nome, "redes_decidir")
        checar("p_acao=publicado", corpo.get("p_acao"), "publicado")
        checar("p_por=consultor (nunca 'roveda' — distingue publicação automática nos relatórios)", corpo.get("p_por"), "consultor")
        checar("p_url_post repassado", corpo.get("p_url_post"), "https://www.linkedin.com/feed/update/share:123")
finally:
    publicar.estoque.ler = _ler_original
    publicar_linkedin.publicar = _publicar_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_linkedin — controle NEGATIVO: publicou mas redes_decidir recusa "
      "(já decidida por outro caminho) -> 'falhou' (nunca finge sucesso sem registro no banco) ==")
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": None}
publicar_linkedin.publicar = lambda *a, **k: {"ok": True, "url_post": "https://www.linkedin.com/feed/update/share:999", "post_id": "urn:li:share:999"}
publicar.supa.rpc = lambda *a, **k: {"ok": False, "motivo": "ja_decidida"}
try:
    r = publicar.publicar_via_linkedin("innconta", ROW_LINKEDIN)
    checar("redes_decidir recusou -> 'falhou'", r, "falhou")
finally:
    publicar.estoque.ler = _ler_original
    publicar_linkedin.publicar = _publicar_original
    publicar.supa.rpc = _rpc_original

print("\n== rodar() — despacho por canal: canal sem conector (threads) nunca lê estoque nem "
      "tenta publicar, só marca aguardando_api direto (mesma regra vale para qualquer canal fora "
      "de CANAIS_AUTOMATICOS — 'instagram' e 'linkedin_pagina' são os únicos com conector hoje, "
      "23/09/2026, ver redes/testar_publicar_instagram.py para o despacho do Instagram) ==")
_select_original = publicar.supa.select
chamou_estoque = {"sim": False}
chamadas_patch = []
publicar.supa.select = lambda *a, **k: [ROW_OUTRO_CANAL]
publicar.estoque.ler = lambda *a, **k: (chamou_estoque.__setitem__("sim", True) or {"_corpo": "x", "imagem": None})
publicar.supa.patch = lambda tabela, filtro, corpo: (chamadas_patch.append((tabela, filtro, corpo)) or [{}])
try:
    r = publicar.rodar("innconta", modo_qa=True, so_peca_id="qa-adversario-nao-publica-de-verdade")
    checar("threads -> nunca leu estoque", chamou_estoque["sim"], False)
    checar("threads -> marcou aguardando_api via PATCH 1x", len(chamadas_patch) == 1, True)
    checar("threads -> 0 publicadas", r["publicadas"], 0)
    checar("threads -> 1 aguardando_api", r["aguardando_api"], 1)
finally:
    publicar.supa.select = _select_original
    publicar.estoque.ler = _ler_original
    publicar.supa.patch = _patch_original

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (4 cenários de publicar_via_linkedin + 1 de despacho por canal em rodar()).")
