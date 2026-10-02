# -*- coding: utf-8 -*-
"""InnConta · Consultor de Redes — publicação real no Instagram `@innconta.oficial`
(Instagram API with Instagram Login — dispensa Página do Facebook, PLAYBOOK §7-V).

Chamado por `redes/publicar.py::publicar_via_instagram` quando existe um token válido em
`ic_segredo.ig_access_token` (renovado sozinho a cada mês por `redes/ig_renovar_token.py`,
23/09/2026 — token de 60 dias gerado pelo painel developers.facebook.com, valor inicial em
no cofre local, fora deste repo) — `IG_ACCESS_TOKEN`
(GitHub Secret) é só o FALLBACK, para não quebrar antes do primeiro seed. Sem nenhum dos dois, a
peça é marcada `calendario_status='aguardando_api'`, mesmo padrão do LinkedIn em
`redes/publicar_linkedin.py`.

Sem SDK, urllib puro (mesmo padrão de `redes/lib/supa.py` e `redes/publicar_linkedin.py`).

Fluxo IMAGEM (Graph API do Instagram, v21.0):
1. a imagem local precisa de uma URL pública — sobe pro bucket `redes-publico` do Supabase
   InnConta (público, criado 23/09/2026 só pra isso; nunca reaproveitar um bucket que já mistura
   entrada/saída — PAR-01/achado "bucket público mistura entrada e saída");
2. `POST /{ig_user_id}/media` (image_url + caption) -> creation_id;
3. achado real 23/09/2026 (1ª tentativa de estreia, run 35883429884, HTTP 400 OAuthException
   9007/2207027 "The media is not ready for publishing"): container de IMAGEM também processa de
   forma assíncrona, nem sempre está pronto na hora — POLLING de
   `GET /{creation_id}?fields=status_code` a cada 3s (teto 2min) até `FINISHED`, mesmo mecanismo
   do Reels, só que com intervalo/teto próprios (`POLL_INTERVALO_S_IMAGEM`/`POLL_TETO_S_IMAGEM`);
4. `POST /{ig_user_id}/media_publish` (creation_id) -> media id real, publicado de verdade. Se
   ainda assim devolver 9007/2207027 (janela curta entre FINISHED e a publicação aceitar), retry
   automático com 10s de espera, no máximo 3 vezes (`_media_publish`) — qualquer outro erro sobe
   na hora, sem retry;
5. `GET /{media_id}?fields=permalink` -> URL pública do post, pra gravar em `url_post`.

Fluxo VÍDEO/REELS (achado 23/09/2026 — PLAYBOOK §7-V: a versão anterior só sabia mandar
`image_url`, então as peças de vídeo do calendário sairiam FALHANDO ou como imagem parada):
1. sobe o .mp4 (formato `stories`, 1080x1920 — recomendado pela Meta para Reels, PLAYBOOK §7-V)
   pro mesmo bucket público, mesma rotina de upload (generalizada para qualquer content-type,
   não só imagem) + a capa (.png, opcional) como `cover_url`;
2. `POST /{ig_user_id}/media` com `media_type=REELS`, `video_url`, `caption`, `cover_url`
   (opcional), `share_to_feed=true` -> creation_id;
3. a Graph API processa o vídeo de forma assíncrona — POLLING de
   `GET /{creation_id}?fields=status_code` a cada 5s (teto 5min) até `FINISHED`; `ERROR`/`EXPIRED`
   vira `PublicacaoFalhou` com o status observado; estourar o teto sem `FINISHED` também;
4. só então `POST /{ig_user_id}/media_publish` (mesmo passo 3 do fluxo imagem) -> `media_id`;
5. `GET /{media_id}?fields=permalink` -> URL pública do post.

Fluxo CARROSSEL (24/09/2026 — a peça da PGFN é um carrossel de 6 quadros; até aqui só havia imagem
única e Reels): a Graph API pede 3 níveis de contêiner, nesta ordem —
1. cada quadro sobe pro bucket `redes-publico` e vira um contêiner FILHO: `POST /{ig_user_id}/media`
   com `image_url` + `is_carousel_item=true` (sem legenda), creation_id por item;
2. cada filho passa pelo mesmo polling de `FINISHED` da imagem (3 s, teto 2 min, `_esperar_pronto`);
   `ERROR`/`EXPIRED`/timeout de QUALQUER filho aborta tudo com `PublicacaoFalhou` nomeando o item;
3. contêiner PAI: `POST /{ig_user_id}/media` com `media_type=CAROUSEL`, `children=<ids separados por
   vírgula, na ordem dos quadros>` e `caption`; polling `FINISHED` do pai;
4. `media_publish` do PAI (mesmo `_media_publish`, mesmo retry de 9007/2207027) e permalink.
Limite da API: 2 a 10 itens — fora disso `PublicacaoFalhou` ANTES de subir qualquer arquivo.
Sobras do bucket: `publicar()` apaga os quadros do carrossel depois de publicar (e
`criar_container_carrossel` apaga o que já subiu se falhar no meio); o ENSAIO apaga os que sobram
do dry-run (`residuos`, PAR-01e). Imagem única e Reels seguem como antes.

`criar_container()` isola os passos 1-3 (upload + `POST /media` + polling do vídeo) SEM nunca
chamar `media_publish` — é o que o ENSAIO GERAL (`redes/ensaio_geral.py`) usa para provar que o
mecanismo funciona (contêiner real criado e `FINISHED`) sem publicar nada de verdade.
`publicar()` reaproveita `criar_container()` e só ela chama `media_publish`.

IG_USER_ID é o id numérico da conta Instagram Business (`innconta.oficial`), não segredo —
variável do repo (GitHub Variable), não Secret."""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import marcas  # noqa: E402
import supa  # noqa: E402

GRAPH_VERSION = "v21.0"
GRAPH_BASE = "https://graph.instagram.com/" + GRAPH_VERSION
BUCKET = "redes-publico"

# Reels: polling do processamento do vídeo — intervalo curto o bastante para não segurar o
# job por muito tempo, teto generoso o bastante para vídeos curtos (<=90s, PLAYBOOK §7-V)
# processarem com folga.
POLL_INTERVALO_S = 5
POLL_TETO_S = 300

# Imagem: mesmo mecanismo de polling do Reels (achado 23/09/2026, run 35883429884 — container de
# imagem também pode não estar pronto na hora), intervalo/teto menores porque imagem processa bem
# mais rápido que vídeo.
POLL_INTERVALO_S_IMAGEM = 3
POLL_TETO_S_IMAGEM = 120

# Carrossel: limites da Graph API (contêiner CAROUSEL aceita de 2 a 10 filhos).
CARROSSEL_MIN_ITENS = 2
CARROSSEL_MAX_ITENS = 10

# media_publish devolvendo 9007/2207027 ("The media is not ready for publishing") mesmo após
# status_code=FINISHED — janela curta observada na estreia real; retry com espera fixa, nunca
# mascarando qualquer outro erro.
RETRY_MEDIA_NAO_PRONTA_MAX = 3
RETRY_MEDIA_NAO_PRONTA_ESPERA_S = 10


class TokenAusente(Exception):
    pass


class PublicacaoFalhou(Exception):
    pass


def _token(marca="innconta"):
    """Token da MARCA: `ic_segredo.ig_access_token_<marca>` (renovado sozinho por `redes/ig_renovar_token.py`).
    Compatibilidade so para a InnConta: se a chave nova faltar le a legada `ic_segredo.ig_access_token` e, por ultimo,
    `IG_ACCESS_TOKEN` (GitHub Secret, so fallback). Outra marca sem token = TokenAusente (o chamador pula com log,
    sem derrubar as demais)."""
    tok = supa.segredo(marcas.chave_token(marca))
    if tok:
        return tok
    if marca == "innconta":
        tok = supa.segredo("ig_access_token") or os.environ.get("IG_ACCESS_TOKEN")
        if tok:
            return tok
    raise TokenAusente("ic_segredo.%s ausente — Instagram de %s ainda nao conectado." % (marcas.chave_token(marca), marca))


def _ig_user_id(marca="innconta"):
    """IG user id da marca: do registro (`regras.json`, nao e segredo). Compat: `IG_USER_ID` do ambiente vale so para a InnConta."""
    uid = str(marcas.carregar(marca).get("ig_user_id") or "").strip()
    if marca == "innconta" and os.environ.get("IG_USER_ID"):
        uid = os.environ["IG_USER_ID"]  # compat: a GitHub Variable legada da InnConta, se existir, vale
    if not uid:
        raise TokenAusente("ig_user_id ausente no regras.json de %s." % marca)
    return uid


def _post_com_opcionais(url, campos, opcionais):
    """POST do contêiner com campos OPCIONAIS de alcance (`alt_text`, `collaborators`): se a API recusar (campo nao
    suportado nesse tipo de login/midia, colaborador que nao aceita), tenta de novo sem eles, um por vez, e devolve
    (resposta, aplicados). Nunca deixa um campo de alcance derrubar a publicacao."""
    aplicados = [k for k in opcionais if campos.get(k)]
    corpo = dict(campos)
    while True:
        try:
            return _post_form(url, corpo), aplicados
        except PublicacaoFalhou as e:
            if not aplicados:
                raise
            saiu = aplicados.pop()
            print("aviso: a API recusou o contêiner com `%s` (%s) — tentando sem ele." % (saiu, str(e)[:160]))
            corpo.pop(saiu, None)


def _subir_midia_supabase(caminho_local, nome_arquivo, pasta="instagram"):
    """Sobe o arquivo local (imagem OU vídeo — `mimetypes.guess_type` já resolve `.mp4` para
    `video/mp4` sem precisar de mapa próprio) pro bucket público `redes-publico` (Storage REST
    API do Supabase, service_role) e devolve (url_publica, caminho_remoto) — a Graph API do
    Instagram exige `image_url`/`video_url` público, não aceita upload binário direto.
    Generalizada 23/09/2026 (antes só sabia subir imagem) — mesma rotina para os 2 tipos de
    mídia e para a capa (.png) de um Reels."""
    if not supa.URL or not supa.KEY:
        raise PublicacaoFalhou("SB_URL/SB_SERVICE_ROLE ausentes no ambiente — não dá pra subir a mídia.")
    tipo, _ = mimetypes.guess_type(caminho_local)
    tipo = tipo or "application/octet-stream"
    with open(caminho_local, "rb") as f:
        dados = f.read()
    caminho_remoto = pasta + "/" + nome_arquivo
    url_upload = supa.URL + "/storage/v1/object/" + BUCKET + "/" + caminho_remoto
    req = urllib.request.Request(
        url_upload, method="POST", data=dados,
        headers={"apikey": supa.KEY, "Authorization": "Bearer " + supa.KEY,
                 "Content-Type": tipo, "x-upsert": "true",
                 "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"},
    )
    try:
        urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        raise PublicacaoFalhou("upload pro bucket redes-publico HTTP %d: %s" % (e.code, e.read()[:300]))
    url_publica = supa.URL + "/storage/v1/object/public/" + BUCKET + "/" + caminho_remoto
    return url_publica, caminho_remoto


def remover_midia_supabase(caminho_remoto):
    """DELETE no Storage REST do bucket `redes-publico` — usado pelo ENSAIO GERAL
    (`redes/ensaio_geral.py`) para tirar do ar a mídia de prova depois do dry-run (PAR-01e,
    resíduo de teste sai com prova, nunca promessa). `True` só quando o Storage confirma a
    remoção; falha fica registrada pelo chamador, nunca escondida."""
    url = supa.URL + "/storage/v1/object/" + BUCKET + "/" + caminho_remoto
    req = urllib.request.Request(
        url, method="DELETE",
        headers={"apikey": supa.KEY, "Authorization": "Bearer " + supa.KEY,
                 "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"},
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except urllib.error.HTTPError:
        return False


def listar_midia_supabase(pasta="instagram", limite=200):
    """Lista `redes-publico/<pasta>` — usado pelo ENSAIO GERAL para provar resíduo zero por
    CONTAGEM (não por suposição de que o DELETE funcionou)."""
    url = supa.URL + "/storage/v1/object/list/" + BUCKET
    corpo = json.dumps({"prefix": pasta, "limit": limite}).encode("utf-8")
    req = urllib.request.Request(
        url, method="POST", data=corpo,
        headers={"apikey": supa.KEY, "Authorization": "Bearer " + supa.KEY,
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as e:
        raise PublicacaoFalhou("listagem do bucket redes-publico HTTP %d: %s" % (e.code, e.read()[:300]))


def _post_form(url, campos, timeout=30):
    body = urllib.parse.urlencode(campos).encode("utf-8")
    req = urllib.request.Request(url, method="POST", data=body,
                                  headers={"User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise PublicacaoFalhou("HTTP %d: %s" % (e.code, e.read()[:300]))


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise PublicacaoFalhou("HTTP %d: %s" % (e.code, e.read()[:300]))


def _esperar_pronto(creation_id, token, intervalo=POLL_INTERVALO_S, teto=POLL_TETO_S):
    """Polling de `GET /{creation_id}?fields=status_code` até `FINISHED` — a Graph API processa
    a mídia (vídeo OU imagem, achado 23/09/2026: imagem também pode não estar pronta na hora, run
    35883429884) de forma assíncrona, então criar o container não significa que ela já pode ser
    publicada. `ERROR`/`EXPIRED` vira PublicacaoFalhou nomeando o status observado (nunca um erro
    genérico); estourar o teto sem `FINISHED` também é falha, não sucesso silencioso. Vídeo usa
    `POLL_INTERVALO_S`/`POLL_TETO_S`, imagem usa `POLL_INTERVALO_S_IMAGEM`/`POLL_TETO_S_IMAGEM`
    (chamador passa o par certo — ver `criar_container`)."""
    decorrido = 0
    status = None
    while decorrido <= teto:
        info = _get(GRAPH_BASE + "/" + creation_id + "?fields=status_code&access_token=" + token)
        status = info.get("status_code")
        if status == "FINISHED":
            return status
        if status in ("ERROR", "EXPIRED"):
            raise PublicacaoFalhou("container de mídia (creation_id=%s) terminou com status %s" % (creation_id, status))
        time.sleep(intervalo)
        decorrido += intervalo
    raise PublicacaoFalhou("timeout aguardando FINISHED (%ds) — último status observado: %s" % (teto, status))


def _media_nao_pronta_para_publicar(mensagem_erro):
    """Reconhece o erro 9007/2207027 ('The media is not ready for publishing') dentro da mensagem
    de uma PublicacaoFalhou — janela curta observada na estreia real (23/09/2026, run
    35883429884) mesmo depois do container reportar FINISHED no polling. Só este padrão
    específico justifica retry automático; qualquer outro erro sobe na hora."""
    return "9007" in mensagem_erro and "2207027" in mensagem_erro


def _media_publish(ig_user_id, creation_id, token):
    """POST /{ig_user_id}/media_publish com retry específico pro erro 9007/2207027 — até
    `RETRY_MEDIA_NAO_PRONTA_MAX` tentativas extras, esperando `RETRY_MEDIA_NAO_PRONTA_ESPERA_S`
    entre elas. Qualquer outro erro (ou esgotar as tentativas) sobe imediatamente — nunca mascara
    uma falha real."""
    url = GRAPH_BASE + "/" + ig_user_id + "/media_publish"
    campos = {"creation_id": creation_id, "access_token": token}
    tentativa = 0
    while True:
        tentativa += 1
        try:
            return _post_form(url, campos)
        except PublicacaoFalhou as e:
            if not _media_nao_pronta_para_publicar(str(e)) or tentativa > RETRY_MEDIA_NAO_PRONTA_MAX:
                raise
            time.sleep(RETRY_MEDIA_NAO_PRONTA_ESPERA_S)


def contar_posts_publicados(marca="innconta"):
    """`GET /{ig_user_id}/media?fields=id`, paginando — a contagem REAL de posts publicados na
    conta. Usado pelo ENSAIO GERAL (`redes/ensaio_geral.py`) para medir ANTES e DEPOIS do
    dry-run inteiro: a mesma contagem nos dois momentos é o efeito persistido observado de que
    nenhuma publicação real aconteceu (PAR-01e/PQV-02 — nunca uma promessa de "não deveria ter
    publicado", uma contagem que bate de verdade)."""
    ig_user_id = _ig_user_id(marca)
    token = _token(marca)
    total = 0
    url = GRAPH_BASE + "/" + ig_user_id + "/media?fields=id&limit=100&access_token=" + token
    while url:
        info = _get(url)
        total += len(info.get("data") or [])
        url = (info.get("paging") or {}).get("next")
    return total


def criar_container_carrossel(texto, caminhos_quadros, nome_base=None, marca="innconta", alt_text=None, collaborators=None):
    """Carrossel: sobe cada quadro, cria os contêineres FILHOS (`is_carousel_item=true`), espera
    cada um chegar a `FINISHED`, cria o PAI (`media_type=CAROUSEL`, `children`, `caption`) e espera
    o pai também. NUNCA chama `media_publish`. Falha em qualquer ponto apaga do bucket o que já
    subiu e levanta `PublicacaoFalhou` (falha limpa, sem resíduo). Devolve o mesmo dict de
    `criar_container` + `itens_ids` (creation_id de cada filho) e `residuos` (caminhos no bucket)."""
    quadros = list(caminhos_quadros or [])
    if not (CARROSSEL_MIN_ITENS <= len(quadros) <= CARROSSEL_MAX_ITENS):
        raise PublicacaoFalhou("carrossel exige de %d a %d quadros (recebeu %d)"
                               % (CARROSSEL_MIN_ITENS, CARROSSEL_MAX_ITENS, len(quadros)))
    token = _token(marca)
    ig_user_id = _ig_user_id(marca)
    url_media = GRAPH_BASE + "/" + ig_user_id + "/media"
    remotos, itens_ids = [], []
    aplicados = []
    try:
        for i, caminho in enumerate(quadros, start=1):
            nome = "%s-%02d-%s" % (nome_base, i, os.path.basename(caminho)) if nome_base else os.path.basename(caminho)
            image_url, remoto = _subir_midia_supabase(caminho, nome)
            remotos.append(remoto)
            campos_item = {"image_url": image_url, "is_carousel_item": "true", "access_token": token}
            if alt_text:
                campos_item["alt_text"] = ("Quadro %d de %d. %s" % (i, len(quadros), alt_text))[:1000]
            criado, _ap = _post_com_opcionais(url_media, campos_item, ("alt_text",))
            if "alt_text" in _ap and "alt_text" not in aplicados:
                aplicados.append("alt_text")
            item_id = criado.get("id")
            if not item_id:
                raise PublicacaoFalhou("quadro %d do carrossel sem id na resposta: %s" % (i, json.dumps(criado)[:300]))
            itens_ids.append(item_id)
        for i, item_id in enumerate(itens_ids, start=1):
            try:
                _esperar_pronto(item_id, token, intervalo=POLL_INTERVALO_S_IMAGEM, teto=POLL_TETO_S_IMAGEM)
            except PublicacaoFalhou as e:
                raise PublicacaoFalhou("quadro %d/%d do carrossel: %s" % (i, len(itens_ids), e))
        campos_pai = {"media_type": "CAROUSEL", "children": ",".join(itens_ids), "caption": texto, "access_token": token}
        if collaborators:
            campos_pai["collaborators"] = json.dumps(list(collaborators))
        pai, _ap = _post_com_opcionais(url_media, campos_pai, ("collaborators",))
        if "collaborators" in _ap:
            aplicados.append("collaborators")
        creation_id = pai.get("id")
        if not creation_id:
            raise PublicacaoFalhou("contêiner pai do carrossel sem id na resposta: %s" % json.dumps(pai)[:300])
        try:
            _esperar_pronto(creation_id, token, intervalo=POLL_INTERVALO_S_IMAGEM, teto=POLL_TETO_S_IMAGEM)
        except PublicacaoFalhou as e:
            raise PublicacaoFalhou("contêiner pai do carrossel: %s" % e)
    except Exception:
        for r in remotos:
            remover_midia_supabase(r)
        raise
    return {"creation_id": creation_id, "token": token, "midia_remota": remotos[0], "capa_remota": None,
            "itens_ids": itens_ids, "residuos": remotos, "aplicados": aplicados}


def criar_container(texto, caminho_imagem=None, caminho_video=None, marca="innconta",
                     nome_arquivo=None, capa_local=None, caminhos_carrossel=None, alt_text=None, collaborators=None):
    """Sobe a mídia (imagem OU vídeo, nunca as duas) e cria o container real na Graph API
    (`POST /media`) — para vídeo, espera o polling até `FINISHED`. NUNCA chama `media_publish`:
    é o ponto onde `publicar()` segue adiante e onde o ENSAIO GERAL para de propósito. Devolve
    {"creation_id", "token", "midia_remota", "capa_remota"} — os dois últimos são os caminhos no
    bucket, para o chamador poder limpar o resíduo (PAR-01e). `caminhos_carrossel` (lista de 2 a 10
    imagens locais) despacha para `criar_container_carrossel` (`nome_arquivo` vira o prefixo dos
    arquivos no bucket)."""
    if caminhos_carrossel:
        return criar_container_carrossel(texto, caminhos_carrossel, nome_base=nome_arquivo, marca=marca,
                                         alt_text=alt_text, collaborators=collaborators)
    if not caminho_imagem and not caminho_video:
        raise PublicacaoFalhou("Instagram exige imagem/vídeo — peça sem mídia não publica.")
    token = _token(marca)
    ig_user_id = _ig_user_id(marca)

    campos = {"caption": texto, "access_token": token}
    midia_remota = None
    capa_remota = None

    if caminho_video:
        nome = nome_arquivo or os.path.basename(caminho_video)
        video_url, midia_remota = _subir_midia_supabase(caminho_video, nome)
        campos["media_type"] = "REELS"
        campos["video_url"] = video_url
        campos["share_to_feed"] = "true"
        if collaborators:  # Reels aceita `collaborators`; `alt_text` NAO (a doc da Meta: so posts de imagem)
            campos["collaborators"] = json.dumps(list(collaborators))
        if capa_local and os.path.isfile(capa_local):
            cover_url, capa_remota = _subir_midia_supabase(capa_local, os.path.basename(capa_local))
            campos["cover_url"] = cover_url
    else:
        nome = nome_arquivo or os.path.basename(caminho_imagem)
        image_url, midia_remota = _subir_midia_supabase(caminho_imagem, nome)
        campos["image_url"] = image_url
        if alt_text:  # so imagem (doc da Meta, mar/2025)
            campos["alt_text"] = alt_text[:1000]
        if collaborators:
            campos["collaborators"] = json.dumps(list(collaborators))

    criado, aplicados = _post_com_opcionais(GRAPH_BASE + "/" + ig_user_id + "/media", campos, ("alt_text", "collaborators"))
    creation_id = criado.get("id")
    if not creation_id:
        raise PublicacaoFalhou("media container sem id na resposta: %s" % json.dumps(criado)[:300])

    if caminho_video:
        _esperar_pronto(creation_id, token)
    else:
        _esperar_pronto(creation_id, token, intervalo=POLL_INTERVALO_S_IMAGEM, teto=POLL_TETO_S_IMAGEM)

    return {"creation_id": creation_id, "token": token, "midia_remota": midia_remota, "capa_remota": capa_remota,
            "residuos": [r for r in (midia_remota, capa_remota) if r], "aplicados": aplicados}


def publicar(texto, caminho_imagem=None, caminho_video=None, marca="innconta",
             nome_arquivo=None, capa_local=None, caminhos_carrossel=None, alt_text=None, collaborators=None,
             primeiro_comentario=None):
    """Publica um post real na conta `innconta.oficial` (imagem OU vídeo/Reels). Devolve
    {"ok": True, "url_post": "...", "post_id": "..."} ou levanta TokenAusente/PublicacaoFalhou —
    o chamador (redes/publicar.py) decide o que fazer com cada uma, mesmo contrato de
    publicar_linkedin.publicar. Compatível com o contrato antigo (`publicar(texto, caminho_imagem,
    marca=...)`, posicional) — `caminho_video`/`capa_local` são aditivos."""
    ig_user_id = _ig_user_id(marca)
    container = criar_container(texto, caminho_imagem, caminho_video, marca, nome_arquivo, capa_local,
                                caminhos_carrossel=caminhos_carrossel, alt_text=alt_text, collaborators=collaborators)

    try:
        publicado = _media_publish(ig_user_id, container["creation_id"], container["token"])
    except PublicacaoFalhou:
        if caminhos_carrossel:  # não publicou: não deixa os quadros no bucket público
            for r in container.get("residuos", []):
                remover_midia_supabase(r)
        raise
    if caminhos_carrossel:  # publicou: a Meta já copiou os quadros; as sobras saem do bucket
        for r in container.get("residuos", []):
            remover_midia_supabase(r)
    media_id = publicado.get("id")
    if not media_id:
        raise PublicacaoFalhou("media_publish sem id na resposta: %s" % json.dumps(publicado)[:300])

    permalink = None
    try:
        info = _get(GRAPH_BASE + "/" + media_id + "?fields=permalink&access_token=" + container["token"])
        permalink = info.get("permalink")
    except PublicacaoFalhou:
        pass  # publicou mesmo assim; sem permalink não é motivo pra reportar falha
    url_post = permalink or ("https://www.instagram.com/p/" + media_id)
    comentario_ok = None
    if primeiro_comentario:
        # hashtags no 1o comentario (opcional): precisa da permissao de comentarios; falha NAO desfaz a publicacao
        try:
            _post_form(GRAPH_BASE + "/" + media_id + "/comments", {"message": primeiro_comentario[:2200],
                                                                  "access_token": container["token"]})
            comentario_ok = True
        except PublicacaoFalhou as e:
            print("aviso: primeiro comentario NAO postado (%s)" % str(e)[:160])
            comentario_ok = False
    aplicados = container.get("aplicados") or []
    return {"ok": True, "url_post": url_post, "post_id": media_id, "collab_aplicado": "collaborators" in aplicados,
            "alt_aplicado": "alt_text" in aplicados, "comentario_ok": comentario_ok}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--texto", default="[teste] publicar_instagram.py — nunca deve rodar sem --mock")
    ap.add_argument("--imagem", default=None)
    ap.add_argument("--video", default=None)
    ap.add_argument("--mock", action="store_true", help="não fala com a rede nem com o Supabase — valida montagem só")
    a = ap.parse_args()

    if a.mock:
        fake_url = "https://exemplo.supabase.co/storage/v1/object/public/redes-publico/instagram/teste.png"
        assert BUCKET == "redes-publico"
        assert GRAPH_BASE.startswith("https://graph.instagram.com/")
        print("MOCK OK — bucket:", BUCKET, "| graph base:", GRAPH_BASE, "| image_url exemplo:", fake_url)
        sys.exit(0)

    try:
        print(publicar(a.texto, a.imagem, a.video))
    except TokenAusente as e:
        print("SEM TOKEN (esperado até IG_ACCESS_TOKEN existir):", e)
        sys.exit(2)
    except PublicacaoFalhou as e:
        print("FALHOU:", e)
        sys.exit(1)
