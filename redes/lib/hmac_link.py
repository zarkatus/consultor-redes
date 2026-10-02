# -*- coding: utf-8 -*-
"""Token de aprovação por link — HMAC de uso único (na prática: a UNICIDADE vem do estado no
banco, não do token — ver functions/api/redes-aprovar.js). Espelha exatamente o que a Pages
Function calcula em JS via Web Crypto (SubtleCrypto HMAC-SHA256); qualquer mudança aqui exige a
mesma mudança lá — os dois lados são testados um contra o outro em redes/testar_hmac_link.py.

`escopo` entra na assinatura para que um link de aprovação de CONTEÚDO nunca possa ser reusado
como se fosse um link de aprovação de CALENDÁRIO (ou vice-versa) — mesmo id/acao/exp."""
import hashlib
import hmac
import time


def assinar(segredo, escopo, peca_id, acao, exp_unix):
    msg = "%s|%s|%s|%d" % (escopo, peca_id, acao, int(exp_unix))
    return hmac.new(segredo.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def gerar_link(base_url, segredo, peca_id, acao, escopo="conteudo", validade_dias=7, agora=None, extra=None):
    agora = agora or time.time()
    exp = int(agora + validade_dias * 86400)
    sig = assinar(segredo, escopo, peca_id, acao, exp)
    url = "%s/api/redes-aprovar?id=%s&acao=%s&escopo=%s&exp=%d&sig=%s" % (
        base_url.rstrip("/"), peca_id, acao, escopo, exp, sig
    )
    if extra:
        import urllib.parse
        url += "".join("&%s=%s" % (k, urllib.parse.quote(str(v))) for k, v in extra.items())
    return url


def gerar_link_expirado(base_url, segredo, peca_id, acao, escopo="conteudo", agora=None):
    """Só para prova/QA: assina corretamente mas com exp no passado — prova que a checagem de
    validade é pela DATA, não só pela assinatura."""
    agora = agora or time.time()
    exp = int(agora - 3600)
    sig = assinar(segredo, escopo, peca_id, acao, exp)
    return "%s/api/redes-aprovar?id=%s&acao=%s&escopo=%s&exp=%d&sig=%s" % (
        base_url.rstrip("/"), peca_id, acao, escopo, exp, sig
    )


def verificar(segredo, escopo, peca_id, acao, exp_unix, sig, agora=None):
    agora = agora or time.time()
    esperado = assinar(segredo, escopo, peca_id, acao, exp_unix)
    if not hmac.compare_digest(esperado, sig or ""):
        return False, "assinatura_invalida"
    if agora > int(exp_unix):
        return False, "expirado"
    return True, "ok"
