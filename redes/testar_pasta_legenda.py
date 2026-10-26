"""Prova: a legenda da InnConta no Instagram nomeia a pasta (26/10/2026). Positivo + controles negativos."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publicar  # noqa: E402

NL = chr(10) * 2
base = "Gancho." + NL + "Corpo." + NL + "innconta.com.br/frente/contas-consumo"
falhas = []


def prova(nome, ok):
    print(("OK   - " if ok else "FALHA - ") + nome)
    if not ok:
        falhas.append(nome)


r = publicar._com_pasta(base, {}, "innconta")
prova("pasta entra logo apos o gancho", r.split(NL)[1] == "\U0001F4C2 Pasta InnConta: Contas de consumo")
prova("gancho continua a 1a linha", r.split(NL)[0] == "Gancho.")
prova("idempotente (reconciliacao compara o mesmo texto)", publicar._com_pasta(r, {}, "innconta") == r)
prova("controle NEGATIVO: outra marca intacta", publicar._com_pasta(base, {}, "fairco") == base)
prova("controle NEGATIVO: sem pasta (feriado) intacto", publicar._com_pasta("Feriado." + NL + "Texto", {}, "innconta") == "Feriado." + NL + "Texto")
prova("nota_origem da peca vale", "Energia" in publicar._com_pasta("Gancho." + NL + "Corpo", {"nota_origem": "innconta.com.br/frente/energia (x)"}, "innconta"))
print("TODAS AS PROVAS PASSARAM" if not falhas else "FALHARAM: %s" % falhas)
sys.exit(1 if falhas else 0)
