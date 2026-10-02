# -*- coding: utf-8 -*-
"""Relatório mensal (dia 1, por e-mail ao CVO, 1 página): entregas do mês anterior × mínimo
contratual de referência (10 postagens: 6 imagens feed+stories + 4 vídeos), o que ficou
aguardando/expirou, e métricas nativas quando houver API — por enquanto: cadência cumprida
(redes.json), contatos do mês com origem=rede:* (ic-origem.js já grava a origem nos formulários
desde 22/09/2026 — candidaturas de parceiro, Inn Host e leads), cliques via redes.json.
Agnóstico de marca (PGA-01): roda por marca, nenhum nome de marca no código."""
import calendar
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import supa  # noqa: E402

# e-mail do CVO só pelo Secret CVO_EMAIL (repositório público desde 02/10/2026); sem ele, a central recebe
CVO_EMAIL = os.environ.get("CVO_EMAIL") or "central@innconta.com.br"
MINIMO_POSTAGENS = 10
MINIMO_IMAGENS = 6
MINIMO_VIDEOS = 4


def mes_anterior(hoje=None):
    hoje = hoje or datetime.date.today()
    primeiro_deste_mes = hoje.replace(day=1)
    ultimo_mes_anterior = primeiro_deste_mes - datetime.timedelta(days=1)
    return "%04d-%02d" % (ultimo_mes_anterior.year, ultimo_mes_anterior.month)


TABELAS_COM_ORIGEM = ("ic_parceiro_candidatura", "ic_inn_host_candidatura", "ic_lead")


def janela_do_mes(mes_ref):
    """'2026-08' -> ('2026-08-01', '2026-09-01') para filtrar criado_em >= ini e < fim."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    ini = datetime.date(ano, mes, 1)
    fim = datetime.date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1)
    return ini.isoformat(), fim.isoformat()


def contatos_de_rede_no_mes(mes_ref):
    """Contatos do mês cuja origem foi classificada como rede (rede:linkedin, rede:instagram...)
    por ic-origem.js (22/09/2026) e gravada por ic_parceiro_candidatar / inn-host / contato.
    Devolve (lista de linhas, contagem por origem). Falha de uma tabela não derruba as outras."""
    ini, fim = janela_do_mes(mes_ref)
    linhas, por_origem = [], {}
    for tabela in TABELAS_COM_ORIGEM:
        try:
            achadas = supa.select(tabela, "origem=ilike.rede:*&criado_em=gte.%s&criado_em=lt.%s&select=id,origem&limit=2000" % (ini, fim))
        except Exception:
            achadas = []
        for l in achadas:
            l["_tabela"] = tabela
            por_origem[l.get("origem") or "rede:?"] = por_origem.get(l.get("origem") or "rede:?", 0) + 1
        linhas.extend(achadas)
    return linhas, por_origem


def fila_linkedin_aguardando_api(marca):
    """Mesma lógica de `redes/informe_comercial.py::fila_linkedin_aguardando_api` — contagem
    NEUTRA de peças `linkedin_pagina` com `calendario_status='aguardando_api'`. Consultada SEM
    filtro de `mes_ref`: depois de `redes/publicar.py::_marcar_aguardando_api` (PLAYBOOK §7-V-8),
    essas peças ficam com `mes_ref=None` (voltaram pra fila, não pertencem a nenhum mês) — a
    query normal de `linhas` deste relatório (escopada por `mes_ref=eq.%s`) nunca as veria."""
    try:
        r = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&canal=eq.linkedin_pagina&calendario_status=eq.aguardando_api&select=peca_id" % marca,
        )
    except Exception:
        r = []
    return len(r)


def montar(marca="innconta", mes_ref=None, destino_email=None):
    mes_ref = mes_ref or mes_anterior()
    linhas = supa.select("ic_redes_publicacao", "marca=eq.%s&mes_ref=eq.%s&select=*" % (marca, mes_ref))
    publicadas = [l for l in linhas if l["status"] == "publicado"]
    aguardando = [l for l in linhas if l["status"] in ("aguardando", "aprovado")]
    expiradas = [l for l in linhas if l["status"] == "expirado"]
    recusadas = [l for l in linhas if l["status"] == "recusado"]
    imagens = [l for l in publicadas if (l.get("formato") or "").startswith("imagem") or l.get("formato") == "carrossel"]
    videos = [l for l in publicadas if l.get("formato") == "video"]
    vagas_video_reservadas = [l for l in linhas if l.get("tipo") == "video"]

    contatos_rede, por_origem = contatos_de_rede_no_mes(mes_ref)
    fila_linkedin = fila_linkedin_aguardando_api(marca)

    html = ["<h2>InnConta · relatório mensal de redes — %s</h2>" % mes_ref]
    html.append("<p><b>Entregas × mínimo contratual de referência (Anexo I):</b></p><ul>")
    html.append("<li>Postagens publicadas: %d / %d mínimo</li>" % (len(publicadas), MINIMO_POSTAGENS))
    html.append("<li>Imagens (feed+stories/carrossel): %d / %d mínimo</li>" % (len(imagens), MINIMO_IMAGENS))
    html.append("<li>Vídeos publicados: %d / %d mínimo (%d vagas reservadas no mês)</li>" % (len(videos), MINIMO_VIDEOS, len(vagas_video_reservadas)))
    html.append("</ul>")
    html.append("<p><b>Pendências:</b> %d aguardando decisão/publicação, %d expiradas sem decisão em 7 dias, %d recusadas.</p>"
                 % (len(aguardando), len(expiradas), len(recusadas)))
    html.append("<p>%d peças do LinkedIn em fila aguardando acesso à API.</p>" % fila_linkedin)
    detalhe = ", ".join("%s=%d" % (k, v) for k, v in sorted(por_origem.items())) or "nenhum no mês"
    html.append("<p><b>Métricas nativas:</b> ainda sem API de publicação ativa nesta marca — 0 métrica nativa de alcance/clique. "
                 "Contatos que chegaram por rede no mês (candidaturas de parceiro, Inn Host e leads com origem rede:*, "
                 "capturada por ic-origem.js nos formulários): %d (%s).</p>" % (len(contatos_rede), detalhe))
    html.append("<p style='font-size:12px;color:#999'>Consultor de Redes · relatório automático, agnóstico de marca.</p>")
    corpo = "".join(html)

    resp = supa.enviar_email("InnConta · relatório mensal de redes — %s" % mes_ref, destino_email or CVO_EMAIL, corpo)
    print("relatório mensal enviado:", resp)
    return {
        "mes_ref": mes_ref, "publicadas": len(publicadas), "imagens": len(imagens), "videos": len(videos),
        "vagas_video": len(vagas_video_reservadas), "aguardando": len(aguardando), "expiradas": len(expiradas),
        "recusadas": len(recusadas), "contatos_rede": len(contatos_rede), "fila_linkedin": fila_linkedin,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default="innconta")
    ap.add_argument("--mes-ref", default=None)
    ap.add_argument("--email", default=None)
    a = ap.parse_args()
    print(montar(a.marca, a.mes_ref, a.email))
