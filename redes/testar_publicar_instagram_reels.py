# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o Supabase/bucket, sem tocar a Graph API de verdade) do
fluxo de VÍDEO/REELS de `redes/publicar_instagram.py` — achado 23/09/2026 (PLAYBOOK §7-V): a
versão anterior só sabia mandar `image_url`, então as peças de vídeo do calendário
(`2026-09-22-video-energia-instagram`, `2026-09-22-video-patrimonial-instagram`) sairiam
FALHANDO ou como imagem parada. Cobre os 3 desfechos do polling (`_esperar_pronto`) — `FINISHED`,
`ERROR`, timeout — mais a garantia de que `criar_container` (usada pelo ENSAIO GERAL,
`redes/ensaio_geral.py`) NUNCA chama `media_publish`, e que `publicar()` só chama depois do
`FINISHED`. Mesmo padrão de `redes/testar_ig_renovar_token.py` (mock com contagem de chamadas).

Roda `python3 redes/testar_publicar_instagram_reels.py` a partir da raiz do repo; sai com código
!= 0 se qualquer prova falhar."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
os.environ["IG_USER_ID"] = "qa-ig-user-id"
import publicar_instagram  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %r (esperado %r)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


_token_original = publicar_instagram._token
_upload_original = publicar_instagram._subir_midia_supabase
_post_original = publicar_instagram._post_form
_get_original = publicar_instagram._get
_sleep_original = publicar_instagram.time.sleep


def _mockar_comuns(sequencia_status):
    """Instala os mocks comuns aos 3 cenários de vídeo: token fixo, upload sem rede, POST /media
    devolve creation_id fixo, GET de status_code consome `sequencia_status` (uma chamada por
    item da lista — estoura IndexError se o código chamar mais vezes do que o esperado, o que é
    intencional: prova que o polling para exatamente na hora certa), time.sleep vira no-op
    (a prova não espera 5s de verdade por chamada)."""
    chamadas = {"post": [], "get": 0, "sleep": 0}
    publicar_instagram._token = lambda *a, **k: "token-de-teste"
    publicar_instagram._subir_midia_supabase = lambda caminho, nome, pasta="instagram": (
        "https://exemplo.supabase.co/storage/v1/object/public/redes-publico/" + pasta + "/" + nome,
        pasta + "/" + nome,
    )

    def _post_mock(url, campos, timeout=30):
        chamadas["post"].append(url)
        if url.endswith("/media"):
            return {"id": "creation-id-123"}
        if url.endswith("/media_publish"):
            return {"id": "media-id-456"}
        raise AssertionError("POST inesperado: %s" % url)
    publicar_instagram._post_form = _post_mock

    it = iter(sequencia_status)

    def _get_mock(url, timeout=30):
        chamadas["get"] += 1
        if "status_code" in url:
            return {"status_code": next(it)}
        if "permalink" in url:
            return {"permalink": "https://www.instagram.com/reel/ABC123/"}
        raise AssertionError("GET inesperado: %s" % url)
    publicar_instagram._get = _get_mock
    publicar_instagram.time.sleep = lambda s: chamadas.__setitem__("sleep", chamadas["sleep"] + 1)
    return chamadas


def _restaurar():
    publicar_instagram._token = _token_original
    publicar_instagram._subir_midia_supabase = _upload_original
    publicar_instagram._post_form = _post_original
    publicar_instagram._get = _get_original
    publicar_instagram.time.sleep = _sleep_original


print("== criar_container — vídeo: 2 rodadas IN_PROGRESS, 3ª FINISHED -> container criado, "
      "NUNCA chama media_publish (é o ENSAIO GERAL usando este caminho) ==")
chamadas = _mockar_comuns(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
try:
    r = publicar_instagram.criar_container("legenda de teste", caminho_video="/tmp/fake.mp4", capa_local=None)
    checar("creation_id devolvido", r["creation_id"], "creation-id-123")
    checar("polling fez exatamente 3 GETs de status", chamadas["get"], 3)
    checar("dormiu 2x (entre as 3 checagens, não depois da última)", chamadas["sleep"], 2)
    checar("NUNCA chamou media_publish", any(u.endswith("/media_publish") for u in chamadas["post"]), False)
    checar("mídia remota devolvida pro chamador limpar depois", r["midia_remota"], "instagram/fake.mp4")
finally:
    _restaurar()

print("\n== publicar() — vídeo: mesmo caminho de criar_container, e SÓ DEPOIS do FINISHED chama "
      "media_publish -> post publicado com url_post real ==")
chamadas = _mockar_comuns(["FINISHED"])
try:
    r = publicar_instagram.publicar("legenda de teste", caminho_video="/tmp/fake.mp4")
    checar("publicou -> ok True", r["ok"], True)
    checar("post_id devolvido", r["post_id"], "media-id-456")
    checar("url_post veio do permalink real", r["url_post"], "https://www.instagram.com/reel/ABC123/")
    checar("chamou /media e /media_publish, nesta ordem", chamadas["post"],
           ["https://graph.instagram.com/v21.0/qa-ig-user-id/media",
            "https://graph.instagram.com/v21.0/qa-ig-user-id/media_publish"])
finally:
    _restaurar()

print("\n== controle NEGATIVO — vídeo: Graph API devolve ERROR -> PublicacaoFalhou nomeando o "
      "status, NUNCA chama media_publish ==")
chamadas = _mockar_comuns(["ERROR"])
try:
    levantou = False
    try:
        publicar_instagram.criar_container("legenda de teste", caminho_video="/tmp/fake.mp4")
    except publicar_instagram.PublicacaoFalhou as e:
        levantou = True
        checar("mensagem cita o status ERROR", "ERROR" in str(e), True)
    checar("levantou PublicacaoFalhou", levantou, True)
    checar("NUNCA chamou media_publish", any(u.endswith("/media_publish") for u in chamadas["post"]), False)
finally:
    _restaurar()

print("\n== controle NEGATIVO — vídeo: Graph API devolve EXPIRED -> PublicacaoFalhou também ==")
chamadas = _mockar_comuns(["EXPIRED"])
try:
    levantou = False
    try:
        publicar_instagram.criar_container("legenda de teste", caminho_video="/tmp/fake.mp4")
    except publicar_instagram.PublicacaoFalhou as e:
        levantou = True
        checar("mensagem cita o status EXPIRED", "EXPIRED" in str(e), True)
    checar("levantou PublicacaoFalhou (EXPIRED)", levantou, True)
finally:
    _restaurar()

print("\n== controle NEGATIVO — vídeo: nunca sai de IN_PROGRESS -> estoura o teto (timeout), "
      "PublicacaoFalhou, NUNCA chama media_publish ==")
sequencia_infinita = ["IN_PROGRESS"] * 1000  # generoso o bastante pra nunca esgotar via StopIteration
chamadas = _mockar_comuns(sequencia_infinita)
try:
    levantou = False
    try:
        # teto pequeno (6s) e intervalo pequeno (2s) só pra este teste não depender do teto real
        # de 300s — o mecanismo é o mesmo, só os parâmetros encolhidos pra rodar em milissegundos.
        publicar_instagram._esperar_pronto("creation-id-123", "token-de-teste", intervalo=2, teto=6)
    except publicar_instagram.PublicacaoFalhou as e:
        levantou = True
        checar("mensagem cita timeout", "timeout" in str(e).lower(), True)
    checar("levantou PublicacaoFalhou (timeout)", levantou, True)
    checar("NUNCA chamou media_publish", any(u.endswith("/media_publish") for u in chamadas["post"]), False)
finally:
    _restaurar()

print("\n== imagem (sem vídeo) — FINISHED na 1ª checagem: media_type/video_url ausentes do POST, "
      "mas o polling roda igual (achado 23/09/2026, run 35883429884 — imagem também processa "
      "assíncrono), media_publish só depois do FINISHED ==")
chamadas = _mockar_comuns(["FINISHED"])
try:
    r = publicar_instagram.publicar("legenda de teste", caminho_imagem="/tmp/fake.png")
    checar("publicou imagem -> ok True", r["ok"], True)
    checar("polling rodou 1x pra imagem (status FINISHED de cara) + 1 de permalink", chamadas["get"], 2)
    checar("NUNCA dormiu (FINISHED já na 1ª checagem)", chamadas["sleep"], 0)
finally:
    _restaurar()

print("\n== imagem — IN_PROGRESS 2x, 3ª FINISHED: mesmo mecanismo de polling do Reels, com "
      "intervalo/teto próprios de imagem (POLL_INTERVALO_S_IMAGEM/POLL_TETO_S_IMAGEM) ==")
chamadas = _mockar_comuns(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
try:
    r = publicar_instagram.criar_container("legenda de teste", caminho_imagem="/tmp/fake.png")
    checar("creation_id devolvido (imagem)", r["creation_id"], "creation-id-123")
    checar("polling fez exatamente 3 GETs de status (imagem)", chamadas["get"], 3)
    checar("dormiu 2x (imagem, entre as 3 checagens)", chamadas["sleep"], 2)
    checar("NUNCA chamou media_publish (criar_container)", any(u.endswith("/media_publish") for u in chamadas["post"]), False)
finally:
    _restaurar()

print("\n== media_publish — 9007/2207027 ('media not ready') 2x seguidas, 3ª tentativa publica: "
      "retry automático com espera fixa, no máximo RETRY_MEDIA_NAO_PRONTA_MAX vezes ==")
chamadas = _mockar_comuns(["FINISHED"])
respostas_publish = iter([
    publicar_instagram.PublicacaoFalhou('HTTP 400: b\'{"error":{"message":"The media is not ready for publishing.","type":"OAuthException","code":9007,"error_subcode":2207027}}\''),
    publicar_instagram.PublicacaoFalhou('HTTP 400: b\'{"error":{"message":"The media is not ready for publishing.","type":"OAuthException","code":9007,"error_subcode":2207027}}\''),
    {"id": "media-id-456"},
])


def _post_mock_retry_9007(url, campos, timeout=30):
    chamadas["post"].append(url)
    if url.endswith("/media"):
        return {"id": "creation-id-123"}
    if url.endswith("/media_publish"):
        item = next(respostas_publish)
        if isinstance(item, Exception):
            raise item
        return item
    raise AssertionError("POST inesperado: %s" % url)


publicar_instagram._post_form = _post_mock_retry_9007
try:
    r = publicar_instagram.publicar("legenda de teste", caminho_imagem="/tmp/fake.png")
    checar("publicou após 2 retries de 9007 -> ok True", r["ok"], True)
    checar("post_id devolvido (3ª tentativa)", r["post_id"], "media-id-456")
    checar("media_publish chamado 3x (2 falhas 9007 + 1 sucesso)",
           sum(1 for u in chamadas["post"] if u.endswith("/media_publish")), 3)
    checar("dormiu pelo menos 2x extra pro retry de 9007 (10s cada, mockado como no-op)",
           chamadas["sleep"] >= 2, True)
finally:
    _restaurar()

print("\n== media_publish — erro que NÃO é 9007/2207027: sobe na hora, sem retry ==")
chamadas = _mockar_comuns(["FINISHED"])
respostas_publish = iter([
    publicar_instagram.PublicacaoFalhou("HTTP 400: b'{\"error\":{\"message\":\"Invalid parameter\",\"code\":100}}'"),
])
publicar_instagram._post_form = _post_mock_retry_9007
try:
    levantou = False
    try:
        publicar_instagram.publicar("legenda de teste", caminho_imagem="/tmp/fake.png")
    except publicar_instagram.PublicacaoFalhou as e:
        levantou = True
        checar("mensagem cita o erro original (código 100)", "100" in str(e), True)
    checar("levantou PublicacaoFalhou sem retry", levantou, True)
    checar("media_publish chamado 1x só (sem retry pra erro que não é 9007/2207027)",
           sum(1 for u in chamadas["post"] if u.endswith("/media_publish")), 1)
finally:
    _restaurar()

print("\n== contar_posts_publicados — pagina até paging.next acabar (usado pelo ensaio geral pra "
      "provar antes/depois que 0 foi publicado) ==")
publicar_instagram._token = lambda *a, **k: "token-de-teste"
paginas = iter([
    {"data": [{"id": "1"}, {"id": "2"}], "paging": {"next": "https://graph.instagram.com/v21.0/qa-ig-user-id/media?after=xyz"}},
    {"data": [{"id": "3"}], "paging": {}},
])


def _get_paginado(url, timeout=30):
    return next(paginas)


publicar_instagram._get = _get_paginado
try:
    total = publicar_instagram.contar_posts_publicados()
    checar("soma as 2 páginas (2+1)", total, 3)
finally:
    _restaurar()

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (10 cenários: vídeo/Reels — sucesso, publish só após FINISHED, "
      "ERROR, EXPIRED, timeout; imagem — FINISHED de cara, IN_PROGRESS->FINISHED, retry de "
      "9007/2207027 no media_publish, erro não-9007 sem retry; contar_posts_publicados).")
