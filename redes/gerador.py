# -*- coding: utf-8 -*-
"""Gerador de peças de Instagram por marca (29/09/2026, sessão instagram-contas-grupo).

Lê as páginas do SITE da marca (sitemap.xml + páginas), escolhe uma SEÇÃO ainda não usada, manda uma IA GRATUITA
redigir a peça e grava em `redes/estoque/<marca>/` como `status: rascunho` (quem aprova é o Conselho Editorial).
Tudo por configuração, zero código por marca (PGA-01): a marca vem de `redes/kit/<marca>/regras.json`
(voz, temas, palavras-chave, hashtags, discrição, collab) e de `marca.json` (identidade da arte).

Regra dura (a mesma do Conselho): NADA fabricado. Todo número da peça tem de existir literalmente na página-fonte;
peça com número que a página não traz é REJEITADA e reescrita (ou descartada), nunca publicada. Marca com
`discricao.sigilo` não leva número operacional (número de norma, como "Lei 14.300/2022", é fato público e passa). Sem a
palavra "casa", "agente", "bot", sem emoji, sem promessa de resultado.

Alcance (ordem do CVO: "as postagens têm que ter MÁXIMO alcance, de forma gratuita"): primeira linha da legenda é um
gancho de até 125 caracteres; ao menos uma palavra-chave da marca na legenda; 3 a 5 hashtags; chamada para
salvar/compartilhar/comentar; texto alternativo. Mix de formatos: carrossel (5-7 lâminas) e reels quando o conteúdo
permite, feed simples no resto.

COLLAB (regra do CVO, 29/09/2026: cada marca faz ao menos uma por semana): a cada 7 peças, ao menos
`collab.min_por_semana` (1) e no máximo `collab.max_por_semana` (2) levam `collab: <parceiro>`. O tema é ESCOLHIDO por
afinidade real (termos de `kit/<marca>/afinidades.json` casados com o texto da seção), o parceiro rodiza entre
`collab.parceiros`, a legenda diz "Em colaboração com X (@handle)" e nunca atribui ao parceiro fato que a página-fonte
não traga.

Uso (a partir da raiz do repo):
    python redes/gerador.py --marca incorpmine --quantidade 14                 # site vivo, IA do Conselho (Workers AI/Groq/Gemini)
    python redes/gerador.py --marca incorpmine --quantidade 3 --motor ia       # semeadura local: ia.mjs (casa-ias)
    python redes/gerador.py --marca incorpmine --quantidade 3 --site-dir C:\\...\\public   # páginas de uma cópia local do site
    python redes/gerador.py --marca incorpmine --quantidade 3 --renderizar     # já renderiza a arte (Playwright)
`--motor conselho` (padrão) reaproveita, por import, `conselho/modelos.py::conversar` (sem editá-lo).
Teste sem rede: `python redes/testar_gerador.py`.
"""
import argparse
import datetime
import hashlib
import html as _html
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser

RAIZ = os.path.dirname(os.path.abspath(__file__))
for _p in (RAIZ, os.path.join(RAIZ, "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import estoque  # noqa: E402  (redes/lib/estoque.py, interface existente, sem alterações)

IA_MJS = os.environ.get("CASA_IAS_MJS", os.path.expanduser(os.path.join("~", "_ferramentas", "casa-ias", "ia.mjs")))
FORMATOS = ("carrossel", "reels", "feed")
MAX_GANCHO = 125
CTA_PADRAO = ("Salve para consultar depois e compartilhe com quem decide isso.",
              "Salve este post e compartilhe com quem precisa ler isto.",
              "Compartilhe com quem acompanha o tema e salve para consultar.")
PROIBIDOS_GERAIS = [r"\bcasas?\b", r"\bagentes?\b", r"\bbots?\b", r"\bgaranti(?:mos|do|da|a|e)\b", r"\bgarantia de\b",
                    r"\bcestas?\b", r"\bloteamentos?\b", r"\bresultado garantido\b", r"\bsem risco\b", r"\brentabilidade de\b"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2705\u274C\uFE0F]")


# ---------------------------------------------------------------------------------------------- regras da marca
def carregar_regras(marca):
    with open(os.path.join(RAIZ, "kit", marca, "regras.json"), encoding="utf-8") as fh:
        r = json.load(fh)
    for k in ("marca", "nome", "site", "handle_instagram", "voz", "temas", "palavras_chave", "hashtags", "collab", "discricao"):
        if k not in r:
            raise ValueError("regras.json de %s sem o campo %r" % (marca, k))
    return r


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c)).lower()


# ---------------------------------------------------------------------------------------------- leitura do site
class _Extrator(HTMLParser):
    """Texto legível de uma página, em blocos: (nível do título | 'p', texto). Ignora script/style/nav/footer/svg/form."""
    PULA = {"script", "style", "nav", "footer", "svg", "form", "noscript", "template", "button", "select", "header"}
    BLOCOS = {"h1", "h2", "h3", "h4", "p", "li", "blockquote", "td", "th", "dd", "dt", "figcaption", "summary"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pula = 0
        self.pilha = []
        self.tag = None
        self.buf = []
        self.blocos = []
        self.titulo = ""
        self.descricao = ""
        self._em_title = False
        self.links = []

    VAZIAS = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "path", "circle", "rect", "line", "use", "col", "area", "base", "embed", "param", "track"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._em_title = True
        if tag == "meta" and (a.get("name") or "").lower() == "description":
            self.descricao = a.get("content") or ""
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in self.VAZIAS:
            if tag == "br" and self.pula == 0:
                self.buf.append(" ")
            return
        lang = (a.get("lang") or "").lower()
        outro_idioma = ("lang-es" in a or "lang-en" in a or lang[:2] in ("en", "es")
                        or "en" in (a.get("class") or "").split() or "es" in (a.get("class") or "").split())
        pula = tag in self.PULA or outro_idioma  # só o português entra no texto-fonte
        self.pilha.append((tag, pula))
        if pula:
            self.pula += 1
        elif self.pula == 0 and tag in self.BLOCOS:
            self._fecha()
            self.tag = tag

    def handle_endtag(self, tag):
        if tag == "title":
            self._em_title = False
        if tag in self.VAZIAS:
            return
        if any(t == tag for t, _ in self.pilha):
            while self.pilha:
                t, pula = self.pilha.pop()
                if pula:
                    self.pula -= 1
                if t == tag:
                    break
        if self.pula == 0 and tag in self.BLOCOS:
            self._fecha()

    def handle_data(self, d):
        if self._em_title:
            self.titulo += d
        elif self.pula == 0 and self.tag:
            self.buf.append(d)

    def _fecha(self):
        t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if t and self.tag:
            self.blocos.append((self.tag, t))
        self.buf, self.tag = [], None


def extrair_pagina(html_txt, url=""):
    """{url, titulo, descricao, blocos:[(tag,texto)], secoes:[{titulo, slug, texto}], texto}"""
    ex = _Extrator()
    ex.feed(html_txt)
    ex._fecha()
    titulo = re.sub(r"\s+", " ", ex.titulo).strip()
    secoes, atual = [], {"titulo": None, "partes": []}
    h1 = next((t for tag, t in ex.blocos if tag == "h1"), titulo)
    for tag, t in ex.blocos:
        if tag in ("h1", "h2", "h3"):
            if atual["partes"]:
                secoes.append(atual)
            atual = {"titulo": t, "partes": []}
        else:
            atual["partes"].append(t)
    if atual["partes"]:
        secoes.append(atual)
    out = []
    for s in secoes:
        texto = " ".join(dict.fromkeys(s["partes"]))  # dedup de linhas repetidas (menus, rótulos)
        tit = re.sub(r"[\s#¶§↗→]+$", "", s["titulo"] or h1)
        out.append({"titulo": tit, "slug": _slug(tit), "texto": texto})
    return {"url": url, "titulo": titulo, "h1": h1, "descricao": ex.descricao, "blocos": ex.blocos,
            "secoes": out, "texto": " ".join(t for _, t in ex.blocos), "links": ex.links}


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", _sem_acento(t)).strip("-")[:60] or "secao"


def _http(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; gerador-redes)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


class Site:
    """Fonte das páginas: HTTP (workflow) ou pasta local `--site-dir` (semeadura/teste). Mesma interface."""

    def __init__(self, base_url, site_dir=None, leitor=None):
        self.base = base_url.rstrip("/")
        self.dir = site_dir
        self.leitor = leitor  # função(url)->html, injetável nos testes
        self._cache = {}

    def ler(self, url):
        if url in self._cache:
            return self._cache[url]
        if self.leitor:
            txt = self.leitor(url)
        elif self.dir:
            txt = self._ler_local(url)
        else:
            txt = _http(url)
        self._cache[url] = txt
        return txt

    def _ler_local(self, url):
        caminho = re.sub(r"^https?://[^/]+", "", url).split("#")[0].split("?")[0].strip("/")
        for c in (caminho, caminho + ".html", os.path.join(caminho, "index.html")):
            p = os.path.join(self.dir, c) if c else os.path.join(self.dir, "index.html")
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
        if not caminho:
            with open(os.path.join(self.dir, "index.html"), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        raise FileNotFoundError(url)

    def urls(self, dominios):
        """URLs do sitemap.xml (páginas em português) dentro dos domínios de origem."""
        try:
            xml = self.ler(self.base + "/sitemap.xml")
        except Exception:  # noqa: BLE001 - sem sitemap: só a home
            xml = ""
        achadas = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
        if len(achadas) == 1 and achadas[0].endswith("sitemap.xml"):
            achadas = []
        out = []
        for u in achadas or [self.base + "/"]:
            host = re.sub(r"^https?://([^/]+).*", r"\1", u)
            if dominios and not any(host == d or host.endswith("." + d) for d in dominios):
                continue
            if re.search(r"/(en|es)/|/materiais/|/sistema/|404|privacidade|termos|/verificar|solicitar|/contato|/obrigado", u):
                continue
            out.append(u)
        return list(dict.fromkeys(out))


CITACAO_NORMA = re.compile(
    r"\b(?:Leis?(?:\s+Complementar)?|Decreto(?:-Lei)?|Resolu[çc][ãa]o(?:\s+Normativa)?|Portaria|Instru[çc][ãa]o Normativa|REN|IN|Medida Provis[óo]ria|MP|arts?\.?|artigos?)"
    r"\s*(?:n[ºo°.]*\s*)?\d[\d.,/\-º°ª]*(?:\s*(?:,|e|a)\s*\d[\d.,/\-º°ª]*)*", re.I)
NUM_RE = re.compile(r"\d[\d.,]*\d|\d")


def numeros_do_texto(txt):
    """Números como aparecem (com ponto/vírgula), normalizados para comparar: '1.000' == '1000'."""
    achados = set()
    for m in NUM_RE.findall(txt or ""):
        achados.add(_norm_num(m))
    return achados


def _norm_num(n):
    n = n.strip(".,")
    return re.sub(r"[.,](?=\d{3}\b)", "", n).replace(",", ".")


# ---------------------------------------------------------------------------------------------- escolha
def unidades_disponiveis(site, regras, usadas, ler_pagina=extrair_pagina, minimo=380, excluir_urls=None):
    """[(pagina, secao)] ainda não usadas, com texto suficiente, intercaladas por página (variedade).
    `excluir_urls` (normalizadas por `artigos.normalizar`): páginas que são ARTIGO registrado (novo/pauta/consumido/
    descartado) saem da fila de seções — o artigo vira UMA peça pelo caminho do artigo, nunca também por seção."""
    porpagina = []
    excluir = set(excluir_urls or ())
    if excluir:
        import artigos  # noqa: E402
    for u in site.urls(regras.get("dominios_origem") or []):
        if excluir and artigos.normalizar(u) in excluir:
            continue
        try:
            pg = ler_pagina(site.ler(u), u)
        except Exception:  # noqa: BLE001 - página fora do ar não derruba o lote
            continue
        us = []
        vedados = [_sem_acento(t) for t in regras["discricao"].get("nao_citar", []) if t]
        for s in pg["secoes"]:
            if len(s["texto"]) < minimo or (u, s["slug"]) in usadas:
                continue
            if any(t in _sem_acento(u + " " + s["titulo"]) for t in vedados):  # discrição: nem chega a redigir sobre o vedado
                continue
            us.append((pg, s))
        if us:
            us.sort(key=lambda t: -min(len(t[1]["texto"]), 1800))  # seções mais ricas primeiro (até 1800 car.)
            porpagina.append(us)
    # intercala: 1ª seção de cada página, depois a 2ª... (não esgota uma página antes de tocar as outras)
    out, i = [], 0
    while any(i < len(us) for us in porpagina):
        for us in porpagina:
            if i < len(us):
                out.append(us[i])
        i += 1
    return out


LIMITE_ARTIGO = 8000  # caracteres do artigo que vão ao prompt (o artigo inteiro, não uma seção; acima de LIMITE_CURTO vai ao Gemini)


def unidade_do_artigo(site, url, ler_pagina=extrair_pagina):
    """(pagina, secao) com o ARTIGO INTEIRO como texto-fonte (título = h1). A validação de número usa o mesmo texto."""
    pg = ler_pagina(site.ler(url), url)
    texto = " ".join(dict.fromkeys(s["texto"] for s in pg["secoes"] if s["texto"]))
    titulo = re.sub(r"\s+", " ", pg.get("h1") or pg.get("titulo") or "").strip()
    fim = [x for x in re.sub(r"^https?://[^/]+", "", url).split("/") if x]
    slug = "artigo-" + _slug(fim[-1] if fim else titulo)[:32]
    return pg, {"titulo": titulo, "slug": slug, "texto": texto, "artigo": True}


def usadas_da_marca(marca):
    usadas = set()
    for p in estoque.listar(marca):
        u = str(p.get("nota_origem") or "")
        usadas.add((u, str(p.get("secao") or "")))
    return usadas


# ---------------------------------------------------------------------------------------------- redação
def _prompt(regras, pagina, secao, formato, collab):
    v = regras["voz"]
    artigo = bool(secao.get("artigo"))
    abertura = ("Você redige UMA peça de Instagram para a empresa %(nome)s que RESUME FIELMENTE o ARTIGO abaixo, publicado "
                "no site da empresa: a tese e os pontos centrais do próprio artigo, na ordem dele, sem acrescentar nada; a "
                "peça convida a ler o artigo completo (o link entra na legenda por fora; não escreva URL). "
                if artigo else
                "Você redige UMA peça de Instagram para a empresa %(nome)s, só com o que está no TEXTO-FONTE abaixo. ")
    return (
        abertura +
        "Português do Brasil, tom: %(tom)s.\n"
        "REGRAS DURAS: (1) todo número, prazo, percentual, sigla técnica e fato tem de aparecer LITERALMENTE no TEXTO-FONTE; "
        "na dúvida, corte a frase; nunca invente. (2) Proibido: %(proibidos)s; a palavra 'casa' (use o nome da empresa), "
        "'agente', 'bot', 'cesta', 'loteamento' (use 'parcelamento do solo'); emoji; promessa de resultado; nome de cliente. (3) Preferidos: %(preferidos)s. "
        "(4) Foco: autoridade sobre o que a empresa faz, texto verdadeiro que defende a operação; problema sempre com a resposta ao lado. "
        "Cite número só quando essencial e literal; prefira o método e o critério ao número. "
        "(5) Gancho: primeira linha da legenda com no máximo %(g)d caracteres, concreta, sem clichê. "
        "(6) Inclua ao menos uma destas palavras-chave, naturalmente, na legenda: %(pk)s. "
        "(7) Termine a legenda com uma chamada para salvar e compartilhar, curta. "
        "%(disc)s%(collab)s\n"
        "Formato: %(formato)s. %(estrutura)s\n"
        "Responda SOMENTE com JSON válido, sem markdown: "
        '{"gancho": "...", "legenda": "corpo da legenda SEM o gancho e SEM hashtags, 2 a 4 frases", "cta": "chamada para salvar/compartilhar", '
        '"titulo": "título da arte, até 90 caracteres, use <em>palavra</em> em 1 a 3 palavras de destaque", "rotulo": "rótulo do tema, 1 a 3 palavras", '
        '"laminas": [{"rotulo": "2 a 4 palavras", "texto": "até 170 caracteres", "valor": "número ou prazo em destaque, SÓ se existir no texto-fonte, senão omita", "unidade": ""}], '
        '"roteiro": ["frases curtas de até 80 caracteres (só reels)"], "alt_text": "descrição da imagem em 1 frase", "palavra_chave": "a usada"}\n\n'
        "TÍTULO DA PÁGINA: %(pt)s\nSEÇÃO: %(st)s\nTEXTO-FONTE:\n%(tx)s\n"
    ) % {
        "nome": regras["nome"], "tom": v.get("tom", ""), "proibidos": "; ".join(v.get("proibidos", [])),
        "preferidos": "; ".join(v.get("preferidos", [])), "g": MAX_GANCHO, "pk": ", ".join(regras["palavras_chave"][:14]),
        "disc": ("SIGILO: NENHUM número, valor, prazo ou volume operacional; só conceitos e método. " if regras["discricao"].get("sigilo") else ""),
        "collab": (" Esta peça é publicada em COLLAB com %s (a legenda ganha a linha de colaboração por fora; NÃO escreva você essa linha). Escreva do ponto de vista de %s e NÃO atribua ao parceiro nenhum fato, número ou serviço que o TEXTO-FONTE não traga." % (collab["nome"], regras["nome"]) if collab else ""),
        "formato": formato,
        "estrutura": {"carrossel": "laminas: 5 itens (a capa e o fecho são montados por fora, totalizando 7 lâminas); cada lâmina uma ideia; 'valor' só onde o texto-fonte traz número/prazo.",
                      "reels": "roteiro: 5 frases (a última é a chamada); laminas: [].",
                      "feed": "laminas: [] ; o título é a pergunta ou a tese; inclua 'card': {\"rotulo\": \"...\", \"texto\": \"1 a 2 frases do texto-fonte\"}."}[formato],
        "pt": pagina["titulo"], "st": secao["titulo"], "tx": secao["texto"][:LIMITE_ARTIGO if artigo else 5500],
    }


def _json_da_resposta(bruto):
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (bruto or "").strip())
    try:
        return json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                return None
    return None


class CotaAdiada(Exception):
    """Todos os provedores GRATUITOS estão sem cota: a peça é ADIADA e registrada, nunca redigida por modelo pago."""


LIMITE_CURTO = 9000  # caracteres do prompt; acima disso o texto é "longo" e vai primeiro ao Gemini (janela grande, cascata por cota)


def motor_conselho(prompt):
    """IA GRATUITA do Conselho (Workers AI, Groq, Gemini, OpenRouter só ':free'). Reaproveita conselho/modelos.py por import.
    Curto: cadeia normal (Workers AI/Groq primeiro). Longo: Gemini primeiro (exclui os demais na 1ª tentativa). Em 429 de
    TODOS: CotaAdiada (o lote adia e registra). Nunca há provedor pago na cadeia; este módulo só chama provedores gratuitos."""
    sys.path.insert(0, os.path.join(RAIZ, "conselho"))
    import modelos  # noqa: E402
    msgs = [{"role": "user", "content": prompt}]
    try:
        if len(prompt) > LIMITE_CURTO:
            try:
                return modelos.conversar("redator", msgs, max_saida=2200, excluir_provedores=("cf", "groq", "openrouter"))[0]
            except modelos.CotaEsgotada:
                pass
        return modelos.conversar("redator", msgs, max_saida=2200)[0]
    except modelos.CotaEsgotada as e:
        raise CotaAdiada(str(e)[:200])


def motor_ia(prompt):
    """Semeadura local pela central de IAs gratuitas (conteúdo público do site: sem barreira de sigilo)."""
    import time
    for tentativa in range(4):
        r = subprocess.run(["node", IA_MJS], input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=300)
        if r.returncode == 0:
            return r.stdout
        if r.returncode == 4 or "NENHUMA IA gratuita" in (r.stderr or ""):  # 429 em todas: espera a janela da cota e tenta de novo
            time.sleep(50)
            continue
        raise RuntimeError("ia.mjs falhou (%s): %s" % (r.returncode, (r.stderr or "")[:200]))
    raise CotaAdiada("ia.mjs: nenhuma IA gratuita respondeu após 4 esperas de cota")


MOTORES = {"conselho": motor_conselho, "ia": motor_ia}


# ---------------------------------------------------------------------------------------------- validação
def validar(dados, pagina, secao, regras, formato):
    """Lista de motivos de rejeição (vazia = a peça pode ir a rascunho)."""
    m = []
    fonte = pagina["titulo"] + " " + pagina["descricao"] + " " + secao["titulo"] + " " + secao["texto"]
    gancho = (dados.get("gancho") or "").strip()
    legenda = (dados.get("legenda") or "").strip()
    cta = (dados.get("cta") or "").strip()
    titulo_txt = re.sub(r"<[^>]+>", "", dados.get("titulo") or "")
    lam = dados.get("laminas") or []
    tudo = " ".join([gancho, legenda, cta, titulo_txt, dados.get("rotulo") or "", dados.get("alt_text") or ""]
                    + [" ".join(str(x.get(k, "")) for k in ("rotulo", "texto", "valor", "unidade")) for x in lam if isinstance(x, dict)]
                    + [str(x) for x in (dados.get("roteiro") or [])]
                    + [str((dados.get("card") or {}).get(k, "")) for k in ("rotulo", "texto")])
    if not gancho or len(gancho) > MAX_GANCHO:
        m.append("gancho ausente ou com %d caracteres (máx %d)" % (len(gancho), MAX_GANCHO))
    if not legenda:
        m.append("legenda vazia")
    if not titulo_txt or len(titulo_txt) > 110:
        m.append("título ausente ou longo demais (%d)" % len(titulo_txt))
    if not (dados.get("alt_text") or "").strip():
        m.append("sem texto alternativo")
    if not re.search(r"salv|compartilh|coment", _sem_acento(cta + " " + legenda)):
        m.append("sem chamada para salvar/compartilhar/comentar")
    if not any(_sem_acento(k) in _sem_acento(gancho + " " + legenda + " " + cta) for k in regras["palavras_chave"]):
        m.append("nenhuma palavra-chave do regras.json na legenda")
    for pad in PROIBIDOS_GERAIS:
        if re.search(pad, _sem_acento(tudo)):
            m.append("termo proibido: %s" % pad)
    for pr in regras["voz"].get("proibidos", []):
        if len(pr) > 3 and re.search(r"(?<!\w)%s(?!\w)" % re.escape(_sem_acento(pr)), _sem_acento(tudo)):
            m.append("proibido da marca: %s" % pr)
    for nc in regras["discricao"].get("nao_citar", []):
        if _sem_acento(nc) in _sem_acento(tudo):
            m.append("citação vedada pela discrição: %s" % nc)
    if EMOJI.search(tudo):
        m.append("emoji")
    if "#" in gancho + legenda:
        m.append("hashtag dentro da legenda (elas vão à parte)")
    nums = numeros_do_texto(tudo)
    if regras["discricao"].get("sigilo"):
        # sigilo cobre número OPERACIONAL; número de norma (Lei 14.300/2022, art. 5º) é fato público e passa
        operacionais = numeros_do_texto(CITACAO_NORMA.sub(" ", tudo))
        if operacionais:
            m.append("marca sob sigilo e a peça traz número(s) fora de citação de norma: %s" % sorted(operacionais))
    fnum = numeros_do_texto(fonte)
    soltos = sorted(n for n in nums if n not in fnum)
    if soltos:
        m.append("número(s) que a página-fonte não traz: %s" % soltos)
    if formato == "carrossel" and not (4 <= len(lam) <= 5):
        m.append("carrossel precisa de 4 a 5 lâminas de conteúdo, o que dá 6 a 7 com capa e fecho (achou %d)" % len(lam))
    if formato == "reels" and not (4 <= len(dados.get("roteiro") or []) <= 6):
        m.append("reels precisa de 4 a 6 frases de roteiro")
    if formato == "reels":
        for fr in dados.get("roteiro") or []:
            if len(str(fr)) > 90:
                m.append("frase de roteiro com mais de 90 caracteres")
                break
    if formato == "feed" and not (dados.get("card") or {}).get("texto"):
        m.append("feed sem card de texto")
    for x in lam:
        if isinstance(x, dict) and len(str(x.get("texto", ""))) > 200:
            m.append("lâmina com mais de 200 caracteres")
            break
    return m


# ---------------------------------------------------------------------------------------------- montagem da peça
def escolher_formato(indice, secao, quantidade_total):
    """Carrossel de preferência; reels em ~1 de cada 7 quando a seção é enumerável; feed no resto."""
    ciclo = ("carrossel", "carrossel", "feed", "carrossel", "reels", "carrossel", "feed")
    f = ciclo[indice % len(ciclo)]
    n_itens = len(re.findall(r"[.;:]", secao["texto"]))
    if f == "carrossel" and len(secao["texto"]) < 500:
        f = "feed"
    if f == "reels" and n_itens < 4:
        f = "carrossel"
    return f


def carregar_json_opcional(marca, nome):
    try:
        with open(os.path.join(RAIZ, "kit", marca, nome), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def dados_do_parceiro(slug):
    """Nome e @ do parceiro, lidos do kit dele (marca.json / regras.json): nada chumbado."""
    nome = carregar_json_opcional(slug, "marca.json").get("nome") or slug
    handle = carregar_json_opcional(slug, "regras.json").get("handle_instagram") or (carregar_json_opcional(slug, "marca.json").get("arte_v2") or {}).get("handle")
    return {"slug": slug, "nome": nome, "handle": handle}


def afinidade(secao, marca, regras, minimo=3):
    """{parceiro: pontos} = quantos termos de afinidades.json aparecem no texto da seção (sem acento)."""
    afin = carregar_json_opcional(marca, "afinidades.json")
    alvo = _sem_acento(secao["titulo"] + " " + secao["texto"])
    out = {}
    for parceiro in regras["collab"].get("parceiros", []):
        pts = sum(1 for t in afin.get(parceiro, []) if _sem_acento(t) in alvo)
        if _sem_acento(dados_do_parceiro(parceiro)["nome"]) in alvo:
            pts += 3  # a própria seção cita o parceiro
        if pts >= minimo:  # collab genuína: a seção cita o parceiro ou toca 3 termos da afinidade (o limiar cai a 2 e 1 só para o slot obrigatório)
            out[parceiro] = pts
    return out


def planejar_slots(quantidade, min_sem=1, max_sem=2):
    """Índices (0-based) das peças collab: 1 por bloco de 7 (obrigatório) e 1 opcional (só com afinidade forte)."""
    obrig, opc = [], []
    for b in range((quantidade + 6) // 7):
        base = b * 7
        if min_sem >= 1 and base + 2 < quantidade:
            obrig.append(base + 2)
        elif min_sem >= 1 and base < quantidade:
            obrig.append(min(quantidade - 1, base))
        if max_sem >= 2 and base + 5 < quantidade:
            opc.append(base + 5)
    return obrig, opc


def _escolher_hashtags(regras, dados, n=4, texto=""):
    """3 a 5 hashtags do regras.json; as que casam com o texto da peça vêm primeiro (relevância), as demais completam."""
    base = [h if h.startswith("#") else "#" + h for h in regras["hashtags"]]
    alvo = re.sub(r"[^a-z0-9]", "", _sem_acento(texto))
    rel = [h for h in base if re.sub(r"[^a-z0-9]", "", _sem_acento(h)) and re.sub(r"[^a-z0-9]", "", _sem_acento(h)) in alvo]
    ordem = rel + [h for h in base if h not in rel]
    return ordem[:max(3, min(5, n))]


def _limpa_texto(v):
    """Tipografia segura: hífen/travessão viram sinais comuns (a fonte da arte não tem U+2011; travessão fora, regra da casa)."""
    if isinstance(v, str):
        v = v.replace("‑", "-").replace("‐", "-").replace("‒", "-").replace(" ", " ").replace(" ", " ")
        v = re.sub(r"\s*[—–]\s*", ", ", v)
        return v.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    if isinstance(v, list):
        return [_limpa_texto(x) for x in v]
    if isinstance(v, dict):
        return {k: _limpa_texto(x) for k, x in v.items()}
    return v


def _limpa_html(t):
    return _html.unescape(re.sub(r"\s+", " ", t or "")).strip()


def _foto_da_marca(marca, chave):
    """Foto do kit (crédito conferido em fotos/FONTES.md) escolhida de forma determinística; marca sem foto = fundo sólido."""
    d = os.path.join(RAIZ, "kit", marca, "fotos")
    fotos = sorted(f[:-4] for f in os.listdir(d) if f.endswith(".jpg")) if os.path.isdir(d) else []
    if not fotos:
        return None
    return fotos[int(hashlib.sha1(chave.encode()).hexdigest(), 16) % len(fotos)]


def ajustar_rotulo(rot, limite=26):
    """Kicker da capa cabe em uma linha a 390 px: corta por palavras inteiras (vale testado: 'Desenvolvimento
    organizacional' quebrava e empurrava o contador 1/7)."""
    if len(rot) <= limite:
        return rot
    out = ""
    for w in rot.split():
        if len((out + " " + w).strip()) > limite:
            break
        out = (out + " " + w).strip()
    return out


def ajustar_url_arte(url, limite=34):
    """Rodapé da arte: URL longa quebra em duas linhas; acima do limite fica só o domínio."""
    return url if len(url) <= limite else url.split("/")[0]


def montar_spec_arte(regras, dados, pagina, secao, formato, categoria, url_arte, foto=None):
    """Especificação para `arte_v2.py` (em `_arte/pecas-v2.json`)."""
    rot = ajustar_rotulo(_limpa_html(dados.get("rotulo") or ""))
    spec = {"modelo": "carrossel" if formato == "carrossel" else "pergunta", "categoria": categoria,
            "frente_rotulo": rot, "titulo": dados["titulo"].strip(), "url": ajustar_url_arte(url_arte)}
    if foto:
        spec["foto"] = foto
    if formato == "carrossel":
        spec["so_quadros"] = True
        lam = [{"tipo": "capa", "deslize": "Deslize"}]
        for x in dados["laminas"]:
            if str(x.get("valor") or "").strip():
                lam.append({"tipo": "regra", "rotulo": x.get("rotulo", ""), "valor": str(x["valor"]).strip(),
                            "unidade": str(x.get("unidade") or ""), "texto": x["texto"]})
            else:
                lam.append({"tipo": "acao", "rotulo": x.get("rotulo", ""), "texto": x["texto"]})
        lam.append({"tipo": "fecho", "rotulo": "Guarde para consultar", "texto": dados["cta"].strip(),
                    "nota": "Leia na fonte: " + url_arte})
        spec["laminas"] = lam
    else:
        c = dados.get("card") or {}
        spec["card"] = {"tipo": "texto", "rotulo": c.get("rotulo") or "O que a página diz", "texto": c.get("texto") or dados["legenda"][:160]}
        spec["fonte"] = url_arte
    return spec


def _url_curta(url):
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


def gerar_uma(regras, pagina, secao, formato, seq, motor, collab=None, categoria="marco", hoje=None, tentativas=3, pts_af=0):
    """Redige, valida e devolve ((frontmatter, corpo, spec_arte, peca_id), []) ou (None, motivos) se nada passou.
    `collab` = dict do parceiro ({slug, nome, handle}) ou None."""
    ultimo = []
    dados = None
    for _t in range(tentativas):
        p = _prompt(regras, pagina, secao, formato, collab)
        if ultimo:
            p += "\nSUA TENTATIVA ANTERIOR FOI REJEITADA por: %s. Corrija SÓ isso e mantenha o resto.\n" % "; ".join(ultimo)
        try:
            dados = _json_da_resposta(motor(p))
        except CotaAdiada as e:
            return None, ["ADIADA: sem cota gratuita (%s)" % str(e)[:80]]
        except Exception as e:  # noqa: BLE001 - motor fora do ar: tenta de novo, depois desiste desta seção
            ultimo = ["motor falhou: %s" % str(e)[:120]]
            continue
        if not isinstance(dados, dict):
            ultimo = ["resposta não era JSON"]
            continue
        dados = _limpa_texto(dados)
        dados["titulo"] = _limpa_html(dados.get("titulo", ""))
        dados["laminas"] = [x for x in (dados.get("laminas") or []) if isinstance(x, dict)][:5]  # capa + 5 + fecho = 7 lâminas no máximo
        for x in dados["laminas"]:  # valor em destaque só se for quantidade curta (%, prazo, contagem); código de norma vira texto
            if str(x.get("valor") or "").strip() and not re.fullmatch(r"[\d][\d.,]{0,7}(\s?(%|mil|milh[õo]es?|bilh[õo]es?|anos?|meses|dias|horas|t|kg|MW|kW|MWh|GW|GWh|ha|km|m²))?", str(x["valor"]).strip()):
                x.pop("valor", None)
        if formato == "feed" and not (dados.get("card") or {}).get("texto"):
            prim = re.split(r"(?<=[.!?])\s", (dados.get("legenda") or "").strip())[0]
            dados["card"] = {"rotulo": "O que a página diz", "texto": prim[:170]}
        ultimo = validar(dados, pagina, secao, regras, formato)
        if not ultimo:
            break
    if ultimo or not dados:
        return None, ultimo
    hoje = hoje or datetime.date.today()
    tags = _escolher_hashtags(regras, dados, 4, dados["gancho"] + " " + dados["legenda"] + " " + secao["titulo"])
    url = pagina["url"]
    url_curta = _url_curta(url)
    linha_collab = ""
    if collab:
        linha_collab = "Em colaboração com %s%s.\n\n" % (collab["nome"], " (%s)" % collab["handle"] if collab.get("handle") else "")
    legenda = "%s\n\n%s\n\n%s%s\n\n%s\n%s" % (dados["gancho"].strip(), dados["legenda"].strip(), linha_collab, dados["cta"].strip(), url_curta, " ".join(tags))
    # a marca entra no id: ic_redes_publicacao.peca_id e UNIQUE global e secoes como "Fontes"/"Como usar" se repetem
    # entre marcas no mesmo dia (sem a marca, a peca da 2a marca nao entraria no lote)
    slug = "%s-%s-%s-%02d" % (hoje.isoformat(), regras["marca"], secao["slug"][:40], seq)
    peca_id = "%s-instagram" % slug
    pasta = "redes/estoque/%s/_gerados/%s" % (regras["marca"], peca_id)
    rot = _limpa_html(dados.get("rotulo") or "")
    if rot and rot.lower() == categoria.lower():
        dados["rotulo"] = ""  # o selo já diz a categoria; não repete
    spec = montar_spec_arte(regras, dados, pagina, secao, formato, categoria, url_curta, _foto_da_marca(regras["marca"], peca_id))
    import arte_v2  # noqa: E402 - só p/ montar texto_arte no formato que a arte consome (sem Playwright)
    texto_arte = arte_v2.texto_da_arte(spec, regras["marca"])
    fm = {
        "marca": regras["marca"], "canal": "instagram", "tipo": "video" if formato == "reels" else ("4" if formato == "carrossel" else "5"),
        "formato": formato, "pilar": "A", "nota_origem": url, "secao": secao["slug"],
        "imagem": ("%s/quadro-01.png" % pasta) if formato == "carrossel" else ("%s-feed.png" % pasta) if formato == "feed" else None,
        "mes_ref": hoje.strftime("%Y-%m"), "data_publicacao": None, "status": "rascunho",
        "aprovado_em": None, "aprovado_por": None, "publicado_em": None, "url_post": None, "publicado_por": None,
        "roteiro": [str(x) for x in dados["roteiro"]] if formato == "reels" else None,
        "arquivo_mp4": None, "legenda_srt": None, "capa": None,
    }
    if formato == "carrossel":
        n = len(spec["laminas"])
        fm["quadros"] = ["%s/quadro-%02d.png" % (pasta, i + 1) for i in range(n)]
    if formato == "feed":
        fm["imagem_stories"] = "%s-stories.png" % pasta
    fm.update({
        "fontes": [{"dado": _limpa_html(secao["titulo"]), "norma": pagina["titulo"], "url": url,
                    "verificado": "%s, texto lido na página publicada" % hoje.strftime("%d/%m/%Y")}],
        "arte": "v2", "categoria": categoria, "texto_arte": texto_arte, "alt_text": _limpa_html(dados["alt_text"]),
        "hashtags": tags, "palavra_chave": dados.get("palavra_chave") or None,
        "gancho": dados["gancho"].strip(),
    })
    if secao.get("artigo"):
        fm["origem"] = "artigo"  # resumo do artigo inteiro (redes/artigos.py): o registro em ic_redes_artigo aponta para esta peça
    if collab:
        fm["collab"] = collab["slug"]
        fm["collab_afinidade"] = pts_af  # pontos de afinidade da seção com o parceiro (>= 3 forte; 1 a 2 = último recurso do slot obrigatório): o Conselho pesa
    return (fm, legenda, spec, peca_id), []


def _fila_de_artigos(marca, regras, site, artigos_reg, gravar, log):
    """(unidades de artigo `novo`, na ordem de prioridade; {id(secao): linha}; URLs reservadas ao caminho do artigo).
    Registro indisponível: nenhuma unidade de artigo e TODA URL que casa o padrão de artigo sai das seções (o artigo
    espera o banco voltar; nunca é consumido por seção enquanto isso)."""
    import artigos  # noqa: E402
    try:
        linhas = artigos_reg.linhas(marca)
    except Exception as e:  # noqa: BLE001
        conf = artigos.config(regras)
        padrao = re.compile(conf["padrao"]) if conf else None
        reserv = {artigos.normalizar(u) for u in site.urls(regras.get("dominios_origem") or [])
                  if padrao and padrao.search(re.sub(r"^https?://[^/]+", "", u).rstrip("/") + "/")}
        log("  (aviso) registro de artigos indisponível (%s): artigo espera; %d URL(s) de artigo fora das seções" % (str(e)[:100], len(reserv)))
        return [], {}, reserv
    fila, linha_de = [], {}
    for row in artigos.pendentes(marca, artigos_reg, linhas):
        try:
            pg, sc = unidade_do_artigo(site, row["url"])
        except urllib.error.HTTPError as e:
            if e.code in (404, 410) and gravar:
                artigos.registrar_falha(artigos_reg, row, ["a página do artigo saiu do site (HTTP %d)" % e.code], definitivo=True)
            log("  (aviso) artigo %s ilegível agora (HTTP %d)" % (row["url"], e.code))
            continue
        except Exception as e:  # noqa: BLE001 - fora do ar agora: tenta na próxima rodada, sem gastar tentativa
            log("  (aviso) artigo %s ilegível agora (%s)" % (row["url"], str(e)[:80]))
            continue
        if len(sc["texto"]) < 380:
            if gravar:
                artigos.registrar_falha(artigos_reg, row, ["texto do artigo curto demais para resumir (%d caracteres lidos)" % len(sc["texto"])])
            log("  (aviso) artigo %s com texto curto demais (%d car.)" % (row["url"], len(sc["texto"])))
            continue
        linha_de[id(sc)] = row
        fila.append((pg, sc))
    return fila, linha_de, artigos.reservadas(linhas)


def gerar_lote(marca, quantidade, motor, site=None, site_dir=None, hoje=None, gravar=True, log=print, leitor=None,
               artigos_reg=None, so_artigos=False):
    """Gera até `quantidade` peças. Com `artigos_reg` (redes/artigos.py `Registro`), os ARTIGOS NOVOS do site vêm
    primeiro (fonte prioritária, uma peça por artigo) e só depois as seções antigas ainda não usadas; `so_artigos`
    não recorre a seção nenhuma (pauta de artigo com o estoque saudável)."""
    regras = carregar_regras(marca)
    site = site or Site(regras["site"], site_dir, leitor)
    usadas = usadas_da_marca(marca)
    fila_art, linha_de, reserv = ([], {}, set())
    if artigos_reg is not None:
        fila_art, linha_de, reserv = _fila_de_artigos(marca, regras, site, artigos_reg, gravar, log)
        if fila_art:
            log("%s: %d artigo(s) novo(s) do site na frente da fila" % (marca, len(fila_art)))
    fila = list(fila_art) if so_artigos else list(fila_art) + unidades_disponiveis(site, regras, usadas, excluir_urls=reserv)
    log("%s: %d unidade(s) disponíveis (%d artigo(s) novo(s)); pedido: %d peça(s)" % (marca, len(fila), len(fila_art), quantidade))
    cats = (carregar_json_opcional(marca, "marca.json").get("arte_v2") or {}).get("categorias") or {}
    parceiros = regras["collab"].get("parceiros", [])
    base = len(estoque.listar(marca))  # peças que a marca já tem: os blocos de 7 seguem o índice GLOBAL (retomar um lote não desalinha o collab)
    obrig, opc = planejar_slots(base + quantidade, int(regras["collab"].get("min_por_semana", 0)), int(regras["collab"].get("max_por_semana", 0)))
    hoje = hoje or datetime.date.today()
    feitas, recusadas, adiadas = [], [], []
    ultimo_parceiro, seq, restante = None, 0, list(fila)
    devendo_collab = False  # slot de collab obrigatório que um artigo sem afinidade não pôde ocupar: passa à próxima peça
    for idx in range(quantidade):
        if not restante:
            break
        arts = [(pg, sc) for pg, sc in restante if sc.get("artigo")]
        base_cands = arts or restante  # artigo novo SEMPRE antes de seção antiga
        candidatos = base_cands[:]  # ordem intercalada por página (variedade)
        quer_collab = (base + idx) in obrig or (base + idx) in opc or devendo_collab
        if quer_collab and parceiros:
            obrigatorio = (base + idx) in obrig or devendo_collab
            for minimo in ((3, 2, 1) if obrigatorio else (4,)):  # slot obrigatório: afrouxa o limiar de afinidade antes de faltar collab na semana
                pontuados = []
                for pg, sc in base_cands:
                    af = afinidade(sc, marca, regras, minimo)
                    if af:
                        # rodízio: penaliza repetir o parceiro anterior
                        par, pts = sorted(af.items(), key=lambda kv: (kv[0] == ultimo_parceiro, -kv[1]))[0]
                        pontuados.append((pts - (0.5 if par == ultimo_parceiro else 0), par, pg, sc, pts))
                pontuados.sort(key=lambda t: -t[0])
                if pontuados:
                    break
            if pontuados:
                candidatos = [(pg, sc, par, pts) for _s, par, pg, sc, pts in pontuados]
                devendo_collab = False
            elif arts and obrigatorio:
                log("  (aviso) artigo novo sem afinidade para collab no índice %d: sai solo; a collab passa à próxima peça" % idx)
                devendo_collab, quer_collab = True, False
            else:
                log("  (aviso) sem seção com afinidade para collab no índice %d" % idx)
                quer_collab = False
        if not quer_collab:
            candidatos = [(pg, sc, None, 0) for pg, sc in candidatos]
        ok = False
        for pagina, secao, parceiro, pts_af in candidatos[:6]:
            seq += 1
            formato = escolher_formato(base + len(feitas), secao, quantidade)
            categoria = "marco" if re.search(r"\d", secao["texto"]) else "metodo"
            if cats and categoria not in cats:
                categoria = next(iter(cats))
            res, motivos = gerar_uma(regras, pagina, secao, formato, seq, motor, dados_do_parceiro(parceiro) if parceiro else None, categoria, hoje, pts_af=pts_af)
            restante = [(a, b) for a, b in restante if not (a is pagina and b is secao)]
            linha_art = linha_de.get(id(secao))
            if res is None and motivos and motivos[0].startswith("ADIADA"):
                adiadas.append((pagina["url"], secao["slug"]))
                _registrar_adiadas(marca, adiadas)
                log("  ADIADA (sem cota gratuita em nenhum provedor): lote interrompido; registrado em _arte/adiadas.json")
                return feitas, recusadas
            if res is None:
                recusadas.append((pagina["url"], secao["titulo"], motivos))
                if linha_art is not None and gravar:
                    import artigos  # noqa: E402
                    artigos.registrar_falha(artigos_reg, linha_art, motivos)
                log("  descartada: %s | %s -> %s" % (_url_curta(pagina["url"]), secao["titulo"][:50], "; ".join(motivos)[:220]))
                continue
            fm, corpo, spec, peca_id = res
            if gravar:
                if linha_art is not None:  # banco ANTES do arquivo: se o registro falhar, a peça não nasce (nada repete amanhã)
                    import artigos  # noqa: E402
                    artigos.marcar_pauta(artigos_reg, linha_art, peca_id, secao["titulo"])
                estoque.escrever(marca, peca_id, fm, corpo)
                _gravar_spec(marca, peca_id[:-len("-instagram")], spec)
            feitas.append((peca_id, formato, parceiro))
            if parceiro:
                ultimo_parceiro = parceiro
            log("  ok %-9s %s%s%s" % (formato, peca_id, "  [collab %s]" % parceiro if parceiro else "", "  [artigo]" if linha_art is not None else ""))
            ok = True
            break
        if not ok:
            log("  (aviso) nenhuma unidade passou para o índice %d" % idx)
    return feitas, recusadas



def _registrar_adiadas(marca, adiadas):
    d = os.path.join(RAIZ, "estoque", marca, "_arte")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "adiadas.json"), "w", encoding="utf-8") as fh:
        json.dump([{"url": u, "secao": s, "em": datetime.datetime.now().isoformat(timespec="seconds")} for u, s in adiadas], fh, ensure_ascii=False, indent=1)


def gerar_artigo(*_a, **_k):
    """ESQUELETO (próxima fase, `--tipo artigo`): artigo semanal LONGO por marca. Especificação:
    entrada = 1 a 3 seções relacionadas do site (mesma leitura de `unidades_disponiveis`); saída = `redes/estoque/<marca>/artigos/
    <AAAA-MM-DD>-<slug>.md` (frontmatter `tipo: artigo`, `status: rascunho`, `nota_origem`, `fontes`) com 900 a 1400 palavras,
    título com palavra-chave, 3 a 5 intertítulos, resumo de 2 linhas e chamada final; mesma `validar` (número só se está na
    página-fonte, sem "casa"/"agente"/"bot", sem promessa), mesma guarda de sigilo e de collab. Motor: texto longo vai ao
    Gemini (cascata de modelos por cota), curto ao Groq/Workers AI; 429 de todos = adiar e registrar. Custo zero: só provedores gratuitos."""
    raise NotImplementedError("gerador de artigo semanal: esqueleto documentado; implementar na próxima fase (ver docstring)")


def _gravar_spec(marca, slug, spec):
    d = os.path.join(RAIZ, "estoque", marca, "_arte")
    os.makedirs(d, exist_ok=True)
    caminho = os.path.join(d, "pecas-v2.json")
    dados = {}
    if os.path.isfile(caminho):
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    dados[slug] = spec
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--marca", required=True)
    ap.add_argument("--tipo", choices=("post", "artigo"), default="post", help="post (padrão) ou artigo semanal longo (esqueleto)")
    ap.add_argument("--quantidade", type=int, default=7)
    ap.add_argument("--motor", choices=sorted(MOTORES), default="conselho")
    ap.add_argument("--site-dir", help="pasta local com as páginas do site (em vez do site vivo)")
    ap.add_argument("--renderizar", action="store_true", help="renderiza a arte (Playwright) das peças geradas")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.tipo == "artigo":
        gerar_artigo(a.marca, a.quantidade)
    feitas, recusadas = gerar_lote(a.marca, a.quantidade, MOTORES[a.motor], site_dir=a.site_dir)
    print("geradas: %d | descartadas: %d" % (len(feitas), len(recusadas)))
    if a.renderizar and feitas:
        import arte_v2
        for peca_id, _f, _c in feitas:
            arte_v2.rodar(a.marca, filtro=peca_id[:-len("-instagram")], formatos=("feed",))
    return 0 if feitas else 1


if __name__ == "__main__":
    sys.exit(main())
