# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem banco, sem Instagram, sem GitHub) de `redes/vigia.py` — mesmo padrão dos demais
`testar_*.py`. Cada checagem tem o CONTROLE NEGATIVO (estado saudável -> nenhuma anomalia) e a falha injetada
(-> anomalia com valor observado e ação). Cobre também: e-mail só quando há anomalia (sempre à central, nunca ao CVO);
registro em toda rodada; QA nunca executa auto-cura; produção executa (descartar escalada, re-disparar, renovar token,
plano de reposição); escalada por acúmulo (3 rodadas seguidas); 401/403 classificado como credencial; --injetar
recusado fora de QA.

Roda `python redes/testar_vigia.py` a partir da raiz do repo; sai com código != 0 se qualquer prova falhar."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import vigia  # noqa: E402

FALHAS = []
BRT = vigia.BRT
AGORA = datetime.datetime(2026, 10, 8, 17, 40, tzinfo=BRT)
HOJE = AGORA.date()


def checar(nome, got, esperado):
    ok = got == esperado
    print(("OK  " if ok else "FALHA") + " - %s -> %r (esperado %r)" % (nome, got, esperado))
    if not ok:
        FALHAS.append(nome)


def iso(d, h=12):
    return datetime.datetime(d.year, d.month, d.day, h, 0, tzinfo=BRT).isoformat()


def linhas_saudaveis(marca="mx"):
    out = []
    for i in range(1, 11):  # 10 aprovadas, uma por dia a partir de amanhã
        d = HOJE + datetime.timedelta(days=i)
        out.append({"id": "f%d" % i, "peca_id": "%s-fut-%d" % (marca, i), "status": "aprovado", "canal": "instagram",
                    "data_publicacao": d.isoformat(), "publicado_em": None, "enviado_em": iso(HOJE - datetime.timedelta(days=1)),
                    "aprovado_em": iso(HOJE - datetime.timedelta(days=1))})
    out.append({"id": "p0", "peca_id": "%s-hoje" % marca, "status": "publicado", "canal": "instagram",
                "data_publicacao": HOJE.isoformat(), "publicado_em": iso(HOJE, 10), "url_post": "https://www.instagram.com/p/HOJE/"})
    out.append({"id": "p1", "peca_id": "%s-velha" % marca, "status": "publicado", "canal": "instagram",
                "data_publicacao": (HOJE - datetime.timedelta(days=5)).isoformat(),
                "publicado_em": iso(HOJE - datetime.timedelta(days=5), 10), "url_post": "https://www.instagram.com/p/VELHA/"})
    out.append({"id": "e1", "peca_id": "%s-esc" % marca, "status": "escalado", "enviado_em": iso(HOJE - datetime.timedelta(days=2))})
    return out


class FontesFalsas:
    def __init__(self, linhas=None, votos=None, pendentes=None, token="tok-falso", me=None, expira="2026-12-20",
                 runs=None, st_runs=200, historico=None, media=None, colabs=None):
        self._linhas = linhas if linhas is not None else linhas_saudaveis()
        self._votos = votos if votos is not None else [{"peca_id": "x", "revisor": "fato", "passa": True}]
        self._pendentes = pendentes if pendentes is not None else []
        self._token = token
        self._me = me or (200, {"user_id": "111", "username": "mx.oficial"})
        self._expira = expira
        self._runs = runs if runs is not None else [
            {"id": 1, "status": "completed", "conclusion": "success", "event": "schedule",
             "display_title": "Consultor de redes · 20 0 * * *", "updated_at": iso(HOJE, 2)},
            {"id": 2, "status": "completed", "conclusion": "success", "event": "schedule",
             "display_title": "Consultor de redes · 10 11-20 * * *", "updated_at": iso(HOJE, 10)},
            {"id": 3, "status": "completed", "conclusion": "success", "event": "schedule",
             "display_title": "Consultor de redes · 0 8 * * *", "updated_at": iso(HOJE, 5)}]
        self._st_runs = st_runs
        self._hist = historico or []
        self._media = media if media is not None else [
            {"id": "m1", "permalink": "https://www.instagram.com/p/HOJE/", "timestamp": iso(HOJE, 10)},
            {"id": "m2", "permalink": "https://www.instagram.com/p/VELHA/", "timestamp": iso(HOJE - datetime.timedelta(days=5), 10)}]
        self._colabs = colabs or {}
        self.emails, self.registros, self.dispatches, self.recusadas, self.renovadas = [], [], [], [], []

    def linhas(self, marca):
        return [dict(x) for x in self._linhas]

    def votos(self, marca, desde):
        return self._votos

    def consumo(self, d):
        return [{"provedor": "cf", "chamadas": 10, "falhas": 0}]

    def segredo(self, chave):
        return self._expira if chave.startswith("ig_token_expira_em") else None

    def historico(self, canal, n=10):
        return self._hist

    def runs_alertados(self, desde):
        return set()

    def pendentes_estoque(self, marca, decididas):
        return list(self._pendentes)

    def token(self, marca):
        return self._token

    def secoes_disponiveis(self, marca, excluir=None):
        self.excluir_secoes = set(excluir or ())
        return getattr(self, "_secoes", 50)

    def artigos(self, marca, regras, gravar=True):
        self.artigos_gravar = gravar
        if getattr(self, "_artigos_erro", None):
            raise RuntimeError(self._artigos_erro)
        base = {"indice": "ok", "http": 200, "erro": None, "url_indice": "https://mx.test/sitemap.xml", "no_indice": 3,
                "registrados": 3, "novos": 0, "em_pauta": 0, "consumidos": 3, "descartados": 0, "base": 0,
                "ultimo_artigo_visto": "2026-10-01", "descartados_26h": [], "detectados_agora": 0, "base_agora": 0,
                "transicoes": [], "reservadas": ["https://mx.test/insights/a"]}
        base.update(getattr(self, "_artigos", {}) or {})
        return dict(base)

    def ig_me(self, token):
        if token == vigia.TOKEN_INJETADO:
            return 400, {"error": {"code": 190, "message": "Invalid OAuth access token"}}
        return self._me

    def ig_media(self, uid, token):
        return 200, {"data": self._media}

    def ig_colaboradores(self, media_id, token):
        return self._colabs.get(media_id, (200, {"data": []}))

    def gh_runs(self, desde):
        return self._st_runs, self._runs

    def gh_dispatch(self, tarefa):
        self.dispatches.append(tarefa)
        return 204

    def recusar_escalada(self, row, motivo):
        self.recusadas.append((row["id"], motivo))
        return True

    def renovar_token(self, marca):
        self.renovadas.append(marca)
        return {"ok": True, "expira_em": "2026-12-07"}

    def registrar(self, canal, texto, entregue, veredito):
        self.registros.append((canal, texto, entregue, veredito))

    def email(self, assunto, para, html):
        self.emails.append((assunto, para, html))


REGRAS = {"mx": {"marca": "mx", "ig_user_id": "111", "handle_instagram": "@mx.oficial",
                 "publicar": {"instagram": True, "horario_brt": "09:00"}}}


def rodar(f, qa=False, **k):
    plano = {}
    rel = vigia.rodar(fontes=f, qa=qa, agora=AGORA, regras_todas=REGRAS, plano_repor=plano, **k)
    return rel, plano


def chaves(rel):
    return sorted(a["chave"].split(":")[0] for a in rel["anomalias"])


print("== CONTROLE NEGATIVO: tudo saudável -> 0 anomalia, 0 e-mail, 1 registro ==")
f = FontesFalsas()
rel, plano = rodar(f)
checar("sem anomalia", chaves(rel), [])
checar("sem e-mail", len(f.emails), 0)
checar("registro gravado (canal redes_vigia, entregue True)", [(r[0], r[2]) for r in f.registros], [("redes_vigia", True)])
checar("sem auto-cura", (f.dispatches, f.recusadas, f.renovadas, plano), ([], [], [], {}))
checar("token conferido e dias para vencer", (rel["marcas"]["mx"]["token"]["token"], rel["marcas"]["mx"]["token"]["dias_para_vencer"]), ("válido", 73))
checar("post de hoje conferido no perfil", rel["marcas"]["mx"]["publicacao"]["conferidas_no_perfil"], 1)

print("\n== 1 · Conselho parado: fila pendente e 0 votos ==")
f = FontesFalsas(votos=[], pendentes=["a", "b"])
rel, _ = rodar(f)
checar("anomalia conselho_parado", "conselho_parado" in chaves(rel), True)
checar("e-mail à central (nunca ao CVO)", [e[1] for e in f.emails], [vigia.CENTRAL])
f = FontesFalsas(votos=[], pendentes=[])
rel, _ = rodar(f)
checar("controle: 0 votos mas fila vazia -> sem anomalia", "conselho_parado" in chaves(rel), False)

print("\n== 2 · Publicação ==")
ls = linhas_saudaveis() + [{"id": "v1", "peca_id": "mx-vencida", "status": "aprovado", "canal": "instagram",
                            "data_publicacao": (HOJE - datetime.timedelta(days=1)).isoformat()}]
f = FontesFalsas(linhas=ls)
rel, _ = rodar(f)
checar("vencida -> atrasada", "atrasada" in chaves(rel), True)
checar("produção re-dispara publicar (uma vez)", f.dispatches, ["publicar"])
ls = [x for x in linhas_saudaveis() if x["id"] != "p0"] + [{"id": "h1", "peca_id": "mx-hoje2", "status": "aprovado",
                                                            "canal": "instagram", "data_publicacao": HOJE.isoformat()}]
f = FontesFalsas(linhas=ls)
rel, _ = rodar(f)
checar("peça de hoje não saiu após rodada de publicar -> nao_saiu_hoje", "nao_saiu_hoje" in chaves(rel), True)
f = FontesFalsas(linhas=ls, runs=[r for r in FontesFalsas()._runs if "11-20" not in r["display_title"]] +
                 [{"id": 9, "status": "completed", "conclusion": "success", "event": "schedule",
                   "display_title": "Consultor de redes · 10 11-20 * * *", "updated_at": iso(HOJE, 8)}])
rel, _ = rodar(f)
checar("controle: publicar só rodou ANTES do horário -> sem nao_saiu_hoje", "nao_saiu_hoje" in chaves(rel), False)
f = FontesFalsas(media=[{"id": "m2", "permalink": "https://www.instagram.com/p/VELHA/", "timestamp": iso(HOJE - datetime.timedelta(days=5))}])
rel, _ = rodar(f)
checar("publicado no banco e ausente do perfil -> fora_do_perfil", "fora_do_perfil" in chaves(rel), True)
f = FontesFalsas(media=FontesFalsas()._media + [{"id": "m9", "permalink": "https://www.instagram.com/p/DUP/", "timestamp": iso(HOJE, 11)}])
rel, _ = rodar(f)
checar("perfil com post a mais nas 24h -> post_sem_registro (duplicado)", "post_sem_registro" in chaves(rel), True)

print("\n== 8 · Primeiro post de marca nova conferido no perfil ==")
ls = [x for x in linhas_saudaveis() if x["id"] != "p1"]
f = FontesFalsas(linhas=ls)
rel, _ = rodar(f)
checar("primeiro post conferido", (rel["marcas"]["mx"]["publicacao"].get("primeiro_post") or {}).get("conferido_no_perfil"), True)
f = FontesFalsas(linhas=ls, media=[])
rel, _ = rodar(f)
checar("primeiro post AUSENTE do perfil -> fora_do_perfil + conferido False",
       ("fora_do_perfil" in chaves(rel), rel["marcas"]["mx"]["publicacao"]["primeiro_post"]["conferido_no_perfil"]), (True, False))

print("\n== 3 · Estoque ==")
ls = [x for x in linhas_saudaveis() if not x["id"].startswith("f")]
f = FontesFalsas(linhas=ls, pendentes=[])
orig = vigia._arte_v2
vigia._arte_v2 = lambda m: {"categorias": {}}
try:
    rel, plano = rodar(f)
    checar("estoque zerado -> estoque_baixo", "estoque_baixo" in chaves(rel), True)
    checar("marca com arte_v2 -> plano de reposição de 7 (teto)", plano, {"mx": 7})
    f = FontesFalsas(linhas=ls, pendentes=["p%d" % i for i in range(14)])
    rel, plano = rodar(f)
    checar("fila do Conselho já cheia -> alerta sem repor", (("estoque_baixo" in chaves(rel)), plano), (True, {}))
    rel, plano = rodar(FontesFalsas(linhas=ls), qa=True)
    checar("QA nunca repõe (só propõe)", (plano, [c["cura"] for c in rel["curas_propostas"]]), ({}, ["repor:7"]))
finally:
    vigia._arte_v2 = orig
vigia_arte = vigia._arte_v2
vigia._arte_v2 = lambda m: None
try:
    rel, plano = rodar(FontesFalsas(linhas=ls))
    checar("marca sem arte_v2 -> alerta com ação, sem plano", (("estoque_baixo" in chaves(rel)), plano), (True, {}))
finally:
    vigia._arte_v2 = vigia_arte

f = FontesFalsas()
f._secoes = 2
rel, _ = rodar(f)
checar("site com 2 seções livres -> fonte_acabando", "fonte_acabando" in chaves(rel), True)
f = FontesFalsas()
f._secoes = None
rel, _ = rodar(f)
checar("controle: seções não medidas -> sem fonte_acabando", "fonte_acabando" in chaves(rel), False)

print("\n== 3-A · Artigo novo do site como fonte (redes/artigos.py) ==")
orig = vigia._arte_v2
vigia._arte_v2 = lambda m: {"categorias": {}}
try:
    # controle negativo: 50 seções livres, 0 artigo novo -> nada de fonte_acabando, nenhum plano
    f = FontesFalsas()
    rel, plano = rodar(f)
    checar("controle: fonte folgada e 0 artigo novo -> sem fonte_acabando e sem plano", ("fonte_acabando" in chaves(rel), plano), (False, {}))
    checar("vigia em produção GRAVA o ciclo de artigos", f.artigos_gravar, True)
    checar("URLs de artigo registrado saem da conta de seções", f.excluir_secoes, {"https://mx.test/insights/a"})
    # artigo novo com o estoque saudável -> pauta de artigo (só artigos), teto por dia
    f = FontesFalsas()
    f._artigos = {"novos": 5}
    rel, plano = rodar(f)
    checar("5 artigos novos, estoque saudável -> plano só de artigos, teto %d/dia" % vigia.LIMITES["artigos_por_dia"],
           plano, {"mx": {"quantidade": vigia.LIMITES["artigos_por_dia"], "so_artigos": True}})
    checar("artigo novo não é anomalia (sem e-mail)", (chaves(rel), len(f.emails)), ([], 0))
    checar("número no registro: artigos_novos e fonte_inedita = seções + artigos",
           (rel["marcas"]["mx"]["estoque"]["artigos_novos"], rel["marcas"]["mx"]["estoque"]["fonte_inedita"]), (5, 55))
    # QA: só lê (gravar=False) e só propõe
    f = FontesFalsas()
    f._artigos = {"novos": 1}
    rel, plano = rodar(f, qa=True)
    checar("QA: ciclo de artigos só leitura, sem plano, pauta proposta",
           (f.artigos_gravar, plano, [c["cura"] for c in rel["curas_propostas"]]), (False, {}, ["pauta_artigo:1"]))
    # estoque baixo + artigo novo: a reposição (7) vale e o gerador já põe artigo na frente
    ls0 = [x for x in linhas_saudaveis() if not x["id"].startswith("f")]
    f = FontesFalsas(linhas=ls0, pendentes=[])
    f._artigos = {"novos": 1}
    rel, plano = rodar(f)
    checar("estoque baixo + artigo novo -> reposição normal (int, artigo vai na frente no gerador)", plano, {"mx": 7})
    # SEM artigo novo e fonte baixa -> fonte_acabando diz que fica sem pauta inédita, com valor observado
    f = FontesFalsas()
    f._secoes = 2
    rel, _ = rodar(f)
    a = [x for x in rel["anomalias"] if x["chave"].startswith("fonte_acabando")]
    checar("sem artigo novo + 2 seções -> fonte_acabando", bool(a), True)
    checar("observado traz 0 artigo novo, índice, último artigo e data-limite",
           bool(a) and all(t in a[0]["observado"] for t in ("0 artigo(s) novo(s)", "índice ok: 3 artigo(s) no site", "2026-10-01", "cobrem a agenda até ~")), True)
    checar("ação diz SEM ARTIGO NOVO, sem pauta inédita, nada inventado, seção antiga só com o CVO",
           bool(a) and all(t in a[0]["acao"] for t in ("SEM ARTIGO NOVO", "sem pauta inédita", "nada é inventado", "decisão do CVO")), True)
    # com artigo novo suficiente, a mesma pouca seção NÃO alerta (artigo conta como fonte)
    f = FontesFalsas()
    f._secoes = 2
    f._artigos = {"novos": 6}
    rel, _ = rodar(f)
    checar("2 seções + 6 artigos novos = 8 >= 7 -> sem fonte_acabando (artigo conta como fonte)", "fonte_acabando" in chaves(rel), False)
    f = FontesFalsas()
    f._secoes = 2
    f._artigos = {"novos": 2}
    rel, _ = rodar(f)
    a = [x for x in rel["anomalias"] if x["chave"].startswith("fonte_acabando")]
    checar("2 seções + 2 artigos = 4 -> fonte_acabando, ação fala dos artigos virando pauta",
           bool(a) and "2 artigo(s) novo(s) virando pauta" in a[0]["acao"], True)
    # empty state gracioso: marca sem nenhum artigo no site (índice vazio, nada registrado) -> sem artigos_indice
    f = FontesFalsas()
    f._artigos = {"indice": "vazio", "no_indice": 0, "registrados": 0, "consumidos": 0, "ultimo_artigo_visto": None, "reservadas": []}
    rel, _ = rodar(f)
    checar("marca sem artigo nenhum (índice vazio, 0 registrado) -> sem anomalia de índice", "artigos_indice" in chaves(rel), False)
    f._secoes = 1
    rel, _ = rodar(f)
    a = [x for x in rel["anomalias"] if x["chave"].startswith("fonte_acabando")]
    checar("marca sem artigo + 1 seção -> fonte_acabando com 'nenhum artigo novo registrado'",
           bool(a) and "nenhum artigo novo registrado" in a[0]["observado"] and "índice vazio: 0 artigo(s)" in a[0]["observado"], True)
    # índice que esvaziou tendo artigos registrados -> alerta
    f = FontesFalsas()
    f._artigos = {"indice": "vazio", "no_indice": 0, "registrados": 4, "base": 0}
    rel, _ = rodar(f)
    checar("índice ficou vazio com 4 artigos registrados -> artigos_indice", "artigos_indice" in chaves(rel), True)
    # site fora do ar -> alerta técnico à central (nunca mudo)
    f = FontesFalsas()
    f._artigos = {"indice": "indisponivel", "http": None, "erro": "URLError: timed out", "no_indice": 0}
    rel, _ = rodar(f)
    a = [x for x in rel["anomalias"] if x["chave"].startswith("artigos_indice")]
    checar("site fora do ar -> artigos_indice com o erro observado", bool(a) and "timed out" in a[0]["observado"], True)
    checar("... e-mail à CENTRAL (AOP-01), nunca ao CVO", [e[1] for e in f.emails], [vigia.CENTRAL])
    f = FontesFalsas()
    f._artigos = {"indice": "negado", "http": 403, "erro": "HTTP 403", "no_indice": 0}
    rel, _ = rodar(f)
    a = [x for x in rel["anomalias"] if x["chave"].startswith("artigos_indice")]
    checar("403 no índice -> 'acesso NEGADO', não 'fora do ar'", bool(a) and "NEGADO" in a[0]["acao"] and "fora do ar" not in a[0]["acao"], True)
    # detector quebrado (banco) -> anomalia, as outras checagens seguem
    f = FontesFalsas()
    f._artigos_erro = "SELECT ic_redes_artigo HTTP 404: relation does not exist"
    rel, _ = rodar(f)
    checar("detector quebrado -> artigos_erro e o resto do vigia segue (token checado)",
           ("artigos_erro" in chaves(rel), rel["marcas"]["mx"].get("token", {}).get("token")), (True, "válido"))
    # artigo descartado nas últimas 26 h -> avisa uma vez
    f = FontesFalsas()
    f._artigos = {"descartados_26h": ["https://mx.test/insights/b"], "descartados": 1}
    rel, _ = rodar(f)
    checar("artigo descartado nas 26 h -> artigo_descartado com a URL",
           [x["observado"] for x in rel["anomalias"] if x["chave"].startswith("artigo_descartado")], ["1 artigo(s): https://mx.test/insights/b"])
finally:
    vigia._arte_v2 = orig
vigia._arte_v2 = lambda m: None
try:
    f = FontesFalsas()
    f._artigos = {"novos": 3}
    rel, plano = rodar(f)
    checar("marca SEM arte_v2 com artigo novo -> sem plano (gerador não se aplica), número registrado",
           (plano, rel["marcas"]["mx"]["artigos"]["novos"]), ({}, 3))
finally:
    vigia._arte_v2 = orig

print("\n== 4 · Token ==")
rel, _ = rodar(FontesFalsas(token=None))
checar("marca ativa sem token -> sem_token", "sem_token" in chaves(rel), True)
f = FontesFalsas(me=(400, {"error": {"code": 190, "message": "Error validating access token"}}))
rel, _ = rodar(f)
anom = [a for a in rel["anomalias"] if a["chave"].startswith("token_invalido")]
checar("HTTP 400/190 -> token_invalido (credencial)", bool(anom), True)
checar("mensagem diz CREDENCIAL, não queda", "CREDENCIAL" in anom[0]["o_que"] if anom else False, True)
rel, _ = rodar(FontesFalsas(me=(503, {})))
checar("HTTP 503 -> ig_api_indisponivel (serviço, não credencial)",
       ("ig_api_indisponivel" in chaves(rel), "token_invalido" in chaves(rel)), (True, False))
rel, _ = rodar(FontesFalsas(me=(200, {"user_id": "999", "username": "outra"})))
checar("token de outra conta -> token_outra_conta", "token_outra_conta" in chaves(rel), True)
f = FontesFalsas(expira=None)
rel, _ = rodar(f)
checar("sem data de validade -> produção renova sozinha, sem anomalia", (f.renovadas, chaves(rel)), (["mx"], []))
checar("depois de renovar, dias conhecidos", rel["marcas"]["mx"]["token"]["dias_para_vencer"], 60)
f = FontesFalsas(expira=(HOJE + datetime.timedelta(days=5)).isoformat())
f.renovar_token = lambda m: {"ok": False, "motivo": "http_400"}
rel, _ = rodar(f)
checar("perto de vencer e renovação falha -> token_nao_renovou", "token_nao_renovou" in chaves(rel), True)
f = FontesFalsas(expira=None)
rel, _ = rodar(f, qa=True)
checar("QA não renova (só propõe)", (f.renovadas, [c["cura"] for c in rel["curas_propostas"]]), ([], ["renovar_token"]))

print("\n== 5 · Runs ==")
runs = FontesFalsas()._runs + [{"id": 77, "status": "completed", "conclusion": "timed_out", "event": "schedule",
                                "display_title": "Consultor de redes · 0 8 * * *", "html_url": "u77", "updated_at": iso(HOJE, 5)}]
rel, _ = rodar(FontesFalsas(runs=runs))
checar("run agendado que estourou o tempo -> run_vermelho", ("run_vermelho" in chaves(rel), rel["runs"]["runs_anunciados"]), (True, ["77"]))
f = FontesFalsas(runs=runs)
f.runs_alertados = lambda desde: {"77"}
rel, _ = rodar(f)
checar("controle: run já anunciado ontem -> não repete", "run_vermelho" in chaves(rel), False)
runs_f = FontesFalsas()._runs + [{"id": 76, "status": "completed", "conclusion": "failure", "event": "schedule",
                                  "display_title": "Consultor de redes · 0 8 * * *"}]
rel, _ = rodar(FontesFalsas(runs=runs_f))
checar("controle: 'failure' agendado já foi pelo passo de falha -> só registro",
       ("run_vermelho" in chaves(rel), rel["runs"]["vermelhos_ja_alertados_pelo_passo"]), (False, 1))
runs_m = FontesFalsas()._runs + [{"id": 78, "status": "completed", "conclusion": "failure", "event": "workflow_dispatch",
                                  "triggering_actor": {"login": "zarkatus"}, "display_title": "Consultor de redes · ensaio"}]
rel, _ = rodar(FontesFalsas(runs=runs_m))
checar("controle: dispatch MANUAL vermelho -> só registro, sem alerta", ("run_vermelho" in chaves(rel), rel["runs"]["vermelhos_manuais"]), (False, 1))
runs_qa = FontesFalsas()._runs + [{"id": 79, "status": "completed", "conclusion": "failure", "event": "schedule",
                                   "display_title": "Consultor de redes · vigia (qa)"}]
rel, _ = rodar(FontesFalsas(runs=runs_qa))
checar("controle: run de QA vermelho -> sem alerta", "run_vermelho" in chaves(rel), False)
f = FontesFalsas(runs=[r for r in FontesFalsas()._runs if "20 0" not in r["display_title"]])
rel, _ = rodar(f)
checar("conselho_diario não rodou -> nao_rodou + re-disparo", ("nao_rodou" in chaves(rel), f.dispatches), (True, ["conselho_diario"]))
f = FontesFalsas(runs=FontesFalsas()._runs[1:] + [{"id": 5, "status": "completed", "conclusion": "success",
                                                    "display_title": "Consultor de redes"}])
rel, _ = rodar(f)
checar("controle: run sem run-name (antigo) na janela -> dead-man não julga", ("nao_rodou" in chaves(rel), f.dispatches), (False, []))
rel, _ = rodar(FontesFalsas(st_runs=403, runs=[]))
checar("GitHub 403 -> gh_credencial (credencial, não queda)", "gh_credencial" in chaves(rel), True)
checar("tarefa_do_titulo cron", vigia.tarefa_do_titulo("Consultor de redes · 0 9 * * *"), "conselho_diario")
checar("tarefa_do_titulo dispatch qa", vigia.tarefa_do_titulo("Consultor de redes · vigia (qa)"), "vigia")
checar("tarefa_do_titulo antigo", vigia.tarefa_do_titulo("Consultor de redes"), None)
checar("tarefa_do_titulo pg_cron", vigia.tarefa_do_titulo("Consultor de redes · publicar [agendado]"), "publicar")
checar("tarefa_do_titulo pg_cron qa", vigia.tarefa_do_titulo("Consultor de redes · vigia (qa) [agendado]"), "vigia")
runs_pg = FontesFalsas()._runs + [{"id": 80, "status": "completed", "conclusion": "timed_out", "event": "workflow_dispatch",
                                   "triggering_actor": {"login": "zarkatus"}, "display_title": "Consultor de redes · conselho_diario [agendado]"}]
rel, _ = rodar(FontesFalsas(runs=runs_pg))
checar("disparo do pg_cron que estourou o tempo -> automático, alerta", ("run_vermelho" in chaves(rel), rel["runs"]["vermelhos_manuais"]), (True, 0))
f = FontesFalsas(runs=[r for r in FontesFalsas()._runs if "10 11-20" not in r["display_title"]])
rel, _ = rodar(f)
checar("controle: dia sem run de publicar (pg_cron só dispara com peça devida) -> sem nao_rodou", ("nao_rodou" in chaves(rel), f.dispatches), (False, []))

print("\n== 6 · Escalada parada (BECO) ==")
ls = linhas_saudaveis() + [{"id": "e9", "peca_id": "mx-esc-velha", "status": "escalado",
                            "enviado_em": iso(HOJE - datetime.timedelta(days=9)), "conselho_motivos": ["fato: número fora da fonte"]}]
f = FontesFalsas(linhas=ls)
rel, _ = rodar(f)
checar("escalada > 7 dias -> escalada_parada", "escalada_parada" in chaves(rel), True)
checar("produção descarta SÓ a velha, com motivo gravado", [r[0] for r in f.recusadas], ["e9"])
checar("motivo cita o Conselho", "número fora da fonte" in (f.recusadas[0][1] if f.recusadas else ""), True)
f = FontesFalsas(linhas=ls)
rel, _ = rodar(f, qa=True)
checar("QA não descarta", f.recusadas, [])
checar("controle: escalada de 2 dias não é tocada", [a for a in rodar(FontesFalsas())[0]["anomalias"] if a["chave"].startswith("escalada")], [])

print("\n== 7 · Collab ==")
ls = linhas_saudaveis()
ls[-3] = dict(ls[-3], collab_planejada="parceira", collab_com=None)  # p0 publicado hoje planejado em collab, saiu solo
rel, _ = rodar(FontesFalsas(linhas=ls))
checar("collab planejada saiu solo -> collab_solo", "collab_solo" in chaves(rel), True)
ls = linhas_saudaveis()
ls[-2] = dict(ls[-2], collab_com="parceira")  # p1 (5 dias) em collab
f = FontesFalsas(linhas=ls, colabs={"m2": (200, {"data": [{"username": "parceira.oficial", "invite_status": "Pending"}]})})
rel, _ = rodar(f)
checar("convite pendente há 5 dias -> collab_convite", "collab_convite" in chaves(rel), True)
f = FontesFalsas(linhas=ls, colabs={"m2": (200, {"data": [{"username": "parceira.oficial", "invite_status": "Accepted"}]})})
rel, _ = rodar(f)
checar("controle: convite aceito -> sem anomalia", "collab_convite" in chaves(rel), False)

print("\n== Escalada por acúmulo (PJC-01f) ==")
hist = [{"quando": (HOJE - datetime.timedelta(days=i)).isoformat() + "T20:40", "veredito": {"chaves": ["sem_token:mx"]}} for i in (1, 2)]
f = FontesFalsas(token=None, historico=hist)
rel, _ = rodar(f)
checar("3ª rodada seguida -> assunto [ESCALADA]", f.emails[0][0].startswith("[ESCALADA]") if f.emails else False, True)
f = FontesFalsas(token=None, historico=[hist[0], {"quando": "2026-10-06T20:40", "veredito": {"chaves": []}}])
rel, _ = rodar(f)
checar("controle: 2ª rodada (intervalo quebrado) -> sem [ESCALADA]", f.emails[0][0].startswith("[ESCALADA]") if f.emails else True, False)

hist_r = [{"quando": (HOJE - datetime.timedelta(days=1)).isoformat() + "T20:50", "veredito": {"repor": {"mx": 0}}},
          {"quando": (HOJE - datetime.timedelta(days=1)).isoformat() + "T20:40", "veredito": {"chaves": ["sem_token:mx"]}}]
checar("linha de reposição no mesmo canal não quebra a contagem", vigia.contar_seguidas("sem_token:mx", hist_r), 1)

print("\n== Rodada rápida (21:45/12:40 BRT: checa e re-dispara; sem reposição/artigos/token; e-mail só se anomalia nova) ==")
orig = vigia._arte_v2
vigia._arte_v2 = lambda m: {"categorias": {}}  # marca com gerador automático: a completa repõe
try:
    f = FontesFalsas(linhas=[], expira=(HOJE + datetime.timedelta(days=3)).isoformat())
    rel, plano = rodar(f, rapida=True)
    checar("rápida com estoque zero -> anomalia estoque_baixo continua sendo vista", "estoque_baixo" in chaves(rel), True)
    checar("rápida -> NÃO planeja reposição por IA", plano, {})
    checar("rápida -> reposição vira só proposta", any(str(c.get("cura", "")).startswith("repor:") for c in rel["curas_propostas"]), True)
    checar("rápida -> NÃO roda o ciclo de artigos", hasattr(f, "artigos_gravar"), False)
    checar("rápida -> NÃO renova token (fica para a completa)", f.renovadas, [])
    f = FontesFalsas(linhas=[], expira=(HOJE + datetime.timedelta(days=3)).isoformat())
    rel, plano = rodar(f)
    checar("controle: completa no mesmo estado -> planeja reposição", bool(plano), True)
    checar("controle: completa -> roda o ciclo de artigos", hasattr(f, "artigos_gravar"), True)
    checar("controle: completa -> renova token", f.renovadas, ["mx"])
finally:
    vigia._arte_v2 = orig
ontem_mesma = [{"quando": (HOJE - datetime.timedelta(days=1)).isoformat() + "T20:40:00+00:00", "veredito": {"chaves": ["sem_token:mx"]}}]
f = FontesFalsas(token=None, historico=ontem_mesma)
rel, _ = rodar(f, rapida=True)
checar("rápida com anomalia JÁ avisada na rodada anterior -> sem e-mail", len(f.emails), 0)
checar("rápida sem e-mail -> ainda registra a rodada (dead-man)", [r[1].startswith("vigia rápida") for r in f.registros], [True])
f = FontesFalsas(token=None, historico=[{"quando": ontem_mesma[0]["quando"], "veredito": {"chaves": []}}])
rel, _ = rodar(f, rapida=True)
checar("rápida com anomalia NOVA -> e-mail à central, assunto 'vigia rápida'",
       [(e[1], "vigia rápida" in e[0]) for e in f.emails], [(vigia.CENTRAL, True)])
f = FontesFalsas(token=None, historico=ontem_mesma)
rel, _ = rodar(f)
checar("controle: completa repete o resumo mesmo já avisada", len(f.emails), 1)
f = FontesFalsas()
rel, _ = rodar(f, rapida=True)
checar("controle: rápida saudável -> nenhuma anomalia, nenhum e-mail", (chaves(rel), len(f.emails)), ([], 0))
hoje_e_ontem = [{"quando": HOJE.isoformat() + "T15:40:00+00:00", "veredito": {"chaves": ["sem_token:mx"]}},
                {"quando": (HOJE - datetime.timedelta(days=1)).isoformat() + "T20:40:00+00:00", "veredito": {"chaves": ["sem_token:mx"]}}]
checar("escalada: rodada rápida de HOJE não conta como dia anterior", vigia.contar_seguidas("sem_token:mx", hoje_e_ontem, HOJE), 1)
checar("controle: sem 'hoje' a mesma lista contaria 2", vigia.contar_seguidas("sem_token:mx", hoje_e_ontem), 2)
madrugada = [{"quando": HOJE.isoformat() + "T00:45:00+00:00", "veredito": {"chaves": ["sem_token:mx"]}}]
checar("escalada: 00:45 UTC é 21:45 BRT do dia ANTERIOR (conta como ontem)", vigia.contar_seguidas("sem_token:mx", madrugada, HOJE), 1)

print("\n== QA e injeção ==")
try:
    vigia.rodar(fontes=FontesFalsas(), qa=False, injetar=["estoque_zero:mx"], agora=AGORA, regras_todas=REGRAS)
    checar("--injetar sem --qa é recusado", False, True)
except SystemExit:
    checar("--injetar sem --qa é recusado", True, True)
f = FontesFalsas()
rel, _ = rodar(f, qa=True, injetar=["token_invalido:mx", "run_falhou"])
checar("QA com injeção -> token_invalido + run_vermelho", sorted(set(chaves(rel)) & {"token_invalido", "run_vermelho"}),
       ["run_vermelho", "token_invalido"])
checar("QA -> e-mail só a central+qa-vigia@", [e[1] for e in f.emails], [vigia.CENTRAL_QA])
checar("QA -> registro no canal redes_vigia_qa", [r[0] for r in f.registros], ["redes_vigia_qa"])
checar("QA -> nada executado", (f.dispatches, f.recusadas, f.renovadas), ([], [], []))

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for x in FALHAS:
        print(" -", x)
    sys.exit(1)
print("TODAS AS PROVAS DO VIGIA PASSARAM.")
