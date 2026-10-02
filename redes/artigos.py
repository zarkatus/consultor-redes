# -*- coding: utf-8 -*-
"""ARTIGO NOVO DO SITE -> PAUTA DE POST (30/09/2026, fio redes-consultor-multimarca-merge; decisão do CVO: "usar o
artigo semanal como fonte" de conteúdo inédito, porque o site de algumas marcas estava ficando sem seção nova).

O que faz, por marca e só por configuração (PGA-01, nenhum `if marca ==`):
  1. DETECTA: lê o índice público de artigos do site (`regras.json` -> `artigos.indice`, um sitemap.xml ou uma página
     de índice com links) e fica com as URLs que casam `artigos.padrao` (regex no caminho), nos `dominios_origem`,
     sem as cópias /en/ e /es/. Cada URL nova vira UMA linha em `ic_redes_artigo` (sql/redes-artigos.sql): `novo`
     (vira pauta) ou `base` (o estoque já tinha usado a página por seções antes do detector: nunca repete).
     Idempotente: UNIQUE (marca, url, qa) + ignore-duplicates; a 2ª execução não cria nada.
  2. PRIORIDADE: o gerador (`gerador.gerar_lote`) põe os artigos `novo` NA FRENTE das seções antigas; a peça é um
     resumo fiel do artigo inteiro, com o link na legenda, e passa pelas mesmas regras (número só se está no artigo,
     sem "casa"/"agente"/"bot", sigilo, discrição) e depois pelo Conselho. Gerou -> `pauta` (+ `peca_id`).
     A URL de artigo registrado (fora `base`) sai da fila de SEÇÕES: o mesmo texto nunca vira duas peças.
  3. SINCRONIZA com o Conselho (`ic_redes_publicacao`): aprovado/publicado -> `consumido`; recusado/expirado/retirado
     -> volta a `novo` com tentativa +1 (novo ângulo), e na 3ª vira `descartado` com motivo; pauta cuja peça não
     chegou ao estoque nem ao banco em 30 h (push da reposição falhou) -> volta a `novo`.
  4. MEDE para o vigia (`resumo`): artigos no índice, novos a consumir, em pauta, consumidos, descartados, estado do
     índice (ok | vazio | sem_config | indisponivel | negado). Site fora do ar / 5xx / timeout = `indisponivel`;
     401/403 = `negado` (credencial/WAF, nunca "caiu"): o vigia alerta a central (AOP-01), nunca erro mudo.

Nada é inventado: sem artigo novo, a marca fica sem pauta inédita e o vigia diz isso com o valor observado (a
cadência de post acompanha a de artigos; reaproveitar seção antiga depende de decisão do CVO).

CLI (a partir da raiz do repo):
    python redes/artigos.py estado [--marcas m1,m2]            # só lê (índice + banco), não grava nada
    python redes/artigos.py provar --qa --marcas m1,m2 [--max 1] # prova ponta a ponta em QA (linhas qa=true):
        artigo X -> pauta no banco -> peça gerada (IA gratuita) -> Conselho em QA -> consumido -> 2ª execução não repete
    python redes/artigos.py limpar-qa                          # remove o resíduo da prova, com contagem zero
Teste sem rede: `python redes/testar_artigos.py`."""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
for _p in (RAIZ, os.path.join(RAIZ, "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TABELA = "ic_redes_artigo"
MAX_TENTATIVAS = 3          # peças recusadas a partir do mesmo artigo antes de descartá-lo (com motivo)
PAUTA_ORFA_H = 30           # pauta sem peça no estoque e sem linha no banco depois disso = push falhou -> volta a novo
STATUS_APROVADO = ("aprovado", "publicado")
STATUS_RECUSADO = ("recusado", "expirado", "retirado")
IDIOMAS_FORA = re.compile(r"^/(en|es)(/|$)")
CANAL_QA = "redes_artigos_qa"


# ---------------------------------------------------------------------------------------------- URLs
def normalizar(u):
    """https://host/caminho — sem www, query, âncora nem barra final; host minúsculo. '' se não for URL http."""
    u = (u or "").strip().strip("'\"")
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u.lstrip("/")
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return ""
    caminho = re.sub(r"/{2,}", "/", p.path or "/").rstrip("/")
    caminho = re.sub(r"(/index)?\.html?$", "", caminho)
    return "https://%s%s" % (host, caminho)


def urls_citadas(texto, dominios):
    """URLs dos domínios da marca citadas num campo livre (nota_origem do estoque, que às vezes é 'dominio/caminho
    (fonte: ...)' sem esquema). Normalizadas."""
    out = set()
    for d in dominios or []:
        for m in re.finditer(r"(?:https?://)?(?:www\.)?" + re.escape(d) + r"(/[A-Za-z0-9/_\-.%]*)?", texto or ""):
            n = normalizar(m.group(0))
            if n:
                out.add(n)
    return out


def config(regras):
    """{'indice': url, 'padrao': regex} do regras.json da marca, ou None (marca sem índice de artigos configurado)."""
    a = regras.get("artigos") or {}
    if not a.get("indice") or not a.get("padrao"):
        return None
    return a


def _http(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; consultor-redes-artigos)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def listar_indice(regras, ler=None):
    """Lê o índice de artigos da marca. Devolve {estado, indice, http, urls, erro}.
    estado: ok (>=1 artigo) | vazio (índice leu, 0 artigo casou o padrão) | sem_config | indisponivel (rede, DNS,
    timeout, 5xx, 404 do próprio índice) | negado (401/403: credencial/WAF, não é queda)."""
    conf = config(regras)
    if not conf:
        return {"estado": "sem_config", "indice": None, "http": None, "urls": [], "erro": None}
    ler = ler or _http
    indice = conf["indice"]
    try:
        txt = ler(indice)
    except urllib.error.HTTPError as e:
        return {"estado": "negado" if e.code in (401, 403) else "indisponivel", "indice": indice, "http": e.code,
                "urls": [], "erro": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001 - rede/DNS/timeout/arquivo ausente: indisponível (nunca mudo)
        return {"estado": "indisponivel", "indice": indice, "http": None, "urls": [], "erro": "%s: %s" % (type(e).__name__, str(e)[:120])}
    brutas = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", txt or "")
    if not brutas:  # página de índice (HTML): os links dela
        brutas = [urllib.parse.urljoin(indice, h) for h in re.findall(r"""href\s*=\s*["']([^"'#][^"']*)["']""", txt or "")]
    dominios = [d.lower() for d in (regras.get("dominios_origem") or [])]
    padrao = re.compile(conf["padrao"])
    out = []
    for b in brutas:
        n = normalizar(b)
        if not n:
            continue
        host = urllib.parse.urlsplit(n).hostname or ""
        if dominios and not any(host == d or host.endswith("." + d) for d in dominios):
            continue
        caminho = urllib.parse.urlsplit(n).path or "/"
        if IDIOMAS_FORA.search(caminho) or not padrao.search(caminho + "/"):
            continue
        if n not in out:
            out.append(n)
    return {"estado": "ok" if out else "vazio", "indice": indice, "http": 200, "urls": out, "erro": None}


# ---------------------------------------------------------------------------------------------- registro (banco)
class Registro:
    """Leitura/escrita de `ic_redes_artigo` (service_role). `qa=True` só enxerga/grava linhas da prova. Os testes trocam
    esta classe por uma falsa com a mesma interface."""

    def __init__(self, qa=False):
        import supa  # noqa: E402
        self.supa = supa
        self.qa = bool(qa)
        if not (supa.URL and supa.KEY):
            raise RuntimeError("SB_URL/SB_SERVICE_ROLE ausentes: registro de artigos indisponível")

    def linhas(self, marca):
        return self.supa.select(TABELA, "marca=eq.%s&qa=is.%s&select=*&order=id.asc&limit=5000"
                                % (urllib.parse.quote(marca), "true" if self.qa else "false")) or []

    def inserir(self, linhas):
        if not linhas:
            return []
        chaves = sorted({k for x in linhas for k in x})  # PostgREST em lote exige as MESMAS chaves em todo objeto (PGRST102)
        corpo = [dict({k: x.get(k) for k in chaves}, qa=self.qa) for x in linhas]
        req = urllib.request.Request(self.supa.URL + "/rest/v1/%s?on_conflict=marca,url,qa" % TABELA, method="POST",
                                     data=json.dumps(corpo).encode("utf-8"),
                                     headers=self.supa._cab({"Prefer": "resolution=ignore-duplicates,return=representation"}))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"[]")
        except urllib.error.HTTPError as e:
            raise RuntimeError("INSERT %s HTTP %d: %s" % (TABELA, e.code, e.read()[:300]))

    def atualizar(self, id_, campos):
        campos = dict(campos, atualizado_em=_agora().isoformat())
        return self.supa.patch(TABELA, "id=eq.%s&qa=is.%s" % (id_, "true" if self.qa else "false"), campos)

    def estado_pecas(self, peca_ids):
        """{peca_id: status} em ic_redes_publicacao (produção). Em QA não há linha lá: quem consome é a prova."""
        ids = [p for p in peca_ids if p]
        if not ids or self.qa:
            return {}
        filtro = ",".join('"%s"' % p.replace('"', "") for p in ids)
        rows = self.supa.select("ic_redes_publicacao", "peca_id=in.(%s)&select=peca_id,status" % urllib.parse.quote(filtro))
        return {r["peca_id"]: r["status"] for r in rows or []}


def _agora():
    return datetime.datetime.now(datetime.timezone.utc)


def _dt(v):
    if not v:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def usadas_do_estoque(marca, regras, pecas=None):
    """URLs normalizadas que o estoque da marca já usou como fonte (nota_origem)."""
    if pecas is None:
        import estoque  # noqa: E402
        pecas = estoque.listar(marca)
    out = set()
    for p in pecas:
        out |= urls_citadas(str(p.get("nota_origem") or ""), regras.get("dominios_origem") or [])
    return out


# ---------------------------------------------------------------------------------------------- detecção e ciclo
def detectar(marca, regras, registro, usadas=None, ler=None, gravar=True, indice=None):
    """Lê o índice e registra as URLs que o banco ainda não conhece. Devolve {indice, http, erro, no_indice, novos,
    base, linhas_novas}. `gravar=False` (QA do vigia): calcula o que entraria sem escrever nada."""
    idx = indice or listar_indice(regras, ler)
    conhecidas = {r["url"] for r in registro.linhas(marca)}
    usadas = usadas if usadas is not None else usadas_do_estoque(marca, regras)
    linhas = []
    for u in idx["urls"]:
        if u in conhecidas:
            continue
        if u in usadas:
            linhas.append({"marca": marca, "url": u, "status": "base",
                           "motivo": "página já usada pelo estoque (seções) antes do detector: não vira pauta"})
        else:
            linhas.append({"marca": marca, "url": u, "status": "novo"})
    if gravar and linhas:
        registro.inserir(linhas)
    return {"indice": idx["estado"], "http": idx["http"], "erro": idx["erro"], "url_indice": idx["indice"],
            "no_indice": len(idx["urls"]), "novos": sum(1 for x in linhas if x["status"] == "novo"),
            "base": sum(1 for x in linhas if x["status"] == "base"), "linhas_novas": linhas}


def sincronizar(marca, registro, existe_no_estoque=None, agora=None, gravar=True):
    """Leva o desfecho do Conselho para o registro. Devolve a lista de transições [(url, de, para, motivo)]."""
    agora = agora or _agora()
    if existe_no_estoque is None:
        import estoque  # noqa: E402

        def existe_no_estoque(m, pid):
            return os.path.isfile(estoque.caminho(m, pid))
    pautas = [r for r in registro.linhas(marca) if r.get("status") == "pauta"]
    if not pautas:
        return []
    estado = registro.estado_pecas([r.get("peca_id") for r in pautas])
    mudancas = []
    for r in pautas:
        pid, st = r.get("peca_id"), estado.get(r.get("peca_id"))
        campos = None
        if st in STATUS_APROVADO:
            campos = {"status": "consumido", "consumido_em": agora.isoformat(), "motivo": "Conselho: %s (%s)" % (st, pid)}
        elif st in STATUS_RECUSADO:
            t = int(r.get("tentativas") or 0) + 1
            if t >= MAX_TENTATIVAS:
                campos = {"status": "descartado", "tentativas": t, "peca_id": None,
                          "motivo": "%d peça(s) recusada(s) a partir deste artigo (última %s: %s)" % (t, pid, st)}
            else:
                campos = {"status": "novo", "tentativas": t, "peca_id": None, "pauta_em": None,
                          "motivo": "peça %s %s; volta à fila para novo ângulo (tentativa %d de %d)" % (pid, st, t + 1, MAX_TENTATIVAS)}
        elif st is None and pid and not existe_no_estoque(marca, pid):
            desde = _dt(r.get("pauta_em"))
            if desde and agora - desde > datetime.timedelta(hours=PAUTA_ORFA_H):
                campos = {"status": "novo", "peca_id": None, "pauta_em": None,
                          "motivo": "peça %s não chegou ao estoque nem ao Conselho em %d h (push da reposição?)" % (pid, PAUTA_ORFA_H)}
        if campos:
            mudancas.append((r["url"], r["status"], campos["status"], campos.get("motivo")))
            if gravar:
                registro.atualizar(r["id"], campos)
    return mudancas


def pendentes(marca, registro, linhas=None):
    """Artigos `novo`, o mais recente primeiro (o artigo da semana passa na frente do acervo antigo)."""
    linhas = linhas if linhas is not None else registro.linhas(marca)
    novos = [r for r in linhas if r.get("status") == "novo"]
    return sorted(novos, key=lambda r: (-(_dt(r.get("visto_em")) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)).timestamp(), r.get("id") or 0))


def reservadas(linhas):
    """URLs que o gerador NÃO usa por seção: artigo registrado fora de `base` (é do caminho do artigo)."""
    return {r["url"] for r in linhas if r.get("status") != "base"}


def marcar_pauta(registro, linha, peca_id, titulo=None):
    campos = {"status": "pauta", "peca_id": peca_id, "pauta_em": _agora().isoformat(), "motivo": None}
    if titulo:
        campos["titulo"] = titulo[:300]
    return registro.atualizar(linha["id"], campos)


def registrar_falha(registro, linha, motivos, definitivo=False):
    """Gerador não conseguiu peça válida do artigo (ou a página saiu do ar): tentativa +1; na última (ou definitivo),
    `descartado` com motivo (o vigia avisa a central)."""
    t = int(linha.get("tentativas") or 0) + 1
    mot = "; ".join(str(m) for m in motivos)[:480]
    if definitivo or t >= MAX_TENTATIVAS:
        return registro.atualizar(linha["id"], {"status": "descartado", "tentativas": t, "motivo": "gerador: " + mot})
    return registro.atualizar(linha["id"], {"tentativas": t, "motivo": "gerador (tentativa %d): %s" % (t, mot)})


def consumir(registro, linha, via):
    return registro.atualizar(linha["id"], {"status": "consumido", "consumido_em": _agora().isoformat(), "motivo": via[:300]})


def resumo(linhas, det=None, agora=None):
    """Números para o vigia e para o registro."""
    agora = agora or _agora()
    c = {s: 0 for s in ("base", "novo", "pauta", "consumido", "descartado")}
    for r in linhas:
        c[r.get("status")] = c.get(r.get("status"), 0) + 1
    ult = max((_dt(r.get("visto_em")) for r in linhas if r.get("status") != "base" and _dt(r.get("visto_em"))), default=None)
    desc_recentes = [r["url"] for r in linhas if r.get("status") == "descartado"
                     and (_dt(r.get("atualizado_em")) or agora) >= agora - datetime.timedelta(hours=26)]
    out = {"registrados": len(linhas), "novos": c["novo"], "em_pauta": c["pauta"], "consumidos": c["consumido"],
           "descartados": c["descartado"], "base": c["base"], "ultimo_artigo_visto": ult.date().isoformat() if ult else None,
           "descartados_26h": desc_recentes}
    if det:
        out.update({"indice": det["indice"], "http": det["http"], "erro": det["erro"], "url_indice": det["url_indice"],
                    "no_indice": det["no_indice"], "detectados_agora": det["novos"], "base_agora": det["base"]})
    return out


def ciclo(marca, regras, registro, gravar=True, ler=None, usadas=None, existe_no_estoque=None):
    """Sincroniza + detecta + resume (o que o vigia chama por marca). `gravar=False` = só leitura (QA)."""
    mud = sincronizar(marca, registro, existe_no_estoque, gravar=gravar)
    det = detectar(marca, regras, registro, usadas=usadas, ler=ler, gravar=gravar)
    linhas = registro.linhas(marca)
    if not gravar:  # QA: soma o que entraria, sem escrever
        linhas = linhas + [dict(x, visto_em=_agora().isoformat()) for x in det["linhas_novas"]]
    res = resumo(linhas, det)
    res["transicoes"] = [{"url": u, "de": a, "para": b} for u, a, b, _m in mud]
    res["reservadas"] = sorted(reservadas(linhas))  # em QA inclui as que ENTRARIAM (a conta de seções fica igual à de produção)
    return res


# ---------------------------------------------------------------------------------------------- prova ponta a ponta (QA)
def provar(marcas_lista, maximo=1, log=print):
    """Prova em QA (linhas qa=true, votos `qa-conselho-*`, nada publicado, nada commitado): por marca, detecta, gera a
    peça do artigo mais novo pelo gerador (IA gratuita), roda o Conselho em QA, registra `consumido` se aprovada e faz a
    2ª execução (não pode repetir). Grava UMA linha em ic_aviso_log canal `redes_artigos_qa` com o placar. Começa limpando
    o resíduo de prova anterior (autocontida); o resíduo DESTA prova fica para ser mostrado e sai com `limpar-qa`."""
    import estoque  # noqa: E402
    import gerador  # noqa: E402
    import lote_aprovacao  # noqa: E402
    import supa  # noqa: E402
    # autocontida: resíduo de prova anterior (linha qa em `pauta` cuja peça morreu com o runner efêmero) sai antes
    antes = limpar_qa(log=log)
    if any(antes.values()):
        raise RuntimeError("resíduo QA anterior não saiu: %s" % antes)
    reg = Registro(qa=True)
    placar = {}
    for m in marcas_lista:
        regras = gerador.carregar_regras(m)
        p = {"marca": m}
        det1 = detectar(m, regras, reg)
        p["execucao_1"] = {k: det1[k] for k in ("indice", "http", "erro", "no_indice", "novos", "base")}
        log("[%s] execução 1: índice %s (%s artigo(s) no índice; %d novo(s), %d base)" % (m, det1["indice"], det1["no_indice"], det1["novos"], det1["base"]))
        pend = pendentes(m, reg)
        if pend and not (gerador.carregar_json_opcional(m, "marca.json").get("arte_v2")):
            p["resultado"] = "%d artigo(s) novo(s) registrado(s); marca sem gerador automático (arte_v2): a pauta segue o fluxo da marca" % len(pend)
            log("[%s] %s" % (m, p["resultado"]))
            placar[m] = p
            continue
        if not pend:
            p["resultado"] = ("sem artigo novo: a marca fica sem pauta inédita (índice %s, %d artigo(s)); nada é inventado"
                              % (det1["indice"], det1["no_indice"]))
            log("[%s] %s" % (m, p["resultado"]))
            placar[m] = p
            continue
        feitas, recusadas = gerador.gerar_lote(m, maximo, gerador.MOTORES["conselho"], log=log, artigos_reg=reg, so_artigos=True)
        p["gerador"] = {"feitas": [f[0] for f in feitas], "descartadas": len(recusadas)}
        linhas = {r["url"]: r for r in reg.linhas(m)}
        em_pauta = [r for r in linhas.values() if r["status"] == "pauta"]
        p["pautas"] = [{"url": r["url"], "peca_id": r["peca_id"]} for r in em_pauta]
        for r in em_pauta:
            pid = r["peca_id"]
            estoque.atualizar_status(m, pid, status="aprovado")  # = fila do Conselho (mesmo passo do vigia repor)
            res = lote_aprovacao.rodar(m, so_peca_id=pid, qa=True, escaladas_se_novas=True)
            decisao = "aprovado" if res.get("aprovado") else "escalado" if res.get("escalado") else "adiado" if res.get("adiado") else "sem_decisao"
            p.setdefault("conselho", {})[pid] = decisao
            log("[%s] Conselho (QA) %s -> %s" % (m, pid, decisao))
            if decisao == "aprovado":
                consumir(reg, r, "Conselho QA aprovou %s" % pid)
            elif decisao == "adiado":
                log("[%s] Conselho ADIOU (sem cota gratuita agora; nunca modelo pago): o artigo fica em 'pauta' e a prova "
                    "de aprovação se repete depois da virada da cota (00:00 UTC = 21:00 BRT)" % m)
        # 2ª execução: nada novo no índice; o artigo consumido não volta; uma peça só por artigo no estoque
        det2 = detectar(m, regras, reg)
        pend2 = {r["url"] for r in pendentes(m, reg)}
        pecas = estoque.listar(m)
        por_url = {}
        for pc in pecas:
            n = normalizar(str(pc.get("nota_origem") or ""))
            if pc.get("origem") == "artigo":
                por_url[n] = por_url.get(n, 0) + 1
        usados = [r["url"] for r in reg.linhas(m) if r["status"] in ("pauta", "consumido")]
        p["execucao_2"] = {"detectados_agora": det2["novos"] + det2["base"],
                           "consumido_voltou_a_fila": sorted(set(usados) & pend2),
                           "pecas_por_artigo": {u: por_url.get(u, 0) for u in usados}}
        p["nao_repete"] = (det2["novos"] + det2["base"] == 0 and not (set(usados) & pend2)
                           and all(por_url.get(u, 0) == 1 for u in usados))
        p["registro"] = [{k: r.get(k) for k in ("url", "status", "peca_id", "tentativas", "motivo")}
                         for r in reg.linhas(m) if r["status"] != "novo" or r["url"] in {x["url"] for x in pend[:maximo]}][:10]
        log("[%s] execução 2: %s" % (m, json.dumps(p["execucao_2"], ensure_ascii=False)))
        placar[m] = p
    try:
        supa.registrar_aviso("prova artigo -> pauta (QA): %s" % ", ".join("%s=%s" % (m, (v.get("conselho") or v.get("resultado", ""))) for m, v in placar.items())[:400],
                             marca="consultor-redes", canal=CANAL_QA, entregue=True, veredito=placar)
    except Exception as e:  # noqa: BLE001
        log("registro da prova em ic_aviso_log falhou: %s" % str(e)[:160])
    return placar


def limpar_qa(log=print):
    """Remove o resíduo da prova: linhas qa=true, votos `qa-conselho-*` das peças de artigo da prova, registro do canal
    QA. Devolve as contagens DEPOIS (tem de ser zero)."""
    import supa  # noqa: E402
    pids = [r["peca_id"] for r in supa.select(TABELA, "qa=is.true&select=peca_id&peca_id=not.is.null") or []]
    for pid in pids:
        supa.excluir("ic_redes_revisao", "peca_id=eq.%s" % urllib.parse.quote("qa-conselho-" + pid))
    supa.excluir(TABELA, "qa=is.true")
    supa.excluir("ic_aviso_log", "canal=eq.%s" % CANAL_QA)
    depois = {"artigos_qa": len(supa.select(TABELA, "qa=is.true&select=id") or []),
              "votos_qa": sum(len(supa.select("ic_redes_revisao", "peca_id=eq.%s&select=id" % urllib.parse.quote("qa-conselho-" + p)) or []) for p in pids),
              "aviso_qa": len(supa.select("ic_aviso_log", "canal=eq.%s&select=id" % CANAL_QA) or [])}
    log("resíduo da prova depois da limpeza: %s" % depois)
    return depois


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Artigo novo do site -> pauta de post (Consultor de Redes)")
    ap.add_argument("acao", choices=("estado", "provar", "limpar-qa"))
    ap.add_argument("--marcas", default="")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--max", type=int, default=1)
    a = ap.parse_args(argv)
    import marcas as _marcas  # noqa: E402
    lista = [x.strip() for x in a.marcas.split(",") if x.strip()] or sorted(_marcas.instagram_ativas_regras())
    if a.acao == "limpar-qa":
        d = limpar_qa()
        return 0 if not any(d.values()) else 1
    if a.acao == "provar":
        if not a.qa:
            raise SystemExit("provar só roda com --qa (linhas qa=true, Conselho em QA, nada publicado)")
        r = provar(lista, max(1, min(3, a.max)))
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str)[:12000])
        falhou = [m for m, v in r.items() if v.get("pautas") is not None and not v.get("nao_repete")]
        return 1 if falhou else 0
    import gerador  # noqa: E402
    try:
        reg = Registro(qa=False)
    except RuntimeError as e:
        print("sem banco (%s): só o índice" % e)
        for m in lista:
            idx = listar_indice(gerador.carregar_regras(m))
            print(m, idx["estado"], len(idx["urls"]), idx["erro"] or "")
        return 0
    for m in lista:
        res = ciclo(m, gerador.carregar_regras(m), reg, gravar=False)
        print(m, json.dumps({k: v for k, v in res.items() if k != "transicoes"}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
