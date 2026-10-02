# -*- coding: utf-8 -*-
"""Os dois únicos e-mails do Conselho Editorial ao CVO (o resto é automático):

1. ESCALADAS (semanal, junto do lote): lista TODAS as peças em status 'escalado' — não só as desta
   semana — com os motivos do conselho e 2 links assinados: "Aprovar mesmo assim" / "Descartar"
   (reaproveita functions/api/redes-aprovar.js, escopo 'conteudo'). Reenviar toda semana, com link
   novo de 7 dias, é o que impede o BECO (PJC-01c): peça escalada nunca fica presa num link vencido.
   Sem escalada nenhuma = nenhum e-mail.
2. RESUMO SEMANAL depois do fato (segunda, junto do informe, SÓ ao CVO): publicadas na semana (cada
   uma com link "Retirar post", escopo 'retirada'), aprovadas pelo conselho, escaladas, barradas e
   os motivos mais frequentes dos revisores.

Destino: CVO_EMAIL (e a central técnica em cópia nas escaladas). --qa manda só para
central+qa-conselho@innconta.com.br. Nunca WhatsApp em QA."""
import collections
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
AQUI = os.path.dirname(os.path.abspath(__file__))
REDES = os.path.dirname(AQUI)
for p in (AQUI, REDES, os.path.join(REDES, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)
import email_lote  # noqa: E402
import estoque  # noqa: E402
import hmac_link  # noqa: E402
import supa  # noqa: E402

BASE_URL = os.environ.get("BASE_URL", "https://innconta.com.br")
CENTRAL = "central@innconta.com.br"
# e-mail do CVO só pelo Secret CVO_EMAIL (repositório público desde 02/10/2026); sem ele, a central recebe
CVO_EMAIL = os.environ.get("CVO_EMAIL") or CENTRAL
QA_EMAIL = "central+qa-conselho@innconta.com.br"
PREFIXO_QA = "qa-conselho-"


def _segredo_hmac():
    s = os.environ.get("REDES_APROVACAO_SECRET", "")
    if not s:
        raise RuntimeError("REDES_APROVACAO_SECRET ausente")
    return s


def _texto_da_peca(marca, row):
    if row.get("texto_aprovado"):
        return row["texto_aprovado"]
    try:
        return estoque.ler(estoque.caminho(marca, row["peca_id"])).get("_corpo", "")
    except Exception:
        return "(texto no estoque não encontrado nesta rodada)"


ACAO_ESCALADA = ("AÇÃO (central técnica): corrigir cada ponto acima na peça do estoque (texto, arte, fonte), provar com "
                 "`python redes/lote_aprovacao.py --qa --peca-id <id>` (só provedores de reserva) e devolver à fila "
                 "(apagar a linha 'escalado' de ic_redes_publicacao e de ic_redes_revisao). Nada disto pede decisão do CVO.")


def itens_escaladas(marca, linhas):
    itens = []
    for row in linhas:
        motivos = row.get("conselho_motivos") or []
        itens.append({
            "meta": "MARCA %s · %s · %s · %d volta(s) do conselho" % (
                row.get("marca") or marca, row.get("canal", ""), row["peca_id"], row.get("conselho_rodadas") or 0),
            "texto": "MARCA: %s\nMOTIVOS DO CONSELHO:\n- " % (row.get("marca") or marca) + "\n- ".join(str(m)[:300] for m in motivos[:8]) +
                     "\n\n" + ACAO_ESCALADA + "\n\nPEÇA:\n" + _texto_da_peca(marca, row)[:900],
            "imagem_url": None,
            "botoes": [],
        })
    return itens


def destinatarios_escaladas(qa=False):
    """Escalada NUNCA vai ao CVO (ordem de 25/09/2026): só a central técnica (QA: só a caixa de prova)."""
    return [QA_EMAIL] if qa else [CENTRAL]


def enviar_escaladas(marca="innconta", qa=False, linhas=None):
    """Manda 1 e-mail com todas as escaladas à CENTRAL. `linhas` injetável (QA/teste); senão lê do banco."""
    if linhas is None:
        filtro = ("marca=eq.%s&" % marca) if marca else ""  # marca=None: escaladas de TODAS as marcas
        linhas = supa.select("ic_redes_publicacao", filtro + "status=eq.escalado&select=*&order=enviado_em")
        if not qa:
            linhas = [l for l in linhas if not l["peca_id"].startswith(PREFIXO_QA)]
    if not linhas:
        print("escaladas: nenhuma — nenhum e-mail.")
        return {"escaladas": 0}
    html = email_lote.montar(
        "%d peça(s) escalada(s) pelo Conselho Editorial: correção técnica" % len(linhas),
        "O conselho automático (5 revisores + redator, até 3 voltas) não chegou a consenso nestas peças. "
        "Cada uma traz o motivo de cada reprovação e a ação. Fila técnica: não exige decisão do CVO.",
        itens_escaladas(marca, linhas),
        rodape_extra="Conselho Editorial · Consultor de Redes · InnConta",
    )
    para = destinatarios_escaladas(qa)
    nomes = sorted({l.get("marca") or marca or "innconta" for l in linhas})
    resp = supa.enviar_email("InnConta · %d peça(s) escalada(s) pelo Conselho Editorial [%s] (correção técnica)" % (
        len(linhas), ", ".join(nomes)), para, html)
    print("e-mail de escaladas:", resp, "->", para)
    return {"escaladas": len(linhas), "email_resp": resp, "para": para}


def montar_resumo(marca="innconta", qa=False, hoje=None, enviar=True):
    hoje = hoje or datetime.date.today()
    ini = (hoje - datetime.timedelta(days=7)).isoformat()
    seg = _segredo_hmac()
    publicadas = supa.select("ic_redes_publicacao",
                             "marca=eq.%s&publicado_em=gte.%s&select=*&order=publicado_em" % (marca, ini))
    aprovadas = supa.select("ic_redes_publicacao",
                            "marca=eq.%s&aprovado_por=eq.conselho&aprovado_em=gte.%s&select=peca_id,canal,conselho_rodadas" % (marca, ini))
    escaladas = supa.select("ic_redes_publicacao", "marca=eq.%s&status=eq.escalado&select=peca_id" % marca)
    descartadas = supa.select("ic_redes_publicacao",
                              "marca=eq.%s&status=eq.recusado&aprovado_em=gte.%s&select=peca_id" % (marca, ini))
    votos = supa.select("ic_redes_revisao", "criado_em=gte.%s&passa=eq.false&select=peca_id,revisor,motivos" % ini)
    votos = [v for v in votos if not v["peca_id"].startswith(PREFIXO_QA)]
    if not qa:  # linhas de prova nunca entram no resumo real
        publicadas, aprovadas, escaladas, descartadas = (
            [x for x in lst if not x["peca_id"].startswith(PREFIXO_QA)]
            for lst in (publicadas, aprovadas, escaladas, descartadas))
    pausa = (supa.segredo("redes_pausa") or "").strip() == "1"

    por_revisor = collections.Counter(v["revisor"] for v in votos)
    exemplos = collections.defaultdict(list)
    for v in votos:
        for m in (v.get("motivos") or [])[:1]:
            if len(exemplos[v["revisor"]]) < 2:
                exemplos[v["revisor"]].append("%s: %s" % (v["peca_id"], str(m)[:180]))

    itens = []
    for row in publicadas:
        botoes = []
        if row.get("status") == "publicado":
            botoes = [("Retirar post", hmac_link.gerar_link(BASE_URL, seg, row["id"], "retirar", escopo="retirada"), "recusar")]
        itens.append({"meta": "%s · %s · %s" % (row.get("canal", ""), (row.get("publicado_em") or "")[:10], row["peca_id"]),
                      "texto": (row.get("url_post") or "(sem link do post)") + ("\nRETIRADO" if row.get("status") == "retirado" else ""),
                      "imagem_url": None, "botoes": botoes})
    linhas_barradas = "\n".join("- %s: %d reprovação(ões). Ex.: %s" % (r, n, " | ".join(exemplos[r]))
                                for r, n in por_revisor.most_common())
    itens.append({"meta": "Conselho Editorial · últimos 7 dias", "imagem_url": None, "botoes": [],
                  "texto": "Aprovadas pelo conselho: %d\nEscaladas (em correção técnica na central, sem ação sua): %d\nDescartadas: %d\n"
                           "Chave de parada (ic_segredo.redes_pausa): %s\n\nReprovações por revisor:\n%s" % (
                               len(aprovadas), len(escaladas), len(descartadas), "LIGADA" if pausa else "desligada",
                               linhas_barradas or "- nenhuma")})
    resumo = {"publicadas": len(publicadas), "aprovadas_conselho": len(aprovadas), "escaladas": len(escaladas),
              "descartadas": len(descartadas), "reprovacoes": dict(por_revisor), "pausa": pausa}
    if not enviar:
        return resumo
    html = email_lote.montar("Redes · resumo da semana (depois do fato)",
                             "O que saiu, o que o conselho barrou e por quê. Cada post publicado tem o link para retirá-lo.",
                             itens, rodape_extra="Conselho Editorial · Consultor de Redes · InnConta")
    para = QA_EMAIL if qa else CVO_EMAIL
    resp = supa.enviar_email("InnConta · redes: %d publicada(s), %d escalada(s) na semana" % (
        len(publicadas), len(escaladas)), para, html)
    print("resumo semanal:", resumo, "->", para, resp)
    resumo["email_resp"] = resp
    return resumo


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["resumo", "escaladas"])
    ap.add_argument("--marca", default="innconta")
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if a.acao == "resumo":
        print(montar_resumo(a.marca, a.qa))
    else:
        print(enviar_escaladas(a.marca, a.qa))
