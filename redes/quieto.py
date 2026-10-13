# -*- coding: utf-8 -*-
"""Roda um comando com a saída FORA do log do Actions (02/10/2026: o repositório é público, e o log de run de
repositório público é público). Os scripts do Consultor imprimem texto de peça, motivo do Conselho e da guarda
(inclusive nome de cliente barrado): nada disso pode ir ao log aberto.

    python redes/quieto.py <rotulo> -- <comando> [args...]

No log público sai só "<rotulo>: exit N, L linhas". A saída inteira fica em $RUNNER_TEMP/quieto-<rotulo>.log
(some com o runner). Em falha (ou com QUIETO_LOG_CENTRAL=true), a cauda vai por e-mail à central técnica
(AOP-01) pela RPC ic_email do banco InnConta. Devolve o exit code do comando: o passo falha quando ele falha.
Sem SB_URL/SB_SERVICE_ROLE o e-mail é pulado com aviso (o exit code continua valendo).

Resumo público (13/10/2026): o comando pode deixar linhas de ESTADO no log aberto com `quieto.anotar("chave=valor ...")`
(ex.: `publicar marca=innconta estado=cedo`). Só passa linha no alfabeto de _RESUMO_OK (minúsculas, dígitos, `_ : = - , .`
e espaço), até _RESUMO_MAX linhas: texto de peça, nome próprio e motivo do Conselho não cabem nesse alfabeto. Nasceu de
~40 min de depuração de um "exit 0 sem publicar" que era só o guard de horário."""
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

CENTRAL = "central@innconta.com.br"
CAUDA = 150
_RESUMO_ENV = "QUIETO_RESUMO"
_RESUMO_OK = re.compile(r"[a-z0-9_:=,. -]{1,160}")
_RESUMO_MAX = 30


def anotar(linha):
    """Chamado pelo comando filho: deixa uma linha de estado para o log público. Fora do quieto.py (sem a variável)
    não faz nada; nunca levanta."""
    arq = os.environ.get(_RESUMO_ENV)
    if not arq:
        return
    try:
        with open(arq, "a", encoding="utf-8") as f:
            f.write(" ".join(str(linha).splitlines()) + chr(10))
    except Exception:
        pass


def _resumo_publico(arq):
    try:
        with open(arq, encoding="utf-8", errors="replace") as f:
            linhas = f.read().splitlines()
    except Exception:
        return []
    boas = [l for l in linhas if _RESUMO_OK.fullmatch(l)]
    if len(boas) < len(linhas):
        boas.append("resumo: %d linha(s) fora do alfabeto publico, omitida(s)" % (len(linhas) - len(boas)))
    return boas[:_RESUMO_MAX]


def _email(rotulo, codigo, cauda):
    url = (os.environ.get("SB_URL") or os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SB_SERVICE_ROLE") or os.environ.get("SB_SERVICE") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not (url and key):
        print("%s: sem SB_URL/SB_SERVICE_ROLE, cauda do log NAO enviada a central" % rotulo)
        return
    run = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", ""), os.environ.get("GITHUB_REPOSITORY", ""),
                                     os.environ.get("GITHUB_RUN_ID", ""))
    situacao = "falhou (exit %d)" % codigo if codigo else "rodou (exit 0, log pedido)"
    corpo = {"p_para": CENTRAL,
             "p_assunto": "[%s] Consultor de redes: %s %s" % ("ALERTA" if codigo else "LOG", rotulo, situacao),
             "p_html": ("<p><b>Passo:</b> <code>%s</code> %s.</p><p><b>Run:</b> %s</p>"
                        "<p>Últimas %d linhas (o log público do Actions não traz a saída, repositório público):</p>"
                        "<pre style=\"font-size:12px;white-space:pre-wrap\">%s</pre>")
                       % (html.escape(rotulo), situacao, html.escape(run), CAUDA, html.escape(cauda))}
    req = urllib.request.Request(url + "/rest/v1/rpc/ic_email", method="POST", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print("%s: cauda do log enviada a central" % rotulo)
    except Exception as e:  # o e-mail nunca troca o resultado do passo
        print("%s: envio da cauda a central falhou (%s)" % (rotulo, type(e).__name__))


def main(argv):
    if len(argv) < 3 or argv[1] != "--":
        print(__doc__)
        return 2
    rotulo, cmd = argv[0], argv[2:]
    pasta = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    arq = os.path.join(pasta, "quieto-%s.log" % "".join(c if c.isalnum() or c in "-_" else "_" for c in rotulo))
    resumo = arq[:-4] + ".resumo"
    if os.path.exists(resumo):
        os.remove(resumo)
    with open(arq, "w", encoding="utf-8", errors="replace") as f:
        codigo = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, env=dict(os.environ, **{_RESUMO_ENV: resumo}))
    with open(arq, encoding="utf-8", errors="replace") as f:
        linhas = f.read().splitlines()
    print("%s: exit %d, %d linhas (saida fora do log publico)" % (rotulo, codigo, len(linhas)))
    for l in _resumo_publico(resumo):
        print("  " + l)
    if codigo or os.environ.get("QUIETO_LOG_CENTRAL", "").lower() == "true":
        _email(rotulo, codigo, "\n".join(linhas[-CAUDA:]))
    return codigo


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
