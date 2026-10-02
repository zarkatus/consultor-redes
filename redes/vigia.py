# -*- coding: utf-8 -*-
"""VIGIA DIÁRIO do Consultor de Redes (CVO 30/09/2026: "é imprescindível que estes consultores trabalhem de forma
autônoma e automatizada, com conselho, etc, tudo, pra que a gente não tenha que ficar lembrando, ativar nada").

Roda todo dia 17:40 BRT (20:40 UTC, `.github/workflows/redes-consultor.yml`, job `vigia`), DEPOIS da última rodada de
publicar (17:10) e ANTES do Conselho das 21:20 — assim a reposição de estoque que ele dispara entra no Conselho da mesma
noite, e o gerador usa a sobra da franquia gratuita do dia UTC (que zera às 21:00 BRT). Por marca com
`publicar.instagram=true` (redes/kit/<marca>/regras.json, PGA-01), com NÚMEROS OBSERVADOS:
  1. conselho: votos nas últimas 26 h, decisões (aprovadas/escaladas), barradas pela guarda, fila pendente de revisão;
  2. publicação: peça com data vencida e não publicada; peça de HOJE que já teve rodada de publicar e não saiu; post
     marcado publicado no banco que NÃO aparece no perfil real (API); post no perfil sem registro (duplicado);
  3. estoque: peças aprovadas a publicar (>= hoje) e furos na agenda dos próximos 7 dias; abaixo do mínimo -> REPÕE
     sozinho (gerador, marca com `arte_v2`) para o Conselho da noite; FONTE INÉDITA = artigos novos do site ainda não
     consumidos (redes/artigos.py: detecta no índice da marca, registra em `ic_redes_artigo`, planeja até 2 pautas de
     artigo por dia, antes de seção antiga) + seções não usadas; índice fora do ar/negado e artigo descartado alertam;
  4. token do Instagram: válido (GET /me), da conta certa (user_id do regras.json), dias até vencer; sem data ou perto
     de vencer -> RENOVA sozinho (`ig_renovar_token.renovar_marca`);
  5. runs do workflow nas últimas 26 h: vermelho/timeout; tarefa diária que o agendador do GitHub não rodou ->
     RE-DISPARA sozinho (workflow_dispatch); consumo/falhas da IA gratuita (`ic_redes_consumo`);
  6. peça `escalado` parada há mais de 7 dias (BECO, PJC-01c) -> DESCARTA com registro (`redes_decidir` recusar,
     p_por='vigia', motivo gravado; a peça continua no git e o Conselho já registrou por quê);
  7. collab planejada que saiu solo; convite de collab pendente/recusado pelo parceiro;
  8. primeiro post de marca nova: confere que saiu e aparece no perfil (sem conferência manual).

Só ALERTA quando há anomalia: um e-mail à CENTRAL TÉCNICA (AOP-01, nunca caixa pessoal, nunca WhatsApp), com o que
quebrou, o valor observado e a ação; 401/403 é credencial, nunca "serviço caiu". Toda rodada (com ou sem anomalia)
grava UMA linha em `ic_aviso_log` (canal `redes_vigia`) com os números — é o registro de execução. A mesma anomalia
3 dias seguidos sobe como ESCALADA (assunto "[ESCALADA]", PJC-01f) à central, que o Consultor da Central Técnica lê.

RODADAS RÁPIDAS (--rapida, CVO 30/09/2026: "não pode depender de um aviso, uma sessão, um PC"): 21:45 BRT, logo depois
do Conselho, e 12:40 BRT, depois das publicações da manhã. Mesmas checagens e re-disparo; sem reposição por IA, ciclo
de artigos nem renovação de token (ficam na completa das 17:40); e-mail só com anomalia NOVA frente à rodada anterior.
Quem confere o 1º post, o Conselho da noite e o publicar é este vigia, não uma sessão de IA.

--qa: e-mail só a central+qa-vigia@, registro no canal `redes_vigia_qa`, NENHUMA auto-cura executada (só listada).
--injetar (só com --qa): falha controlada para a prova adversarial (PQV-02): token_invalido:<marca> (token trocado por
lixo e chamado na API REAL), estoque_zero:<marca>, escalada_velha:<marca>, atrasada:<marca>, run_falhou.
Falha ('failure') de run agendado ou re-disparado já vai à central pelo passo final `if: failure()` do job `redes`
(PR #97); o vigia só anuncia o que esse passo não pega (timed_out, startup_failure) e dead-man por tarefa.

Zero Claude, zero modelo pago: o vigia não chama IA (o gerador da reposição usa só os provedores gratuitos do Conselho).
NUNCA imprime token (só status/booleanos)."""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
for _p in (RAIZ, os.path.join(RAIZ, "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import marcas  # noqa: E402
import supa  # noqa: E402

CENTRAL = "central@innconta.com.br"
CENTRAL_QA = "central+qa-vigia@innconta.com.br"
CANAL = "redes_vigia"
CANAL_QA = "redes_vigia_qa"
REMETENTE = "Central InnConta <central@innconta.com.br>"
REPO_GH = os.environ.get("GITHUB_REPOSITORY") or "zarkatus/consultor-redes"
WORKFLOW = "redes-consultor.yml"
BRT = datetime.timezone(datetime.timedelta(hours=-3))

LIMITES = {
    "estoque_min": 7,          # peças aprovadas a publicar (>= amanhã) abaixo disso = estoque baixo
    "repor_max": 7,            # teto de peças novas por marca por dia (gerador)
    "furo_dias": 7,            # olha a agenda dos próximos N dias
    "escalada_max_dias": 7,    # escalada parada além disso = BECO -> descarte com registro
    "token_min_dias": 21,      # token com menos dias que isso (ou sem data) -> renova
    "escalar_apos": 3,         # mesma anomalia em N rodadas seguidas -> [ESCALADA]
    "janela_h": 26,            # janela das checagens de "últimas 24 h" (folga para o atraso do agendador)
    "collab_pendente_dias": 3,
    "fonte_min": 7,            # fonte inédita (artigos novos + seções ainda não usadas) abaixo disso = a reposição vai secar
    "artigos_por_dia": 2,      # pautas de ARTIGO NOVO por marca por dia com o estoque saudável (estoque baixo: a reposição já põe artigo na frente)
}

# o mesmo mapa do passo "Decidir a tarefa" do workflow (run-name traz o cron ou a tarefa)
CRON_TAREFA = {
    "30 10 * * 1": "lote", "0 11 5 * *": "calendario", "0 10 1 * *": "relatorio", "0 11 * * 1": "informe",
    "10 11-20 * * *": "publicar", "0 8 * * *": "metricas", "0 9 10 * *": "renovar_ig",
    "20 0 * * *": "conselho_diario", "0 9 * * *": "conselho_diario", "40 20 * * *": "vigia",
    "45 0 * * *": "vigia", "40 15 * * *": "vigia",  # rápidas: 21:45 BRT (depois do Conselho) e 12:40 BRT (depois da manhã)
}
# tarefa diária -> o vigia exige ao menos 1 run concluído na janela; se faltar, re-dispara (workflow_dispatch).
# 'publicar' saiu (30/09/2026): o disparo agora é do pg_cron do banco (sql/redes-disparo-pg-cron.sql), que só aciona o
# Actions quando há peça devida — dia sem peça não tem run, e isso é o certo. Publicação que devia sair e não saiu é
# pega pela checagem do perfil real, não pela contagem de runs.
TAREFAS_DIARIAS = ("conselho_diario", "metricas")
# sufixo do run-name quando quem disparou foi o pg_cron do banco (input origem=pg_cron): é agendado, sem gente olhando
SUFIXO_AGENDADO = "[agendado]"
TOKEN_INJETADO = "TOKEN-INVALIDO-INJETADO-PELO-VIGIA-QA"


# ---------------------------------------------------------------------------------------------- utilidades
def agora_brt():
    return datetime.datetime.now(BRT)


def _dt(v):
    if not v:
        return None
    if isinstance(v, datetime.datetime):
        return v if v.tzinfo else v.replace(tzinfo=datetime.timezone.utc)
    s = str(v).replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def _data(v):
    if not v:
        return None
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _norm_link(u):
    return re.sub(r"[?#].*$", "", str(u or "")).rstrip("/").lower()


def anomalia(chave, marca, item, o_que, observado, acao, cura=None):
    return {"chave": chave, "marca": marca, "item": item, "o_que": o_que, "observado": observado, "acao": acao,
            "cura": cura}


def tarefa_do_titulo(titulo):
    """'Consultor de redes · 10 11-20 * * *' -> 'publicar'; '... · vigia (qa)' -> 'vigia'. Título antigo sem o sufixo
    (runs de antes do run-name) -> None (indeterminado: não entra no dead-man, não gera alerta falso)."""
    m = re.search(r"·\s*(.+?)\s*(\(qa\))?\s*$", str(titulo or "").replace(SUFIXO_AGENDADO, "").rstrip())
    if not m:
        return None
    bruto = m.group(1).strip()
    return CRON_TAREFA.get(bruto, bruto if re.fullmatch(r"[a-z_]+", bruto) else None)


# ---------------------------------------------------------------------------------------------- fontes (I/O)
class Fontes:
    """Tudo que o vigia lê ou escreve lá fora. Os testes (redes/testar_vigia.py) trocam esta classe por uma falsa."""

    def __init__(self, gh_token=None):
        self.gh_token = gh_token if gh_token is not None else (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "")

    # banco
    def linhas(self, marca):
        return supa.select("ic_redes_publicacao",
                           "marca=eq.%s&select=id,peca_id,status,canal,data_publicacao,publicado_em,url_post,enviado_em,"
                           "aprovado_em,criado_em,collab_planejada,collab_com,conselho_motivos,calendario_status&limit=5000"
                           % marca)

    def votos(self, marca, desde):
        return supa.select("ic_redes_revisao", "marca=eq.%s&criado_em=gte.%s&select=peca_id,revisor,passa&limit=5000"
                           % (marca, urllib.parse.quote(desde.isoformat())))

    def consumo(self, desde_dia):
        return supa.select("ic_redes_consumo", "dia=gte.%s&select=dia,marca,provedor,chamadas,falhas" % desde_dia.isoformat())

    def segredo(self, chave):
        return supa.segredo(chave)

    def historico(self, canal, n=10):
        return supa.select("ic_aviso_log", "canal=eq.%s&select=quando,veredito&order=quando.desc&limit=%d" % (canal, n))

    def runs_alertados(self, desde):
        """run_id já anunciados por uma rodada anterior do vigia (evita repetir o mesmo run no dia seguinte)."""
        linhas = supa.select("ic_aviso_log", "canal=eq.%s&quando=gte.%s&select=veredito"
                             % (CANAL, urllib.parse.quote(desde.isoformat())))
        return {str(i) for l in linhas or [] for i in (((l.get("veredito") or {}).get("runs") or {}).get("runs_anunciados") or [])}

    # estoque (git)
    def pendentes_estoque(self, marca, decididas):
        """Peças do estoque prontas para o Conselho (frontmatter `status: aprovado`, fora vídeo sem render) e ainda sem
        decisão no banco."""
        import estoque  # noqa: E402 (yaml só quando precisa)
        out = []
        for p in estoque.listar(marca):
            if p.get("status") == "aprovado" and p["_peca_id"] not in decididas:
                out.append(p["_peca_id"])
        return out

    def secoes_disponiveis(self, marca, excluir=None):
        """Quantas seções do SITE da marca o gerador ainda não usou (fonte da reposição), fora as páginas que são artigo
        registrado (essas contam como artigo). None = não mediu."""
        if not _arte_v2(marca):
            return None
        try:
            import gerador  # noqa: E402
            r = gerador.carregar_regras(marca)
            return len(gerador.unidades_disponiveis(gerador.Site(r["site"]), r, gerador.usadas_da_marca(marca), excluir_urls=excluir))
        except Exception as e:  # noqa: BLE001
            print("seções do site de %s indisponíveis (%s)" % (marca, str(e)[:80]))
            return None

    def artigos(self, marca, regras, gravar=True):
        """Ciclo do detector de artigo novo (redes/artigos.py): sincroniza com o Conselho, detecta no índice do site e
        resume. `gravar=False` (QA) só lê. Devolve o resumo + `reservadas` (URLs que saem da conta de seções)."""
        import artigos  # noqa: E402
        return artigos.ciclo(marca, regras, artigos.Registro(qa=False), gravar=gravar)

    # Instagram
    def token(self, marca):
        import publicar_instagram as pi  # noqa: E402
        try:
            return pi._token(marca)
        except pi.TokenAusente:
            return None

    def _ig_get(self, caminho, token):
        import publicar_instagram as pi  # noqa: E402
        sep = "&" if "?" in caminho else "?"
        req = urllib.request.Request(pi.GRAPH_BASE + caminho + sep + "access_token=" + urllib.parse.quote(token),
                                     headers={"User-Agent": "Mozilla/5.0 (innconta-consultor-redes-vigia)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return 200, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                corpo = json.loads(e.read() or b"{}")
            except ValueError:
                corpo = {}
            return e.code, corpo
        except Exception as e:  # noqa: BLE001 - rede: devolve status None (indisponível, não credencial)
            return None, {"erro": type(e).__name__}

    def ig_me(self, token):
        return self._ig_get("/me?fields=user_id,username", token)

    def ig_media(self, uid, token):
        return self._ig_get("/%s/media?fields=id,permalink,timestamp&limit=25" % uid, token)

    def ig_colaboradores(self, media_id, token):
        return self._ig_get("/%s/collaborators" % media_id, token)

    # GitHub
    def _gh(self, metodo, caminho, corpo=None):
        req = urllib.request.Request("https://api.github.com" + caminho, method=metodo,
                                     data=json.dumps(corpo).encode() if corpo is not None else None,
                                     headers={"Authorization": "Bearer " + self.gh_token, "Accept": "application/vnd.github+json",
                                              "User-Agent": "innconta-consultor-redes-vigia"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except Exception as e:  # noqa: BLE001
            return None, {"erro": type(e).__name__}

    def gh_runs(self, desde):
        if not self.gh_token:
            return None, []
        st, j = self._gh("GET", "/repos/%s/actions/workflows/%s/runs?per_page=100&created=%%3E%%3D%s"
                         % (REPO_GH, WORKFLOW, desde.strftime("%Y-%m-%dT%H:%M:%SZ")))
        return st, (j.get("workflow_runs") or []) if st == 200 else []

    def gh_dispatch(self, tarefa):
        st, _ = self._gh("POST", "/repos/%s/actions/workflows/%s/dispatches" % (REPO_GH, WORKFLOW),
                         {"ref": "main", "inputs": {"tarefa": tarefa}})
        return st

    # escritas (auto-cura e registro)
    def recusar_escalada(self, row, motivo):
        r = supa.rpc("redes_decidir", {"p_id": row["id"], "p_acao": "recusar", "p_por": "vigia"})
        if r and r.get("ok"):
            supa.patch("ic_redes_publicacao", "id=eq.%s" % row["id"], {"motivo_recusa": motivo[:500]})
        return bool(r and r.get("ok"))

    def renovar_token(self, marca):
        import ig_renovar_token  # noqa: E402
        return ig_renovar_token.renovar_marca(marca, alertar=False)  # falha entra no e-mail único do vigia

    def registrar(self, canal, texto, entregue, veredito):
        supa.registrar_aviso(texto, marca="consultor-redes", canal=canal, entregue=entregue, veredito=veredito)

    def email(self, assunto, para, html):
        return supa.enviar_email(assunto, para, html, remetente=REMETENTE)


# ---------------------------------------------------------------------------------------------- checagens (puras)
def checar_conselho(marca, linhas, votos, pendentes, desde):
    decididas = [r for r in linhas if (_dt(r.get("enviado_em")) or _dt(r.get("criado_em")) or desde) >= desde
                 and r.get("status") in ("aprovado", "escalado", "publicado")]
    aprov = sum(1 for r in decididas if r.get("status") in ("aprovado", "publicado") and r.get("aprovado_em")
                and _dt(r["aprovado_em"]) >= desde)
    esc = sum(1 for r in decididas if r.get("status") == "escalado")
    barradas = len({v["peca_id"] for v in votos if v.get("revisor") == "guarda" and not v.get("passa")})
    pecas_revistas = len({v["peca_id"] for v in votos})
    num = {"votos": len(votos), "pecas_revistas": pecas_revistas, "aprovadas": aprov, "escaladas": esc,
           "barradas_guarda": barradas, "pendentes_revisao": len(pendentes)}
    anoms = []
    if pendentes and not votos:
        anoms.append(anomalia(
            "conselho_parado:" + marca, marca, 1, "O Conselho não revisou nenhuma peça da marca nas últimas %dh"
            % LIMITES["janela_h"], "%d peça(s) esperando revisão, 0 votos gravados em ic_redes_revisao" % len(pendentes),
            "Ver o run conselho_diario (21:20/06:00 BRT) no Actions e as falhas por provedor em ic_redes_consumo; se "
            "for cota, a próxima rodada retoma sozinha; se for erro de código, corrigir e disparar tarefa=conselho_diario."))
    return num, anoms


def checar_publicacao(marca, linhas, hoje, agora, horario_min, runs_publicar, perfil, primeira_vez):
    """perfil: {"status": http, "posts": [{id, permalink, timestamp}]} ou None (sem token)."""
    anoms, curas = [], []
    num = {}
    abertas = [r for r in linhas if r.get("status") == "aprovado" and not r.get("publicado_em")]
    vencidas = sorted([r for r in abertas if _data(r.get("data_publicacao")) and _data(r["data_publicacao"]) < hoje],
                      key=lambda r: str(r["data_publicacao"]))
    de_hoje = [r for r in linhas if _data(r.get("data_publicacao")) == hoje and r.get("status") in ("aprovado", "publicado")]
    hoje_pendentes = [r for r in de_hoje if not r.get("publicado_em")]
    num.update(vencidas=len(vencidas), agendadas_hoje=len(de_hoje), publicadas_hoje=len(de_hoje) - len(hoje_pendentes))
    if vencidas:
        anoms.append(anomalia(
            "atrasada:" + marca, marca, 2, "Peça aprovada com data vencida e NÃO publicada",
            "%d peça(s); a mais antiga de %s (%s)" % (len(vencidas), vencidas[0]["data_publicacao"], vencidas[0]["peca_id"]),
            "O vigia re-dispara tarefa=publicar (idempotente). Se continuar, ler o log do publicar: 'arte não renderizada', "
            "'publicação Instagram falhou' ou token.", cura="dispatch:publicar"))
    # hoje: só é anomalia se já houve rodada de publicar concluída depois do horário da marca
    minutos = agora.hour * 60 + agora.minute
    rodou_depois = [r for r in runs_publicar if r.get("status") == "completed"
                    and _dt(r.get("updated_at")) and _dt(r["updated_at"]).astimezone(BRT).date() == hoje
                    and (_dt(r["updated_at"]).astimezone(BRT).hour * 60 + _dt(r["updated_at"]).astimezone(BRT).minute) >= horario_min]
    if hoje_pendentes and minutos >= horario_min + 60 and rodou_depois:
        anoms.append(anomalia(
            "nao_saiu_hoje:" + marca, marca, 2, "A peça de hoje não saiu, embora o publicar já tenha rodado depois do horário",
            "%s agendada para %s; horário da marca %02d:%02d BRT; %d rodada(s) de publicar depois disso"
            % (hoje_pendentes[0]["peca_id"], hoje, horario_min // 60, horario_min % 60, len(rodou_depois)),
            "O vigia re-dispara tarefa=publicar; se falhar de novo, o log do publicar diz o motivo (arte, token, API).",
            cura="dispatch:publicar"))
    # banco x perfil real
    if perfil is not None and perfil.get("status") == 200:
        posts = perfil.get("posts") or []
        links = {_norm_link(p.get("permalink")) for p in posts}
        limite = agora - datetime.timedelta(hours=48)
        recentes = [r for r in linhas if r.get("status") == "publicado" and _dt(r.get("publicado_em"))
                    and _dt(r["publicado_em"]) >= limite and r.get("canal") == "instagram"]
        sumidas = [r for r in recentes if _norm_link(r.get("url_post")) not in links]
        num["publicadas_48h_banco"] = len(recentes)
        num["conferidas_no_perfil"] = len(recentes) - len(sumidas)
        if sumidas:
            anoms.append(anomalia(
                "fora_do_perfil:" + marca, marca, 2, "Post marcado como publicado no banco NÃO aparece no perfil real",
                "%d de %d; ex.: %s (%s)" % (len(sumidas), len(recentes), sumidas[0]["peca_id"], sumidas[0].get("url_post")),
                "Abrir o link; se o post foi apagado, 'retirar' a linha; se a url_post está errada, corrigir a url_post."))
        posts_24h = [p for p in posts if _dt(p.get("timestamp")) and _dt(p["timestamp"]) >= agora - datetime.timedelta(hours=24)]
        banco_24h = [r for r in recentes if _dt(r["publicado_em"]) >= agora - datetime.timedelta(hours=24)]
        num["posts_perfil_24h"] = len(posts_24h)
        if len(posts_24h) > len(banco_24h):
            anoms.append(anomalia(
                "post_sem_registro:" + marca, marca, 2, "Há mais posts no perfil nas últimas 24h do que publicações registradas",
                "perfil %d x banco %d (possível post DUPLICADO ou publicado fora do Consultor)" % (len(posts_24h), len(banco_24h)),
                "Conferir o perfil; se for duplicado, apagar o repetido no app e checar o selo do publicar (_selar_publicada)."))
        if primeira_vez and recentes:
            ok = [r for r in recentes if _norm_link(r.get("url_post")) in links]
            num["primeiro_post"] = {"conferido_no_perfil": bool(ok), "peca_id": (ok or recentes or [{}])[0].get("peca_id"),
                                    "url": (ok or recentes or [{}])[0].get("url_post")}
    elif perfil is not None:
        num["perfil"] = "indisponível (HTTP %s)" % perfil.get("status")
    return num, anoms, curas


def checar_estoque(marca, linhas, pendentes, amanha, regras_arte, secoes=None, artigos=None):
    """Estoque aprovado, furos na agenda e FONTE INÉDITA (artigos novos do site ainda não consumidos + seções antigas
    ainda não usadas). `artigos` = resumo de redes/artigos.py (None = não mediu)."""
    futuras = [r for r in linhas if r.get("status") == "aprovado" and not r.get("publicado_em")
               and (r.get("canal") or "instagram") == "instagram"
               and (not _data(r.get("data_publicacao")) or _data(r["data_publicacao"]) >= amanha)]
    dias = {_data(r.get("data_publicacao")) for r in futuras if _data(r.get("data_publicacao"))}
    janela = [amanha + datetime.timedelta(days=i) for i in range(LIMITES["furo_dias"])]
    furos = [d.isoformat() for d in janela if d not in dias]
    art = artigos if isinstance(artigos, dict) and "novos" in artigos else None
    novos = art["novos"] if art else None
    fonte = None if secoes is None else secoes + (novos or 0)
    num = {"aprovadas_a_publicar": len(futuras), "sem_data": sum(1 for r in futuras if not r.get("data_publicacao")),
           "pendentes_revisao": len(pendentes), "furos_7d": furos, "secoes_no_site": secoes,
           "artigos_novos": novos, "fonte_inedita": fonte}
    anoms = []
    if fonte is not None and fonte < LIMITES["fonte_min"]:
        # 1 post por dia: o que está aprovado + na fila + a fonte inédita cobre a agenda até ~esta data
        ate = amanha + datetime.timedelta(days=max(0, len(futuras) + len(pendentes) + fonte - 1))
        if art:
            ind = "índice %s: %s artigo(s) no site" % (art.get("indice") or "?", art.get("no_indice") if art.get("no_indice") is not None else "?")
            ult = ("último artigo novo visto em %s" % art["ultimo_artigo_visto"]) if art.get("ultimo_artigo_visto") else "nenhum artigo novo registrado"
        else:
            ind, ult = "índice de artigos não medido", "artigos não medidos"
        observado = ("%d artigo(s) novo(s) a consumir (%s; %s) + %d seção(ões) antiga(s) não usada(s) = %d de fonte inédita "
                     "(mínimo %d); estoque aprovado %d + fila do Conselho %d cobrem a agenda até ~%s"
                     % (novos or 0, ind, ult, secoes, fonte, LIMITES["fonte_min"], len(futuras), len(pendentes), ate.strftime("%d/%m")))
        if not novos:
            acao = ("SEM ARTIGO NOVO no site: a marca fica sem pauta inédita a partir de ~%s. Publicar artigo novo no site "
                    "(entra no índice %s e vira pauta sozinho no vigia seguinte). A cadência de post passa a acompanhar a "
                    "de artigos: nada é inventado e seção antiga não é reaproveitada sem decisão do CVO."
                    % (ate.strftime("%d/%m"), (art or {}).get("url_indice") or "de artigos do kit"))
        else:
            acao = ("%d artigo(s) novo(s) virando pauta (prioridade sobre seção antiga). Para manter post diário sem "
                    "repetir conteúdo, o site precisa de artigo novo toda semana; sem isso a pauta inédita acaba em ~%s."
                    % (novos, ate.strftime("%d/%m")))
        anoms.append(anomalia("fonte_acabando:" + marca, marca, 3,
                              "A marca está ficando sem fonte inédita para post (artigo novo do site + seção não usada)",
                              observado, acao))
    falta = LIMITES["estoque_min"] - len(futuras)
    # furo nos próximos 3 dias sem peça sem data para tapá-lo (o calendário diário das 21:20 data as sem data)
    furo_iminente = [f for f in furos if f <= (amanha + datetime.timedelta(days=2)).isoformat()] and not num["sem_data"]
    if falta > 0 or furo_iminente:
        repor = max(0, min(LIMITES["repor_max"], 2 * LIMITES["estoque_min"] - len(futuras) - len(pendentes)))
        if regras_arte and repor > 0:
            cura, acao = "repor:%d" % repor, ("O vigia gera %d peça(s) nova(s) do site da marca (gerador, IA gratuita) e "
                                              "as põe na fila do Conselho desta noite." % repor)
        elif regras_arte:
            cura, acao = None, ("Já há %d peça(s) na fila do Conselho; se ele aprovar, o estoque volta. Se elas escalarem, "
                                "o vigia repõe amanhã." % len(pendentes))
        else:
            cura, acao = None, ("Marca sem `arte_v2` no marca.json (gerador automático não se aplica): produzir peças no "
                                "estoque pelo fluxo da marca ou acrescentar `arte_v2` ao kit para o vigia repor sozinho.")
        anoms.append(anomalia(
            "estoque_baixo:" + marca, marca, 3, "Estoque de peças aprovadas abaixo do mínimo",
            "%d aprovada(s) a publicar (mínimo %d), %d na fila do Conselho, furos na agenda dos próximos %d dias: %s"
            % (len(futuras), LIMITES["estoque_min"], len(pendentes), LIMITES["furo_dias"], ", ".join(furos[:7]) or "nenhum"),
            acao, cura=cura))
    return num, anoms


def checar_artigos(marca, art):
    """Índice de artigos ilegível (site fora do ar, 5xx, timeout = serviço; 401/403 = acesso negado, não queda), índice
    que esvaziou tendo artigos registrados, e artigo DESCARTADO nas últimas 26 h. Nunca erro mudo."""
    anoms = []
    if not isinstance(art, dict):
        return anoms
    if art.get("erro_ciclo"):
        anoms.append(anomalia("artigos_erro:" + marca, marca, 3, "O detector de artigo novo não rodou para a marca",
                              art["erro_ciclo"], "Defeito do detector ou do banco (ic_redes_artigo): ler o log do run vigia. "
                              "Enquanto isso nenhum artigo vira pauta, mas nenhum se perde (o registro é por URL)."))
        return anoms
    est = art.get("indice")
    if est in ("indisponivel", "negado"):
        if est == "negado":
            acao = ("HTTP %s = acesso NEGADO (firewall/regra de bot/credencial), não queda do site: liberar o índice %s para "
                    "o User-Agent do Consultor. Nenhum artigo se perde: o vigia tenta de novo amanhã."
                    % (art.get("http"), art.get("url_indice")))
        else:
            acao = ("Site ou índice fora do ar (rede, DNS, timeout ou 5xx): abrir %s. Nenhum artigo se perde: o registro é "
                    "por URL e o vigia tenta de novo amanhã." % art.get("url_indice"))
        anoms.append(anomalia("artigos_indice:" + marca, marca, 3, "O índice de artigos do site não pôde ser lido (artigo novo não é detectado)",
                              "%s: %s (%s)" % (est, art.get("erro") or "", art.get("url_indice")), acao))
    elif est == "vazio" and (art.get("registrados") or 0) > (art.get("base") or 0):
        anoms.append(anomalia("artigos_indice:" + marca, marca, 3, "O índice de artigos do site ficou VAZIO tendo artigos registrados",
                              "0 artigo casou o padrão em %s; %d artigo(s) já registrado(s)" % (art.get("url_indice"), art.get("registrados") or 0),
                              "Sitemap quebrado ou artigos mudaram de caminho: conferir o sitemap do site e o `artigos.padrao` do regras.json da marca."))
    if art.get("descartados_26h"):
        anoms.append(anomalia("artigo_descartado:" + marca, marca, 3, "Artigo do site descartado como fonte (não virou peça aprovada)",
                              "%d artigo(s): %s" % (len(art["descartados_26h"]), ", ".join(art["descartados_26h"][:5])),
                              "Motivo em ic_redes_artigo.motivo (gerador barrou 3 vezes, Conselho recusou 3 vezes ou a página saiu do "
                              "site). Corrigido o texto do artigo, voltar a linha para status 'novo' e ele vira pauta no vigia seguinte."))
    return anoms


def checar_token(marca, token, me, expira, uid_esperado, hoje, handle=""):
    """me = (status, corpo) do GET /me; expira = 'AAAA-MM-DD' ou None."""
    num, anoms = {"token": "ausente"}, []
    if not token:
        anoms.append(anomalia(
            "sem_token:" + marca, marca, 4, "Marca com publicação ligada e SEM token do Instagram",
            "ic_segredo.%s vazio" % marcas.chave_token(marca),
            "Gerar o token no painel da Meta (login da conta %s) e gravar em ic_segredo; até lá a marca não publica."
            % (handle or marca)))
        return num, anoms
    st, corpo = me
    erro = (corpo or {}).get("error") or {}
    if st == 200:
        uid = str((corpo or {}).get("user_id") or (corpo or {}).get("id") or "")
        num["token"] = "válido"
        num["conta"] = (corpo or {}).get("username")
        if uid_esperado and uid and uid != str(uid_esperado):
            num["token"] = "de outra conta"
            anoms.append(anomalia(
                "token_outra_conta:" + marca, marca, 4, "O token da marca abre OUTRA conta do Instagram",
                "user_id do token %s x esperado %s (@%s)" % (uid, uid_esperado, num["conta"]),
                "Gerar o token logado na conta certa (%s) e regravar ic_segredo.%s; a marca publicaria no perfil errado."
                % (handle or marca, marcas.chave_token(marca))))
            return num, anoms
    elif st in (400, 401, 403) or erro.get("code") in (190, 102):
        num["token"] = "inválido"
        anoms.append(anomalia(
            "token_invalido:" + marca, marca, 4, "Token do Instagram recusado pela API (CREDENCIAL, não queda do serviço)",
            "HTTP %s, erro %s/%s: %s" % (st, erro.get("code"), erro.get("error_subcode"), str(erro.get("message") or "")[:120]),
            "Gerar token novo no painel da Meta para %s e gravar em ic_segredo.%s (PLAYBOOK §7-V-5). A renovação automática "
            "não recupera token já inválido." % (handle or marca, marcas.chave_token(marca))))
        return num, anoms
    else:
        num["token"] = "não verificado (API indisponível: HTTP %s)" % st
        anoms.append(anomalia(
            "ig_api_indisponivel:" + marca, marca, 4, "API do Instagram não respondeu (serviço, NÃO credencial)",
            "GET /me -> %s %s" % (st, (corpo or {}).get("erro") or ""),
            "Nada a fazer se passar; se repetir amanhã, ver status da Meta (metastatus.com)."))
        return num, anoms
    d = _data(expira)
    num["expira_em"] = d.isoformat() if d else None
    num["dias_para_vencer"] = (d - hoje).days if d else None
    if d is None or (d - hoje).days < LIMITES["token_min_dias"]:
        num["renovar"] = True
    return num, anoms


def checar_runs(st, runs, agora, alertados):
    num = {"api": st, "runs": len(runs)}
    anoms = []
    if st is None and not runs:
        num["api"] = "sem GH_TOKEN"
        return num, anoms, {}
    if st in (401, 403):
        anoms.append(anomalia(
            "gh_credencial", "grupo", 5, "Sem permissão para ler os runs do GitHub (CREDENCIAL)",
            "HTTP %s em actions/workflows/%s/runs" % (st, WORKFLOW),
            "Dar `actions: write` ao job vigia (permissions) ou conferir o GH_TOKEN."))
        return num, anoms, {}
    if st != 200:
        num["api"] = "indisponível (HTTP %s)" % st
        return num, anoms, {}
    por_tarefa, falhas = {}, []
    for r in runs:
        t = tarefa_do_titulo(r.get("display_title"))
        qa = "(qa)" in str(r.get("display_title") or "")
        if t:
            por_tarefa.setdefault(t, []).append(r)
        # só o que roda SEM gente olhando: agendado, ou re-disparado pelo próprio vigia (ator github-actions[bot]).
        # Dispatch manual que falha é visto por quem disparou: fica só no registro (vermelhos_manuais).
        automatico = (r.get("event") == "schedule" or "[bot]" in str((r.get("triggering_actor") or {}).get("login") or "")
                      or SUFIXO_AGENDADO in str(r.get("display_title") or ""))
        if r.get("status") == "completed" and r.get("conclusion") in ("failure", "timed_out", "startup_failure") and not qa:
            falhas.append((t or "indeterminada", r, automatico))
    num["por_tarefa"] = {t: len(v) for t, v in sorted(por_tarefa.items())}
    # 'failure' de run automático JÁ foi à central pelo passo final `if: failure()` do job (PR #97): aqui só entra o
    # que aquele passo não pega — job que estourou o tempo (timed_out: o passo não roda) ou nem subiu (startup_failure).
    novas = [(t, r) for t, r, auto in falhas if auto and r.get("conclusion") != "failure" and str(r.get("id")) not in alertados]
    num["runs_anunciados"] = [str(r.get("id")) for _t, r in novas]
    num["vermelhos"] = sum(1 for f in falhas if f[2])
    num["vermelhos_ja_alertados_pelo_passo"] = sum(1 for f in falhas if f[2] and f[1].get("conclusion") == "failure")
    num["vermelhos_manuais"] = sum(1 for f in falhas if not f[2])
    if novas:
        anoms.append(anomalia(
            "run_vermelho", "grupo", 5, "Run automático do Consultor de redes estourou o tempo ou nem subiu (o passo de falha não roda nesses casos)",
            "; ".join("%s (%s) %s" % (t, r.get("conclusion"), r.get("html_url")) for t, r in novas[:5]),
            "Abrir o log do run; 'quota' = cota gratuita (a próxima rodada retoma), 'timeout' = travou num provedor, "
            "traceback = defeito de código a corrigir."))
    classificados = sum(len(v) for v in por_tarefa.values())
    faltando = []
    if classificados == len(runs) and runs:  # só julga o "não rodou" quando todo run da janela é identificável
        for t in TAREFAS_DIARIAS:
            ok = [r for r in por_tarefa.get(t, []) if r.get("status") != "completed" or r.get("conclusion") == "success"]
            if not ok:
                faltando.append(t)
    num["nao_rodou"] = faltando
    for t in faltando:
        anoms.append(anomalia(
            "nao_rodou:" + t, "grupo", 5, "O agendador do GitHub não rodou a tarefa diária '%s' com sucesso nas últimas %dh"
            % (t, LIMITES["janela_h"]), "0 run concluído com sucesso de %s na janela" % t,
            "O vigia re-dispara tarefa=%s (workflow_dispatch)." % t, cura="dispatch:" + t))
    return num, anoms, por_tarefa


def checar_consumo(linhas):
    tot = {}
    for l in linhas or []:
        p = l.get("provedor") or "?"
        a = tot.setdefault(p, {"chamadas": 0, "falhas": 0})
        a["chamadas"] += int(l.get("chamadas") or 0)
        a["falhas"] += int(l.get("falhas") or 0)
    return tot


def checar_escaladas(marca, linhas, agora):
    lim = agora - datetime.timedelta(days=LIMITES["escalada_max_dias"])
    esc = [r for r in linhas if r.get("status") == "escalado"]
    velhas = [r for r in esc if (_dt(r.get("enviado_em")) or _dt(r.get("criado_em")) or agora) < lim]
    num = {"escaladas": len(esc), "escaladas_velhas": len(velhas)}
    anoms = []
    if velhas:
        anoms.append(anomalia(
            "escalada_parada:" + marca, marca, 6,
            "Peça escalada pelo Conselho parada há mais de %d dias sem correção (BECO)" % LIMITES["escalada_max_dias"],
            "%d peça(s); ex.: %s" % (len(velhas), velhas[0]["peca_id"]),
            "O vigia DESCARTA com registro (status recusado, p_por=vigia, motivo gravado). A peça segue no git: para "
            "reaproveitar, corrigir e salvar com peca_id novo.", cura="descartar:" + ",".join(r["id"] for r in velhas)))
    return num, anoms, velhas


def checar_collab(marca, linhas, agora, colabs_por_media):
    """colabs_por_media: {url_post_normalizada: (status, corpo)} do GET /{media}/collaborators."""
    lim = agora - datetime.timedelta(days=8)
    recentes = [r for r in linhas if r.get("status") == "publicado" and _dt(r.get("publicado_em")) and _dt(r["publicado_em"]) >= lim]
    solo = [r for r in recentes if r.get("collab_planejada") and not r.get("collab_com")]
    num = {"collab_publicadas_8d": sum(1 for r in recentes if r.get("collab_com")), "collab_saiu_solo": len(solo)}
    anoms = []
    if solo:
        anoms.append(anomalia(
            "collab_solo:" + marca, marca, 7, "Collab planejada saiu SOLO (a API recusou o convite)",
            "%d post(s); ex.: %s com %s" % (len(solo), solo[0]["peca_id"], solo[0]["collab_planejada"]),
            "Conferir se o perfil do parceiro é público/profissional; a regra de 1 collab/semana é conferida na segunda."))
    pend, recus = [], []
    for r in recentes:
        if not r.get("collab_com"):
            continue
        st, corpo = colabs_por_media.get(_norm_link(r.get("url_post")), (None, {}))
        if st != 200:
            continue
        for c in (corpo or {}).get("data") or []:
            s = str(c.get("invite_status") or "").lower()
            idade = (agora - _dt(r["publicado_em"])).days
            if s == "declined":
                recus.append((r, c))
            elif s == "pending" and idade >= LIMITES["collab_pendente_dias"]:
                pend.append((r, c))
    num["convites_pendentes"], num["convites_recusados"] = len(pend), len(recus)
    if pend or recus:
        r, c = (pend or recus)[0]
        anoms.append(anomalia(
            "collab_convite:" + marca, marca, 7, "Convite de collab pendente há %d+ dias ou recusado pelo parceiro"
            % LIMITES["collab_pendente_dias"],
            "%d pendente(s), %d recusado(s); ex.: %s -> @%s (%s)" % (len(pend), len(recus), r["peca_id"], c.get("username"),
                                                                      c.get("invite_status")),
            "Aceitar o convite no app do Instagram da conta parceira (Atividade > Convites de colaboração)."))
    return num, anoms


def contar_seguidas(chave, historico, hoje=None):
    """Quantos DIAS SEGUIDOS anteriores (mais recente primeiro; vale a última rodada de cada dia BRT) já tinham a
    anomalia. Rodadas de hoje (a rápida das 12:40 antes da completa das 17:40) não contam como dia anterior."""
    n, dias = 0, set()
    for h in historico or []:
        v = h.get("veredito") or {}
        if "chaves" not in v:  # linha de reposição (mesmo canal) não é rodada do vigia
            continue
        q = _dt(h.get("quando"))
        dia = q.astimezone(BRT).date().isoformat() if q else str(h.get("quando") or "")[:10]
        if hoje is not None and dia == hoje.isoformat():
            continue
        if dia in dias:
            continue
        dias.add(dia)
        if chave in (v.get("chaves") or []):
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------------------------------------- rodada
def _injecoes(lista):
    out = {}
    for item in lista or []:
        for x in str(item).split(","):
            x = x.strip()
            if not x:
                continue
            k, _, m = x.partition(":")
            out.setdefault(k, set()).add(m or "*")
    return out


def rodar(fontes=None, qa=False, injetar=None, so_marcas=None, agora=None, regras_todas=None, plano_repor=None,
          sem_cura=False, rapida=False):
    """rapida=True (crons 21:45 e 12:40 BRT, logo depois do Conselho e das publicações da manhã): as mesmas checagens e
    o re-disparo de tarefa, SEM o que é diário e caro (reposição por IA, ciclo de artigos, renovação de token, que ficam
    na completa das 17:40); e-mail só com anomalia NOVA em relação à rodada anterior (a completa repete o resumo)."""
    fontes = fontes or Fontes()
    agora = agora or agora_brt()
    hoje = agora.astimezone(BRT).date()
    amanha = hoje + datetime.timedelta(days=1)
    desde = agora - datetime.timedelta(hours=LIMITES["janela_h"])
    inj = _injecoes(injetar) if qa else {}
    if injetar and not qa:
        raise SystemExit("--injetar só vale com --qa (falha controlada nunca roda em produção)")
    regras_todas = regras_todas if regras_todas is not None else marcas.instagram_ativas_regras()
    ativas = [m for m in regras_todas if not so_marcas or m in so_marcas]
    executa_cura = not qa and not sem_cura

    # horários efetivos (mesma regra do publicar)
    try:
        import alcance  # noqa: E402
        rec = alcance.recomendados(list(regras_todas))
        horarios = {m: alcance.horario_efetivo(m, regras_todas, rec) for m in regras_todas}
    except Exception as e:  # noqa: BLE001
        print("horários indisponíveis (%s) — usa 09:00" % str(e)[:80])
        horarios = {}

    st_runs, runs = fontes.gh_runs(desde.astimezone(datetime.timezone.utc))
    if "run_falhou" in inj:
        runs = list(runs) + [{"id": 999000001, "status": "completed", "conclusion": "timed_out", "event": "schedule",
                              "display_title": "Consultor de redes · 10 11-20 * * *",
                              "html_url": "https://github.com/%s/actions/runs/999000001 (INJETADO QA)" % REPO_GH,
                              "updated_at": agora.isoformat()}]
        st_runs = st_runs or 200
    try:
        alertados = fontes.runs_alertados(desde)
    except Exception:  # noqa: BLE001
        alertados = set()
    num_runs, anom_runs, por_tarefa = checar_runs(st_runs, runs, agora, alertados)
    try:
        consumo = checar_consumo(fontes.consumo(hoje - datetime.timedelta(days=1)))
    except Exception as e:  # noqa: BLE001
        consumo = {"erro": str(e)[:80]}

    relatorio = {"quando": agora.isoformat(), "qa": qa, "injetado": sorted("%s:%s" % (k, ",".join(sorted(v))) for k, v in inj.items()),
                 "marcas": {}, "runs": num_runs, "consumo_ia_2d": consumo, "curas": [], "curas_propostas": []}
    anomalias = list(anom_runs)

    for m in ativas:
        r = regras_todas[m]
        num = {}
        try:
            linhas = fontes.linhas(m) or []
            if "escalada_velha" in inj and (m in inj["escalada_velha"] or "*" in inj["escalada_velha"]):
                linhas = list(linhas) + [{"id": "qa-injetado-escalada", "peca_id": "qa-injetado-escalada-" + m,
                                          "status": "escalado", "enviado_em": (agora - datetime.timedelta(days=10)).isoformat()}]
            if "atrasada" in inj and (m in inj["atrasada"] or "*" in inj["atrasada"]):
                linhas = list(linhas) + [{"id": "qa-injetado-atrasada", "peca_id": "qa-injetado-atrasada-" + m,
                                          "status": "aprovado", "canal": "instagram",
                                          "data_publicacao": (hoje - datetime.timedelta(days=2)).isoformat()}]
            decididas = {x["peca_id"] for x in linhas if x.get("status") not in ("rascunho", "aguardando")}
            pendentes = fontes.pendentes_estoque(m, decididas)
            votos = fontes.votos(m, desde) or []
            zerar = "estoque_zero" in inj and (m in inj["estoque_zero"] or "*" in inj["estoque_zero"])
            if zerar:
                linhas_estoque, pendentes_estoque = [x for x in linhas if x.get("status") != "aprovado"], []
            else:
                linhas_estoque, pendentes_estoque = linhas, pendentes

            n1, a1 = checar_conselho(m, linhas, votos, pendentes, desde)
            num["conselho"] = n1
            anomalias += a1

            # token e perfil
            token = fontes.token(m)
            if "token_invalido" in inj and (m in inj["token_invalido"] or "*" in inj["token_invalido"]):
                token = TOKEN_INJETADO
            me = fontes.ig_me(token) if token else (None, {})
            chave_exp = marcas.chave_expira(m)
            expira = fontes.segredo(chave_exp) or (fontes.segredo("ig_token_expira_em") if m == "innconta" else None)
            uid = str(r.get("ig_user_id") or "") or (os.environ.get("IG_USER_ID") if m == "innconta" else "")
            n4, a4 = checar_token(m, token, me, expira, uid, hoje, r.get("handle_instagram"))
            anomalias += a4
            if n4.pop("renovar", False):
                if executa_cura and not rapida:
                    res = fontes.renovar_token(m)
                    relatorio["curas"].append({"marca": m, "cura": "renovar_token", "ok": bool(res.get("ok")),
                                               "expira_em": res.get("expira_em"), "motivo": res.get("motivo")})
                    if res.get("ok"):
                        n4["expira_em"], n4["dias_para_vencer"] = res["expira_em"], (_data(res["expira_em"]) - hoje).days
                    else:
                        anomalias.append(anomalia(
                            "token_nao_renovou:" + m, m, 4, "Token sem data de validade ou perto de vencer e a renovação FALHOU",
                            "motivo %s; vencimento conhecido: %s" % (res.get("motivo"), expira or "desconhecido"),
                            "Token ainda vale (GET /me respondeu 200). Se o motivo for http_400 com token recém-gerado "
                            "(< 24 h), a renovação passa amanhã sozinha; se repetir 3 dias, gerar token novo no painel Meta."))
                else:
                    relatorio["curas_propostas"].append({"marca": m, "cura": "renovar_token",
                                                         "motivo": "vence em %s" % (expira or "data desconhecida")})
            num["token"] = n4

            perfil = None
            colabs = {}
            if n4.get("token") == "válido":
                stp, j = fontes.ig_media(uid, token)
                perfil = {"status": stp, "posts": (j or {}).get("data") or []}
                por_link = {_norm_link(p.get("permalink")): p.get("id") for p in perfil["posts"]}
                for x in linhas:
                    if x.get("collab_com") and x.get("status") == "publicado":
                        mid = por_link.get(_norm_link(x.get("url_post")))
                        if mid:
                            colabs[_norm_link(x.get("url_post"))] = fontes.ig_colaboradores(mid, token)
            publicadas_antes = [x for x in linhas if x.get("status") == "publicado" and _dt(x.get("publicado_em"))
                                and _dt(x["publicado_em"]) < agora - datetime.timedelta(hours=48)]
            n2, a2, _ = checar_publicacao(m, linhas, hoje, agora, horarios.get(m, 540), por_tarefa.get("publicar", []),
                                          perfil, primeira_vez=not publicadas_antes)
            num["publicacao"] = n2
            anomalias += a2

            try:
                art = {} if rapida else fontes.artigos(m, r, gravar=not qa)
            except Exception as e:  # noqa: BLE001 - detector quebrado vira anomalia, nunca derruba o resto
                art = {"erro_ciclo": "%s: %s" % (type(e).__name__, str(e)[:160])}
            reserv = set(art.pop("reservadas", []) or [])
            num["artigos"] = {k: v for k, v in art.items() if k != "transicoes"}
            if art.get("transicoes"):
                num["artigos"]["transicoes"] = art["transicoes"][:10]
            anomalias += checar_artigos(m, art)
            n3, a3 = checar_estoque(m, linhas_estoque, pendentes_estoque, amanha,
                                    bool(_arte_v2(m)), None if rapida else fontes.secoes_disponiveis(m, reserv),
                                    None if rapida else art)
            num["estoque"] = n3
            anomalias += a3
            # artigo novo vira pauta mesmo com o estoque saudável (a reposição por estoque baixo, se houver, sobrescreve
            # este plano e já põe os artigos na frente)
            if _arte_v2(m) and (art.get("novos") or 0) > 0:
                qtd = min(LIMITES["artigos_por_dia"], int(art["novos"]))
                if executa_cura:
                    relatorio["curas"].append({"marca": m, "cura": "pauta_artigo", "quantidade": qtd, "ok": None,
                                               "obs": "executado no passo 'Repor estoque' do job"})
                    if plano_repor is not None and m not in plano_repor:
                        plano_repor[m] = {"quantidade": qtd, "so_artigos": True}
                else:
                    relatorio["curas_propostas"].append({"marca": m, "cura": "pauta_artigo:%d" % qtd})

            n6, a6, velhas = checar_escaladas(m, linhas, agora)
            num["escaladas"] = n6
            anomalias += a6

            n7, a7 = checar_collab(m, linhas, agora, colabs)
            num["collab"] = n7
            anomalias += a7
        except Exception as e:  # noqa: BLE001 - uma marca que quebra não derruba as outras; vira anomalia
            anomalias.append(anomalia("vigia_erro:" + m, m, 0, "O vigia não conseguiu checar a marca",
                                      "%s: %s" % (type(e).__name__, str(e)[:160]),
                                      "Defeito do vigia ou do banco: ler o log do run vigia."))
        relatorio["marcas"][m] = num

    # marcas fora da publicação: só o estado (lista do que ainda exige humano)
    try:
        relatorio["fora_da_publicacao"] = sorted(m for m in marcas.todas() if m not in regras_todas)
    except Exception:  # noqa: BLE001
        relatorio["fora_da_publicacao"] = []

    # auto-curas
    feitos_dispatch = set()
    for a in anomalias:
        cura = a.get("cura") or ""
        if not cura:
            continue
        if not executa_cura:
            relatorio["curas_propostas"].append({"marca": a["marca"], "cura": cura.split(":")[0] + ":" + cura.split(":")[1][:60]})
            continue
        if cura.startswith("dispatch:"):
            t = cura.split(":", 1)[1]
            if t in feitos_dispatch:
                continue
            feitos_dispatch.add(t)
            st = fontes.gh_dispatch(t)
            relatorio["curas"].append({"cura": "dispatch", "tarefa": t, "http": st, "ok": st == 204})
            if st in (401, 403):
                a["acao"] += " (re-disparo NEGADO: HTTP %s = permissão do GITHUB_TOKEN, não queda)" % st
        elif cura.startswith("descartar:"):
            ids = cura.split(":", 1)[1].split(",")
            linhas_m = {x["id"]: x for x in (fontes.linhas(a["marca"]) or [])}
            ok = 0
            for i in ids:
                row = linhas_m.get(i)
                if not row or row.get("status") != "escalado":
                    continue
                mot = "; ".join(str(x) for x in (row.get("conselho_motivos") or [])[:2])[:300]
                if fontes.recusar_escalada(row, "vigia %s: escalada sem correção há mais de %d dias; Conselho: %s"
                                           % (hoje.isoformat(), LIMITES["escalada_max_dias"], mot)):
                    ok += 1
            relatorio["curas"].append({"marca": a["marca"], "cura": "descartar_escaladas", "pedidas": len(ids), "feitas": ok})
            a["acao"] = "FEITO pelo vigia: %d de %d descartada(s) com registro. " % (ok, len(ids)) + a["acao"]
        elif cura.startswith("repor:") and rapida:  # reposição por IA é da completa (17:40), uma vez por dia
            relatorio["curas_propostas"].append({"marca": a["marca"], "cura": cura, "obs": "fica para a rodada completa"})
        elif cura.startswith("repor:"):
            qtd = int(cura.split(":", 1)[1])
            relatorio["curas"].append({"marca": a["marca"], "cura": "repor", "quantidade": qtd, "ok": None,
                                       "obs": "executado no passo 'Repor estoque' do job"})
            if plano_repor is not None:
                plano_repor[a["marca"]] = qtd

    # escalada por acúmulo
    canal = CANAL_QA if qa else CANAL
    try:
        hist = fontes.historico(canal, 20) or []  # 3 rodadas/dia + reposição: 20 linhas cobrem os 3 dias da escalada
    except Exception:  # noqa: BLE001
        hist = []
    for a in anomalias:
        a["dias_seguidos"] = 1 + contar_seguidas(a["chave"], hist, hoje)
    escaladas = [a for a in anomalias if a["dias_seguidos"] >= LIMITES["escalar_apos"]]

    relatorio["rapida"] = rapida
    relatorio["anomalias"] = anomalias
    relatorio["chaves"] = sorted({a["chave"] for a in anomalias})
    avisar = anomalias
    if rapida:
        anterior = next((set((h.get("veredito") or {}).get("chaves") or []) for h in hist
                         if "chaves" in (h.get("veredito") or {})), set())
        avisar = [a for a in anomalias if a["chave"] not in anterior]
        relatorio["ja_avisadas"] = len(anomalias) - len(avisar)
    email_ok = None
    if avisar:
        email_ok = _alertar(fontes, avisar, [a for a in escaladas if a in avisar], relatorio, qa)
    relatorio["email"] = email_ok
    texto = ("vigia%s: %d anomalia(s)%s" % (" rápida" if rapida else "", len(anomalias),
                                            (": " + ", ".join(relatorio["chaves"][:8])) if anomalias else " — tudo em ordem"))
    try:
        fontes.registrar(canal, texto, bool(email_ok) if avisar else True, _enxuto(relatorio))
    except Exception as e:  # noqa: BLE001
        print("aviso: registro em ic_aviso_log falhou:", str(e)[:160])
    print(texto)
    print(json.dumps(_enxuto(relatorio), ensure_ascii=False, indent=1, default=str)[:6000])
    return relatorio


def _arte_v2(marca):
    try:
        with open(os.path.join(RAIZ, "kit", marca, "marca.json"), encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("arte_v2")
    except (OSError, ValueError):
        return None


def _enxuto(rel):
    out = dict(rel)
    out["anomalias"] = [{k: a.get(k) for k in ("chave", "marca", "item", "observado", "dias_seguidos")} for a in rel.get("anomalias", [])]
    return out


def _alertar(fontes, anomalias, escaladas, relatorio, qa):
    para = CENTRAL_QA if qa else CENTRAL
    marcas_afetadas = sorted({a["marca"] for a in anomalias})
    assunto = "%sConsultor de Redes · vigia%s: %d anomalia(s)%s (%s)%s" % (
        "[ESCALADA] " if escaladas else "", " rápida" if relatorio.get("rapida") else "", len(anomalias),
        " nova(s)" if relatorio.get("rapida") else "", ", ".join(marcas_afetadas)[:80], " [QA]" if qa else "")
    linhas = []
    for a in sorted(anomalias, key=lambda x: (-x["dias_seguidos"], x["item"], x["marca"])):
        linhas.append("<tr><td>%s</td><td>%d</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _esc(a["marca"]), a["item"], _esc(a["o_que"]), _esc(a["observado"]), _esc(a["acao"]),
            ("%d dia(s)" % a["dias_seguidos"]) + (" ESCALADA" if a["dias_seguidos"] >= LIMITES["escalar_apos"] else "")))
    curas = "".join("<li>%s</li>" % _esc(json.dumps(c, ensure_ascii=False)) for c in relatorio["curas"]) or "<li>nenhuma</li>"
    html = (
        "<p>Vigia diário do Consultor de Redes (%s%s). Só chega e-mail quando há anomalia; o registro completo de cada "
        "rodada fica em <code>ic_aviso_log</code> (canal <code>%s</code>).</p>"
        "%s"
        "<table border='1' cellpadding='4' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
        "<tr><th>marca</th><th>item</th><th>o que quebrou</th><th>valor observado</th><th>ação</th><th>há</th></tr>%s</table>"
        "<p><b>Auto-curas executadas:</b></p><ul>%s</ul>"
        "<p>Itens: 1 conselho · 2 publicação · 3 estoque · 4 token · 5 runs · 6 escalada parada · 7 collab.</p>"
    ) % (relatorio["quando"][:16], ", QA" if qa else "", CANAL_QA if qa else CANAL,
         ("<p><b>ESCALADA:</b> %d anomalia(s) sem resposta há %d+ rodadas seguidas.</p>" % (len(escaladas), LIMITES["escalar_apos"])
          if escaladas else ""), "".join(linhas), curas)
    try:
        r = fontes.email(assunto, para, html)
        relatorio["email_id"] = (r or {}).get("id") if isinstance(r, dict) else None  # id do Resend: prova de entrega
        return True
    except Exception as e:  # noqa: BLE001
        print("ALERTA: e-mail do vigia à central falhou:", type(e).__name__, str(e)[:160])
        return False


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------------------------- reposição de estoque
def repor(plano, log=print):
    """Gera as peças do plano {marca: quantidade} pelo gerador (site vivo, IA gratuita do Conselho) e as põe na FILA do
    Conselho (frontmatter `status: aprovado` = pronta para revisão; quem aprova de verdade é o Conselho, por unanimidade).
    Devolve {marca: [peca_id,...]}. O commit/push é do passo do workflow (só redes/estoque/**)."""
    import estoque  # noqa: E402
    import gerador  # noqa: E402
    try:
        import artigos  # noqa: E402
        reg = artigos.Registro(qa=False)
    except Exception as e:  # noqa: BLE001 - sem banco: o gerador segue só com seções e os artigos esperam
        log("repor: registro de artigos indisponível (%s)" % str(e)[:120])
        reg = None
    out = {}
    for marca, item in sorted(plano.items()):
        qtd = int(item.get("quantidade", 0)) if isinstance(item, dict) else int(item)
        so_artigos = bool(item.get("so_artigos")) if isinstance(item, dict) else False
        if not _arte_v2(marca) or qtd <= 0:
            continue
        try:
            feitas, recusadas = gerador.gerar_lote(marca, qtd, gerador.MOTORES["conselho"], log=log, artigos_reg=reg,
                                                   so_artigos=so_artigos)
        except Exception as e:  # noqa: BLE001
            log("repor[%s] FALHOU: %s: %s" % (marca, type(e).__name__, str(e)[:160]))
            out[marca] = []
            continue
        ids = []
        for peca_id, _f, _c in feitas:
            estoque.atualizar_status(marca, peca_id, status="aprovado")
            ids.append(peca_id)
        log("repor[%s]: %d gerada(s) e na fila do Conselho, %d descartada(s) pelo gerador" % (marca, len(ids), len(recusadas)))
        out[marca] = ids
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vigia diário do Consultor de Redes")
    ap.add_argument("acao", nargs="?", default="vigiar", choices=("vigiar", "repor"))
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--injetar", action="append", default=[], help="só com --qa: token_invalido:<m>,estoque_zero:<m>,...")
    ap.add_argument("--marcas", default="", help="restringe às marcas (vírgula)")
    ap.add_argument("--sem-cura", action="store_true", help="não executa auto-cura (só registra o que faria)")
    ap.add_argument("--rapida", action="store_true", help="rodada rápida (21:45/12:40 BRT): checa e re-dispara; sem "
                    "reposição, artigos nem renovação de token; e-mail só com anomalia nova")
    ap.add_argument("--plano", default="", help="arquivo JSON {marca: qtd} (vigiar grava; repor lê)")
    ap.add_argument("--repor-forcado", default="", help="marca:qtd[,marca:qtd] — acrescenta ao plano de reposição (operação/prova do commit)")
    a = ap.parse_args(argv)
    if a.acao == "repor":
        plano = {}
        if a.plano and os.path.isfile(a.plano):
            with open(a.plano, encoding="utf-8") as fh:
                plano = json.load(fh)
        feitas = repor(plano)
        placar = {m: len(v) for m, v in feitas.items()}
        print("reposição:", placar)
        vazias = sorted(m for m, n in placar.items() if n == 0)
        f = Fontes()
        try:
            f.registrar(CANAL, "reposição de estoque: %s" % placar, not vazias, {"repor": placar, "plano": plano})
        except Exception as e:  # noqa: BLE001
            print("registro da reposição falhou:", str(e)[:160])
        if vazias:
            try:
                f.email("Consultor de Redes · reposição de estoque NÃO gerou peça (%s)" % ", ".join(vazias), CENTRAL,
                        "<p>O vigia pediu peças novas e o gerador não produziu nenhuma para: <b>%s</b> (plano %s).</p>"
                        "<p><b>Ação:</b> ler o log do run vigia, passo 'Repor estoque': 'ADIADA' = sem cota gratuita (repete "
                        "amanhã sozinho); '0 seção(ões) disponíveis' = o site da marca não tem seção nova (publicar página ou "
                        "artigo novo no site); 'descartada' em todas = validação do gerador barrou.</p>" % (_esc(", ".join(vazias)), _esc(plano)))
            except Exception as e:  # noqa: BLE001
                print("e-mail da reposição falhou:", str(e)[:160])
        return 0
    plano = {}
    so = [x.strip() for x in a.marcas.split(",") if x.strip()] or None
    rodar(qa=a.qa, injetar=a.injetar, so_marcas=so, plano_repor=None if a.rapida else plano, sem_cura=a.sem_cura,
          rapida=a.rapida)
    for item in [x for x in a.repor_forcado.split(",") if ":" in x and not a.rapida]:
        m, _, n = item.partition(":")
        if not a.qa and _arte_v2(m.strip()):
            plano[m.strip()] = max(1, min(LIMITES["repor_max"], int(n)))
    if a.plano:
        with open(a.plano, "w", encoding="utf-8") as fh:
            json.dump(plano, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
