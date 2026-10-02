# -*- coding: utf-8 -*-
"""Calendário editorial do MÊS — até dia 5, monta o calendário (mínimo 10 postagens: 6
imagens/carrossel/texto + 4 vídeos), distribuído por terça=LinkedIn, quinta=Instagram,
sexta=perfil Roveda (§6 do plano de mídia), quarta=vídeo. Manda ao CVO até dia 8 em lote
próprio (link assinado, escopo=calendario). Vídeo (Consultor de Redes v1, PLAYBOOK §7-V,
22/09/2026): as 4 vagas de quarta-feira são preenchidas PRIMEIRO com peças de vídeo reais
já aprovadas em conteúdo (roteiro passou pela guarda e foi renderizado no lote semanal,
redes/video/renderizar_pendentes.py) — só sobra "vaga reservada, sem conteúdo" para o que
o estoque ainda não tiver produzido a tempo do ciclo do mês.

Mínimo contratual de referência (Anexo I, PLAYBOOK): 6 imagens (feed+stories) + 4 vídeos (roteiro)
= 10 postagens/mês, calendário até dia 5, aprovação até dia 8, relatório mensal dia 1."""
import calendar
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import alcance  # noqa: E402
import email_lote  # noqa: E402
import marcas  # noqa: E402
import supa  # noqa: E402

# CVO 30/09/2026: o calendario vai a CENTRAL tecnica como registro, sem links de aprovacao (a aprovacao e do Conselho
# Editorial desde 23/09; o clique nunca travou nada: o publicar nao le calendario_status)
CENTRAL_EMAIL = os.environ.get("REDES_CENTRAL_EMAIL", "central@innconta.com.br")

DIA_POR_CANAL = {"linkedin_pagina": 1, "instagram": 3, "perfil_roveda": 4}  # 0=seg ... terça=1, quinta=3, sexta=4
DIA_VIDEO = 2  # quarta — vaga reservada, sem canal fixo ainda


def _datas_do_dia_semana(ano, mes, dia_semana):
    _, ultimo = calendar.monthrange(ano, mes)
    return [datetime.date(ano, mes, d) for d in range(1, ultimo + 1) if datetime.date(ano, mes, d).weekday() == dia_semana]


def _dias_livres_instagram(marca, mes_ref, ano, mes):
    """POSTAGEM DIARIA no Instagram (CVO 29/09/2026: todas as contas postam todo dia): as vagas do Instagram sao TODOS os
    dias do mes ainda sem peca daquela marca (uma por dia), em vez de so a quinta."""
    _, ultimo = calendar.monthrange(ano, mes)
    ocupados = set()
    try:
        for r in supa.select("ic_redes_publicacao",
                             "marca=eq.%s&canal=eq.instagram&mes_ref=eq.%s&data_publicacao=not.is.null&select=data_publicacao"
                             % (marca, mes_ref)):
            d = r.get("data_publicacao") if isinstance(r, dict) else None
            if isinstance(d, str):
                ocupados.add(d[:10])
    except Exception as e:
        print("dias ocupados do Instagram indisponiveis (%s) — usa o mes inteiro." % str(e)[:100])
    return [datetime.date(ano, mes, d) for d in range(1, ultimo + 1)
            if datetime.date(ano, mes, d).isoformat() not in ocupados]


def _horario_txt(marca):
    """Horario efetivo da marca (regras.json ou recomendacao do relatorio de alcance) para constar no e-mail."""
    try:
        ativas = marcas.instagram_ativas_regras()
        if marca not in ativas:
            return ""
        m = alcance.horario_efetivo(marca, ativas, alcance.recomendados(list(ativas)))
        return " as %02d:%02d BRT" % (m // 60, m % 60)
    except Exception:
        return ""


def primeiro_dia_agendavel(agora=None):
    """Nunca agenda dia passado: com data <= hoje o publicar solta TODAS as peças vencidas na mesma rodada. Depois das
    17h BRT o publicar do dia já encerrou (última rodada 17:10), então o primeiro dia livre é amanhã (30/09/2026)."""
    agora = agora or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
    return agora.date() + datetime.timedelta(days=1 if agora.hour >= 17 else 0)


def montar(marca, mes_ref, destino_email=None, diario=False, agora=None):
    """mes_ref: 'AAAA-MM'. Usa peças já 'aprovado' no conteúdo, sem data ainda, + reserva 4 vagas
    de vídeo. Idempotente: peça que já tem data_publicacao neste mes_ref não é remexida.

    Peça `aprovado` sem `data_publicacao` (qualquer motivo — nunca teve calendário, ou voltou pra
    fila via `redes/publicar.py::_marcar_aguardando_api`, que limpa a data) já compete por vaga
    normalmente nesta query — é o comportamento padrão confirmado por leitura do código
    (23/09/2026, PLAYBOOK §7-V-8), não presumido.

    LinkedIn é a ÚNICA exceção deliberada: peça `canal='linkedin_pagina'` com
    `calendario_status='aguardando_api'` só volta a competir por vaga quando `linkedin_token`
    existir (`supa.segredo`) — sem isso, reagendar todo mês só reproduz o mesmo ciclo (nova data
    -> `publicar.py` tenta -> ainda sem token -> `aguardando_api` de novo, e-mail de aprovação
    inútil enviado ao CVO por nada)."""
    ano, mes = (int(x) for x in mes_ref.split("-"))
    linkedin_token_disponivel = bool(supa.segredo("linkedin_token"))
    candidatas = supa.select(
        "ic_redes_publicacao",
        "marca=eq.%s&status=eq.aprovado&data_publicacao=is.null&tipo=neq.video&select=*&order=criado_em" % marca,
    )
    if not linkedin_token_disponivel:
        antes = len(candidatas)
        candidatas = [c for c in candidatas
                      if not (c.get("canal") == "linkedin_pagina" and c.get("calendario_status") == "aguardando_api")]
        adiadas = antes - len(candidatas)
        if adiadas:
            print("calendário %s: %d peça(s) LinkedIn aguardando_api NÃO reagendada(s) — ainda sem linkedin_token."
                  % (mes_ref, adiadas))
    usados = {c: 0 for c in DIA_POR_CANAL}
    slots = {c: _datas_do_dia_semana(ano, mes, d) for c, d in DIA_POR_CANAL.items()}
    slots["instagram"] = _dias_livres_instagram(marca, mes_ref, ano, mes)  # diario
    minimo = primeiro_dia_agendavel(agora)
    slots = {c: [d for d in lista if d >= minimo] for c, lista in slots.items()}
    preferido = alcance.formato_preferido(marca)  # recomendacao do relatorio de alcance (so com amostra >= 10 posts)
    if preferido:
        rank = lambda c: 0 if preferido.lower() in str(c.get("formato") or "").lower() else 1  # noqa: E731
        candidatas = sorted(candidatas, key=rank)
    itens_email = []
    n_imagem_agendada = 0  # snapshot separado — itens_email também recebe os itens de vídeo
    # mais abaixo (mesmo e-mail, mesmo formato), então len(itens_email) sozinho passaria a
    # contar vídeo em dobro contra vagas_video (achado na verificação real desta sessão: o log
    # dizia "15 postagens" quando só 11 linhas de fato ganharam data em 2026-10).
    for row in candidatas:
        canal = row.get("canal") or "linkedin_pagina"
        lista = slots.get(canal, slots["linkedin_pagina"])
        i = usados.get(canal, 0)
        if i >= len(lista):
            continue  # mês sem mais vagas daquele dia — sobra para o mês seguinte
        data = lista[i]
        usados[canal] = i + 1
        supa.patch("ic_redes_publicacao", "id=eq.%s" % row["id"], {
            "mes_ref": mes_ref, "data_publicacao": data.isoformat(), "calendario_status": "aguardando",
        })
        itens_email.append({
            "meta": "%s · %s · agendado %s%s" % (row["peca_id"], canal, data.strftime("%d/%m (%a)"),
                                                _horario_txt(marca) if canal == "instagram" else ""),
            "texto": "Peça aprovada pelo Conselho Editorial. Data agendada.",
            "imagem_url": None, "botoes": [],
        })
        n_imagem_agendada += 1

    # 4 vagas de vídeo, quarta-feira — PRIMEIRO tenta preencher com peças de vídeo REAIS
    # já aprovadas (roteiro passou pela guarda e foi renderizado no lote semanal — ver
    # redes/video/renderizar_pendentes.py, PLAYBOOK §7-V); só reserva vaga VAZIA
    # (dívida a preencher) para o que sobrar sem conteúdo aprovado ainda no ciclo.
    if diario:
        # rodada DIÁRIA (depois do Conselho, 30/09/2026): só dá data à peça recém-aprovada do mês corrente. Vagas de
        # vídeo e o e-mail ficam com a rodada mensal (dia 5) — sem isso seriam um e-mail por marca por dia.
        print("calendário diário %s[%s]: %d peça(s) de imagem/texto agendada(s)" % (mes_ref, marca, n_imagem_agendada))
        return {"agendadas": n_imagem_agendada, "diario": True}
    datas_video = [d for d in _datas_do_dia_semana(ano, mes, DIA_VIDEO) if d >= minimo][:4]
    candidatas_video = supa.select(
        "ic_redes_publicacao",
        "marca=eq.%s&status=eq.aprovado&data_publicacao=is.null&tipo=eq.video&select=*&order=criado_em" % marca,
    )
    vagas_video = []
    for i, data in enumerate(datas_video, start=1):
        peca_id_vaga = "%s-video-vaga-%02d" % (mes_ref, i)
        if i - 1 < len(candidatas_video):
            row = candidatas_video[i - 1]
            supa.patch("ic_redes_publicacao", "id=eq.%s" % row["id"], {
                "mes_ref": mes_ref, "data_publicacao": data.isoformat(), "calendario_status": "aguardando",
            })
            # a vaga PLACEHOLDER (se um ciclo anterior já tiver reservado essa data sem
            # conteúdo) precisa ser CONSUMIDA agora — é reserva, não dado, e uma peça real
            # já ocupou o lugar dela. Nunca vira 'substituida': o CHECK de `status` só aceita
            # rascunho/aguardando/aprovado/recusado/expirado/publicado (sql/redes-publicacao.sql)
            # — a única forma correta de "consumir" um placeholder é excluir a linha (achado
            # real 22/09/2026: sem isso, o relatório mensal contava 8 vídeos "reservados" onde
            # só existem 4 vagas de verdade).
            removida = supa.excluir("ic_redes_publicacao", "peca_id=eq.%s&status=eq.rascunho" % peca_id_vaga)
            consumida = bool(removida)
            vagas_video.append({"peca_id": row["peca_id"], "data": data.isoformat(),
                                 "status": "preenchida com peça real"
                                           + (" (placeholder %s consumido)" % peca_id_vaga if consumida else "")})
            itens_email.append({
                "meta": "%s · vídeo · %s · agendado %s" % (row.get("canal", ""), row["peca_id"], data.strftime("%d/%m (%a)")),
                "texto": "Vídeo aprovado pelo Conselho Editorial. Data agendada.",
                "imagem_url": None, "botoes": [],
            })
            continue
        ja_existe = supa.select("ic_redes_publicacao", "peca_id=eq.%s&select=id" % peca_id_vaga)
        if ja_existe:
            vagas_video.append({"peca_id": peca_id_vaga, "data": data.isoformat(), "status": "já reservada"})
            continue
        try:
            import json
            import urllib.request
            req = urllib.request.Request(
                supa.URL + "/rest/v1/ic_redes_publicacao", method="POST",
                data=json.dumps({
                    "marca": marca, "canal": "a_definir", "peca_id": peca_id_vaga, "tipo": "video",
                    "formato": "video", "mes_ref": mes_ref, "data_publicacao": data.isoformat(),
                    "status": "rascunho", "calendario_status": None,
                }).encode("utf-8"),
                headers={"apikey": supa.KEY, "Authorization": "Bearer " + supa.KEY,
                         "Content-Type": "application/json", "Prefer": "return=minimal"})
            urllib.request.urlopen(req, timeout=20)
            vagas_video.append({"peca_id": peca_id_vaga, "data": data.isoformat(), "status": "reservada agora (sem conteúdo aprovado ainda)"})
        except Exception as e:
            vagas_video.append({"peca_id": peca_id_vaga, "data": data.isoformat(), "status": "erro: %s" % e})

    # total real de linhas que ganharam data neste ciclo: imagem/texto + as 4 vagas de vídeo
    # (preenchidas com peça real OU reservadas vazias) — nunca len(itens_email) sozinho, que
    # conta vídeo em dobro (ele também vira um item do mesmo e-mail, ver comentário acima).
    n_video_real = sum(1 for v in vagas_video if "peça real" in v["status"])
    total_postagens = n_imagem_agendada + len(vagas_video)
    print("calendário %s: %d peças de imagem/texto agendadas + %d vagas de vídeo (%d preenchidas "
          "com peça real, %d ainda reservadas vazias) = %d postagens (mínimo contratual: 10)"
          % (mes_ref, n_imagem_agendada, len(vagas_video), n_video_real,
             len(vagas_video) - n_video_real, total_postagens))
    for v in vagas_video:
        print("  vaga de vídeo:", v)

    if not itens_email:
        print("nada para aprovar no calendário (sem peças de conteúdo aprovadas e sem data ainda).")
        return {"agendadas": 0, "vagas_video": vagas_video, "total": total_postagens}

    html = email_lote.montar(
        "calendário editorial de %s (%d datas: %d imagem/texto + %d vídeo)"
        % (mes_ref, len(itens_email), n_imagem_agendada, n_video_real),
        "Registro do calendário do mês (só informativo). As peças já foram aprovadas pelo Conselho Editorial e saem nas datas abaixo; para mudar uma data, PATCH em ic_redes_publicacao.data_publicacao.",
        itens_email,
        rodape_extra="Mínimo contratual de referência: 10 postagens/mês (6 imagens + 4 vídeos).",
    )
    resp = supa.enviar_email("InnConta · redes: calendário de %s (%s) · registro" % (mes_ref, marca), destino_email or CENTRAL_EMAIL, html)
    print("e-mail do calendário enviado:", resp)
    return {"agendadas": len(itens_email), "vagas_video": vagas_video, "total": total_postagens, "email_resp": resp}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default=None, help="uma marca; sem isso, todas com publicar.instagram ligado")
    ap.add_argument("--mes-ref", required=True)
    ap.add_argument("--email", default=None)
    ap.add_argument("--diario", action="store_true", help="só agenda imagem/texto recém-aprovado, sem vídeo e sem e-mail")
    a = ap.parse_args()
    for m in ([a.marca] if a.marca else (marcas.instagram_ativas() or ["innconta"])):
        try:
            print(m, montar(m, a.mes_ref, a.email, diario=a.diario))
        except Exception as e:  # uma marca com problema nao derruba o calendario das outras
            print("calendario[%s] FALHOU (segue nas demais): %s: %s" % (m, type(e).__name__, str(e)[:200]))
