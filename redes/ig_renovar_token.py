# -*- coding: utf-8 -*-
"""InnConta · Consultor de Redes — renovação automática do token do Instagram
(`ic_segredo.ig_access_token`, conta `@innconta.oficial`, PLAYBOOK §7-V-5).

Por que existe: o token de longa duração emitido pelo painel da Meta dura 60 dias (armadilha
documentada em §7-V-5, "ASSUMIDO... renovar via ig_refresh_token bem antes do prazo por
segurança"). O GitHub Actions NÃO consegue atualizar o próprio Secret do repo em tempo de
execução — por isso a renovação vive no banco (`ic_segredo`, PLAYBOOK §"ic_segredo"/§7-E), não
no GitHub: `redes/publicar_instagram.py::_token` já lê de lá primeiro (fallback `IG_ACCESS_TOKEN`
só até o primeiro seed).

Fluxo (documentado pela Meta, `graph.instagram.com/refresh_access_token`):
1. lê o token ATUAL de `ic_segredo.ig_access_token` (ou de `--chave`/`--token`, só para QA —
   nunca em produção);
2. `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<atual>`;
3. 200 -> grava o token NOVO + nova expiração (`ig_token_expira_em`) em `ic_segredo`, registra
   'renovado' em `ic_aviso_log` (`redes/lib/supa.py::registrar_aviso`);
4. qualquer falha (HTTP != 200, exceção de rede, resposta sem `access_token`, ou a própria chave
   sem valor pra renovar) -> e-mail à CENTRAL TÉCNICA (`central@innconta.com.br`, AOP-01: alerta
   técnico nunca na caixa pessoal do CVO) com o status observado e a ação (gerar token novo no
   painel Meta e gravar em `ic_segredo`) + registro `entregue:false` em `ic_aviso_log`.

Roda mensal (dia 10, 06:00 BRT — o token de 60 dias renova a cada 30 sem risco, folga de 30 dias
antes de vencer) via `.github/workflows/redes-consultor.yml`, tarefa `renovar_ig`, e por
`workflow_dispatch` a qualquer momento. `--qa` redireciona o e-mail de falha para
`central+qa-ig@innconta.com.br` (nunca à central real) — mesmo padrão de
`redes/informe_comercial.py`.

NUNCA imprime o token (nem parcial, nem comprimento junto de outro dado que o identifique) — só
booleans/status HTTP/motivo/data de expiração."""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import marcas  # noqa: E402
import supa  # noqa: E402

CHAVE_TOKEN = "ig_access_token"
CHAVE_EXPIRA = "ig_token_expira_em"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
CENTRAL = "central@innconta.com.br"
CENTRAL_QA = "central+qa-ig@innconta.com.br"


def _alertar_central(status, motivo, modo_qa, marca="innconta", chave=CHAVE_TOKEN):
    """AOP-01: alerta operacional (canal caiu / credencial venceu) vai SEMPRE para a central
    técnica, nunca para a caixa pessoal do CVO. Mensagem com valor observado + ação (AOP-01e)."""
    destino = CENTRAL_QA if modo_qa else CENTRAL
    status_txt = str(status) if status is not None else "sem resposta HTTP (falha de rede/execução)"
    assunto = "InnConta · token do Instagram NÃO renovou (%s)" % marca
    corpo_html = (
        "<p>O token de acesso do Instagram (<code>ic_segredo.%s</code>, marca "
        "<strong>%s</strong>, Consultor de Redes) <strong>NÃO renovou</strong>.</p>"
        "<p><strong>Status observado:</strong> %s<br><strong>Motivo:</strong> %s</p>"
        "<p><strong>Ação:</strong> gerar um token novo no painel da Meta "
        "(developers.facebook.com → app \"InnConta Consultor de Redes\" → API do Instagram → "
        "Configuração da API com login do Instagram → 2. Gerar tokens de acesso) e gravar o valor "
        "em <code>public.ic_segredo</code> (chave <code>%s</code>, + "
        "a chave de expiracao correspondente com a nova data) — passo a passo em PLAYBOOK.md §7-V-5.</p>"
    ) % (chave, marca, status_txt, motivo, chave)
    email_ok = False
    try:
        supa.enviar_email(assunto, destino, corpo_html, remetente="Central InnConta <central@innconta.com.br>")
        email_ok = True
    except Exception as e:
        print("ALERTA: renovação falhou E o e-mail à central também falhou:", type(e).__name__, "-", e)
    try:
        supa.registrar_aviso(
            "token do Instagram NAO renovou: status %s; acao: gerar token novo no painel Meta e gravar em ic_segredo" % status_txt,
            marca=marca, canal="instagram_token", entregue=False,
            veredito={"renovado": False, "status": status, "motivo": motivo, "email_central": email_ok, "destino": destino},
        )
    except Exception as e:
        print("aviso: falhou ao registrar em ic_aviso_log (não bloqueia o alerta já enviado):", e)
    print("NAO renovado — alerta técnico enviado a", destino, "- email_ok:", email_ok)
    return email_ok


def renovar(chave=CHAVE_TOKEN, token_override=None, modo_qa=False, marca="innconta", chave_expira=CHAVE_EXPIRA,
            chave_real=CHAVE_TOKEN, alertar=True):
    """Devolve um dict de resultado (nunca levanta exceção pro chamador — mesmo contrato de
    publicar_via_instagram/publicar_via_linkedin). Chave-only: usa `token_override` só quando
    passado explicitamente (QA/controle negativo) — em produção sempre lê de `ic_segredo`.
    `alertar=False` (redes/vigia.py, 30/09/2026): não manda o e-mail próprio de falha — o vigia consolida a falha no
    e-mail único dele à central (um e-mail por rodada, não um por marca)."""
    alerta =_alertar_central if alertar else (lambda *a, **k: False)
    token_atual = token_override if token_override is not None else supa.segredo(chave)
    if not token_atual:
        motivo = "token_ausente (chave '%s' sem valor em ic_segredo)" % chave
        alerta(None, motivo, modo_qa, marca, chave_real)
        return {"ok": False, "renovado": False, "motivo": "token_ausente", "qa": modo_qa}

    url = REFRESH_URL + "?" + urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": token_atual})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        dados = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        alerta(e.code, "GET refresh_access_token falhou", modo_qa, marca, chave_real)
        return {"ok": False, "renovado": False, "motivo": "http_%d" % e.code, "status": e.code, "qa": modo_qa}
    except Exception as e:
        alerta(None, "exceção %s ao chamar refresh_access_token" % type(e).__name__, modo_qa, marca, chave_real)
        return {"ok": False, "renovado": False, "motivo": "excecao_%s" % type(e).__name__, "qa": modo_qa}

    novo_token = dados.get("access_token")
    if not novo_token:
        alerta(200, "resposta 200 sem access_token no corpo", modo_qa, marca, chave_real)
        return {"ok": False, "renovado": False, "motivo": "sem_access_token_na_resposta", "status": 200, "qa": modo_qa}

    expires_in = dados.get("expires_in") or (60 * 86400)  # segundos; 60 dias é o padrão documentado
    dias = max(1, round(expires_in / 86400))
    nova_expira = (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()

    # só grava de volta a chave real — nunca sobrescreve uma chave de QA/teste com o token novo,
    # pra não confundir produção com um caminho de controle negativo.
    if chave == chave_real and token_override is None:
        supa.gravar_segredo(chave_real, novo_token)
        supa.gravar_segredo(chave_expira, nova_expira)

    texto = "token do Instagram renovado (%s), expira em %s" % (marca, nova_expira)
    try:
        supa.registrar_aviso(texto, marca=marca, canal="instagram_token", entregue=True,
                              veredito={"renovado": True, "expira_em": nova_expira})
    except Exception as e:
        print("aviso: renovou mas falhou ao registrar em ic_aviso_log:", e)
    print("renovado:", texto)
    return {"ok": True, "renovado": True, "expira_em": nova_expira, "qa": modo_qa}


def renovar_marca(marca, modo_qa=False, alertar=True):
    """Renova o token de UMA marca (`ic_segredo.ig_access_token_<marca>` + `ig_token_expira_em_<marca>`)."""
    ch = marcas.chave_token(marca)
    return renovar(chave=ch, modo_qa=modo_qa, marca=marca, chave_expira=marcas.chave_expira(marca), chave_real=ch,
                   alertar=alertar)


def renovar_todas(modo_qa=False):
    """Itera as marcas com publicar.instagram=true. Falha numa NAO derruba as outras (cada falha ja alertou a central)."""
    out = {}
    for m in (marcas.instagram_ativas() or []):
        try:
            out[m] = renovar_marca(m, modo_qa)
        except Exception as e:
            print("renovacao[%s] FALHOU (segue nas demais): %s: %s" % (m, type(e).__name__, str(e)[:160]))
            out[m] = {"ok": False, "motivo": "excecao_%s" % type(e).__name__}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", action="store_true", help="e-mail de falha vai para central+qa-ig@innconta.com.br")
    ap.add_argument("--chave", default=CHAVE_TOKEN,
                     help="chave alternativa em ic_segredo (só QA/controle negativo — ex. chave inexistente)")
    ap.add_argument("--token", default=None,
                     help="override direto do token (só QA/controle negativo — nunca em produção; nunca logado)")
    a = ap.parse_args()
    if a.chave == CHAVE_TOKEN and a.token is None:
        resultado = renovar_todas(modo_qa=a.qa)
    else:
        resultado = renovar(chave=a.chave, token_override=a.token, modo_qa=a.qa)
    print(resultado)
    sys.exit(0)  # falha de renovação já foi tratada (alerta enviado) — não derruba o job do Actions
