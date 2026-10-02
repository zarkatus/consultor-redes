# -*- coding: utf-8 -*-
"""ALCANCE GRATUITO do Consultor de Redes (CVO 29/09/2026: "as postagens tem que ter MAXIMO alcance,
de forma gratuita"). Tudo aqui e agnostico de marca: regras vem de `redes/marcas.py`.

1. CHECAGEM OBJETIVA da legenda (`checar_legenda`) — usada pelo Conselho como revisor de alcance; so
   reprova por falha OBJETIVA, nunca por gosto:
   - a 1a frase/linha cabe antes do "mais" do Instagram (~125 caracteres) e nao e abertura generica;
   - a legenda contem >= 1 palavra-chave da marca (a busca do Instagram le a legenda);
   - 3 a 5 hashtags (nem 0, nem 30);
   - chamada para salvar/compartilhar/comentar;
   - texto alternativo presente (`alt_text` da peca ou, na falta, o `texto_arte` de onde ele e derivado).
2. `corrigir_legenda`: conserto DETERMINISTICO do que e mecanico (hashtags fora de 3-5, sem chamada); o que
   exige texto (gancho, palavra-chave) fica para o redator. Nunca inventa fato.
3. Helpers de publicacao: `alt_text`, `collaborators`, `primeiro_comentario`.
4. Metricas: `coletar` (insights por post -> `ic_redes_metrica`) e `relatorio` (por marca: ranking de formato e de
   horario por alcance medio -> recomendacao em `ic_segredo.redes_recomendacao_<marca>`), com o horario ajustado
   sozinho dentro de JANELA e so com amostra >= AMOSTRA_MIN posts.

Metricas da API (Instagram API with Instagram Login, conferido na doc oficial em 29/09/2026): `reach`, `views`,
`likes`, `comments`, `saved`, `shares`, `total_interactions`. `impressions` so existe para midia anterior a
02/07/2024 e `plays` foi substituida por `views`: por isso `impressoes` <- impressions ou views, e `plays` <- views
so em Reels. Metrica indisponivel vira NULL, nunca erro.

CLI: python redes/alcance.py coletar | relatorio [--marca X]"""
import datetime
import json
import os
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import marcas  # noqa: E402

LIMITE_ANTES_DO_MAIS = 125
HASHTAGS_MIN, HASHTAGS_MAX = 3, 5
ALT_TEXT_MAX = 1000
AMOSTRA_MIN = 10
JANELA_HORARIO = ("08:00", "20:00")  # BRT: o horario recomendado nunca sai daqui
ESCALONAMENTO_MIN = 20  # marcas com o mesmo horario saem com 20 min de intervalo
CTA_PADRAO = "Salve este post para consultar depois."

_RE_HASHTAG = re.compile(r"(?<![\w&])#[^\W\d_][\w]*", re.U)
_CTA = re.compile(r"\b(salv[ea]\w*|compartilh\w+|coment[ea]\w*|envie|mande|marque|responda|conte nos comentarios|"
                  r"me diga|deixe (?:sua|seu)|encaminhe)\b")
_ABERTURA_GENERICA = re.compile(r"^(ola|oi|bom dia|boa tarde|boa noite|hoje|bem[- ]vindos?|neste post|nesta publicacao|"
                                r"confira|fique por dentro|voce sabia)\b")
_ABREV = ("art", "arts", "inc", "par", "n", "no", "sr", "sra", "dr", "dra", "cap", "fl", "ex", "obs", "p", "pag")


def _norm(t):
    n = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower()


def hashtags(texto):
    return _RE_HASHTAG.findall(texto or "")


def _sem_hashtags(texto):
    linhas = []
    for ln in (texto or "").splitlines():
        s = _RE_HASHTAG.sub("", ln).strip()
        if s:
            linhas.append(s)
    return "\n".join(linhas)


def primeira_frase(texto):
    """1a frase da legenda (conhece abreviacoes 'art.', 'arts.'): ate o 1o ponto final/?/! seguido de espaco,
    limitada a 1a linha."""
    corpo = (texto or "").strip()
    linha = corpo.split("\n", 1)[0].strip()
    for m in re.finditer(r"[.!?…](?=\s|$)", linha):
        antes = re.findall(r"([A-Za-zÀ-ÿ]+)$", linha[:m.start()])
        if antes and linha[m.start()] == "." and _norm(antes[0]) in _ABREV:
            continue
        return linha[:m.end()].strip()
    return linha


def tem_alt_text(peca):
    return bool(str((peca or {}).get("alt_text") or "").strip() or str((peca or {}).get("texto_arte") or "").strip())


def checar_legenda(texto, regras, peca=None, hashtags_extra=0):
    """Lista de motivos OBJETIVOS (vazia = ok). `hashtags_extra`: hashtags que irao no 1o comentario."""
    motivos = []
    corpo = (texto or "").strip()
    if not corpo:
        return ["legenda vazia"]
    fr = primeira_frase(corpo)
    n = _norm(fr).strip()
    if not n or len(re.sub(r"\W", "", n)) < 8:
        motivos.append("alcance: a 1a linha nao traz gancho (vazia ou so hashtag/link)")
    elif re.match(r"^(https?://|www\.|[a-z0-9-]+\.(com|com\.br|br|ia\.br)\b)", n):
        motivos.append("alcance: a 1a linha e so um link, sem gancho")
    elif _ABERTURA_GENERICA.match(n):
        motivos.append("alcance: a 1a linha abre de forma generica (%r); abrir com o fato concreto" % fr[:40])
    if len(fr) > LIMITE_ANTES_DO_MAIS:
        motivos.append("alcance: a 1a frase tem %d caracteres e nao cabe antes do 'mais' (~%d); abrir com o fato em ate %d"
                       % (len(fr), LIMITE_ANTES_DO_MAIS, LIMITE_ANTES_DO_MAIS))
    chaves = [_norm(k) for k in (regras.get("palavras_chave") or []) if k]
    if chaves:
        alvo = _norm(corpo)
        if not any(re.search(r"(?<![a-z0-9])" + re.escape(k), alvo) for k in chaves):
            motivos.append("alcance: a legenda nao contem nenhuma palavra-chave da marca (a busca do Instagram le a legenda): %s"
                           % ", ".join((regras.get("palavras_chave") or [])[:6]))
    total = len(hashtags(corpo)) + int(hashtags_extra or 0)
    if total < HASHTAGS_MIN:
        motivos.append("alcance: %d hashtag(s); usar de %d a %d" % (total, HASHTAGS_MIN, HASHTAGS_MAX))
    elif total > HASHTAGS_MAX:
        motivos.append("alcance: %d hashtags; usar de %d a %d (excesso derruba o alcance)" % (total, HASHTAGS_MIN, HASHTAGS_MAX))
    if not _CTA.search(_norm(_sem_hashtags(corpo))):
        motivos.append("alcance: sem chamada para salvar, compartilhar ou comentar")
    if peca is not None and not tem_alt_text(peca):
        motivos.append("alcance: sem texto alternativo (a peca nao tem `alt_text` nem `texto_arte` para derivar)")
    return motivos


_LINK_ENTRE_PARENTESES = re.compile(r"\s*\((?:https?://|www\.)[^)\s]*\)")
_CAUDA_DE_NORMA = re.compile(r",\s+(conforme|segundo|de acordo com|nos termos d[aoe]s?|previst[ao]s? n[ao]s?)\s+", re.I)


def encurtar_primeira_frase(texto):
    """Conserto mecanico da 1a frase longa, SEM modelo e sem inventar nada: (1) tira link entre parenteses da 1a frase
    (no Instagram link na legenda nao e clicavel; a fonte continua em `fontes`); (2) se ainda passa de ~125, a cauda
    ', conforme/segundo <norma>' vira a 2a frase. Caso real (banco adversarial c02, 30/09/2026): o redator LLM colou
    norma + URL na 1a frase (155 caracteres) e a peca escalava por isso."""
    corpo = texto or ""
    fr = primeira_frase(corpo)
    if len(fr) <= LIMITE_ANTES_DO_MAIS:
        return texto
    nova = _LINK_ENTRE_PARENTESES.sub("", fr)
    if len(nova) > LIMITE_ANTES_DO_MAIS:
        m = _CAUDA_DE_NORMA.search(nova)
        if m and m.start() > 20:
            cauda = nova[m.end(1) - len(m.group(1)):]
            nova = nova[:m.start()].rstrip() + ". " + cauda[:1].upper() + cauda[1:]
    return corpo.replace(fr, nova, 1)


def corrigir_legenda(texto, regras):
    """Conserto mecanico: 1a frase longa (link/norma para fora), hashtags para 3-5 (prefere as da marca) e chamada final
    se faltar. Devolve o texto novo (igual ao original quando nada a fazer)."""
    corpo = encurtar_primeira_frase((texto or "")).rstrip()
    if not corpo:
        return texto
    atuais = hashtags(corpo)
    linhas = corpo.splitlines()
    tags_marca = [h for h in (regras.get("hashtags") or []) if h.startswith("#")]
    if len(atuais) > HASHTAGS_MAX:
        proprias = {t.lower() for t in tags_marca}
        ordem = [t for t in atuais if t.lower() in proprias] + [t for t in atuais if t.lower() not in proprias]
        manter = []
        for t in ordem:
            if t.lower() not in [m.lower() for m in manter]:
                manter.append(t)
            if len(manter) == HASHTAGS_MAX:
                break
        sem = [re.sub(r"\s+", " ", _RE_HASHTAG.sub("", ln)).strip() for ln in linhas]
        linhas = [ln for ln in sem if ln] + [" ".join(manter)]
    elif len(atuais) < HASHTAGS_MIN:
        ja = {t.lower() for t in atuais}
        novas = [t for t in tags_marca if t.lower() not in ja][:HASHTAGS_MIN - len(atuais)]
        if novas:
            if linhas and linhas[-1].strip().startswith("#"):
                linhas[-1] = linhas[-1].rstrip() + " " + " ".join(novas)
            else:
                linhas.append(" ".join(novas))
    if not _CTA.search(_norm(_sem_hashtags("\n".join(linhas)))):
        cta = regras.get("cta") or CTA_PADRAO
        if linhas and linhas[-1].strip().startswith("#"):
            linhas.insert(len(linhas) - 1, cta)
        else:
            linhas.append(cta)
    return "\n".join(linhas)


def alt_text(peca):
    """Texto alternativo: `alt_text` do frontmatter ou derivado do `texto_arte` (o que esta na imagem), <= 1000."""
    t = str((peca or {}).get("alt_text") or "").strip() or str((peca or {}).get("texto_arte") or "").strip()
    t = re.sub(r"\s+", " ", t.replace(" / ", ". "))
    return t[:ALT_TEXT_MAX] or None


def primeiro_comentario(peca):
    """Hashtags no 1o comentario so quando a peca pede (`primeiro_comentario:` no frontmatter)."""
    t = str((peca or {}).get("primeiro_comentario") or "").strip()
    return t[:2000] or None


def collaborators(regras, peca, usados_semana=0):
    """Usernames (sem @) para o campo `collaborators`, so quando a peca marca collab (`collab: true` ou lista de marcas),
    limitado a `collab.parceiros` e a `collab.max_por_semana`; a API aceita ate 3 e so contas publicas."""
    pedido = (peca or {}).get("collab")
    if not pedido:
        return []
    cfg = regras.get("collab") or {}
    if int(usados_semana or 0) >= int(cfg.get("max_por_semana") or 0):
        return []
    parceiros = [p.lower() for p in (cfg.get("parceiros") or [])]
    if pedido is True:
        alvos = parceiros
    else:
        lista = pedido if isinstance(pedido, list) else [pedido]
        alvos = [str(p).lower() for p in lista if str(p).lower() in parceiros]
    out = []
    for m in alvos[:3]:
        h = (marcas.carregar(m).get("handle_instagram") or "").lstrip("@")
        if h:
            out.append(h)
    return out


# ------------------------------------------------------------------ collab semanal (regra do CVO 29/09/2026)
# Cada marca faz AO MENOS UMA collab por semana ISO (`collab.min_por_semana`, max em `collab.max_por_semana`). E regra
# de AGENDA, nao de peca: o Conselho nunca reprova por falta de collab. O publicador promove a peca aprovada mais
# adequada da semana (tema que toca o parceiro) e o parceiro sai em rodizio, sem repetir o par duas semanas seguidas
# quando ha alternativa. Sobre a API (Instagram Login): o CONVIDADO nao precisa de token nosso — o post sai no perfil de
# quem publica na hora e so aparece no perfil do parceiro quando ele ACEITA o convite no app (a API nao aceita por ele);
# conta privada ou que nao aceite colaboracoes derruba o campo `collaborators`, e o publicador tenta sem ele (o post sai solo).

def _tokens_tema(regras):
    return {_norm(t) for t in (list(regras.get("temas") or []) + list(regras.get("palavras_chave") or [])) if t}


def semana_iso(d):
    """(segunda, domingo) da semana ISO de `d`."""
    seg = d - datetime.timedelta(days=d.weekday())
    return seg, seg + datetime.timedelta(days=6)


def escolher_collab(regras, pecas, usados_semana, ultimo_parceiro, hoje, regras_dos_parceiros):
    """Regra pura. pecas: [{peca_id, texto, data(date), collab(bool)}] aprovadas e ainda nao publicadas desta semana.
    regras_dos_parceiros: {marca: regras}. Devolve (peca_id, parceiro) ou None (nada a promover / nao precisa)."""
    cfg = regras.get("collab") or {}
    minimo = int(cfg.get("min_por_semana") or 0)
    if minimo <= 0 or int(usados_semana) >= minimo:
        return None
    if any(p.get("collab") for p in pecas):
        return None  # ja ha uma peca da semana marcada como collab: cumpre a regra
    parceiros = [m for m in (cfg.get("parceiros") or [])
                 if (regras_dos_parceiros.get(m) or {}).get("handle_instagram")]
    if not parceiros:
        return None
    _, domingo = semana_iso(hoje)
    pool = [p for p in pecas if p.get("data") and hoje <= p["data"] <= domingo]
    if not pool:
        return None
    ordem = sorted(parceiros)
    if ultimo_parceiro in ordem:  # rodizio: comeca depois do ultimo usado
        i = ordem.index(ultimo_parceiro)
        ordem = ordem[i + 1:] + ordem[:i + 1]
    melhor = None
    for pc in pool:
        alvo = _norm(pc.get("texto") or "")
        for rank, par in enumerate(ordem):
            toks = _tokens_tema(regras_dos_parceiros[par])
            score = sum(1 for t in toks if re.search(r"(?<![a-z0-9])" + re.escape(t), alvo))
            # o ultimo parceiro so vale se nao ha alternativa (ja esta no fim da ordem); desempate pelo rodizio, depois pela data
            chave = (score, -rank, -pc["data"].toordinal())
            if melhor is None or chave > melhor[0]:
                melhor = (chave, pc["peca_id"], par)
    if melhor is None:
        return None
    if melhor[0][0] == 0 and hoje.weekday() < 5:
        return None  # sem tema que toque o parceiro: espera; a partir de sabado a regra da agenda vence
    return melhor[1], melhor[2]


def marcas_sem_collab(linhas_publicadas, marcas_ativas, minimo_por_marca):
    """Regra pura do relatorio: quais marcas fecharam a semana com menos collab que o minimo. `linhas_publicadas`:
    linhas de ic_redes_publicacao publicadas na semana (marca, collab_com)."""
    faltas = []
    for m in marcas_ativas:
        n = sum(1 for l in linhas_publicadas if l.get("marca") == m and l.get("collab_com"))
        if n < minimo_por_marca.get(m, 0):
            faltas.append({"marca": m, "feitas": n, "minimo": minimo_por_marca[m]})
    return faltas


def relatorio_semana_collab(hoje=None, enviar=True, qa=False):
    """Segunda: aponta as marcas que fecharam a SEMANA ANTERIOR sem collab e avisa a central tecnica (AOP-01) com marca,
    motivo e acao. Devolve a lista de faltas."""
    supa = _supa()
    hoje = hoje or datetime.date.today()
    seg, dom = semana_iso(hoje - datetime.timedelta(days=7))
    ativas = marcas.instagram_ativas_regras()
    minimos = {m: int((r.get("collab") or {}).get("min_por_semana") or 0) for m, r in ativas.items()}
    linhas = supa.select("ic_redes_publicacao",
                         "status=eq.publicado&publicado_em=gte.%s&publicado_em=lt.%s&select=marca,collab_com,peca_id"
                         % (seg.isoformat(), (dom + datetime.timedelta(days=1)).isoformat()))
    faltas = marcas_sem_collab(linhas, list(ativas), minimos)
    print("collab da semana %s a %s: faltas=%s" % (seg, dom, faltas))
    if faltas and enviar:
        corpo = "".join(
            "<li><b>%s</b>: %d collab na semana (minimo %d). Motivo provavel: nenhuma peca aprovada tocou o tema do parceiro, "
            "o parceiro nao aceitou o convite ou a API recusou `collaborators`. Acao: conferir `ic_redes_publicacao.collab_com` da "
            "marca na semana, aprovar peca com tema do parceiro e, se a API recusou, checar se o perfil do parceiro e publico.</li>"
            % (f["marca"], f["feitas"], f["minimo"]) for f in faltas)
        _supa().enviar_email("InnConta · redes: %d marca(s) fecharam a semana sem collab" % len(faltas),
                             "central+qa-conselho@innconta.com.br" if qa else "central@innconta.com.br",
                             "<p>Regra do CVO (29/09/2026): cada marca faz ao menos uma collab por semana. Semana %s a %s:</p><ul>%s</ul>"
                             % (seg, dom, corpo))
    return faltas


# ------------------------------------------------------------------ horario efetivo (escalonado)

def _hm(s, padrao=marcas.HORARIO_PADRAO):
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(s or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        m = re.match(r"^(\d{1,2}):(\d{2})$", padrao)
    return int(m.group(1)) * 60 + int(m.group(2))


def horario_efetivo(marca, regras_todas=None, recomendados=None):
    """Minutos desde 00:00 BRT a partir dos quais a marca pode publicar hoje: `publicar.horario_brt` (ou o horario
    recomendado pelo relatorio) + escalonamento de 20 min por marca que empata no mesmo horario (ordem alfabetica).
    Assim as contas nunca disparam juntas."""
    regras_todas = regras_todas if regras_todas is not None else marcas.instagram_ativas_regras()
    recomendados = recomendados or {}
    base = {m: _hm(recomendados.get(m) or r["publicar"].get("horario_brt")) for m, r in regras_todas.items()}
    if marca not in base:
        return _hm(None)
    mesmos = sorted(m for m, v in base.items() if v == base[marca])
    return base[marca] + ESCALONAMENTO_MIN * mesmos.index(marca)


# ------------------------------------------------------------------ metricas

METRICAS_POR_TIPO = {
    "REELS": ["reach", "views", "likes", "comments", "saved", "shares"],
    "FEED": ["reach", "views", "likes", "comments", "saved", "shares"],
}


def _supa():
    import supa
    return supa


def insights_de(media_id, tipo, token, base, get=None):
    """{metrica: valor|None}. Tenta a lista inteira; se a API recusar (metrica nao suportada nesse tipo), tenta uma a
    uma e deixa NULL o que nao vier — nunca quebra."""
    if get is None:
        import publicar_instagram as pi
        get = pi._get
    metricas = METRICAS_POR_TIPO.get("REELS" if tipo == "REELS" else "FEED")
    out = {m: None for m in metricas}

    def _ler(lista):
        j = get("%s/%s/insights?metric=%s&access_token=%s" % (base, media_id, ",".join(lista), token))
        for item in j.get("data") or []:
            vals = item.get("values") or []
            v = vals[0].get("value") if vals else (item.get("total_value") or {}).get("value")
            out[item.get("name")] = v
    try:
        _ler(metricas)
    except Exception:
        for m in metricas:
            try:
                _ler([m])
            except Exception:
                pass
    return out


def linha_metrica(marca, peca_id, media, ins, agora=None):
    agora = agora or datetime.datetime.now(datetime.timezone.utc)
    tipo = media.get("media_product_type") or media.get("media_type") or ""
    reels = tipo == "REELS"
    return {
        "marca": marca, "peca_id": peca_id, "media_id": str(media["id"]),
        "coletado_em": agora.isoformat(), "dia": agora.date().isoformat(),
        "alcance": ins.get("reach"), "impressoes": ins.get("impressions", ins.get("views")),
        "curtidas": ins.get("likes"), "comentarios": ins.get("comments"), "salvos": ins.get("saved"),
        "compartilhamentos": ins.get("shares"), "plays": ins.get("views") if reels else None,
        "formato": "REELS" if reels else ("CAROUSEL" if media.get("media_type") == "CAROUSEL_ALBUM" else "IMAGEM"),
        "publicado_em": media.get("timestamp"),
    }


def coletar(marca, limite=30, token=None, ig_user_id=None):
    """Coleta os insights dos ultimos posts da conta e grava 1 linha por post por dia em `ic_redes_metrica`
    (upsert por marca+media_id+dia). Devolve {"posts": n, "gravadas": n}."""
    import publicar_instagram as pi
    supa = _supa()
    tok = token or pi._token(marca)
    uid = ig_user_id or pi._ig_user_id(marca)
    j = pi._get("%s/%s/media?fields=id,media_type,media_product_type,permalink,timestamp&limit=%d&access_token=%s"
                % (pi.GRAPH_BASE, uid, limite, tok))
    publicadas = supa.select("ic_redes_publicacao", "marca=eq.%s&status=eq.publicado&select=peca_id,url_post" % marca)
    por_link = {(p.get("url_post") or "").rstrip("/"): p["peca_id"] for p in publicadas if p.get("url_post")}
    linhas = []
    for media in j.get("data") or []:
        tipo = media.get("media_product_type") or media.get("media_type")
        ins = insights_de(media["id"], tipo, tok, pi.GRAPH_BASE)
        linhas.append(linha_metrica(marca, por_link.get((media.get("permalink") or "").rstrip("/")), media, ins))
    if linhas:
        supa.upsert("ic_redes_metrica", linhas, "marca,media_id,dia")
    print("metricas %s: %d post(s) coletado(s)" % (marca, len(linhas)))
    return {"posts": len(linhas), "gravadas": len(linhas)}


def _hora_brt(iso):
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00").replace("+0000", "+00:00"))
        return d.astimezone(datetime.timezone(datetime.timedelta(hours=-3))).hour
    except Exception:
        return None


def ranquear(linhas):
    """Regra pura. linhas: 1 por post (a coleta mais recente de cada media) com alcance, formato, publicado_em.
    Devolve {"amostra": n, "por_formato": [(formato, media, n)], "por_hora": [(hora, media, n)]} ordenado."""
    usaveis = [l for l in linhas if l.get("alcance") is not None]

    def agrupar(chave):
        g = {}
        for l in usaveis:
            k = chave(l)
            if k is None:
                continue
            g.setdefault(k, []).append(float(l["alcance"]))
        return sorted(((k, sum(v) / len(v), len(v)) for k, v in g.items()), key=lambda x: -x[1])
    return {"amostra": len(usaveis), "por_formato": agrupar(lambda l: l.get("formato")),
            "por_hora": agrupar(lambda l: _hora_brt(l.get("publicado_em")))}


def recomendar(ranking):
    """Regra pura. So ajusta o horario com amostra >= AMOSTRA_MIN, escolhendo a melhor hora com >= 2 posts DENTRO da
    janela; formato preferido = o de maior alcance medio (>= 2 posts). Sem amostra, nada muda (motivo explicito)."""
    rec = {"amostra": ranking["amostra"], "horario_brt": None, "formato": None, "motivo": ""}
    if ranking["amostra"] < AMOSTRA_MIN:
        rec["motivo"] = "amostra %d < %d posts: nada ajustado" % (ranking["amostra"], AMOSTRA_MIN)
        return rec
    ini, fim = _hm(JANELA_HORARIO[0]) // 60, _hm(JANELA_HORARIO[1]) // 60
    horas = [(h, m, n) for h, m, n in ranking["por_hora"] if ini <= h < fim and n >= 2]
    if horas:
        rec["horario_brt"] = "%02d:00" % horas[0][0]
    formatos = [(f, m, n) for f, m, n in ranking["por_formato"] if n >= 2]
    if formatos:
        rec["formato"] = formatos[0][0]
    rec["motivo"] = "amostra %d posts" % ranking["amostra"]
    return rec


def relatorio(marca, grava=True):
    supa = _supa()
    linhas = supa.select("ic_redes_metrica", "marca=eq.%s&select=*&order=coletado_em.desc&limit=2000" % marca)
    ultimo = {}
    for l in linhas:  # a coleta mais recente de cada post
        ultimo.setdefault(l["media_id"], l)
    rk = ranquear(list(ultimo.values()))
    rec = recomendar(rk)
    print("relatorio de alcance %s: amostra=%d | formatos=%s | horas=%s | recomendacao=%s" % (
        marca, rk["amostra"], [(f, round(m), n) for f, m, n in rk["por_formato"]],
        [("%02dh" % h, round(m), n) for h, m, n in rk["por_hora"][:5]], rec))
    if grava:
        supa.gravar_segredo("redes_recomendacao_" + marca, json.dumps(rec, ensure_ascii=False))
    return {"ranking": rk, "recomendacao": rec}


def recomendados(lista_marcas):
    """{marca: 'HH:MM'} lidos de ic_segredo (so os que tem horario recomendado). Falha de leitura = vazio."""
    out = {}
    for m in lista_marcas:
        try:
            j = json.loads(_supa().segredo("redes_recomendacao_" + m) or "{}")
            if j.get("horario_brt"):
                out[m] = j["horario_brt"]
        except Exception:
            continue
    return out


def formato_preferido(marca):
    try:
        return json.loads(_supa().segredo("redes_recomendacao_" + marca) or "{}").get("formato")
    except Exception:
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["coletar", "relatorio", "collab-semana"])
    ap.add_argument("--marca", default=None)
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if a.acao == "collab-semana":
        relatorio_semana_collab(qa=a.qa)
        sys.exit(0)
    for m in ([a.marca] if a.marca else marcas.instagram_ativas()):
        try:
            (coletar if a.acao == "coletar" else relatorio)(m)
        except Exception as e:  # uma marca sem token/metrica nao derruba as outras
            print("alcance %s %s: PULADA (%s)" % (a.acao, m, str(e)[:200]))
