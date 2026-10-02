# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem tocar o banco, sem tocar o Supabase) de
`redes/ig_renovar_token.py::renovar` — mesmo padrão de `redes/testar_publicar_instagram.py`
(23/09/2026, renovação automática do token do Instagram, PLAYBOOK §7-V-5/§23set2026-renovacao).

Cobre: (1) sucesso -> grava token+expiração novos, registra 'renovado', nunca manda e-mail;
(2) HTTP de erro -> nunca grava, manda e-mail à central, registra entregue:false;
(3) token ausente na chave -> mesmo alerta, sem chamar a rede;
(4) resposta 200 sem access_token -> mesmo alerta;
(5) --qa redireciona o e-mail para central+qa-ig@innconta.com.br, nunca para a central real;
(6) controle negativo de escrita: `--chave`/token de override NUNCA é gravado de volta em
    ic_segredo (só a chave real de produção é).

Roda `python3 redes/testar_ig_renovar_token.py` a partir da raiz do repo; sai com código != 0 se
qualquer prova falhar."""
import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import ig_renovar_token as igr  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %s (esperado %s)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


class _RespostaFake:
    def __init__(self, corpo):
        self._corpo = corpo

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_urlopen_original = igr.urllib.request.urlopen
_segredo_original = igr.supa.segredo
_gravar_original = igr.supa.gravar_segredo
_email_original = igr.supa.enviar_email
_aviso_original = igr.supa.registrar_aviso


def _restaurar():
    igr.urllib.request.urlopen = _urlopen_original
    igr.supa.segredo = _segredo_original
    igr.supa.gravar_segredo = _gravar_original
    igr.supa.enviar_email = _email_original
    igr.supa.registrar_aviso = _aviso_original


print("== renovar() — controle POSITIVO: 200 com access_token novo -> grava token+expiração, "
      "registra 'renovado', NUNCA manda e-mail ==")
chamadas_gravar, chamadas_email, chamadas_aviso = [], [], []
igr.supa.segredo = lambda chave: "token-atual-de-teste-nao-e-segredo-real"
igr.urllib.request.urlopen = lambda req, timeout=30: _RespostaFake(json.dumps({"access_token": "token-novo-de-teste", "expires_in": 5184000}).encode())
igr.supa.gravar_segredo = lambda chave, valor: chamadas_gravar.append((chave, valor))
igr.supa.enviar_email = lambda *a, **k: chamadas_email.append((a, k))
igr.supa.registrar_aviso = lambda *a, **k: chamadas_aviso.append((a, k))
try:
    r = igr.renovar()
    checar("sucesso -> ok True", r["ok"], True)
    checar("sucesso -> renovado True", r["renovado"], True)
    checar("gravou token + expiração (2 chamadas)", len(chamadas_gravar) == 2, True)
    checar("nunca chamou enviar_email no sucesso", len(chamadas_email) == 0, True)
    checar("registrou aviso 1x", len(chamadas_aviso) == 1, True)
    if chamadas_aviso:
        _, kw = chamadas_aviso[0]
        checar("aviso com entregue=True", kw.get("entregue"), True)
finally:
    _restaurar()

print("\n== renovar() — controle NEGATIVO: HTTP 400 da Graph API -> NUNCA grava, manda e-mail à "
      "CENTRAL (nunca caixa pessoal), registra entregue:false ==")
chamadas_gravar, chamadas_email, chamadas_aviso = [], [], []
igr.supa.segredo = lambda chave: "token-atual-de-teste-nao-e-segredo-real"


def _urlopen_erro_400(req, timeout=30):
    raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"mock"}'))


igr.urllib.request.urlopen = _urlopen_erro_400
igr.supa.gravar_segredo = lambda chave, valor: chamadas_gravar.append((chave, valor))
igr.supa.enviar_email = lambda *a, **k: chamadas_email.append((a, k))
igr.supa.registrar_aviso = lambda *a, **k: chamadas_aviso.append((a, k))
try:
    r = igr.renovar()
    checar("HTTP 400 -> ok False", r["ok"], False)
    checar("HTTP 400 -> renovado False", r["renovado"], False)
    checar("HTTP 400 -> nunca gravou nada", len(chamadas_gravar), 0)
    checar("HTTP 400 -> mandou e-mail 1x", len(chamadas_email) == 1, True)
    if chamadas_email:
        args, _ = chamadas_email[0]
        checar("e-mail foi para a CENTRAL técnica (AOP-01), nunca pessoal", args[1], "central@innconta.com.br")
        checar("assunto menciona 'NÃO renovou'", "NÃO renovou" in args[0], True)
    checar("registrou aviso com entregue=False", chamadas_aviso[0][1].get("entregue") if chamadas_aviso else None, False)
finally:
    _restaurar()

print("\n== renovar() — controle NEGATIVO: chave inexistente/token ausente -> mesmo alerta, "
      "SEM tocar a rede (nunca chama urlopen) ==")
chamadas_gravar, chamadas_email, chamou_rede = [], [], {"sim": False}
igr.supa.segredo = lambda chave: None  # chave 'ig_access_token_qa_inexistente' não tem valor


def _urlopen_nao_deveria_chamar(req, timeout=30):
    chamou_rede["sim"] = True
    raise AssertionError("não deveria chamar a rede sem token")


igr.urllib.request.urlopen = _urlopen_nao_deveria_chamar
igr.supa.gravar_segredo = lambda chave, valor: chamadas_gravar.append((chave, valor))
igr.supa.enviar_email = lambda *a, **k: chamadas_email.append((a, k))
igr.supa.registrar_aviso = lambda *a, **k: None
try:
    r = igr.renovar(chave="ig_access_token_qa_inexistente")
    checar("sem token -> ok False", r["ok"], False)
    checar("sem token -> motivo token_ausente", r["motivo"], "token_ausente")
    checar("sem token -> nunca chamou a rede", chamou_rede["sim"], False)
    checar("sem token -> nunca gravou nada", len(chamadas_gravar), 0)
    checar("sem token -> mandou e-mail 1x", len(chamadas_email) == 1, True)
finally:
    _restaurar()

print("\n== renovar() — controle NEGATIVO: resposta 200 sem access_token -> mesmo alerta ==")
chamadas_email = []
igr.supa.segredo = lambda chave: "token-atual-de-teste-nao-e-segredo-real"
igr.urllib.request.urlopen = lambda req, timeout=30: _RespostaFake(json.dumps({"sem_token": True}).encode())
igr.supa.gravar_segredo = lambda chave, valor: (_ for _ in ()).throw(AssertionError("não deveria gravar"))
igr.supa.enviar_email = lambda *a, **k: chamadas_email.append((a, k))
igr.supa.registrar_aviso = lambda *a, **k: None
try:
    r = igr.renovar()
    checar("200 sem access_token -> ok False", r["ok"], False)
    checar("200 sem access_token -> mandou e-mail 1x", len(chamadas_email) == 1, True)
finally:
    _restaurar()

print("\n== renovar(modo_qa=True) — e-mail de falha vai para central+qa-ig@innconta.com.br, "
      "NUNCA para a central real (mesmo padrão de redes/informe_comercial.py) ==")
chamadas_email = []
igr.supa.segredo = lambda chave: None
igr.supa.enviar_email = lambda *a, **k: chamadas_email.append((a, k))
igr.supa.registrar_aviso = lambda *a, **k: None
try:
    r = igr.renovar(modo_qa=True)
    checar("QA -> ok False (chave real sem valor no teste)", r["ok"], False)
    if chamadas_email:
        args, _ = chamadas_email[0]
        checar("QA -> destino é central+qa-ig@innconta.com.br", args[1], "central+qa-ig@innconta.com.br")
finally:
    _restaurar()

print("\n== renovar() — controle: --token override NUNCA é gravado de volta em ic_segredo "
      "(só a chave real de produção é) ==")
chamadas_gravar = []
igr.urllib.request.urlopen = lambda req, timeout=30: _RespostaFake(json.dumps({"access_token": "token-novo-de-teste", "expires_in": 5184000}).encode())
igr.supa.gravar_segredo = lambda chave, valor: chamadas_gravar.append((chave, valor))
igr.supa.enviar_email = lambda *a, **k: None
igr.supa.registrar_aviso = lambda *a, **k: None
try:
    r = igr.renovar(token_override="token-de-controle-negativo-nao-e-segredo-real")
    checar("override renovou (API respondeu 200) mas ok True continua", r["ok"], True)
    checar("override -> NUNCA grava em ic_segredo (é só teste)", len(chamadas_gravar), 0)
finally:
    _restaurar()

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (7 cenários de ig_renovar_token.renovar()).")
