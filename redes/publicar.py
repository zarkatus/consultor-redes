# -*- coding: utf-8 -*-
"""Publicação automática DIÁRIA (TODO DIA, inclusive fim de semana — mudou de "dias úteis" para
"todo dia" em 24/09/2026, meta de postagem diária no Instagram) — peças 'aprovado' com
`data_publicacao <= hoje` e ainda não publicadas (`publicado_em is null`) são publicadas pelo
canal certo.

Diretriz do CVO (23/09/2026): publicar é responsabilidade do CONSULTOR, nunca do Diretor
Comercial (Roveda) — fecha o "kit de 1 clique ao Roveda" (ex-`redes/kit_roveda.py`, agora
`redes/informe_comercial.py`, SÓ informe) como caminho de publicação. Este arquivo é a parte
nova: o que antes era `kit_roveda.py::tentar_publicar_automatico` (só linkedin_pagina, e sem
alternativa: qualquer outro canal caía pro kit humano) vira a rotina diária que decide TODA peça
vencida, canal por canal.

Por canal:
- `linkedin_pagina`: `redes/publicar_linkedin.py` (Community Management API). Sem
  `ic_segredo.linkedin_token` (produto ainda não aprovado) -> marca
  `calendario_status='aguardando_api'` e segue (estado esperado, não erro).
- `instagram`: `redes/publicar_instagram.py` (Instagram API with Instagram Login, conta
  `innconta.oficial`, 23/09/2026). Sem `IG_ACCESS_TOKEN` no ambiente (app em modo desenvolvimento,
  revisão da Meta ainda não solicitada) -> mesmo tratamento `aguardando_api` do LinkedIn.
- qualquer outro canal sem conector implementado hoje -> mesmo tratamento `aguardando_api`, sem
  tentativa de publicar. Nenhuma peça fica presa em silêncio: o estado aparece no informe semanal
  como pendência (`redes/informe_comercial.py::pendencias_de_direcao`).

`_marcar_aguardando_api` (23/09/2026, PLAYBOOK §7-V-8): além do `calendario_status`, limpa
`data_publicacao`/`mes_ref` (None) no mesmo PATCH — a peça VOLTA PRA FILA, não fica datada no
passado como se tivesse sido processada e falhado. Isso é o que permite `redes/calendario.py`
reagendá-la automaticamente assim que o token existir (mesmo tratamento que já dá a qualquer
peça `aprovado` sem data), sem depender de alguém notar a data velha à mão.

`calendario_status='aguardando_api'` é um PATCH direto — campo de AGENDAMENTO/estado auxiliar,
não uma decisão de `status` (mesmo padrão já usado por `redes/calendario.py`). A única transição
de `status` para 'publicado' passa pela RPC `redes_decidir` (`p_por='consultor'`), nunca por
PATCH cru — ver `redes/lib/supa.py::patch`.

Falha REAL de publicação (`PublicacaoFalhou` — erro HTTP do LinkedIn, por exemplo) é diferente
de "sem conector": não marca `aguardando_api` (isso confundiria "canal sem API" com "API com
problema agora"), só loga e tenta de novo na próxima rodada (a peça continua elegível: status/
data/publicado_em não mudaram).

Roda TODO DIA 09:00 BRT (.github/workflows/redes-consultor.yml, tarefa 'publicar'). --qa não
muda a seleção nem a escrita — a prova de segurança vem da própria regra (nenhuma peça real tem
data <= hoje enquanto o calendário aprovado for todo em datas futuras; controle negativo natural,
ver redes/testar_kit_selecao.py). --peca-id força uma peça específica, ignorando a janela de
data (override manual/QA, mesmo padrão do extinto kit_roveda.py)."""
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
sys.path.insert(0, os.path.join(RAIZ, "video"))
import alcance  # noqa: E402
import arte_sob_demanda  # noqa: E402
import estoque  # noqa: E402
import guarda  # noqa: E402
import marcas  # noqa: E402
import publicar_instagram  # noqa: E402
import publicar_linkedin  # noqa: E402
import renderizar_pendentes  # noqa: E402
import supa  # noqa: E402

CANAIS_AUTOMATICOS = ("linkedin_pagina", "instagram")  # canais com conector de publicação implementado hoje


def _eh_video(peca):
    return peca.get("tipo") == "video" or "video" in str(peca.get("formato") or "")


def _midia_da_peca(marca, peca_id, peca):
    """Devolve (imagem_local, video_local, capa_local) para a peça — no máximo um dos dois
    primeiros vem preenchido (Instagram/LinkedIn não aceitam imagem+vídeo juntos).

    Achado 23/09/2026 (PLAYBOOK §7-V): o workflow do Consultor de Redes roda em checkout
    EFÊMERO (github actions), e nada nele comita `arquivo_mp4`/`legenda_srt`/`capa` de volta pro
    repo (só `acompanhamento-semanal.yml`/`pgfn.yml` fazem `git commit`+`push`; `redes-consultor.yml`
    não) — então uma peça de vídeo NUNCA chega no dia de publicar com esses campos já
    preenchidos no frontmatter local, mesmo depois de ter sido renderizada e aprovada na
    semana anterior. Sem isso, `publicar_via_instagram` não teria vídeo nenhum pra publicar.
    Fix: se `arquivo_mp4` já estiver persistido (arquitetura futura em que isso passe a ser
    comitado) e o `-stories.mp4` companheiro existir no disco, usa direto (idempotente); senão
    renderiza ON DEMAND a partir do `roteiro` (que É persistido em git) pelo MESMO caminho do
    lote semanal (`redes/video/renderizar_pendentes.py` — mesma guarda, mesmo `gerar_video_cena`,
    PAR-01d: reaproveitar, nunca duplicar o render). Usa o formato `stories` (1080x1920) para
    Reels, conforme a peça pede (feed é 4:5, não o recomendado pela Meta para Reels)."""
    if not _eh_video(peca):
        imagem = None
        caminho_rel = peca.get("imagem")
        if caminho_rel:
            candidato = os.path.join(os.path.dirname(RAIZ), str(caminho_rel))
            if os.path.isfile(candidato):
                imagem = candidato
        return imagem, None, None

    persistido = peca.get("arquivo_mp4")
    if persistido:
        candidato_feed = os.path.join(os.path.dirname(RAIZ), str(persistido))
        candidato_stories = candidato_feed.replace("-feed.mp4", "-stories.mp4")
        if os.path.isfile(candidato_stories):
            capa_rel = peca.get("capa")
            capa_local = os.path.join(os.path.dirname(RAIZ), str(capa_rel)) if capa_rel else None
            if not (capa_local and os.path.isfile(capa_local)):
                capa_local = None
            return None, candidato_stories, capa_local

    resultados = renderizar_pendentes.renderizar(marca, so_peca_id=peca_id)
    alvo = next((r for r in resultados if r["peca_id"] == peca_id), None)
    if not alvo or not alvo["ok"]:
        motivo = alvo["motivo"] if alvo else "render on-demand não devolveu resultado para " + peca_id
        print("vídeo indisponível para publicar (%s): %s" % (peca_id, motivo))
        return None, None, None
    return None, alvo["arquivo_stories"], alvo["capa"]


def _eh_carrossel(peca):
    """Peça com `formato: carrossel` E uma lista `quadros` (24/09/2026, PLAYBOOK §7-V-11)."""
    quadros = peca.get("quadros")
    if not (isinstance(quadros, list) and quadros):
        return False
    # preferencia por carrossel (alcance, 29/09/2026): peca com >= 2 quadros vira carrossel mesmo com formato de imagem
    return str(peca.get("formato") or "") == "carrossel" or (len(quadros) >= 2 and "video" not in str(peca.get("formato") or ""))


def _quadros_da_peca(peca):
    """Devolve (caminhos_locais_existentes, declarados) dos quadros do carrossel. Quem chama compara
    os dois números: quadro declarado e ausente no disco NUNCA vira carrossel menor em silêncio."""
    declarados = [str(q) for q in (peca.get("quadros") or [])]
    existentes = []
    for q in declarados:
        c = os.path.join(os.path.dirname(RAIZ), q)
        if os.path.isfile(c):
            existentes.append(c)
    return existentes, len(declarados)


def _texto_final(row, peca):
    """Texto que sai: o que o Conselho Editorial aprovou (`texto_aprovado`, pode ter passado pelo
    redator — o checkout do Actions é efêmero, então a versão final mora no banco) ou, para peça
    aprovada antes do conselho existir, o corpo do estoque."""
    return row.get("texto_aprovado") or peca.get("_corpo", "")


# Falha ao ler o banco segue PAUSANDO (falha fechada: não publica às cegas), mas o processo sai com exit 1 no fim
# (03/10/2026: secret do banco inválido por 15 h, 5 rodadas "success" sem publicar nada e sem alerta).
_FALHA_LEITURA = []


def pausado():
    """Chave de parada `ic_segredo.redes_pausa='1'` (PLAYBOOK §7-V-10). Falha ao ler = pausado (e exit 1 no fim)."""
    try:
        return (supa.segredo("redes_pausa") or "").strip() == "1"
    except Exception as e:
        print("não consegui ler ic_segredo.redes_pausa (%s) — tratando como PAUSADO." % e)
        _FALHA_LEITURA.append(str(e)[:120])
        return True


def elegivel_para_publicar(row, hoje=None):
    """Regra pura (sem rede), testável por mock — redes/testar_kit_selecao.py. Peça 'aprovado',
    com `data_publicacao` preenchida e <= hoje (nunca no futuro — publicar não adianta a data),
    ainda sem `publicado_em`."""
    hoje = hoje or datetime.date.today()
    if row.get("status") != "aprovado":
        return False
    if row.get("publicado_em"):
        return False
    dp = row.get("data_publicacao")
    if not dp:
        return False
    if isinstance(dp, str):
        dp = datetime.date.fromisoformat(dp)
    return dp <= hoje


def _marcar_aguardando_api(row):
    """Devolve a peça à FILA — nunca deixa 'datada no passado' como se tivesse sido processada e
    falhado. `calendario_status='aguardando_api'` E `data_publicacao`/`mes_ref` limpos (None) no
    mesmo PATCH: sem isso, a peça ficava com uma data <= hoje já vencida, e o calendário do mês
    seguinte (redes/calendario.py) não tinha como distingui-la de uma peça publicável — ela só
    reaparecia se alguém notasse a data velha à mão (achado real, sessão exec-fila-linkedin,
    23/09/2026). Limpar a data é o que a torna candidata de novo em `montar()` assim que o canal
    ganhar conector/token."""
    try:
        supa.patch("ic_redes_publicacao", "id=eq.%s" % row["id"], {
            "calendario_status": "aguardando_api", "data_publicacao": None, "mes_ref": None,
        })
        print("marcada aguardando_api e devolvida à fila, sem data/mes_ref (sem conector de publicação ainda):",
              row["peca_id"], "- canal:", row.get("canal"))
        return True
    except Exception as e:
        print("falhou ao marcar aguardando_api para", row["peca_id"], ":", e)
        return False


def publicar_via_linkedin(marca, row):
    """Devolve 'publicado' | 'aguardando_api' | 'falhou'. Nunca levanta exceção pro chamador —
    prova por mock em redes/testar_publicar_linkedin.py."""
    try:
        peca = estoque.ler(estoque.caminho(marca, row["peca_id"]))
    except FileNotFoundError:
        print("peça sem arquivo local, não publica:", row["peca_id"])
        return "falhou"
    imagem = None
    caminho_rel = peca.get("imagem")
    if caminho_rel:
        candidato = os.path.join(os.path.dirname(RAIZ), str(caminho_rel))
        if os.path.isfile(candidato):
            imagem = candidato
    try:
        resultado = publicar_linkedin.publicar(_texto_final(row, peca)[:2900], imagem, marca=marca)
    except publicar_linkedin.TokenAusente:
        return "aguardando_api" if _marcar_aguardando_api(row) else "falhou"
    except publicar_linkedin.PublicacaoFalhou as e:
        print("publicação LinkedIn falhou para", row["peca_id"], ":", e, "— tenta de novo na próxima rodada.")
        return "falhou"
    try:
        r = supa.rpc("redes_decidir", {"p_id": row["id"], "p_acao": "publicado", "p_url_post": resultado["url_post"], "p_por": "consultor"})
    except Exception as e:
        print("publicou no LinkedIn mas RPC redes_decidir falhou para", row["peca_id"], ":", e)
        return "falhou"
    if not r or not r.get("ok"):
        print("publicou no LinkedIn mas redes_decidir recusou (já decidida?) para", row["peca_id"], ":", r)
        return "falhou"
    print("publicado automaticamente no LinkedIn:", row["peca_id"], "->", resultado["url_post"])
    return "publicado"


def _extras_de_alcance(marca, row, peca, video=False):
    """(kwargs, parceiros): alt_text, collaborators e primeiro comentario da peca (redes/alcance.py); `parceiros` = marcas
    convidadas (para gravar `collab_com`). Nunca levanta: sem regras/consulta, publica sem os extras."""
    extras = {}
    try:
        regras = marcas.carregar(marca)
        if not video:
            at = alcance.alt_text(peca)
            if at:
                extras["alt_text"] = at
        planejada = row.get("collab_planejada")
        pedido = dict(peca, collab=peca.get("collab") or ([planejada] if planejada else None))
        usados = _collab_usados_na_semana(marca)
        usernames = alcance.collaborators(regras, pedido, usados)
        if usernames:
            extras["collaborators"] = usernames
            extras["_parceiros"] = [m for m in (regras.get("collab") or {}).get("parceiros", [])
                                    if (marcas.carregar(m).get("handle_instagram") or "").lstrip("@") in usernames]
        pc = alcance.primeiro_comentario(peca)
        if pc:
            extras["primeiro_comentario"] = pc
    except Exception as e:
        print("extras de alcance ignorados (%s): %s" % (row.get("peca_id"), str(e)[:120]))
        extras = {}
    parceiros = extras.pop("_parceiros", [])
    return extras, parceiros


def _collab_usados_na_semana(marca, hoje=None):
    hoje = hoje or _hoje_brt()
    seg, _ = alcance.semana_iso(hoje)
    try:
        linhas = supa.select("ic_redes_publicacao", "marca=eq.%s&publicado_em=gte.%s&collab_com=not.is.null&select=peca_id"
                             % (marca, seg.isoformat()))
        return len(linhas) if isinstance(linhas, list) else 0
    except Exception:
        return 0


def garantir_collab_da_semana(marca, hoje=None):
    """Regra do CVO (29/09/2026): >= 1 collab por marca por semana ISO. Se a semana ainda nao tem peca em collab, promove a
    peca aprovada mais adequada (PATCH `collab_planejada` no banco: o checkout do Actions e efemero, o estoque nao muda).
    Devolve (peca_id, parceiro) ou None. Nunca derruba a publicacao."""
    try:
        hoje = hoje or _hoje_brt()
        regras = marcas.carregar(marca)
        seg, dom = alcance.semana_iso(hoje)
        aprovadas = supa.select("ic_redes_publicacao", "marca=eq.%s&status=eq.aprovado&canal=eq.instagram&publicado_em=is.null"
                                "&data_publicacao=gte.%s&data_publicacao=lte.%s&select=*" % (marca, hoje.isoformat(), dom.isoformat()))
        if not isinstance(aprovadas, list):
            return None
        pecas = []
        for r in aprovadas:
            try:
                fm = estoque.ler(estoque.caminho(marca, r["peca_id"]))
            except Exception:
                fm = {}
            pecas.append({"peca_id": r["peca_id"], "texto": r.get("texto_aprovado") or fm.get("_corpo", ""),
                          "data": datetime.date.fromisoformat(str(r["data_publicacao"])[:10]) if r.get("data_publicacao") else None,
                          "collab": bool(r.get("collab_planejada") or fm.get("collab"))})
        semana_passada = supa.select("ic_redes_publicacao", "marca=eq.%s&collab_com=not.is.null&publicado_em=gte.%s&publicado_em=lt.%s"
                                     "&select=collab_com" % (marca, (seg - datetime.timedelta(days=7)).isoformat(), seg.isoformat()))
        ultimo = (semana_passada[0].get("collab_com") if isinstance(semana_passada, list) and semana_passada else None)
        parceiros = {m: marcas.carregar(m) for m in (regras.get("collab") or {}).get("parceiros", [])}
        escolha = alcance.escolher_collab(regras, pecas, _collab_usados_na_semana(marca, hoje), ultimo, hoje, parceiros)
        if not escolha:
            return None
        peca_id, parceiro = escolha
        row = next(r for r in aprovadas if r["peca_id"] == peca_id)
        supa.patch("ic_redes_publicacao", "id=eq.%s" % row["id"], {"collab_planejada": parceiro})
        row["collab_planejada"] = parceiro
        print("collab da semana: peca %s promovida a collab com %s (marca %s)" % (peca_id, parceiro, marca))
        return escolha
    except Exception as e:
        print("garantir_collab_da_semana(%s) ignorado: %s" % (marca, str(e)[:160]))
        return None


def _hoje_brt(agora=None):
    """Data de HOJE em Brasilia (o runner do Actions roda em UTC: depois das 21h BRT `date.today()` ja seria amanha)."""
    agora = agora or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
    return agora.date()


def _agora_brt():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))


def _selar_publicada(row, url_post, motivo, tentativas=2, espera_s=5):
    """O post JA saiu no Instagram mas a RPC redes_decidir falhou: sem selar, a peca segue 'aprovado' sem publicado_em e
    a rodada da hora seguinte posta DE NOVO (publicar roda de hora em hora). Tenta a RPC mais `tentativas` vezes; se
    ainda falhar, sela direto na tabela (so se publicado_em ainda e nulo) e avisa a central (AOP-01). Nunca levanta."""
    import time
    for _ in range(tentativas):
        time.sleep(espera_s)
        try:
            r = supa.rpc("redes_decidir", {"p_id": row["id"], "p_acao": "publicado", "p_url_post": url_post, "p_por": "consultor"})
            if r and r.get("ok"):
                print("  selada na nova tentativa da RPC:", row["peca_id"])
                return True
        except Exception:
            pass
    selou = False
    try:
        supa.patch("ic_redes_publicacao", "id=eq.%s&publicado_em=is.null" % row["id"],
                   {"status": "publicado", "publicado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "url_post": url_post, "publicado_por": "consultor"})
        selou = True
        print("  selada por PATCH direto (RPC indisponivel):", row["peca_id"])
    except Exception as e:
        print("  ATENCAO: nao selou %s (%s) — risco de post duplicado na proxima rodada" % (row["peca_id"], str(e)[:120]))
    try:
        supa.registrar_aviso("publicou %s no Instagram mas redes_decidir falhou (%s); %s. Acao: conferir a linha em "
                             "ic_redes_publicacao e o perfil (%s)" % (row["peca_id"], motivo,
                             "selada por PATCH direto" if selou else "NAO selada: pausar (ic_segredo.redes_pausa='1')", url_post),
                             marca=row.get("marca") or "innconta", canal="redes_publicar", entregue=False,
                             veredito={"selou": selou, "motivo": motivo})
    except Exception:
        pass
    return selou


def publicar_via_instagram(marca, row):
    """Devolve 'publicado' | 'aguardando_api' | 'falhou'. Nunca levanta exceção pro chamador —
    prova por mock em redes/testar_publicar_instagram.py. Mesmo contrato de publicar_via_linkedin.
    Vídeo (Reels) e imagem passam pelo mesmo despacho — `_midia_da_peca` decide qual dos dois."""
    try:
        peca = estoque.ler(estoque.caminho(marca, row["peca_id"]))
    except FileNotFoundError:
        print("peça sem arquivo local, não publica:", row["peca_id"])
        return "falhou"
    motivos_arte = guarda.checar_arte(peca, marca)
    if motivos_arte:
        print("arte v2 ausente, não publica (%s): %s" % (row["peca_id"], "; ".join(motivos_arte)))
        return "falhou"
    ausentes = arte_sob_demanda.garantir(marca, peca)  # PNG fora do git (marcas novas): renderiza só esta peça
    if ausentes:
        print("arte não renderizada, não publica (%s): %d arquivo(s) ausente(s)" % (row["peca_id"], len(ausentes)))
        return "falhou"
    quadros = None
    if _eh_carrossel(peca):
        quadros, declarados = _quadros_da_peca(peca)
        if len(quadros) != declarados:
            print("carrossel com quadro ausente no disco (%d de %d), não publica: %s" % (len(quadros), declarados, row["peca_id"]))
            return "falhou"
        imagem = video = capa = None
    else:
        imagem, video, capa = _midia_da_peca(marca, row["peca_id"], peca)
    extras, parceiros_collab = _extras_de_alcance(marca, row, peca, video=bool(video))
    try:
        resultado = publicar_instagram.publicar(_texto_final(row, peca)[:2200], caminho_imagem=imagem,
                                                  caminho_video=video, capa_local=capa, marca=marca,
                                                  nome_arquivo=row["peca_id"] if quadros else None,
                                                  caminhos_carrossel=quadros, **extras)
    except publicar_instagram.TokenAusente as e:
        if marca != "innconta":  # marca sem token: pula com log, sem mexer na peca nem derrubar as outras
            print("marca %s sem token do Instagram — peca %s NAO tocada (%s)" % (marca, row["peca_id"], str(e)[:100]))
            return "sem_token"
        return "aguardando_api" if _marcar_aguardando_api(row) else "falhou"
    except publicar_instagram.PublicacaoFalhou as e:
        print("publicação Instagram falhou para", row["peca_id"], ":", e, "— tenta de novo na próxima rodada.")
        return "falhou"
    try:
        r = supa.rpc("redes_decidir", {"p_id": row["id"], "p_acao": "publicado", "p_url_post": resultado["url_post"], "p_por": "consultor"})
    except Exception as e:
        print("publicou no Instagram mas RPC redes_decidir falhou para", row["peca_id"], ":", e)
        _selar_publicada(row, resultado["url_post"], "rpc_falhou: %s" % str(e)[:120])
        return "falhou"
    if not r or not r.get("ok"):
        print("publicou no Instagram mas redes_decidir recusou (já decidida?) para", row["peca_id"], ":", r)
        return "falhou"
    print("publicado automaticamente no Instagram:", row["peca_id"], "->", resultado["url_post"])
    if extras.get("collaborators"):
        print("  collab:", "aplicada" if resultado.get("collab_aplicado") else "RECUSADA pela API (saiu solo)", extras["collaborators"])
        if resultado.get("collab_aplicado"):
            try:
                supa.patch("ic_redes_publicacao", "id=eq.%s" % row["id"], {"collab_com": ",".join(parceiros_collab)})
            except Exception as e:
                print("  aviso: collab_com nao gravado (%s)" % str(e)[:120])
    return "publicado"


def _ainda_nao_e_a_hora(marca, agora, so_peca_id):
    """Guard de horario DENTRO da funcao (escalonado por marca): antes do horario efetivo da marca, nao publica. Peca
    forcada (`--peca-id`, QA/operacao) ignora o horario."""
    if so_peca_id or agora is None:
        return False
    try:
        ativas = marcas.instagram_ativas_regras()
        if marca not in ativas:
            return False
        rec = alcance.recomendados(list(ativas))
        limite = alcance.horario_efetivo(marca, ativas, rec)
    except Exception as e:
        print("horario da marca %s indisponivel (%s) — publica sem guard." % (marca, str(e)[:80]))
        return False
    minutos = agora.hour * 60 + agora.minute
    if minutos < limite:
        print("marca %s: ainda nao e a hora (%02d:%02d BRT; publica a partir de %02d:%02d) — nada a fazer nesta rodada."
              % (marca, agora.hour, agora.minute, limite // 60, limite % 60))
        return True
    return False


def rodar(marca="innconta", modo_qa=False, so_peca_id=None, agora=None):
    if pausado():
        print("BANCO ILEGÍVEL (credencial ou rede) — nada é publicado; o run sai com falha." if _FALHA_LEITURA
              else "CHAVE DE PARADA LIGADA (ic_segredo.redes_pausa='1') — nada é publicado.")
        return {"pausado": True, "candidatas": 0, "publicadas": 0, "aguardando_api": 0, "qa": modo_qa}
    if _ainda_nao_e_a_hora(marca, agora, so_peca_id):
        return {"candidatas": 0, "publicadas": 0, "aguardando_api": 0, "qa": modo_qa, "cedo": True}
    hoje = _hoje_brt(agora)
    if not so_peca_id and marcas.carregar(marca)["publicar"].get("instagram"):
        garantir_collab_da_semana(marca, hoje)
    if so_peca_id:
        # override manual/QA — bypassa a janela de data de propósito.
        candidatas = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&peca_id=eq.%s&status=eq.aprovado&select=*" % (marca, so_peca_id),
        )
    else:
        candidatas = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&status=eq.aprovado&data_publicacao=lte.%s&publicado_em=is.null&select=*&order=data_publicacao"
            % (marca, hoje.isoformat()),
        )
        # defesa em profundidade: reaplica a regra pura no cliente (nunca confiar só na query).
        candidatas = [c for c in candidatas if elegivel_para_publicar(c, hoje)]

    publicadas, aguardando_api, sem_token = 0, 0, 0
    for row in candidatas:
        canal = row.get("canal") or ""
        if canal == "linkedin_pagina":
            resultado = publicar_via_linkedin(marca, row)
            if resultado == "publicado":
                publicadas += 1
            elif resultado == "aguardando_api":
                aguardando_api += 1
            # "falhou" -> nada; tenta de novo na próxima rodada, sem marcar estado nenhum.
        elif canal == "instagram":
            resultado = publicar_via_instagram(marca, row)
            if resultado == "publicado":
                publicadas += 1
            elif resultado == "aguardando_api":
                aguardando_api += 1
            elif resultado == "sem_token":
                sem_token += 1
            # "falhou" -> nada; tenta de novo na próxima rodada, sem marcar estado nenhum.
        else:
            if _marcar_aguardando_api(row):
                aguardando_api += 1

    resultado = {"candidatas": len(candidatas), "publicadas": publicadas, "aguardando_api": aguardando_api, "qa": modo_qa}
    if sem_token:
        resultado["sem_token"] = sem_token
    print("publicar[%s]:" % marca, resultado)
    return resultado


def rodar_todas(modo_qa=False, so_peca_id=None, agora=None):
    """Itera as marcas com publicacao ligada (regras.json: publicar.instagram ou publicar.linkedin), na ordem alfabetica.
    Uma marca que falha ou nao tem token NAO derruba as outras; o resultado traz o placar por marca."""
    agora = agora or _agora_brt()
    ativas = [m for m, r in marcas.todas().items() if r["publicar"].get("instagram") or r["publicar"].get("linkedin")]
    if not ativas:
        ativas = ["innconta"]
    out = {}
    for m in ativas:
        try:
            out[m] = rodar(m, modo_qa, so_peca_id, agora)
        except Exception as e:
            print("publicar[%s] FALHOU (segue nas demais): %s: %s" % (m, type(e).__name__, str(e)[:200]))
            out[m] = {"erro": str(e)[:200]}
    print("publicar (todas as marcas):", out)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default=None, help="uma marca; sem isso, todas com publicar.instagram/linkedin ligado")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--peca-id", default=None)
    a = ap.parse_args()
    if a.marca:
        out = {a.marca: rodar(a.marca, a.qa, a.peca_id, _agora_brt())}
        print(out[a.marca])
    else:
        out = rodar_todas(a.qa, a.peca_id)
        print(out)
    # erro de marca ou de leitura do banco não pode sair verde: o run falha, o vigia e a conferência do disparo veem
    falhas = [m for m, r in out.items() if isinstance(r, dict) and r.get("erro")]
    if falhas or _FALHA_LEITURA:
        print("publicar: FALHOU (marcas com erro: %s; leituras do banco falhas: %d)" % (falhas or "-", len(_FALHA_LEITURA)))
        sys.exit(1)
