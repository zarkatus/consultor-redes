# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem Supabase, sem Graph API) do fluxo de CARROSSEL de
`redes/publicar_instagram.py` (24/09/2026, PLAYBOOK §7-V-11 — a peça da PGFN é um carrossel de 6
quadros e o publicador só sabia imagem única e Reels).

Cobre: sucesso (N filhos com is_carousel_item, pai CAROUSEL com children na ORDEM e caption, polling
de cada filho e do pai, media_publish só do pai e só depois do FINISHED, quadros apagados do bucket
depois de publicar); filho que fica IN_PROGRESS e depois FINISHED; filho ERROR (falha limpa, pai
nunca criado, nada publicado, bucket limpo); pai ERROR; mais de 10 e menos de 2 itens (falha ANTES
de subir qualquer arquivo); retry de 9007/2207027 no media_publish do pai; criar_container (ENSAIO)
nunca chama media_publish e devolve `residuos` para o ensaio apagar; despacho de `publicar.py`
(formato carrossel + quadros -> caminhos_carrossel; quadro ausente no disco -> falhou, sem publicar).

Roda `python3 redes/testar_publicar_instagram_carrossel.py` da raiz do repo; != 0 se algo falhar."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "video"))
os.environ["IG_USER_ID"] = "qa-ig-user-id"
import publicar_instagram as pi  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %r (esperado %r)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


_orig = {k: getattr(pi, k) for k in ("_token", "_subir_midia_supabase", "remover_midia_supabase", "_post_form", "_get")}
_sleep_original = pi.time.sleep


def _restaurar():
    for k, v in _orig.items():
        setattr(pi, k, v)
    pi.time.sleep = _sleep_original


def _mockar(status_por_id, publish_respostas=None):
    """status_por_id: {creation_id: [status1, status2, ...]} consumido em ordem por GET status_code
    (estoura StopIteration se o código pedir mais do que o esperado). Cada POST /media com
    is_carousel_item gera id 'item-N'; o pai gera 'pai-1'."""
    est = {"posts": [], "gets": [], "uploads": [], "removidos": [], "sleep": 0, "n_item": 0}
    seqs = {k: iter(v) for k, v in status_por_id.items()}
    pub = iter(publish_respostas or [{"id": "media-id-789"}])
    pi._token = lambda *a, **k: "token-de-teste"

    def _upload(caminho, nome, pasta="instagram"):
        est["uploads"].append(nome)
        return ("https://x.supabase.co/storage/v1/object/public/redes-publico/%s/%s" % (pasta, nome), pasta + "/" + nome)
    pi._subir_midia_supabase = _upload
    pi.remover_midia_supabase = lambda remoto: est["removidos"].append(remoto) or True

    def _post(url, campos, timeout=30):
        est["posts"].append((url, dict(campos)))
        if url.endswith("/media_publish"):
            r = next(pub)
            if isinstance(r, Exception):
                raise r
            return r
        if campos.get("media_type") == "CAROUSEL":
            return {"id": "pai-1"}
        est["n_item"] += 1
        return {"id": "item-%d" % est["n_item"]}
    pi._post_form = _post

    def _get(url, timeout=30):
        est["gets"].append(url)
        if "status_code" in url:
            cid = url.split("/v21.0/")[1].split("?")[0]
            return {"status_code": next(seqs[cid])}
        if "permalink" in url:
            return {"permalink": "https://www.instagram.com/p/CARROSSEL1/"}
        raise AssertionError("GET inesperado: " + url)
    pi._get = _get
    pi.time.sleep = lambda s: est.__setitem__("sleep", est["sleep"] + 1)
    return est


def _quadros(n):
    return ["/tmp/q/quadro-%02d.png" % i for i in range(1, n + 1)]


def _publish_calls(est):
    return [c for c in est["posts"] if c[0].endswith("/media_publish")]


print("== SUCESSO: 6 quadros -> 6 filhos (is_carousel_item), pai CAROUSEL (children na ordem + caption), "
      "polling de todos, media_publish só do pai, quadros apagados do bucket depois ==")
seq = {"item-%d" % i: ["FINISHED"] for i in range(1, 7)}
seq["pai-1"] = ["FINISHED"]
est = _mockar(seq)
try:
    r = pi.publicar("legenda PGFN", caminhos_carrossel=_quadros(6), nome_arquivo="peca-x")
    checar("ok", r["ok"], True)
    checar("post_id do media_publish", r["post_id"], "media-id-789")
    checar("url_post = permalink real", r["url_post"], "https://www.instagram.com/p/CARROSSEL1/")
    filhos = [c for c in est["posts"] if c[1].get("is_carousel_item") == "true"]
    checar("6 filhos criados", len(filhos), 6)
    checar("filho leva image_url e NÃO leva caption", all("image_url" in c[1] and "caption" not in c[1] for c in filhos), True)
    pais = [c for c in est["posts"] if c[1].get("media_type") == "CAROUSEL"]
    checar("1 pai", len(pais), 1)
    checar("children na ordem dos quadros", pais[0][1]["children"], ",".join("item-%d" % i for i in range(1, 7)))
    checar("caption vai no pai", pais[0][1]["caption"], "legenda PGFN")
    checar("media_publish 1x, com creation_id do PAI", [c[1]["creation_id"] for c in _publish_calls(est)], ["pai-1"])
    checar("uploads com prefixo da peça, ordenados", est["uploads"][0], "peca-x-01-quadro-01.png")
    checar("6 quadros apagados do bucket depois de publicar", len(est["removidos"]), 6)
    ordem = [("pub" if c[0].endswith("/media_publish") else "media") for c in est["posts"]]
    checar("media_publish é o ÚLTIMO POST", ordem[-1], "pub")
finally:
    _restaurar()

print("\n== filho IN_PROGRESS 2x e depois FINISHED: polling espera, publica ==")
seq = {"item-%d" % i: ["FINISHED"] for i in range(1, 4)}
seq["item-2"] = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
seq["pai-1"] = ["IN_PROGRESS", "FINISHED"]
est = _mockar(seq)
try:
    r = pi.publicar("legenda", caminhos_carrossel=_quadros(3), nome_arquivo="p")
    checar("publicou", r["ok"], True)
    checar("dormiu 3x (2 no filho + 1 no pai)", est["sleep"], 3)
    checar("media_publish 1x", len(_publish_calls(est)), 1)
finally:
    _restaurar()

print("\n== NEGATIVO: filho 3 termina ERROR -> PublicacaoFalhou nomeando o quadro, pai NUNCA criado, "
      "NADA publicado, bucket limpo ==")
seq = {"item-1": ["FINISHED"], "item-2": ["FINISHED"], "item-3": ["ERROR"], "item-4": ["FINISHED"]}
est = _mockar(seq)
try:
    msg = None
    try:
        pi.publicar("legenda", caminhos_carrossel=_quadros(4), nome_arquivo="p")
    except pi.PublicacaoFalhou as e:
        msg = str(e)
    checar("levantou PublicacaoFalhou", msg is not None, True)
    checar("mensagem cita quadro 3/4 e ERROR", msg is not None and "quadro 3/4" in msg and "ERROR" in msg, True)
    checar("pai nunca criado", any(c[1].get("media_type") == "CAROUSEL" for c in est["posts"]), False)
    checar("nada publicado", len(_publish_calls(est)), 0)
    checar("os 4 quadros subidos foram apagados (sem resíduo)", len(est["removidos"]), 4)
finally:
    _restaurar()

print("\n== NEGATIVO: pai termina ERROR -> falha, nada publicado, bucket limpo ==")
seq = {"item-1": ["FINISHED"], "item-2": ["FINISHED"], "pai-1": ["ERROR"]}
est = _mockar(seq)
try:
    msg = None
    try:
        pi.publicar("legenda", caminhos_carrossel=_quadros(2), nome_arquivo="p")
    except pi.PublicacaoFalhou as e:
        msg = str(e)
    checar("levantou citando o pai", msg is not None and "pai" in msg and "ERROR" in msg, True)
    checar("nada publicado", len(_publish_calls(est)), 0)
    checar("2 quadros apagados", len(est["removidos"]), 2)
finally:
    _restaurar()

print("\n== NEGATIVO: 11 quadros (limite da API é 10) e 1 quadro -> falha LIMPA antes de qualquer upload/POST ==")
for n in (11, 1):
    est = _mockar({})
    try:
        msg = None
        try:
            pi.publicar("legenda", caminhos_carrossel=_quadros(n), nome_arquivo="p")
        except pi.PublicacaoFalhou as e:
            msg = str(e)
        checar("%d quadros: levantou citando 2 a 10" % n, msg is not None and "2 a 10" in msg, True)
        checar("%d quadros: zero upload, zero POST, zero remoção" % n,
               (len(est["uploads"]), len(est["posts"]), len(est["removidos"])), (0, 0, 0))
    finally:
        _restaurar()

print("\n== CONTROLE POSITIVO dos limites: 10 quadros passa, 2 quadros passa ==")
for n in (10, 2):
    seq = {"item-%d" % i: ["FINISHED"] for i in range(1, n + 1)}
    seq["pai-1"] = ["FINISHED"]
    est = _mockar(seq)
    try:
        r = pi.publicar("legenda", caminhos_carrossel=_quadros(n), nome_arquivo="p")
        checar("%d quadros publicam" % n, r["ok"], True)
    finally:
        _restaurar()

print("\n== media_publish do pai: 9007/2207027 1x e depois publica (mesmo retry da imagem) ==")
erro9007 = pi.PublicacaoFalhou('HTTP 400: {"error":{"code":9007,"error_subcode":2207027}}')
seq = {"item-1": ["FINISHED"], "item-2": ["FINISHED"], "pai-1": ["FINISHED"]}
est = _mockar(seq, publish_respostas=[erro9007, {"id": "media-id-789"}])
try:
    r = pi.publicar("legenda", caminhos_carrossel=_quadros(2), nome_arquivo="p")
    checar("publicou após o retry", r["ok"], True)
    checar("media_publish chamado 2x", len(_publish_calls(est)), 2)
finally:
    _restaurar()

print("\n== media_publish com erro que NÃO é 9007: sobe sem retry e limpa o bucket ==")
seq = {"item-1": ["FINISHED"], "item-2": ["FINISHED"], "pai-1": ["FINISHED"]}
est = _mockar(seq, publish_respostas=[pi.PublicacaoFalhou("HTTP 400: code 100")])
try:
    levantou = False
    try:
        pi.publicar("legenda", caminhos_carrossel=_quadros(2), nome_arquivo="p")
    except pi.PublicacaoFalhou:
        levantou = True
    checar("levantou", levantou, True)
    checar("1 tentativa só", len(_publish_calls(est)), 1)
    checar("quadros apagados do bucket", len(est["removidos"]), 2)
finally:
    _restaurar()

print("\n== criar_container (ENSAIO): cria filhos + pai, NUNCA chama media_publish, devolve residuos e itens_ids ==")
seq = {"item-%d" % i: ["FINISHED"] for i in range(1, 7)}
seq["pai-1"] = ["FINISHED"]
est = _mockar(seq)
try:
    c = pi.criar_container("legenda", caminhos_carrossel=_quadros(6), nome_arquivo="peca-x")
    checar("6 itens_ids", len(c["itens_ids"]), 6)
    checar("creation_id é o do pai", c["creation_id"], "pai-1")
    checar("6 residuos para o ensaio apagar", len(c["residuos"]), 6)
    checar("NUNCA media_publish", len(_publish_calls(est)), 0)
    checar("criar_container não apaga (quem apaga é o ensaio, com contagem)", len(est["removidos"]), 0)
finally:
    _restaurar()

print("\n== publicar.py: despacho por formato ==")
import publicar as pub  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
quadros_reais = [
    "redes/estoque/innconta/_gerados/2026-09-22-carrossel-recebiveis/quadro-0%d.png" % i for i in range(1, 7)
]
peca_ok = {"formato": "carrossel", "quadros": quadros_reais}
checar("carrossel com lista de quadros é reconhecido", pub._eh_carrossel(peca_ok), True)
checar("imagem única não é carrossel", pub._eh_carrossel({"formato": "imagem_feed", "quadros": None}), False)
checar("carrossel SEM lista de quadros não é carrossel (cai no caminho da imagem)",
       pub._eh_carrossel({"formato": "carrossel", "quadros": None}), False)
existentes, declarados = pub._quadros_da_peca(peca_ok)
checar("quadros do estoque existem no disco (6 de 6)", (len(existentes), declarados), (6, 6))
existentes, declarados = pub._quadros_da_peca({"quadros": ["redes/nao-existe.png"]})
checar("quadro ausente é contado (0 de 1)", (len(existentes), declarados), (0, 1))

visto = {}
pub.publicar_instagram.publicar = lambda texto, **k: visto.update(k) or {
    "ok": True, "url_post": "https://www.instagram.com/p/X/", "post_id": "1"}
pub.supa.rpc = lambda *a, **k: {"ok": True}
_ler = pub.estoque.ler
try:
    pub.estoque.ler = lambda c: dict(peca_ok, _corpo="texto")
    r = pub.publicar_via_instagram("innconta", {"id": "u", "peca_id": "p1", "texto_aprovado": "texto"})
    checar("carrossel: publicar_via_instagram -> publicado", r, "publicado")
    checar("caminhos_carrossel recebeu 6 quadros", len(visto.get("caminhos_carrossel") or []), 6)
    checar("nome_arquivo = peca_id (prefixo no bucket)", visto.get("nome_arquivo"), "p1")
    checar("sem imagem única junto", visto.get("caminho_imagem"), None)
    visto.clear()
    pub.estoque.ler = lambda c: dict(peca_ok, quadros=quadros_reais + ["redes/nao-existe.png"], _corpo="texto")
    r = pub.publicar_via_instagram("innconta", {"id": "u", "peca_id": "p1", "texto_aprovado": "texto"})
    checar("NEGATIVO: quadro ausente -> falhou, e nem chamou o publicador", (r, visto), ("falhou", {}))
finally:
    pub.estoque.ler = _ler

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS DO CARROSSEL PASSARAM (sucesso, IN_PROGRESS->FINISHED, filho ERROR, pai ERROR, "
      ">10 e <2 itens, limites 2 e 10, retry 9007, erro sem retry, ensaio sem media_publish, despacho).")
