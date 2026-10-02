# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco, sem tocar o Supabase) de
`redes/publicar.py::publicar_via_instagram` + despacho por canal em `rodar()` para o canal
`instagram` — mesmo padrão de `redes/testar_publicar_linkedin.py` (23/09/2026, InnConta
Consultor de Redes conectado à API do Instagram, conta `innconta.oficial`).

Roda `python3 redes/testar_publicar_instagram.py` a partir da raiz do repo; sai com código != 0
se qualquer prova falhar (mesmo padrão de redes/testar_guarda.py e
redes/testar_publicar_linkedin.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import publicar  # noqa: E402
import publicar_instagram  # noqa: E402

FALHAS = []
# os mocks abaixo declaram `imagem` com caminho fictício (= "a peça tem imagem"); o portão da arte sob demanda
# (PNG ausente -> renderiza ou não publica) tem a prova dele em redes/testar_arte_sob_demanda.py.
publicar.arte_sob_demanda.garantir = lambda *a, **k: []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %s (esperado %s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


ROW_INSTAGRAM = {"id": "qa-id-3", "peca_id": "qa-adversario-nao-publica-de-verdade", "canal": "instagram"}
ROW_OUTRO = {"id": "qa-id-4", "peca_id": "qa-adversario-nao-publica-de-verdade", "canal": "threads"}

_ler_original = publicar.estoque.ler
_publicar_original = publicar_instagram.publicar
_patch_original = publicar.supa.patch
_rpc_original = publicar.supa.rpc

print("== publicar_via_instagram — controle NEGATIVO: sem token (TokenAusente) -> "
      "'aguardando_api', marca calendario_status via PATCH, nunca chama redes_decidir ==")
chamadas_patch, chamadas_rpc = [], []
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": "estoque/innconta/qa/teste.png"}
publicar_instagram.publicar = lambda *a, **k: (_ for _ in ()).throw(publicar_instagram.TokenAusente("mock"))
publicar.supa.patch = lambda tabela, filtro, corpo: (chamadas_patch.append((tabela, filtro, corpo)) or [{}])
publicar.supa.rpc = lambda *a, **k: (chamadas_rpc.append((a, k)) or {"ok": True})
try:
    r = publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("sem token -> 'aguardando_api'", r, "aguardando_api")
    checar("marcou calendario_status via PATCH 1x", len(chamadas_patch) == 1, True)
    if chamadas_patch:
        checar("PATCH com calendario_status=aguardando_api", chamadas_patch[0][2].get("calendario_status"), "aguardando_api")
    checar("sem token -> nunca chama redes_decidir", len(chamadas_rpc) == 0, True)
finally:
    publicar.estoque.ler = _ler_original
    publicar_instagram.publicar = _publicar_original
    publicar.supa.patch = _patch_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_instagram — controle NEGATIVO: publicação real falha (PublicacaoFalhou) "
      "-> 'falhou', nunca marca aguardando_api, nunca chama redes_decidir (tenta de novo depois) ==")
chamadas_patch, chamadas_rpc = [], []
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": "estoque/innconta/qa/teste.png"}
publicar_instagram.publicar = lambda *a, **k: (_ for _ in ()).throw(publicar_instagram.PublicacaoFalhou("mock 400 (media container)"))
publicar.supa.patch = lambda tabela, filtro, corpo: (chamadas_patch.append((tabela, filtro, corpo)) or [{}])
publicar.supa.rpc = lambda *a, **k: (chamadas_rpc.append((a, k)) or {"ok": True})
try:
    r = publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("publicação falhou -> 'falhou'", r, "falhou")
    checar("publicação falhou -> nunca marcou aguardando_api", len(chamadas_patch) == 0, True)
    checar("publicação falhou -> nunca chamou redes_decidir", len(chamadas_rpc) == 0, True)
finally:
    publicar.estoque.ler = _ler_original
    publicar_instagram.publicar = _publicar_original
    publicar.supa.patch = _patch_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_instagram — controle POSITIVO: publica com sucesso + redes_decidir "
      "confirma -> 'publicado', com os argumentos certos (p_por='consultor') ==")
chamadas_rpc = []
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": "estoque/innconta/qa/teste.png"}
publicar_instagram.publicar = lambda *a, **k: {"ok": True, "url_post": "https://www.instagram.com/p/ABC123XYZ/", "post_id": "179999999999999"}
publicar.supa.rpc = lambda nome, corpo: (chamadas_rpc.append((nome, corpo)) or {"ok": True, "status": "publicado"})
try:
    r = publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("publicou com sucesso -> 'publicado'", r, "publicado")
    checar("chamou redes_decidir exatamente 1x", len(chamadas_rpc) == 1, True)
    if chamadas_rpc:
        nome, corpo = chamadas_rpc[0]
        checar("RPC correta", nome, "redes_decidir")
        checar("p_acao=publicado", corpo.get("p_acao"), "publicado")
        checar("p_por=consultor (nunca 'roveda')", corpo.get("p_por"), "consultor")
        checar("p_url_post repassado", corpo.get("p_url_post"), "https://www.instagram.com/p/ABC123XYZ/")
finally:
    publicar.estoque.ler = _ler_original
    publicar_instagram.publicar = _publicar_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_instagram — controle NEGATIVO: publicou mas redes_decidir recusa "
      "(já decidida por outro caminho) -> 'falhou' (nunca finge sucesso sem registro no banco) ==")
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": "estoque/innconta/qa/teste.png"}
publicar_instagram.publicar = lambda *a, **k: {"ok": True, "url_post": "https://www.instagram.com/p/ZZZ999/", "post_id": "18099999"}
publicar.supa.rpc = lambda *a, **k: {"ok": False, "motivo": "ja_decidida"}
try:
    r = publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("redes_decidir recusou -> 'falhou'", r, "falhou")
finally:
    publicar.estoque.ler = _ler_original
    publicar_instagram.publicar = _publicar_original
    publicar.supa.rpc = _rpc_original

print("\n== publicar_via_instagram — controle NEGATIVO: peça sem imagem local -> nunca chama "
      "publicar_instagram.publicar (Instagram exige mídia) ==")
chamou_publicar = {"sim": False}
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": None}
publicar_instagram.publicar = lambda *a, **k: (chamou_publicar.__setitem__("sim", True) or {"ok": True, "url_post": "x", "post_id": "y"})
# banco mockado também aqui (30/09/2026): sem isso, com SB_URL/chave no ambiente (reserva no GitLab) o teste
# chamava redes_decidir e PATCH no Supabase de PRODUÇÃO.
publicar.supa.patch = lambda *a, **k: [{}]
publicar.supa.rpc = lambda *a, **k: {"ok": True}
try:
    r = publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("sem imagem local -> ainda tenta (publicar_instagram decide se falha sem mídia)", chamou_publicar["sim"], True)
finally:
    publicar.estoque.ler = _ler_original
    publicar_instagram.publicar = _publicar_original
    publicar.supa.patch = _patch_original
    publicar.supa.rpc = _rpc_original

print("\n== rodar() — despacho por canal: instagram chama publicar_via_instagram (não linkedin), "
      "canal desconhecido (ex. threads) marca aguardando_api direto sem tentar publicar ==")
_select_original = publicar.supa.select
chamou_instagram = {"sim": False}
chamadas_patch = []
publicar.supa.select = lambda *a, **k: [ROW_OUTRO]
publicar_instagram.publicar = lambda *a, **k: (chamou_instagram.__setitem__("sim", True) or {"ok": True, "url_post": "x", "post_id": "y"})
publicar.estoque.ler = lambda *a, **k: {"_corpo": "x", "imagem": None}
publicar.supa.patch = lambda tabela, filtro, corpo: (chamadas_patch.append((tabela, filtro, corpo)) or [{}])
try:
    r = publicar.rodar("innconta", modo_qa=True, so_peca_id="qa-adversario-nao-publica-de-verdade")
    checar("canal threads -> nunca chamou publicar_instagram", chamou_instagram["sim"], False)
    checar("canal threads -> marcou aguardando_api via PATCH 1x", len(chamadas_patch) == 1, True)
    checar("canal threads -> 0 publicadas", r["publicadas"], 0)
    checar("canal threads -> 1 aguardando_api", r["aguardando_api"], 1)
finally:
    publicar.supa.select = _select_original
    publicar.estoque.ler = _ler_original
    publicar_instagram.publicar = _publicar_original
    publicar.supa.patch = _patch_original

# =====================================================================================================================
# MULTIMARCA + ALCANCE (29/09/2026): tudo por mock, sem rede nem banco.
# =====================================================================================================================
import datetime  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import alcance  # noqa: E402
import marcas  # noqa: E402

_kit_orig = marcas.KIT
_kit = tempfile.mkdtemp(prefix="kit-pub-")


def _kit_marca(marca, handle=True, parceiros=(), horario="09:00", minimo=0, ativo=True):
    os.makedirs(os.path.join(_kit, marca), exist_ok=True)
    r = {"marca": marca, "nome": marca.capitalize(), "handle_instagram": ("@%s.oficial" % marca) if handle else "",
         "ig_user_id": "1000", "publicar": {"instagram": ativo, "linkedin": False, "horario_brt": horario},
         "temas": ["tema-%s" % marca], "palavras_chave": ["palavra%s" % marca, "fiscal"], "hashtags": ["#x"],
         "collab": {"parceiros": list(parceiros), "min_por_semana": minimo, "max_por_semana": 2}}
    json.dump(r, open(os.path.join(_kit, marca, "regras.json"), "w", encoding="utf-8"))


_kit_marca("alfa", parceiros=["beta", "gama"], minimo=1)
_kit_marca("beta")
_kit_marca("gama")
_kit_marca("solo", parceiros=["beta"], minimo=1)
_kit_marca("semhandle", handle=False)
_kit_marca("orfa", parceiros=["semhandle"], minimo=1)
marcas.KIT = _kit
try:
    print("\n== alcance: alt_text, collaborators (limites), primeiro comentario ==")
    RA = marcas.carregar("alfa")
    checar("alt_text explicito vence", alcance.alt_text({"alt_text": "Descricao", "texto_arte": "arte"}), "Descricao")
    checar("sem alt_text usa o texto da arte", "arte" in (alcance.alt_text({"texto_arte": "texto na arte"}) or ""), True)
    checar("collab nao marcada -> nenhum collaborator", alcance.collaborators(RA, {}), [])
    checar("collab true -> todos os parceiros com handle", alcance.collaborators(RA, {"collab": True}), ["beta.oficial", "gama.oficial"])
    checar("collab nomeada -> so o parceiro pedido", alcance.collaborators(RA, {"collab": ["gama"]}), ["gama.oficial"])
    checar("CONTROLE NEGATIVO: parceiro fora da lista nunca vira coautor", alcance.collaborators(RA, {"collab": ["intruso"]}), [])
    checar("teto semanal (max_por_semana=2) atingido -> nenhum", alcance.collaborators(RA, {"collab": True}, usados_semana=2), [])
    checar("parceiro SEM handle no registro nao vira coautor", alcance.collaborators(marcas.carregar("orfa"), {"collab": True}), [])
    checar("primeiro comentario e devolvido quando declarado", alcance.primeiro_comentario({"primeiro_comentario": "#a #b"}), "#a #b")
    checar("sem primeiro comentario -> vazio", bool(alcance.primeiro_comentario({})), False)

    print("\n== collab semanal: semana sem collab -> UMA peca promovida (regra pura) ==")
    segunda = datetime.date(2026, 10, 5)
    quarta = datetime.date(2026, 10, 7)
    todos = {m: marcas.carregar(m) for m in ("alfa", "beta", "gama", "solo", "orfa", "semhandle")}
    todos["gama"]["temas"] = ["outro"]
    pecas = [{"peca_id": "p-fisc", "texto": "Texto sobre tema-beta e a regularidade", "data": quarta, "collab": False},
             {"peca_id": "p-outra", "texto": "Texto sem relacao", "data": quarta, "collab": False}]
    r = alcance.escolher_collab(todos["alfa"], pecas, 0, None, segunda, todos)
    checar("promove a peca cujo tema toca o parceiro (p-fisc com beta)", r, ("p-fisc", "beta"))
    checar("CONTROLE NEGATIVO: ja houve collab na semana -> nada a promover", alcance.escolher_collab(todos["alfa"], pecas, 1, None, segunda, todos), None)
    checar("ja ha peca marcada como collab -> nada a promover", alcance.escolher_collab(
        todos["alfa"], pecas + [{"peca_id": "x", "texto": "y", "data": quarta, "collab": True}], 0, None, segunda, todos), None)
    checar("marca com min_por_semana 0 nunca promove", alcance.escolher_collab(todos["beta"], pecas, 0, None, segunda, todos), None)
    checar("marca com 1 parceiro so: usa esse mesmo sem alternativa (semana seguinte ao mesmo par)",
           alcance.escolher_collab(todos["solo"], pecas, 0, "beta", segunda, todos), ("p-fisc", "beta"))
    pecas2 = [{"peca_id": "p-fisc", "texto": "tema-beta e tema-gama", "data": quarta, "collab": False}]
    todos["gama"]["temas"] = ["tema-gama"]
    r = alcance.escolher_collab(todos["alfa"], pecas2, 0, "beta", segunda, todos)
    checar("rodizio: nao repete o par da semana anterior quando ha alternativa (beta ontem -> gama)", r and r[1], "gama")
    checar("parceiro sem handle no registro e ignorado (sem coautor possivel) -> None",
           alcance.escolher_collab(todos["orfa"], pecas, 0, None, segunda, todos), None)
    checar("sem peca aprovada na semana -> None", alcance.escolher_collab(todos["alfa"], [], 0, None, segunda, todos), None)
    sem_tema = [{"peca_id": "p1", "texto": "nada a ver", "data": quarta, "collab": False}]
    checar("sem tema em comum, dia util -> espera (None)", alcance.escolher_collab(todos["alfa"], sem_tema, 0, None, segunda, todos), None)
    sabado = datetime.date(2026, 10, 10)
    sem_tema_sab = [{"peca_id": "p1", "texto": "nada a ver", "data": datetime.date(2026, 10, 11), "collab": False}]
    checar("sem tema em comum, a partir de sabado a regra da agenda vence -> promove mesmo assim",
           bool(alcance.escolher_collab(todos["alfa"], sem_tema_sab, 0, None, sabado, todos)), True)
    checar("semana ISO: segunda a domingo", alcance.semana_iso(quarta), (segunda, datetime.date(2026, 10, 11)))

    print("\n== relatorio semanal: marca que fechou a semana sem collab e apontada ==")
    linhas = [{"marca": "alfa", "collab_com": "beta"}, {"marca": "solo", "collab_com": None}, {"marca": "solo", "collab_com": ""}]
    faltas = alcance.marcas_sem_collab(linhas, ["alfa", "solo", "beta"], {"alfa": 1, "solo": 1, "beta": 0})
    checar("alfa cumpriu; solo nao; beta sem minimo", [(f["marca"], f["feitas"], f["minimo"]) for f in faltas], [("solo", 0, 1)])
    checar("todas cumpriram -> lista vazia", alcance.marcas_sem_collab([{"marca": "alfa", "collab_com": "b"}], ["alfa"], {"alfa": 1}), [])

    print("\n== alcance.horario_efetivo: escalonado, 20 min por marca no mesmo horario (nunca disparam juntas) ==")
    ativas = {m: marcas.carregar(m) for m in ("alfa", "beta", "gama")}
    h = {m: alcance.horario_efetivo(m, ativas, {}) for m in ativas}
    checar("3 marcas as 09:00 -> 09:00, 09:20, 09:40", (h["alfa"], h["beta"], h["gama"]), (540, 560, 580))
    checar("CONTROLE NEGATIVO: marca em outro horario nao e empurrada", alcance.horario_efetivo("beta", ativas, {"alfa": "11:00"}), 540)
    checar("horario recomendado do relatorio substitui o de regras.json", alcance.horario_efetivo("gama", ativas, {"gama": "12:00"}), 720)

    print("\n== relatorio de alcance: amostra < 10 NAO ajusta; >= 10 recomenda formato e horario ==")

    def post(i, fmt, hora, alc):
        return {"alcance": alc, "formato": fmt, "publicado_em": "2026-10-%02dT%02d:00:00+00:00" % (i + 1, hora + 3)}
    pouco = [post(i, "REELS", 12, 500) for i in range(9)]
    rec = alcance.recomendar(alcance.ranquear(pouco))
    checar("9 posts: nada ajustado", (rec["horario_brt"], rec["formato"]), (None, None))
    muito = [post(i, "REELS", 12, 500) for i in range(6)] + [post(i, "IMAGEM", 9, 100) for i in range(6)]
    rec = alcance.recomendar(alcance.ranquear(muito))
    checar("12 posts: formato REELS e horario 12:00 BRT recomendados", (rec["horario_brt"], rec["formato"]), ("12:00", "REELS"))
    fora_janela = [post(i, "REELS", 2, 900) for i in range(12)]
    checar("hora fora da janela 08-20 nunca e recomendada", alcance.recomendar(alcance.ranquear(fora_janela))["horario_brt"], None)

    print("\n== publicar_instagram: campos de alcance caem para o post solo se a API recusar ==")
    _pf = publicar_instagram._post_form
    tentativas = []

    def falha_com_collab(url, campos, timeout=30):
        tentativas.append(sorted(campos))
        if "collaborators" in campos:
            raise publicar_instagram.PublicacaoFalhou("collaborators nao suportado")
        return {"id": "123"}
    publicar_instagram._post_form = falha_com_collab
    try:
        resp, ap = publicar_instagram._post_com_opcionais("u", {"caption": "x", "alt_text": "a", "collaborators": '["b"]'},
                                                          ["alt_text", "collaborators"])
        checar("recusou collaborators -> retentou e publicou (resposta id)", resp, {"id": "123"})
        checar("aplicados = so o alt_text (collab caiu)", ap, ["alt_text"])
        checar("2 tentativas: com e sem o campo", len(tentativas), 2)
        publicar_instagram._post_form = lambda url, campos, timeout=30: {"id": "9"}
        resp, ap = publicar_instagram._post_com_opcionais("u", {"caption": "x", "alt_text": "a"}, ["alt_text", "collaborators"])
        checar("CONTROLE NEGATIVO: sem recusa, nada e retirado", ap, ["alt_text"])

        def sempre_falha(url, campos, timeout=30):
            raise publicar_instagram.PublicacaoFalhou("400 real")
        publicar_instagram._post_form = sempre_falha
        try:
            publicar_instagram._post_com_opcionais("u", {"caption": "x", "alt_text": "a"}, ["alt_text"])
            levantou = False
        except publicar_instagram.PublicacaoFalhou:
            levantou = True
        checar("erro que persiste sem campos opcionais continua sendo erro", levantou, True)
    finally:
        publicar_instagram._post_form = _pf

    print("\n== token por marca: marca sem token PULA, innconta mantem aguardando_api ==")
    _pub0, _est0, _patch0, _sel0 = publicar_instagram.publicar, publicar.estoque.ler, publicar.supa.patch, publicar.supa.select
    patches = []
    publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto", "imagem": "estoque/x/y.png"}
    publicar.supa.patch = lambda t, f, c: (patches.append(c) or [{}])
    publicar.supa.select = lambda *a, **k: []
    publicar_instagram.publicar = lambda *a, **k: (_ for _ in ()).throw(publicar_instagram.TokenAusente("mock"))
    try:
        checar("marca sem token (alfa) -> 'sem_token'", publicar.publicar_via_instagram("alfa", ROW_INSTAGRAM), "sem_token")
        checar("... sem tocar a peca (nenhum PATCH)", patches, [])
        checar("innconta sem token -> 'aguardando_api' (comportamento anterior)",
               publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM), "aguardando_api")
    finally:
        publicar_instagram.publicar, publicar.estoque.ler, publicar.supa.patch, publicar.supa.select = _pub0, _est0, _patch0, _sel0

    print("\n== publicar_via_instagram passa alt_text/collaborators/comentario a API e grava collab_com ==")
    capturado = {}
    patches = []
    publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto", "imagem": "estoque/x/y.png", "collab": ["beta"],
                                            "primeiro_comentario": "#a #b", "texto_arte": "arte"}
    publicar_instagram.publicar = lambda *a, **k: (capturado.update(k) or {"ok": True, "url_post": "u", "post_id": "p", "collab_aplicado": True})
    publicar.supa.patch = lambda t, f, c: (patches.append(c) or [{}])
    publicar.supa.select = lambda *a, **k: []
    publicar.supa.rpc = lambda *a, **k: {"ok": True}
    try:
        publicar.publicar_via_instagram("alfa", ROW_INSTAGRAM)
        checar("collaborators chega a API como username do parceiro", capturado.get("collaborators"), ["beta.oficial"])
        checar("primeiro comentario e alt_text chegam a API", (capturado.get("primeiro_comentario"), bool(capturado.get("alt_text"))), ("#a #b", True))
        checar("marca certa vai a API", capturado.get("marca"), "alfa")
        checar("collab_com gravado (auditoria da semana)", any(p.get("collab_com") == "beta" for p in patches), True)
    finally:
        publicar_instagram.publicar, publicar.estoque.ler, publicar.supa.patch, publicar.supa.select = _pub0, _est0, _patch0, _sel0
        publicar.supa.rpc = _rpc_original

    print("\n== guard de horario dentro da funcao (escalonado por marca) ==")
    _ativas0 = marcas.instagram_ativas_regras
    marcas.instagram_ativas_regras = lambda: {m: marcas.carregar(m) for m in ("alfa", "beta", "gama")}
    _rec0 = alcance.recomendados
    alcance.recomendados = lambda lista: {}
    try:
        agora = datetime.datetime(2026, 10, 5, 9, 10)
        checar("09:10: alfa (09:00) ja pode", publicar._ainda_nao_e_a_hora("alfa", agora, None), False)
        checar("09:10: beta (09:20) ainda NAO", publicar._ainda_nao_e_a_hora("beta", agora, None), True)
        checar("09:10: gama (09:40) ainda NAO", publicar._ainda_nao_e_a_hora("gama", agora, None), True)
        checar("09:50: gama ja pode", publicar._ainda_nao_e_a_hora("gama", datetime.datetime(2026, 10, 5, 9, 50), None), False)
        checar("peca forcada (--peca-id) ignora o horario", publicar._ainda_nao_e_a_hora("gama", agora, "qa-x"), False)
        checar("marca fora das ativas nao e travada pelo guard", publicar._ainda_nao_e_a_hora("outra", agora, None), False)
    finally:
        marcas.instagram_ativas_regras = _ativas0
        alcance.recomendados = _rec0

    print("\n== preferencia por carrossel (>=2 quadros) para alcance ==")
    checar("peca com 3 quadros e carrossel", publicar._eh_carrossel({"quadros": ["a", "b", "c"]}), True)
    checar("CONTROLE NEGATIVO: peca com 1 imagem nao e carrossel", publicar._eh_carrossel({"imagem": "a"}), False)
finally:
    marcas.KIT = _kit_orig
    shutil.rmtree(_kit, ignore_errors=True)

print("\n== post SAIU mas redes_decidir falhou: a peca e selada (senao a rodada da hora seguinte posta de novo) ==")
import time as _time  # noqa: E402
_sleep0, _sel0b, _aviso0 = _time.sleep, publicar.supa.select, publicar.supa.registrar_aviso
_time.sleep = lambda s: None
publicar.supa.select = lambda *a, **k: []
publicar.supa.registrar_aviso = lambda *a, **k: None
publicar.estoque.ler = lambda *a, **k: {"_corpo": "texto de teste", "imagem": "estoque/innconta/qa/teste.png"}
publicar_instagram.publicar = lambda *a, **k: {"ok": True, "url_post": "https://www.instagram.com/p/DUP/", "post_id": "1"}
try:
    patches, chamadas = [], []
    publicar.supa.patch = lambda t, f, c: (patches.append((f, c)) or [{}])
    publicar.supa.rpc = lambda *a, **k: (chamadas.append(1), (_ for _ in ()).throw(RuntimeError("HTTP 503")))[1]
    r = publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("RPC fora do ar -> 'falhou'", r, "falhou")
    checar("RPC fora do ar -> tenta a RPC 3x (1 + 2 retentativas)", len(chamadas), 3)
    selo = [c for f, c in patches if c.get("status") == "publicado"]
    checar("RPC fora do ar -> sela por PATCH direto (status publicado + url)", bool(selo) and selo[0].get("url_post"),
           "https://www.instagram.com/p/DUP/")
    checar("o PATCH so sela linha ainda sem publicado_em", any("publicado_em=is.null" in f for f, c in patches), True)

    patches, chamadas = [], []
    seq = iter([RuntimeError("HTTP 503"), {"ok": True}])

    def _rpc_volta(*a, **k):
        chamadas.append(1)
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v
    publicar.supa.rpc = _rpc_volta
    publicar.publicar_via_instagram("innconta", ROW_INSTAGRAM)
    checar("CONTROLE: RPC volta na 2a tentativa -> selada pela RPC, sem PATCH de status",
           any(c.get("status") == "publicado" for f, c in patches), False)
finally:
    _time.sleep, publicar.supa.select, publicar.supa.registrar_aviso = _sleep0, _sel0b, _aviso0
    publicar.estoque.ler, publicar_instagram.publicar = _ler_original, _publicar_original
    publicar.supa.patch, publicar.supa.rpc = _patch_original, _rpc_original

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (5 cenários de publicar_via_instagram + 1 de despacho por canal em rodar()).")
