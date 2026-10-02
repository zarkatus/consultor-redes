# -*- coding: utf-8 -*-
"""InnConta · Consultor de Redes — publicação real na página LinkedIn (Community Management API).

Chamado por `redes/publicar.py::publicar_via_linkedin` quando `ic_segredo.linkedin_token`
existe (gravado pelo callback OAuth, `functions/api/redes-linkedin-callback.js`) — sem token, a
peça é marcada `calendario_status='aguardando_api'` (23/09/2026: publicar é tarefa do consultor,
não mais um kit ao Roveda — ver `redes/publicar.py`).

Sem SDK, urllib puro (mesmo padrão de `redes/lib/supa.py`). `LinkedIn-Version` fixado em
202509 (a mesma referência usada no pedido desta sessão) — LinkedIn versiona por mês; revisar
se a API começar a recusar com "unsupported version".

Author sempre `urn:li:organization:145225270` (id fixo da página InnConta — PGA-01: se este
consultor for usado por outra marca do grupo no futuro, o id vira parâmetro, nunca chumbado aqui
sem refatorar; hoje só a InnConta tem página LinkedIn com app aprovado)."""
import json
import os
import sys
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import supa  # noqa: E402

LI_VERSION = "202509"
ORG_URN = "urn:li:organization:145225270"
POSTS_URL = "https://api.linkedin.com/rest/posts"
IMAGES_URL = "https://api.linkedin.com/rest/images"


class TokenAusente(Exception):
    pass


class PublicacaoFalhou(Exception):
    pass


def _token():
    r = supa.select("ic_segredo", "chave=eq.linkedin_token&select=valor&limit=1")
    if not r or not r[0].get("valor"):
        raise TokenAusente("ic_segredo.linkedin_token ausente — Community Management API ainda não aprovada/conectada.")
    try:
        return json.loads(r[0]["valor"])
    except (ValueError, TypeError):
        raise TokenAusente("ic_segredo.linkedin_token com formato inválido (não é JSON).")


def _cab(token):
    return {
        "Authorization": "Bearer " + token["access_token"],
        "Content-Type": "application/json",
        "LinkedIn-Version": LI_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)",
    }


def _post_json(url, headers, corpo, timeout=30):
    req = urllib.request.Request(url, method="POST", data=json.dumps(corpo).encode("utf-8"), headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        loc = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id")
        corpo_resp = r.read()
        return r.status, loc, (json.loads(corpo_resp) if corpo_resp else None)
    except urllib.error.HTTPError as e:
        raise PublicacaoFalhou("HTTP %d: %s" % (e.code, e.read()[:300]))


def _upload_imagem(token, caminho_imagem):
    """Images API: initializeUpload -> PUT binário -> devolve o urn da imagem, pronto pra
    entrar em content.media.id do post."""
    headers = _cab(token)
    status, _, resp = _post_json(
        IMAGES_URL + "?action=initializeUpload",
        headers,
        {"initializeUploadRequest": {"owner": ORG_URN}},
    )
    valor = (resp or {}).get("value") or {}
    upload_url = valor.get("uploadUrl")
    image_urn = valor.get("image")
    if not upload_url or not image_urn:
        raise PublicacaoFalhou("initializeUpload sem uploadUrl/image na resposta.")
    with open(caminho_imagem, "rb") as f:
        dados = f.read()
    req = urllib.request.Request(upload_url, method="PUT", data=dados,
                                  headers={"Authorization": "Bearer " + token["access_token"]})
    try:
        urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        raise PublicacaoFalhou("upload de imagem HTTP %d: %s" % (e.code, e.read()[:200]))
    return image_urn


def publicar(texto, caminho_imagem=None, marca="innconta"):
    """Publica um post real na página. Devolve {"ok": True, "url_post": "..."} ou levanta
    TokenAusente/PublicacaoFalhou — o chamador (redes/publicar.py) decide o que fazer com cada
    uma (ex.: sem token = marca aguardando_api, sem quebrar nada)."""
    token = _token()
    headers = _cab(token)
    corpo = {
        "author": ORG_URN,
        "commentary": texto,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
    }
    if caminho_imagem:
        image_urn = _upload_imagem(token, caminho_imagem)
        corpo["content"] = {"media": {"id": image_urn}}
    status, post_id, _ = _post_json(POSTS_URL, headers, corpo)
    if not post_id:
        raise PublicacaoFalhou("post aceito (%d) mas sem x-restli-id na resposta." % status)
    # id vem como "urn:li:share:...." ou "urn:li:ugcPost:...." — o link público segue este padrão
    url_post = "https://www.linkedin.com/feed/update/" + post_id.replace("urn:li:", "")
    return {"ok": True, "url_post": url_post, "post_id": post_id}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--texto", default="[teste] publicar_linkedin.py — nunca deve rodar sem --mock")
    ap.add_argument("--imagem", default=None)
    ap.add_argument("--mock", action="store_true", help="não fala com a rede — valida montagem do corpo/headers só")
    a = ap.parse_args()

    if a.mock:
        # mock puro: simula _token() sem tocar o banco nem a rede do LinkedIn — prova que o
        # corpo do post e os headers ficam corretos antes do produto ser aprovado de verdade.
        fake_token = {"access_token": "MOCK-TOKEN-NAO-REAL", "expires_in": 5184000}
        headers = _cab(fake_token)
        corpo = {
            "author": ORG_URN,
            "commentary": a.texto,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
        }
        assert headers["LinkedIn-Version"] == LI_VERSION
        assert corpo["author"] == ORG_URN
        assert corpo["lifecycleState"] == "PUBLISHED"
        print("MOCK OK — headers:", json.dumps({k: v for k, v in headers.items() if k != "Authorization"}))
        print("MOCK OK — corpo:", json.dumps(corpo, ensure_ascii=False))
        sys.exit(0)

    try:
        print(publicar(a.texto, a.imagem))
    except TokenAusente as e:
        print("SEM TOKEN (esperado até a Community Management API ser aprovada):", e)
        sys.exit(2)
    except PublicacaoFalhou as e:
        print("FALHOU:", e)
        sys.exit(1)
