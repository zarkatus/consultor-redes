# -*- coding: utf-8 -*-
"""Lote SEMANAL de CONTEÚDO — desde 23/09/2026 aprovado pelo CONSELHO EDITORIAL automático, não
mais por link ao CVO (CVO: "Precisamos de revisão e aprovação não humana"; PLAYBOOK §7-V-10).

Para cada peça nova do estoque (frontmatter `status: aprovado` = pronta para revisão; imagem/texto
e vídeo, que é renderizado aqui mesmo antes de ser revisado):
  guarda.py -> 5 revisores -> (redator, até 3 voltas) -> 'aprovado' (aprovado_por='conselho',
  texto final em `texto_aprovado`, entra sozinha no calendário do mês) ou 'escalado'.
No fim, UM e-mail com as escaladas (todas as pendentes) SÓ à central técnica (nunca ao CVO, ordem de
25/09/2026), com o motivo e a ação de correção. Sem escalada, nenhum e-mail.

PRIORIDADE E DATA FIXA (24/09/2026, PLAYBOOK §7-V-11 — peça da PGFN, prazo da adesão 30/09):
peça com `prioridade: urgente` (e/ou `data_publicacao` fixa no frontmatter) é revisada PRIMEIRO na
rodada (`ordenar_por_urgencia`), antes de a franquia gratuita de neurônios acabar nas peças comuns;
e a data fixa é gravada em `ic_redes_publicacao` (`data_publicacao`, `mes_ref`,
`calendario_status='aprovado'`) no mesmo passo em que o Conselho decide (`fixar_data_da_peca`), sem
depender do calendário mensal — que só reagenda linhas com `data_publicacao is null`, então nunca
mexe nela. `reconciliar_datas_fixas` refaz o vínculo a cada rodada se algum PATCH tiver falhado.

Peça já decidida no banco (qualquer status fora de rascunho/aguardando) nunca é reavaliada.
Peça ADIADA por orçamento diário de neurônios não é registrada — volta na próxima rodada.
Chave de parada (`ic_segredo.redes_pausa='1'`) -> nada roda.

--qa: votos gravados com peca_id prefixado `qa-conselho-`, NADA muda em ic_redes_publicacao, e-mail
de escaladas só para central+qa-conselho@innconta.com.br (lista as linhas `escalado` do banco,
inclusive as de prova). Peça já decidida no banco é pulada também em QA (nenhum modelo gasto). Roda segunda 07:30 BRT
(.github/workflows/redes-consultor.yml, tarefa 'lote'; 'conselho' e 'video' por workflow_dispatch).

Ambiente: SB_URL/SB_SERVICE_ROLE, REDES_APROVACAO_SECRET, RESEND_API_KEY, CF_WORKERS_AI_TOKEN,
CLOUDFLARE_ACCOUNT_ID (GEMINI_API_KEY opcional), BASE_URL, CVO_EMAIL."""
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
for p in (RAIZ, os.path.join(RAIZ, "lib"), os.path.join(RAIZ, "video"), os.path.join(RAIZ, "conselho")):
    sys.path.insert(0, p)
import arte_sob_demanda  # noqa: E402
import avisos  # noqa: E402
import conselho  # noqa: E402
import cota  # noqa: E402
import estoque  # noqa: E402
import guarda  # noqa: E402
import insumos  # noqa: E402
import marcas  # noqa: E402
import renderizar_pendentes  # noqa: E402
import supa  # noqa: E402

REPO = os.path.dirname(RAIZ)


def _caminho_local(rel):
    if not rel or str(rel).startswith(("http", "_gerar")):
        return None
    c = os.path.join(REPO, str(rel))
    return c if os.path.isfile(c) else None


def peca_para_conselho(p, video=None, marca=None):
    """Converte uma peça do estoque (frontmatter + corpo) no formato que o conselho revisa. Declara a `marca`: é o
    que liga o Conselho v2 (prompts da marca, checagens de alcance/sigilo/fonte/imagem/repetição)."""
    marca = marca or p.get("marca") or "innconta"
    dominios = marcas.carregar(marca).get("dominios_origem") or None
    imagens = []
    if video:
        imagens = insumos.quadros_do_video(video["arquivo_mp4"])
        texto_arte = (p.get("titulo") or "") + " / " + " / ".join(
            q if isinstance(q, str) else q.get("frase", "") for q in (p.get("roteiro") or []))
    else:
        for q in (p.get("quadros") or [p.get("imagem")]):
            c = _caminho_local(q)
            if c:
                imagens.append(c)
        texto_arte = p.get("texto_arte") or ""
    return {
        "peca_id": p["_peca_id"], "marca": marca, "canal": p.get("canal", ""), "tipo": str(p.get("tipo", "")),
        "texto": p.get("_corpo", ""), "texto_arte": texto_arte, "imagens": imagens,
        "nota_urls": insumos.urls_de_origem(str(p.get("nota_origem") or ""), dominios),
        "alt_text": p.get("alt_text"), "collab": p.get("collab"), "primeiro_comentario": p.get("primeiro_comentario"),
        "data_publicacao": _data_fixa(p),
        "fontes": p.get("fontes") or [],
        "formato": "texto" if (p.get("formato") == "texto" and not imagens) else (p.get("formato") or "imagem"),
    }


def _data_fixa(p):
    """Data fixa do frontmatter como 'AAAA-MM-DD' (YAML solto vira date, entre aspas vira str) ou None."""
    dp = p.get("data_publicacao")
    return str(dp)[:10] if dp else None


def chave_prioridade(p):
    """Urgente primeiro (por data), depois as de data fixa, depois o resto na ordem do estoque."""
    urgente = str(p.get("prioridade") or "").strip().lower() == "urgente"
    dp = _data_fixa(p) or ""
    # data fixa só prioriza quando está PERTO (<= 10 dias): peça de 2027 não pode gastar a cota do dia antes das peças
    # que saem amanhã (1º Conselho multimarca, 30/09/2026: peças InnConta de 2026-11/2027 passaram à frente das marcas novas)
    perto = bool(dp) and dp <= (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    return (0 if urgente else (1 if perto else 2), dp, p.get("_peca_id", ""))


def ordenar_por_urgencia(candidatas):
    """candidatas: lista de (frontmatter, video|None). Ordenação estável — sem urgência, a ordem
    original (nome do arquivo) é preservada."""
    return sorted(candidatas, key=lambda c: chave_prioridade(c[0]))


def ordenar_justo(candidatas):
    """candidatas: lista de (marca, frontmatter, video|None). COTA JUSTA entre marcas (29/09/2026): a franquia gratuita
    e uma so; urgente e data fixa continuam primeiro, mas dentro de cada classe as marcas se revezam (round-robin),
    entao quando a cota acaba todas as marcas ficaram com fatias parecidas em vez de a 1a marca consumir tudo."""
    classes = {}
    for c in candidatas:
        classes.setdefault(chave_prioridade(c[1])[0], []).append(c)
    saida = []
    for k in sorted(classes):
        filas = {}
        for c in sorted(classes[k], key=lambda c: chave_prioridade(c[1])):
            filas.setdefault(c[0], []).append(c)
        nomes = sorted(filas)
        while any(filas.values()):
            for m in nomes:
                if filas[m]:
                    saida.append(filas[m].pop(0))
    return saida


def referencias_para_repeticao(limite=600):
    """Pecas aprovadas/publicadas de TODAS as marcas (texto final) para a anti-repeticao do Conselho v2. Peca antiga
    sem `texto_aprovado` usa o corpo do estoque. Falha de leitura = lista vazia (a checagem so perde memoria)."""
    try:
        linhas = supa.select("ic_redes_publicacao",
                             "status=in.(aprovado,publicado)&select=marca,peca_id,texto_aprovado,data_publicacao"
                             "&order=criado_em.desc&limit=%d" % limite)
    except Exception as e:
        print("referencias de repeticao indisponiveis (%s) — segue sem elas." % str(e)[:120])
        return []
    refs = []
    for r in linhas if isinstance(linhas, list) else []:
        texto = r.get("texto_aprovado")
        if not texto:
            try:
                texto = estoque.ler(estoque.caminho(r["marca"], r["peca_id"])).get("_corpo", "")
            except Exception:
                continue
        refs.append({"marca": r["marca"], "peca_id": r["peca_id"], "texto": texto, "data": r.get("data_publicacao")})
    return refs


def fixar_data_da_peca(peca_id, p, marca="innconta"):
    """PATCH de agendamento (campos não-decisórios, mesmo padrão de calendario.py): a peça de data
    fixa entra no banco já com a data. `calendario_status='aprovado'` = a data foi decidida pelo
    CVO (ordem de 23/09), então nada a confirmar no calendário. Uma tentativa extra; falha vira
    alerta à central técnica (AOP-01), nunca silêncio — peça aprovada sem data não é publicada."""
    dp = _data_fixa(p)
    if not dp:
        return False
    campos = {"data_publicacao": dp, "mes_ref": str(p.get("mes_ref") or dp[:7]), "calendario_status": "aprovado"}
    erro = None
    for _ in range(2):
        try:
            supa.patch("ic_redes_publicacao", "peca_id=eq.%s" % peca_id, campos)
            return True
        except Exception as e:
            erro = e
    print("data fixa NÃO gravada para %s: %s" % (peca_id, erro))
    try:
        supa.enviar_email(
            "InnConta · redes: peça com data fixa sem data no banco (%s)" % peca_id, avisos.CENTRAL,
            "<p>A peça <b>%s</b> foi decidida pelo Conselho, mas o PATCH da data fixa <b>%s</b> falhou "
            "(%s). Sem a data, o publicador das 09:00 BRT não a publica. Ação: rodar "
            "<code>redes-consultor.yml</code> tarefa <code>conselho_diario</code> (a rodada reconcilia a data) "
            "ou gravar <code>data_publicacao</code> em <code>ic_redes_publicacao</code>.</p>"
            % (peca_id, dp, str(erro)[:200]))
    except Exception as e2:
        print("alerta à central também falhou:", e2)
    return False


def reconciliar_datas_fixas(marca="innconta"):
    """Autocura: peça do estoque com data fixa e linha decidida (aprovado/escalado) no banco SEM
    data (PATCH que falhou numa rodada anterior) recebe a data agora. Não mexe em peça devolvida à
    fila de propósito (`aguardando_api`) nem em peça já publicada."""
    refeitas = []
    for p in estoque.listar(marca):
        dp = _data_fixa(p)
        if not dp:
            continue
        r = supa.select("ic_redes_publicacao", "peca_id=eq.%s&select=status,data_publicacao,calendario_status,publicado_em"
                        % p["_peca_id"])
        if not r or r[0].get("data_publicacao") or r[0].get("publicado_em"):
            continue
        if r[0].get("status") in ("aprovado", "escalado") and r[0].get("calendario_status") != "aguardando_api":
            if fixar_data_da_peca(p["_peca_id"], p, marca):
                refeitas.append(p["_peca_id"])
    return refeitas


def avisar_sem_arte(pecas):
    """AOP-01: peça que não ganhou arte nesta rodada vai à central técnica (nunca só no log), com a ação."""
    try:
        supa.enviar_email(
            "InnConta · redes: %d peça(s) sem arte, fora do Conselho nesta rodada" % len(pecas), avisos.CENTRAL,
            "<p>O render sob demanda (<code>redes/arte_sob_demanda.py</code>) não produziu o PNG destas peças, então "
            "elas NÃO foram revisadas (voltam na próxima rodada):</p><ul>%s</ul><p>Ação: abrir o log da rodada em "
            "<code>redes-consultor.yml</code> (linhas <code>arte sob demanda:</code>) e rodar localmente "
            "<code>python redes/arte_v2.py --marca &lt;marca&gt; --filtro &lt;slug&gt; --formatos feed</code> para ver o erro.</p>"
            % "".join("<li>%s</li>" % x for x in pecas[:30]))
    except Exception as e:
        print("aviso de peças sem arte falhou (%s): %s" % (str(e)[:120], pecas[:5]))


def _ja_decidida(peca_id):
    r = supa.select("ic_redes_publicacao", "peca_id=eq.%s&select=status" % peca_id)
    return bool(r) and r[0]["status"] not in ("rascunho", "aguardando")


def rodar(marca="innconta", so_peca_id=None, qa=False, somente_video=False, conversar=None, escaladas_se_novas=False,
          marcas_lista=None):
    """Uma rodada do Conselho. `marcas_lista` (ex.: todas com publicar.instagram) revisa varias marcas na MESMA rodada e
    na MESMA cota gratuita, revezando as marcas (ordenar_justo); sem ela, so `marca` (comportamento anterior)."""
    lista = list(marcas_lista or [marca])
    if conselho.pausado():
        print("CHAVE DE PARADA LIGADA (ic_segredo.redes_pausa='1') — lote/conselho não rodam.")
        return {"pausado": True}
    if not qa:
        print("peças expiradas nesta rodada:", supa.rpc("redes_expirar_vencidas"))
    nomes_base = guarda.clientes_da_base(supa.URL, supa.KEY) if (supa.URL and supa.KEY) else []
    print("nomes da base carregados para a guarda:", len(nomes_base))

    candidatas = []  # (marca, frontmatter, video_render|None)
    for m in lista:
        if not somente_video:
            for p in estoque.listar(m):
                if p.get("status") == "aprovado" and "video" not in str(p.get("tipo") or ""):
                    if not so_peca_id or p["_peca_id"] == so_peca_id:
                        candidatas.append((m, p, None))
        for rv in renderizar_pendentes.renderizar(m, nomes_clientes=nomes_base, so_peca_id=so_peca_id):
            if not rv["ok"]:
                print("vídeo NÃO entrou no conselho:", rv["peca_id"], "-", rv["motivo"])
                continue
            candidatas.append((m, estoque.ler(estoque.caminho(m, rv["peca_id"])), rv))

    candidatas = ordenar_justo(candidatas)  # urgente/data fixa primeiro; marcas se revezam na cota
    if not qa:
        for m in lista:
            refeitas = reconciliar_datas_fixas(m)
            if refeitas:
                print("data fixa reconciliada (%s):" % m, refeitas)
    orc = conselho.Orcamento(conselho.neuronios_hoje())
    print("orçamento: %.0f de %.0f neurônios já gastos hoje (UTC)" % (orc.gasto, orc.teto))
    gravar = conselho.gravador_banco(avisos.PREFIXO_QA if qa else "")
    referencias = referencias_para_repeticao()
    plano_consumo = cota.Consumo.carregar(supa)
    cache_votos = cota.Cache(supa)
    placar = {"aprovado": [], "escalado": [], "adiado": [], "ja_decidida": [], "sem_arte": []}
    por_marca = {}
    for m, p, rv in candidatas:
        pid = p["_peca_id"]
        if _ja_decidida(pid):  # vale também em QA: nunca gasta modelo com peça já decidida
            placar["ja_decidida"].append(pid)
            continue
        # PNG fora do git (marcas novas): renderiza só esta peça antes da revisão visual. Sem arte, a peça NÃO vai ao
        # Conselho (seria escalada para sempre por falta de imagem, que é defeito de infraestrutura, não da peça):
        # fica para a próxima rodada e a central é avisada no fim.
        if rv is None and arte_sob_demanda.garantir(m, p):
            placar["sem_arte"].append(pid)
            continue
        pc = peca_para_conselho(p, rv, marca=m)
        # PLANO DE COTA: cada marca tem a sua fatia da franquia gratuita de cada provedor (redes/conselho/cota.py)
        conv = conversar or cota.conversar_com_plano(orc, plano_consumo, m, lista)
        r = conselho.avaliar(pc, gravar=gravar, conversar=conv,
                             nomes_clientes=nomes_base, orcamento=orc, marca_nome=m,
                             referencias=[x for x in referencias if x["peca_id"] != pid],
                             cache=cache_votos, consumo=plano_consumo)
        print("conselho[%s]:" % m, pid, "->", r["decisao"], "voltas=%d" % r["rodadas"], "neurônios=%.1f" % r["neuronios"])
        for mot in r["motivos"][:5]:
            print("    -", mot[:200])
        placar[r["decisao"]].append(pid)
        por_marca.setdefault(m, {"aprovado": 0, "escalado": 0, "adiado": 0})[r["decisao"]] += 1
        if r["decisao"] == "adiado" or qa:
            continue
        if r["decisao"] == "aprovado":  # a proxima peca da rodada ja e comparada com esta (anti-repeticao)
            referencias.append({"marca": m, "peca_id": pid, "texto": r["texto_final"], "data": pc.get("data_publicacao")})
        reg = supa.rpc("redes_conselho_registrar", {
            "p_marca": m, "p_canal": p.get("canal", ""), "p_peca_id": pid,
            "p_tipo": "video" if rv else str(p.get("tipo", "")), "p_formato": "video" if rv else p.get("formato", ""),
            "p_mes_ref": p.get("mes_ref") or ((_data_fixa(p) or "")[:7] or None), "p_pilar": p.get("pilar", ""), "p_nota_origem": p.get("nota_origem", ""),
            "p_decisao": r["decisao"], "p_motivos": r["motivos"], "p_texto": r["texto_final"], "p_rodadas": r["rodadas"],
        })
        if not reg.get("ok"):
            print("registro recusado pelo banco:", pid, reg)
        elif _data_fixa(p):
            fixar_data_da_peca(pid, p, m)

    # QA: e-mail só para central+qa-conselho@ e lista as linhas escaladas do banco (inclui as de
    # prova `qa-conselho-*`); produção: só a central, sem as de prova.
    # rodada diária (--escaladas-se-novas) só avisa quando ESTA rodada escalou algo; a de segunda
    # (lote) sempre relista todas as pendentes — é o que impede o beco de link vencido.
    try:
        print("consumo do dia gravado em ic_redes_consumo: %d linha(s)" % plano_consumo.flush(supa))
        cache_votos.expurgar()
    except Exception as e:
        print("consumo/cache: erro ao gravar (%s) — segue." % str(e)[:100])
    if placar["sem_arte"] and not qa:
        avisar_sem_arte(placar["sem_arte"])
    if escaladas_se_novas and not placar["escalado"]:
        esc = {"escaladas": 0}
    else:
        esc = avisos.enviar_escaladas(None if len(lista) > 1 else lista[0], qa=qa)
    resultado = {k: len(v) for k, v in placar.items()}
    resultado.update(escaladas_email=esc.get("escaladas", 0), qa=qa, neuronios_dia=round(orc.gasto, 1), por_marca=por_marca)
    print("lote/conselho:", resultado)
    return resultado


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default=None, help="uma marca; sem isso, todas com publicar.instagram ligado (cota dividida)")
    ap.add_argument("--peca-id", default=None)
    ap.add_argument("--qa", action="store_true", help="votos com prefixo qa-conselho-, nada muda na publicação")
    ap.add_argument("--somente-video", action="store_true", help="pula as peças de imagem/texto, só vídeo")
    ap.add_argument("--escaladas-se-novas", action="store_true", help="rodada diária: e-mail só se esta rodada escalou")
    a = ap.parse_args()
    todas = None if a.marca else (marcas.instagram_ativas() or ["innconta"])
    print(rodar(a.marca or todas[0], a.peca_id, qa=a.qa, somente_video=a.somente_video,
                escaladas_se_novas=a.escaladas_se_novas, marcas_lista=todas))
