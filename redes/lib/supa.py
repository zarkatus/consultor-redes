# -*- coding: utf-8 -*-
"""Cliente REST mínimo do Supabase (PostgREST), service_role — sem SDK, sem dependência nova.
Lê SB_URL/SB_SERVICE_ROLE do ambiente (nomes iguais aos das outras Pages Functions do repo,
PLAYBOOK §5) com fallback para SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY (nomes dos GH Secrets já
existentes, usados por scripts/acompanhamento.py)."""
import json
import os
import re
import urllib.error
import urllib.request

import assinatura  # noqa: E402 — mesmo diretório (redes/lib), import plano, PLAYBOOK §23set2026

URL = (os.environ.get("SB_URL") or os.environ.get("SUPABASE_URL") or "").rstrip("/")
KEY = os.environ.get("SB_SERVICE_ROLE") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""


def _cab(extra=None):
    # User-Agent explícito: sem ele, a Cloudflare na frente de algumas APIs (Resend inclusive)
    # devolve 403 "error code: 1010" para o urllib padrão do Python (bateu de verdade no GitHub
    # Actions, 22/09/2026) — mesmo motivo pelo qual scripts/acompanhamento.py já usa isto.
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"}
    h.update(extra or {})
    return h


def rpc(nome, corpo=None, timeout=30):
    req = urllib.request.Request(URL + "/rest/v1/rpc/" + nome, method="POST",
                                  data=json.dumps(corpo or {}).encode("utf-8"), headers=_cab())
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        corpo_erro = e.read()
        raise RuntimeError("RPC %s HTTP %d: %s" % (nome, e.code, corpo_erro[:300]))


def select(tabela, query, timeout=30):
    req = urllib.request.Request(URL + "/rest/v1/" + tabela + "?" + query,
                                  headers=_cab({"Accept": "application/json"}))
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as e:
        raise RuntimeError("SELECT %s HTTP %d: %s" % (tabela, e.code, e.read()[:300]))


def patch(tabela, filtro_query, corpo, timeout=30):
    """PATCH direto — só para campos de AGENDAMENTO (não-decisórios); toda transição de STATUS
    que representa uma decisão passa pelas RPCs redes_decidir/redes_calendario_decidir, nunca
    por PATCH cru, pra manter a atomicidade e o motivo registrado num lugar só."""
    req = urllib.request.Request(URL + "/rest/v1/" + tabela + "?" + filtro_query, method="PATCH",
                                  data=json.dumps(corpo).encode("utf-8"),
                                  headers=_cab({"Prefer": "return=representation"}))
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as e:
        raise RuntimeError("PATCH %s HTTP %d: %s" % (tabela, e.code, e.read()[:300]))


def excluir(tabela, filtro_query, timeout=30):
    """DELETE direto — só para linhas PLACEHOLDER (reserva, não dado real de verdade — ex.:
    vaga de vídeo do calendário consumida por uma peça real, PLAYBOOK §7-V). Nunca usar para
    apagar uma decisão do CVO; isso é sempre 'recusado'/'expirado' via RPC, nunca DELETE."""
    req = urllib.request.Request(URL + "/rest/v1/" + tabela + "?" + filtro_query, method="DELETE",
                                  headers=_cab({"Prefer": "return=representation"}))
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as e:
        raise RuntimeError("DELETE %s HTTP %d: %s" % (tabela, e.code, e.read()[:300]))


def enviar_email(assunto, para, html, texto_alt=None, remetente="InnConta <contato@innconta.com.br>", anexos=None):
    """Resend, chamada HTTP direta (mesmo mecanismo já usado na casa: RESEND_API_KEY).

    anexos: lista de (nome_arquivo, caminho_local) — vai como anexo base64 no MESMO e-mail. Usado
    para as imagens GERADAS pelo consultor (redes/estoque/.../_gerados/), que não são publicadas no
    site (redes/ está fora da lista de permissão do pre-push, PLAYBOOK §1) — anexar garante que a
    prévia chega de qualquer jeito, sem depender de publicar o gerado num caminho novo."""
    import base64
    chave = os.environ.get("RESEND_API_KEY", "")
    if not chave:
        raise RuntimeError("RESEND_API_KEY ausente no ambiente")
    # assinatura padrão da casa (23/09/2026) — aplicada quando o corpo ainda não tem uma; a
    # identidade vem do e-mail em `remetente` ("Nome <email>" ou só "email").
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", remetente or "")
    email_remetente = m.group(0) if m else "contato@innconta.com.br"
    html, texto_alt = assinatura.aplicar_assinatura(html, texto_alt, email_remetente)
    corpo = {"from": remetente, "to": [para] if isinstance(para, str) else para,
             "subject": assunto, "html": html}
    if texto_alt:
        corpo["text"] = texto_alt
    if anexos:
        lista = []
        for nome, caminho in anexos:
            try:
                with open(caminho, "rb") as f:
                    lista.append({"filename": nome, "content": base64.b64encode(f.read()).decode("ascii")})
            except OSError:
                continue
        if lista:
            corpo["attachments"] = lista
    req = urllib.request.Request("https://api.resend.com/emails", method="POST",
                                  data=json.dumps(corpo).encode("utf-8"),
                                  headers={"Authorization": "Bearer " + chave, "Content-Type": "application/json",
                                           "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Resend HTTP %d: %s" % (e.code, e.read()[:300]))


def avisar_wa(fone, texto, marca="InnConta"):
    return rpc("ic_avisar_wa", {"p_fone": fone, "p_texto": texto, "p_marca": marca})


def segredo(chave):
    """Lê `public.ic_segredo` (chave/valor em claro, RLS sem policy — só service_role, PLAYBOOK
    §7-E "Rotação de segredos do vault") e devolve o VALOR CRU (string) da linha, ou None se a
    chave não existir ou o valor estiver vazio. Mesmo padrão já usado por
    `redes/publicar_linkedin.py::_token` (chave `linkedin_token`, JSON) — aqui devolve a string
    crua, quem chama decide se precisa parsear (ex.: `ig_access_token` é o token puro, não JSON).
    Nunca loga o valor — só o booleano/comprimento é seguro de imprimir."""
    r = select("ic_segredo", "chave=eq.%s&select=valor&limit=1" % chave)
    if not r or not r[0].get("valor"):
        return None
    return r[0]["valor"]


def gravar_segredo(chave, valor):
    """Upsert em `public.ic_segredo` (mesmo padrão de `functions/api/redes-linkedin-callback.js`,
    `on_conflict=chave` + `resolution=merge-duplicates`) — usado pela renovação automática do
    token do Instagram (`redes/ig_renovar_token.py`). Nunca loga o valor gravado."""
    req = urllib.request.Request(
        URL + "/rest/v1/ic_segredo?on_conflict=chave", method="POST",
        data=json.dumps([{"chave": chave, "valor": valor}]).encode("utf-8"),
        headers=_cab({"Prefer": "resolution=merge-duplicates,return=minimal"}),
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise RuntimeError("upsert ic_segredo HTTP %d: %s" % (e.code, e.read()[:200]))


def registrar_aviso(texto, marca="innconta", canal="instagram_token", entregue=True, veredito=None, fone=None):
    """Grava uma linha em `public.ic_aviso_log` (tabela de log já existente na casa,
    `sql/vigia-da-rota-de-aviso.sql` — RLS `ic_sou_casa()` para leitura, só service_role escreve)
    — mesma raiz de log usada por `ic_avisar_wa`/vigias SQL, PAR-01d (um recurso real, uma raiz).
    `fone` fica vazio para avisos que não são WhatsApp (ex.: renovação de token)."""
    req = urllib.request.Request(
        URL + "/rest/v1/ic_aviso_log", method="POST",
        data=json.dumps([{
            "fone": fone or "", "marca": marca, "entregue": bool(entregue),
            "veredito": veredito or {}, "texto": (texto or "")[:400], "canal": canal,
        }]).encode("utf-8"),
        headers=_cab({"Prefer": "return=minimal"}),
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise RuntimeError("insert ic_aviso_log HTTP %d: %s" % (e.code, e.read()[:200]))


def inserir(tabela, linhas, timeout=30):
    """INSERT em lote via PostgREST (service_role) — usado pelo Conselho Editorial para gravar
    cada voto em `ic_redes_revisao` (redes/conselho/conselho.py)."""
    req = urllib.request.Request(URL + "/rest/v1/" + tabela, method="POST",
                                  data=json.dumps(linhas).encode("utf-8"),
                                  headers=_cab({"Prefer": "return=minimal"}))
    try:
        urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError("INSERT %s HTTP %d: %s" % (tabela, e.code, e.read()[:300]))


def upsert(tabela, linhas, on_conflict, timeout=30):
    """UPSERT em lote via PostgREST (`on_conflict` = colunas da chave unica, separadas por virgula) — usado pela
    coleta diaria de metricas (redes/alcance.py -> ic_redes_metrica, 1 linha por post por dia)."""
    req = urllib.request.Request(URL + "/rest/v1/" + tabela + "?on_conflict=" + on_conflict, method="POST",
                                  data=json.dumps(linhas).encode("utf-8"),
                                  headers=_cab({"Prefer": "resolution=merge-duplicates,return=minimal"}))
    try:
        urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError("UPSERT %s HTTP %d: %s" % (tabela, e.code, e.read()[:300]))
