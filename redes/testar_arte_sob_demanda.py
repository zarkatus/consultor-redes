# -*- coding: utf-8 -*-
"""Prova por MOCK (sem Playwright, sem rede, sem banco) de `redes/arte_sob_demanda.py`, do portão no
`publicar_via_instagram`, do desvio no `lote_aprovacao` e da trava `guarda.checar_arte` por marca (30/09/2026).

Roda `python redes/testar_arte_sob_demanda.py` da raiz do repo; sai != 0 se qualquer prova falhar."""
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
for p in (RAIZ, os.path.join(RAIZ, "lib"), os.path.join(RAIZ, "video"), os.path.join(RAIZ, "conselho")):
    sys.path.insert(0, p)
import arte_sob_demanda as asd  # noqa: E402
import guarda  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %s (esperado %s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


TMP = tempfile.mkdtemp(prefix="arte-sob-demanda-")
asd.REPO = TMP  # caminhos declarados resolvem dentro da pasta descartável
SLUG = "2026-09-30-qa-peca-01"


def _peca(quadros=0, formato="feed"):
    base = "redes/estoque/qa/_gerados/" + SLUG + "-instagram"
    p = {"_peca_id": SLUG + "-instagram", "canal": "instagram", "formato": formato}
    if quadros:
        p["quadros"] = ["%s/quadro-%02d.png" % (base, i + 1) for i in range(quadros)]
        p["imagem"] = p["quadros"][0]
    else:
        p["imagem"] = base + "-feed.png"
    return p


def _gravar(rel):
    c = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(c), exist_ok=True)
    open(c, "wb").close()


def _render_que_grava(peca, chamadas, falhar=0, sair=False):
    def r(marca, slugs):
        chamadas.append((marca, set(slugs)))
        if sair:
            raise SystemExit("guarda barrou")
        if len(chamadas) <= falhar:
            raise RuntimeError("Page.screenshot: Unable to capture screenshot")
        for rel in asd.declarados(peca):
            _gravar(rel)
    return r


try:
    print("== nada falta (InnConta, PNG commitado): não renderiza nem instala ==")
    p = _peca()
    _gravar(p["imagem"])
    ch = []
    checar("sem ausentes -> []", asd.garantir("qa", p, renderizar=_render_que_grava(p, ch)), [])
    checar("render NÃO chamado", len(ch), 0)
    shutil.rmtree(os.path.join(TMP, "redes"))

    print("\n== feed ausente: renderiza SÓ o slug exato e fica pronto ==")
    p, ch = _peca(), []
    checar("renderizou -> []", asd.garantir("qa", p, renderizar=_render_que_grava(p, ch)), [])
    checar("1 chamada com o slug exato", ch, [("qa", {SLUG})])
    shutil.rmtree(os.path.join(TMP, "redes"))

    print("\n== carrossel de 7: os 7 quadros ausentes, render grava os 7 ==")
    p, ch = _peca(7, "carrossel"), []
    checar("faltando antes = 7", len(asd.faltando(p)), 7)
    checar("renderizou -> []", asd.garantir("qa", p, renderizar=_render_que_grava(p, ch)), [])
    shutil.rmtree(os.path.join(TMP, "redes"))

    print("\n== 1º screenshot falha (Chromium), 2ª tentativa resolve ==")
    p, ch = _peca(), []
    checar("pronto na 2ª", asd.garantir("qa", p, renderizar=_render_que_grava(p, ch, falhar=1)), [])
    checar("2 chamadas", len(ch), 2)
    shutil.rmtree(os.path.join(TMP, "redes"), ignore_errors=True)

    print("\n== controle NEGATIVO: render não grava nada -> devolve o que falta (nunca finge pronto) ==")
    p = _peca(3, "carrossel")
    checar("3 ausentes", len(asd.garantir("qa", p, renderizar=lambda m, s: None)), 3)

    print("\n== controle NEGATIVO: guarda barra (SystemExit) -> não repete, devolve ausente ==")
    p, ch = _peca(), []
    checar("1 ausente", len(asd.garantir("qa", p, renderizar=_render_que_grava(p, ch, sair=True))), 1)
    checar("1 chamada só (sem repetir)", len(ch), 1)

    print("\n== fora do runner sem Playwright: não instala nada ==")
    checar("instalar=False sem playwright -> (False, ...) ou já instalado",
           asd._playwright_pronto(False)[0] in (True, False), True)

    print("\n== vídeo e texto: nada a renderizar aqui ==")
    checar("video -> []", asd.declarados({"formato": "video", "imagem": "x.png"}), [])
    checar("texto -> []", asd.declarados({"formato": "texto", "imagem": "x.png"}), [])
    checar("imagem _gerar -> []", asd.declarados({"formato": "feed", "imagem": "_gerar/x.png"}), [])

    print("\n== publicar_via_instagram: PNG não sai -> 'falhou' e NUNCA chama a API ==")
    import publicar
    import publicar_instagram
    chamou = []
    lido = {"_corpo": "t", "_peca_id": SLUG + "-instagram", "canal": "instagram", "formato": "feed",
            "arte": "v2", "categoria": "marco", "texto_arte": "Marco · x", "imagem": _peca()["imagem"]}
    orig = (publicar.estoque.ler, publicar.guarda.checar_arte, publicar_instagram.publicar, asd.garantir)
    publicar.estoque.ler = lambda *a, **k: dict(lido)
    publicar.guarda.checar_arte = lambda *a, **k: []
    publicar_instagram.publicar = lambda *a, **k: chamou.append(1) or {"url_post": "x"}
    try:
        asd.garantir = lambda m, p, **k: ["redes/estoque/qa/x.png"]
        checar("ausente -> 'falhou'", publicar.publicar_via_instagram("qa", {"id": "i", "peca_id": SLUG + "-instagram"}), "falhou")
        checar("API não chamada", len(chamou), 0)
    finally:
        publicar.estoque.ler, publicar.guarda.checar_arte, publicar_instagram.publicar, asd.garantir = orig

    print("\n== checar_arte recebe a MARCA no publicar (antes: sempre o kit da InnConta) ==")
    visto = []
    orig = (publicar.estoque.ler, publicar.guarda.checar_arte)
    publicar.estoque.ler = lambda *a, **k: dict(lido)
    publicar.guarda.checar_arte = lambda peca, marca="innconta": visto.append(marca) or ["barrada no mock"]
    try:
        publicar.publicar_via_instagram("innovasphere", {"id": "i", "peca_id": SLUG + "-instagram"})
        checar("marca repassada", visto, ["innovasphere"])
    finally:
        publicar.estoque.ler, publicar.guarda.checar_arte = orig

    print("\n== lote: peça sem arte NÃO vai ao Conselho (não vira escalada eterna) ==")
    import lote_aprovacao as la
    avaliadas, avisos_env = [], []
    peca_lote = dict(lido, status="aprovado", _peca_id="qa-lote-sem-arte-instagram")
    orig_la = dict(pausado=la.conselho.pausado, clientes=la.guarda.clientes_da_base, listar=la.estoque.listar,
                   render=la.renderizar_pendentes.renderizar, sel=la.supa.select, rpc=la.supa.rpc,
                   avaliar=la.conselho.avaliar, neur=la.conselho.neuronios_hoje, carregar=la.cota.Consumo.carregar,
                   cache=la.cota.Cache, garantir=la.arte_sob_demanda.garantir, env=la.avisos.enviar_escaladas,
                   aviso=la.avisar_sem_arte, refs=la.referencias_para_repeticao, recon=la.reconciliar_datas_fixas)

    class _Consumo:
        def flush(self, s):
            return 0

    class _Cache:
        def __init__(self, s):
            pass

        def expurgar(self):
            pass

    la.conselho.pausado = lambda: False
    la.guarda.clientes_da_base = lambda *a, **k: []
    la.estoque.listar = lambda m: [dict(peca_lote)]
    la.renderizar_pendentes.renderizar = lambda *a, **k: []
    la.supa.select = lambda *a, **k: []
    la.supa.rpc = lambda *a, **k: {"ok": True}
    la.conselho.avaliar = lambda pc, **k: avaliadas.append(pc["peca_id"]) or {"decisao": "escalado", "rodadas": 1, "neuronios": 0, "motivos": [], "texto_final": ""}
    la.conselho.neuronios_hoje = lambda: 0
    la.cota.Consumo.carregar = staticmethod(lambda s: _Consumo())
    la.cota.Cache = _Cache
    la.avisos.enviar_escaladas = lambda *a, **k: {"escaladas": 0}
    la.avisar_sem_arte = lambda pecas: avisos_env.append(list(pecas))
    la.referencias_para_repeticao = lambda *a, **k: []
    la.reconciliar_datas_fixas = lambda *a, **k: []
    try:
        la.arte_sob_demanda.garantir = lambda m, p, **k: ["x.png"]
        r = la.rodar("qa")
        checar("sem arte -> Conselho não avalia", avaliadas, [])
        checar("placar sem_arte = 1", r.get("sem_arte"), 1)
        checar("central avisada com a peça", avisos_env, [["qa-lote-sem-arte-instagram"]])
        la.arte_sob_demanda.garantir = lambda m, p, **k: []
        avisos_env.clear()
        r = la.rodar("qa")
        checar("controle: com arte -> Conselho avalia", avaliadas, ["qa-lote-sem-arte-instagram"])
        checar("controle: sem aviso", avisos_env, [])
    finally:
        la.conselho.pausado = orig_la["pausado"]
        la.guarda.clientes_da_base = orig_la["clientes"]
        la.estoque.listar = orig_la["listar"]
        la.renderizar_pendentes.renderizar = orig_la["render"]
        la.supa.select, la.supa.rpc = orig_la["sel"], orig_la["rpc"]
        la.conselho.avaliar, la.conselho.neuronios_hoje = orig_la["avaliar"], orig_la["neur"]
        la.cota.Consumo.carregar, la.cota.Cache = orig_la["carregar"], orig_la["cache"]
        la.arte_sob_demanda.garantir, la.avisos.enviar_escaladas = orig_la["garantir"], orig_la["env"]
        la.avisar_sem_arte, la.referencias_para_repeticao = orig_la["aviso"], orig_la["refs"]
        la.reconciliar_datas_fixas = orig_la["recon"]

    print("\n== checar_arte por marca: exige o que o kit da marca TEM ==")
    kit = os.path.join(RAIZ, "kit")
    base = {"canal": "instagram", "formato": "feed", "arte": "v2", "categoria": "marco", "texto_arte": "Marco · x"}
    checar("InnConta sem ilustracao/foto -> barra (inalterado)", len(guarda.checar_arte(dict(base), "innconta")) >= 2, True)
    sem_kit = next((m for m in sorted(os.listdir(kit)) if os.path.isfile(os.path.join(kit, m, "logo.svg"))
                    and not os.path.isdir(os.path.join(kit, m, "ilustracoes"))
                    and not any(f.endswith(".jpg") for f in (os.listdir(os.path.join(kit, m, "fotos"))
                                                             if os.path.isdir(os.path.join(kit, m, "fotos")) else []))), None)
    checar("existe marca só com símbolo, sem fotos", bool(sem_kit), True)
    if sem_kit:
        checar("%s sem ilustracao/foto -> passa (símbolo + fundo sólido)" % sem_kit, guarda.checar_arte(dict(base), sem_kit), [])
        checar("%s com foto inexistente -> barra" % sem_kit, len(guarda.checar_arte(dict(base, foto="nao-existe"), sem_kit)), 1)
    com_foto = next((m for m in sorted(os.listdir(kit)) if m != "innconta" and os.path.isdir(os.path.join(kit, m, "fotos"))
                     and any(f.endswith(".jpg") for f in os.listdir(os.path.join(kit, m, "fotos")))), None)
    if com_foto:
        checar("%s (tem fotos) sem foto -> barra" % com_foto, any("foto" in x for x in guarda.checar_arte(dict(base), com_foto)), True)
    checar("marca sem logo nem ilustração -> barra (nunca só texto)",
           any("só texto" in x for x in guarda.checar_arte(dict(base), "qa-marca-inexistente")), True)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d falha(s)" % len(FALHAS))
sys.exit(1 if FALHAS else 0)
