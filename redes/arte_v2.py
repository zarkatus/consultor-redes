# -*- coding: utf-8 -*-
"""Arte v2 das redes do grupo (ordem do CVO, 25/09/2026: "nenhuma postagem só com texto"; agnóstica de marca em 29/09/2026).

Renderiza cada peça de Instagram como imagem ILUSTRADA e hierarquizada: selo de frente no topo,
ilustração autoral (SVG em linha fina dourada) como herói, a pergunta em Cormorant, um cartão "O que a
norma diz" com o NÚMERO ou o PRAZO em destaque + norma e artigo em linha legível, lockup no rodapé.

Determinístico, sem IA de imagem, sem banco pago, sem rede: HTML + fontes do kit + Chromium (Playwright).
As fontes são as ESTÁTICAS do kit (acento assentado, lição de 24/09 — nunca a variável).

AGNÓSTICA DE MARCA (PGA-01, 29/09/2026): paleta, fontes, lockup, handle, categorias e o símbolo vêm de
`redes/kit/<marca>/marca.json` (bloco `arte_v2`) e de `kit/<marca>/logo.svg`. O que faltar cai no padrão da InnConta,
então a arte da InnConta segue byte a byte a mesma. Sem `ilustracao` na peça, o herói é o símbolo da marca; sem `foto`,
o fundo é sólido. Carrossel tem N lâminas (capa, regra, acao, fecho).

Entrada: `redes/estoque/<marca>/_arte/pecas-v2.json` (slug -> especificação da arte). O texto da arte sai
do texto já aprovado da peça (nada é inventado aqui) e passa por `guarda.checar` ANTES de renderizar.

Uso (a partir da raiz do repo):
    python redes/arte_v2.py                      # todas as peças do JSON, feed + stories
    python redes/arte_v2.py --filtro 2026-09-28  # só slugs que contêm o filtro
    python redes/arte_v2.py --formatos feed      # só um formato
Saída: redes/estoque/<marca>/_gerados/<slug>-instagram-feed.png, <slug>-instagram-stories.png (e <slug>/quadro-NN.png nos
carrosséis). Renderiza em lote e fecha o navegador ao fim (notebook com pouca RAM).

Especificação de uma peça (campos):
  modelo      pergunta | metodo | oficio | marco | feriado | carrossel
  ilustracao  nome do arquivo em redes/kit/<marca>/ilustracoes/ (sem .svg); feriado pode omitir
  kicker      "Pergunta da mesa <span>·</span> Energia"
  data_rotulo (opcional) "1º de outubro" — canto superior direito
  titulo      HTML com <em> (itálico dourado)
  card        {"tipo": "numero", "valor": "5%", "unidade": "", "rotulo": "...", "texto": "..."}
              {"tipo": "texto", "rotulo": "...", "texto": "..."}   (texto pode ter <b>)
  fonte       linha de fonte (norma + artigo); vai ao cartão, corpo >= 30 px
  url         "innconta.com.br/frente/energia" (rodapé); feriado não leva
  feriado:    grande, citacao, fonte, nota_legal
  carrossel:  laminas = [ {"tipo": "capa"|"regra"|"acao"|"fecho", ...}, ... ]   (N >= 3; InnConta usa 3)
  so_quadros  true: carrossel só gera os quadros (não gera a imagem única feed/stories)
"""
import argparse
import json
import os
import re
import sys
import unicodedata

RAIZ_REDES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ_REDES)

FORMATOS = {  # stories: 250 px de área segura acima e abaixo (interface do Instagram)
    "feed": dict(w=1080, h=1350, pt=78, pb=84, m=84, titulo=64, ilu_min=250),
    "stories": dict(w=1080, h=1920, pt=250, pb=234, m=84, titulo=76, ilu_min=380),
}


# ------------------------------------------------------------------------------- identidade por marca (kit/<marca>/marca.json)
# Padrão = InnConta (o que estava chumbado no CSS). Cada marca sobrescreve em marca.json -> "arte_v2".
TEMA_PADRAO = {"fundo": "#14110D", "fundo_rgb": "20,17,13", "texto": "#E7E2D5", "destaque": "#C29C57", "destaque_rgb": "194,156,87",
               "mudo": "#8C8475", "suave": "#B5AB95", "suave2": "#BDB5A2", "claro": "#F0EBDD"}
# literal do CSS (InnConta) -> chave do tema; a troca é textual e vale também para o HTML montado em Python
_TROCAS = (("#14110D", "fundo"), ("20,17,13", "fundo_rgb"), ("#E7E2D5", "texto"), ("#C29C57", "destaque"), ("194,156,87", "destaque_rgb"),
           ("#8C8475", "mudo"), ("#B5AB95", "suave"), ("#BDB5A2", "suave2"), ("#F0EBDD", "claro"))


def _hex_rgb(h):
    h = h.lstrip("#")
    return "%d,%d,%d" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _mistura(a, b, t):
    """a*(1-t)+b*t em #rrggbb (deriva tons de apoio quando a marca não os declara)."""
    ra, rb = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02X%02X%02X" % tuple(round(x * (1 - t) + y * t) for x, y in zip(ra, rb))


_CACHE_TEMA = {}


def marca_json(marca):
    try:
        with open(os.path.join(RAIZ_REDES, "kit", marca, "marca.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def tema(marca):
    """Tokens da marca: cores, fontes, lockup, handle, categorias. Sem bloco `arte_v2` = InnConta."""
    if marca in _CACHE_TEMA:
        return _CACHE_TEMA[marca]
    m = marca_json(marca)
    a = m.get("arte_v2") or {}
    T = dict(TEMA_PADRAO)
    if a.get("fundo") or a.get("destaque"):  # marca própria: deriva o que não vier declarado
        T["fundo"] = a.get("fundo", T["fundo"]); T["texto"] = a.get("texto", T["texto"]); T["destaque"] = a.get("destaque", T["destaque"])
        T["mudo"] = a.get("mudo") or _mistura(T["texto"], T["fundo"], .52)
        T["suave"] = a.get("suave") or _mistura(T["texto"], T["fundo"], .30)
        T["suave2"] = a.get("suave2") or _mistura(T["texto"], T["fundo"], .27)
        T["claro"] = a.get("claro") or _mistura(T["texto"], "#FFFFFF", .35)
        T["fundo_rgb"] = _hex_rgb(T["fundo"]); T["destaque_rgb"] = _hex_rgb(T["destaque"])
    T["fam_titulo"] = a.get("fam_titulo", "Cormorant Garamond")
    T["fam_corpo"] = a.get("fam_corpo", "Jost")
    T["fontes"] = a.get("fontes")  # lista {familia, estilo, peso, arquivo}; None = padrão (Cormorant + Jost do kit)
    T["handle"] = a.get("handle") or ""
    T["mostrar_handle"] = bool(a.get("mostrar_handle"))
    T["categorias"] = a.get("categorias")
    T["lockup"] = m.get("lockup") or {"partes": [{"texto": "Inn"}, {"texto": "Conta"}]}
    T["nome"] = m.get("nome", "InnConta")
    _CACHE_TEMA[marca] = T
    return T


def _tematizar(html, marca):
    T = tema(marca)
    for lit, k in _TROCAS:
        if T[k] != TEMA_PADRAO[k]:
            html = html.replace(lit, T[k])
    if T["fam_titulo"] != "Cormorant Garamond":
        html = html.replace("'Cormorant Garamond'", "'%s'" % T["fam_titulo"])
    if T["fam_corpo"] != "Jost":
        html = html.replace("'Jost'", "'%s'" % T["fam_corpo"])
    return html


GRAO = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'>"
        "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/>"
        "<feColorMatrix values='0 0 0 0 0.9  0 0 0 0 0.85  0 0 0 0 0.75  0 0 0 0.55 0'/></filter>"
        "<rect width='300' height='300' filter='url(%23n)'/></svg>")

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#14110D}
.p{position:relative;overflow:hidden;background:#14110D;color:#E7E2D5;font-family:'Jost',sans-serif;display:flex;flex-direction:column}
.p:before{content:'';position:absolute;inset:0;background:#14110D;z-index:0}
.p>.foto,.p>.veil,.p>.faixa{position:absolute!important;flex:none}
.foto{inset:-14px!important;background-size:cover;background-position:center;z-index:0;filter:blur(3px)}
.veil{inset:0;background:linear-gradient(180deg,rgba(20,17,13,.72) 0%,rgba(20,17,13,.80) 38%,rgba(20,17,13,.90) 62%,rgba(20,17,13,.93) 100%);z-index:1}
.faixa{left:0;right:0;top:0;height:7px;z-index:3}
.sel{display:flex;align-items:center;gap:14px;white-space:nowrap}
.sel svg{width:36px;height:36px;flex:none}
.sel .k{font-size:27px;letter-spacing:.15em}
.p:after{content:'';position:absolute;inset:0;background:url("GRAO");opacity:0;mix-blend-mode:screen;z-index:9;pointer-events:none}
.p>*{position:relative;z-index:2;flex:none}
.top{display:flex;justify-content:space-between;align-items:baseline}
.k{font-weight:600;font-size:26px;letter-spacing:.26em;text-transform:uppercase;color:#C29C57}
.k span{color:#8C8475}
.dt{font-weight:500;font-size:26px;letter-spacing:.16em;text-transform:uppercase;color:#B5AB95;text-align:right}
.ilu{flex:1 1 0!important;min-height:0;margin:14px 0 6px;display:flex;align-items:center;justify-content:center}
.ilu svg{width:100%;height:100%;display:block}
.t{font-family:'Cormorant Garamond',serif;font-weight:500;line-height:1.05;letter-spacing:-.005em;color:#E7E2D5;margin-bottom:22px}
.t em{font-style:italic;color:#C29C57;font-weight:500}
.card{border:1px solid rgba(194,156,87,.45);border-radius:6px;background:linear-gradient(rgba(194,156,87,.07),rgba(194,156,87,.07)),rgba(20,17,13,.84);padding:22px 30px 20px}
.cl{font-weight:600;font-size:26px;letter-spacing:.22em;text-transform:uppercase;color:#C29C57;margin-bottom:10px}
.num{display:flex;align-items:center;gap:30px}
.v{font-feature-settings:'lnum' 1;font-variant-numeric:lining-nums;font-family:'Cormorant Garamond',serif;font-weight:500;color:#C29C57;line-height:.9;letter-spacing:-.02em;white-space:nowrap}
.v small{font-size:.42em;letter-spacing:0;margin-left:.14em;font-weight:500}
.nt{border-left:1px solid rgba(194,156,87,.4);padding-left:26px;font-size:40px;line-height:1.24;color:#E7E2D5;font-weight:400}
.nt b{font-weight:500;color:#E7E2D5}
.tx{font-family:'Cormorant Garamond',serif;font-style:italic;font-weight:500;color:#F0EBDD;line-height:1.14}
.tx b{font-weight:500;color:#C29C57}
.f{font-weight:400;font-size:34px;line-height:1.3;color:#BDB5A2;border-top:1px solid rgba(194,156,87,.3);margin-top:16px;padding-top:12px}
.f b{font-weight:600;color:#B5AB95;letter-spacing:.08em;text-transform:uppercase;font-size:28px;margin-right:12px}
.foot{display:flex;justify-content:space-between;align-items:flex-end;margin-top:26px}
.lk{font-family:'Cormorant Garamond',serif;line-height:.86;font-size:50px}
.lk i{display:block;font-style:normal;font-weight:600;color:#E7E2D5}
.lk u{display:block;text-decoration:none;font-weight:500;color:#C29C57}
.url{font-size:34px;color:#B5AB95;text-align:right;line-height:1.45}
.g{font-family:'Cormorant Garamond',serif;font-weight:500;color:#E7E2D5;line-height:.9;letter-spacing:-.01em}
.q{font-family:'Cormorant Garamond',serif;font-style:italic;font-weight:400;color:#C29C57;line-height:1.18}
.fio{height:1px;background:rgba(194,156,87,.55)}
.mid{flex:1 1 0!important;min-height:0;display:flex;flex-direction:column;justify-content:center;gap:34px}
.big{font-feature-settings:'lnum' 1;font-variant-numeric:lining-nums;font-family:'Cormorant Garamond',serif;font-weight:500;color:#C29C57;line-height:.86;letter-spacing:-.03em}
.big small{font-size:.32em;letter-spacing:0;margin-left:.12em}
.s-st .nt{font-size:44px}.s-st .f{font-size:36px}.s-st .url{font-size:36px}.s-st .cl{font-size:28px}
.dots{display:flex;gap:12px;justify-content:center;margin-top:6px}
.dots i{width:12px;height:12px;border-radius:50%;border:1.5px solid #C29C57;display:block}
.dots i.on{background:#C29C57}
"""


def _font_css(marca):
    import kit_comum  # fonte padrao: do kit da marca se existir, senao a unica copia (kit da InnConta)
    f = lambda n: "file:///" + kit_comum.arquivo(marca, "fonts-estaticas", n).replace("\\", "/")
    fontes = tema(marca)["fontes"]
    if fontes:  # marca própria: arquivos declarados em marca.json (woff2 ou ttf; peso pode ser faixa "100 900")
        return "".join("@font-face{font-family:'%s';font-style:%s;font-weight:%s;src:url(%s) format('%s')}"
                       % (x["familia"], x.get("estilo", "normal"), x["peso"], f(x["arquivo"]),
                          "woff2" if x["arquivo"].endswith(".woff2") else "truetype") for x in fontes)
    faces = [("Cormorant Garamond", "normal", 400, "Cormorant-normal-400.ttf"),
             ("Cormorant Garamond", "normal", 500, "Cormorant-normal-500.ttf"),
             ("Cormorant Garamond", "normal", 600, "Cormorant-normal-600.ttf"),
             ("Cormorant Garamond", "italic", 400, "Cormorant-italic-400.ttf"),
             ("Cormorant Garamond", "italic", 500, "Cormorant-italic-500.ttf"),
             ("Jost", "normal", 400, "Jost-normal-400.ttf"), ("Jost", "normal", 500, "Jost-normal-500.ttf"),
             ("Jost", "normal", 600, "Jost-normal-600.ttf")]
    return "".join("@font-face{font-family:'%s';font-style:%s;font-weight:%d;src:url(%s) format('truetype')}"
                   % (fa, st, w, f(a)) for fa, st, w, a in faces)



# ------------------------------------------------------------------------------- categorias (CATEGORIAS.md)
CATEGORIAS = {  # nome no selo, acento fixo (variação sutil do dourado), ícone (traço 1.8 no acento)
    "pergunta": ("Pergunta da mesa", "#C29C57", '<circle cx="18" cy="18" r="14"/><path d="M13.5 14.5a4.6 4.6 0 1 1 6.6 4.1c-1.4.8-2.1 1.6-2.1 3.1"/><circle cx="18" cy="26.3" r=".9"/>'),
    "oficio": ("Ofício", "#D1A06A", '<path d="M18 3.5l12.5 7.25v14.5L18 32.5 5.5 25.25v-14.5z"/><circle cx="18" cy="18" r="4.6"/>'),
    "marco": ("Marco", "#C9B46F", '<path d="M9 33V4"/><path d="M9 5h19l-4.5 6.5L28 18H9"/>'),
    "metodo": ("Método", "#B4AA82", '<path d="M6 9h4M14 9h16M6 18h4M14 18h16M6 27h4M14 27h16"/>'),
    "feriado": ("Feriado", "#E0C58F", '<path d="M18 3.5l4.3 9.4 10.2 1.1-7.6 6.9 2.2 10.1L18 25.7 8.9 31l2.2-10.1L3.5 14l10.2-1.1z"/>'),
}


ICONES_EXTRA = {  # ícones (traço 1.8) para categorias de outras marcas; as da InnConta ficam em CATEGORIAS
    "ponto": '<circle cx="18" cy="18" r="14"/><path d="M11 18.5l5 5 9-10.5"/>',
    "territorio": '<path d="M3.5 28l9-14 6 8 4-5 9.5 11z"/><circle cx="26" cy="9" r="2.6"/>',
    "numero": '<path d="M11 6l-2 24M23 6l-2 24M5 13h26M4 23h26"/>',
    "cena": '<rect x="4" y="7" width="28" height="22" rx="2"/><path d="M4 22l8-7 6 5 5-4 9 7"/>',
}


def _cat(marca, categoria):
    """(nome no selo, cor de acento, ícone) da categoria. Marca com `categorias` em marca.json usa as próprias."""
    cats = tema(marca)["categorias"]
    if cats:
        c = cats[categoria]
        ic = c.get("icone", "ponto")
        return (c["nome"], c.get("cor") or tema(marca)["destaque"], (CATEGORIAS[ic][2] if ic in CATEGORIAS else ICONES_EXTRA[ic]))
    return CATEGORIAS[categoria]


def _selo(marca, spec):
    nome, cor, icone = _cat(marca, spec["categoria"])
    frente = spec.get("frente_rotulo")
    rotulo = nome + (" <span>·</span> " + frente if frente else "")
    return ('<div class="sel"><svg viewBox="0 0 36 36" fill="none" stroke="%s" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
            '<div class="k" style="color:%s">%s</div></div>' % (cor, icone, cor, rotulo))


def _fundo(marca, spec):
    cor = _cat(marca, spec["categoria"])[1]
    if not spec.get("foto"):  # marca sem foto com crédito conferido: fundo sólido, sem véu de foto
        return '<div class="faixa" style="background:%s"></div>' % cor
    foto = os.path.join(RAIZ_REDES, "kit", marca, "fotos", spec["foto"] + ".jpg")
    return ('<div class="foto" style="background-image:url(file:///%s)"></div><div class="veil"></div><div class="faixa" style="background:%s"></div>'
            % (foto.replace("\\", "/"), cor))


def _ilustracao(marca, nome):
    p = _caminho_svg(marca, nome)
    with open(p, encoding="utf-8") as fh:
        svg = fh.read()
    # o CSS controla o tamanho; preserva a proporção do viewBox
    svg = re.sub(r'\swidth="\d+"', "", svg, count=1)
    svg = re.sub(r'\sheight="\d+"', "", svg, count=1)
    if (marca, nome) in BBOX:  # recorte justo no conteúdo: o desenho ocupa o quadro, não fica pequeno no meio do viewBox
        x, y, w, h = BBOX[(marca, nome)]
        svg = re.sub(r'viewBox="[^"]+"', 'viewBox="%.1f %.1f %.1f %.1f"' % (x, y, w, h), svg, count=1)
    estilo = ' style="width:66%;height:66%"' if nome == SIMBOLO else ""  # símbolo da marca como herói: menor que uma ilustração de quadro cheio
    return svg.replace("<svg ", '<svg preserveAspectRatio="xMidYMid meet"' + estilo + " ", 1)


BBOX = {}
SIMBOLO = "@simbolo"  # sem ilustração autoral, o herói é o símbolo da marca (kit/<marca>/logo.svg)


def _caminho_svg(marca, nome):
    if nome == SIMBOLO:
        return os.path.join(RAIZ_REDES, "kit", marca, "logo.svg")
    return os.path.join(RAIZ_REDES, "kit", marca, "ilustracoes", nome + ".svg")


def _ilu_nome(spec):
    return spec.get("ilustracao") or SIMBOLO


def _medir_bbox(browser, marca, nome, folga=18):
    """Caixa de conteúdo do SVG (getBBox) + folga, para recortar o viewBox. Cache por processo."""
    p = _caminho_svg(marca, nome)
    with open(p, encoding="utf-8") as fh:
        svg = fh.read()
    page = browser.new_page(viewport={"width": 900, "height": 640})
    page.set_content("<html><body style='margin:0'>%s</body></html>" % svg)
    b = page.evaluate("() => { const b = document.querySelector('svg').getBBox(); return [b.x, b.y, b.width, b.height]; }")
    page.close()
    x, y, w, h = b
    BBOX[(marca, nome)] = (x - folga, y - folga, w + 2 * folga, h + 2 * folga)


def _lockup(marca):
    L = tema(marca)["lockup"]
    partes = [p["texto"] for p in L.get("partes", [])]
    if len(partes) >= 2 and not L.get("linha"):  # padrão da InnConta: duas linhas, a segunda no acento
        return '<div class="lk"><i>%s</i><u>%s</u></div>' % (partes[0], partes[1])
    linha = L.get("linha") or (partes[0] if partes else tema(marca)["nome"].upper())
    return ('<div class="lk" style="font-size:36px;letter-spacing:.30em;line-height:1"><i style="font-weight:500">%s</i></div>' % linha)


def _rodape(marca, spec):
    T = tema(marca)
    url = spec.get("url")
    linhas = [x for x in (url, T["handle"] if T["mostrar_handle"] else "") if x]
    return ('<div class="foot">' + _lockup(marca)
            + ('<div class="url">%s</div>' % "<br>".join(linhas) if linhas else "") + "</div>")


def _fonte(txt, rotulo="Fonte"):
    return '<div class="f"><b>%s</b>%s</div>' % (rotulo, txt) if txt else ""


def _card(spec, fmt):
    c = spec.get("card") or {}
    if not c:
        return ""
    fonte = _fonte(spec.get("fonte"))
    if c.get("tipo") == "numero":
        tam = 132 if fmt == "feed" else 150
        un = ("<small>%s</small>" % c["unidade"]) if c.get("unidade") else ""
        return ('<div class="card"><div class="cl">%s</div><div class="num"><div class="v" style="font-size:%dpx">%s%s</div>'
                '<div class="nt">%s</div></div>%s</div>'
                % (c.get("rotulo", "O que a norma diz"), tam, c["valor"], un, c.get("texto", ""), fonte))
    tam = 54 if fmt == "feed" else 62
    return ('<div class="card"><div class="cl">%s</div><div class="tx" style="font-size:%dpx">%s</div>%s</div>'
            % (c.get("rotulo", "O que observar"), tam, c.get("texto", ""), fonte))


def _pagina(marca, F, corpo, spec=None):
    css = CSS.replace("GRAO", GRAO)
    return _tematizar("<!doctype html><html><head><meta charset='utf-8'><style>%s%s</style></head><body>"
            "<div class='p %s' style='width:%dpx;height:%dpx;padding:%dpx %dpx %dpx'>%s</div></body></html>"
            % (_font_css(marca), css, ("s-st" if F["h"] > 1400 else ""), F["w"], F["h"], F["pt"], F["m"], F["pb"], (_fundo(marca, spec) if spec else "") + corpo), marca)


def html_peca(marca, spec, fmt):
    F = FORMATOS[fmt]
    modelo = spec["modelo"]
    top = '<div class="top">%s<div class="dt">%s</div></div>' % (_selo(marca, spec), spec.get("data_rotulo", ""))
    if modelo == "feriado":
        gr = 168 if fmt == "feed" else 200
        qs = 50 if fmt == "feed" else 60
        corpo = (top + '<div class="mid"><div class="g" style="font-size:%dpx">%s</div><div class="fio" style="width:180px"></div>'
                 '<div class="q" style="font-size:%dpx">%s</div><div class="f" style="border:0;padding:0;margin:0">%s</div></div>'
                 '<div class="f" style="border:0;padding:0;margin:0 0 6px;letter-spacing:.03em">%s</div>%s'
                 % (gr, spec["grande"], qs, spec["citacao"], spec.get("fonte", ""), spec.get("nota_legal", ""), _rodape(marca, spec)))
        if spec.get("ilustracao"):
            corpo = corpo.replace('<div class="mid">', '<div class="ilu" style="flex:0 0 %dpx!important;margin:8px 0 0">%s</div><div class="mid">'
                                  % (320 if fmt == "feed" else 460, _ilustracao(marca, spec["ilustracao"])), 1)
    else:
        corpo = (top + '<div class="ilu">%s</div><div class="t" style="font-size:%dpx">%s</div>%s%s'
                 % (_ilustracao(marca, _ilu_nome(spec)), F["titulo"] + (16 if not spec.get("card") else 0), spec["titulo"], _card(spec, fmt), _rodape(marca, spec)))
    return unicodedata.normalize("NFC", _pagina(marca, F, corpo, spec))


MEDE = """() => {
 const p = document.querySelector('.p').getBoundingClientRect();
 const tudo = [...document.querySelectorAll('.p > *:not(.foto):not(.veil):not(.faixa)')].map(e => e.getBoundingClientRect());
 const ilu = document.querySelector('.ilu'); const t = document.querySelector('.t');
 const foot = document.querySelector('.foot').getBoundingClientRect();
 const cont = document.querySelector('.p');
 return {ilu_h: ilu ? ilu.getBoundingClientRect().height : null,
   estoura_y: foot.bottom > p.bottom - parseFloat(getComputedStyle(cont).paddingBottom) + 1,
   estoura_x: tudo.some(b => b.right > p.right + .5 || b.left < p.left - .5),
   foot_bottom: foot.bottom, p_bottom: p.bottom,
   t_h: t ? t.getBoundingClientRect().height : null};
}"""


def _enxugar(caminho):
    """Reduz o PNG (o degradê de fundo pesa ~2 MB): 256 cores com difusão, regravado em RGB (o Instagram
    não recebe PNG paletado). Não altera dimensões nem o texto; é só o peso do arquivo no repositório."""
    from PIL import Image
    im = Image.open(caminho).convert("RGB")
    q = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q.convert("RGB").save(caminho, "PNG", optimize=True)


def _renderizar(browser, html, F, saida, fmt, ajustavel=True):
    """Renderiza; se a ilustração ficar menor que o mínimo, encolhe o título em passos de 3 px (até 44)
    e o cartão em seguida — medido no navegador, nunca estimado. Devolve o dicionário de medidas."""
    tmp = saida[:-4] + ".render.html"
    tam = F["titulo"]
    med = None
    for tentativa in range(9):
        h = html
        if tentativa:
            h = h.replace('class="t" style="font-size:%dpx"' % F["titulo"], 'class="t" style="font-size:%dpx"' % tam)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(h)
        page = browser.new_page(viewport={"width": F["w"], "height": F["h"]})
        page.goto("file:///" + os.path.abspath(tmp).replace("\\", "/"))
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(200)
        med = page.evaluate(MEDE)
        ok = (not ajustavel) or med["ilu_h"] is None or med["ilu_h"] >= F["ilu_min"]
        if ok or tam <= 46:
            page.screenshot(path=saida, clip={"x": 0, "y": 0, "width": F["w"], "height": F["h"]})
            page.close()
            _enxugar(saida)
            break
        page.close()
        tam -= 3
    os.remove(tmp)
    med["titulo_px"] = tam
    med["ok"] = (not med["estoura_y"]) and (not med["estoura_x"]) and (med["ilu_h"] is None or med["ilu_h"] >= F["ilu_min"] * 0.9)
    return med


# ------------------------------------------------------------------------------- carrossel (3 lâminas)
def html_lamina(marca, spec, i, fmt="feed"):
    """Lâmina i de um carrossel de N (3 na InnConta): capa (pergunta + ilustração), regra (número em destaque + fonte),
    acao (o que observar — sem promessa sem sustentação) e fecho (chamada para salvar/compartilhar + link)."""
    F = FORMATOS[fmt]
    lam = spec["laminas"][i]
    n = len(spec["laminas"])
    pts = '<div class="dots">%s</div>' % "".join('<i class="%s"></i>' % ("on" if j == i else "") for j in range(n))
    top = '<div class="top">%s<div class="dt">%d / %d</div></div>' % (_selo(marca, spec), i + 1, n)
    if lam["tipo"] == "capa":
        corpo = (top + '<div class="ilu">%s</div><div class="t" style="font-size:%dpx;margin-bottom:8px">%s</div>'
                 '<div class="dt" style="text-align:left;margin:6px 0 0;color:#C29C57">%s &rarr;</div>%s'
                 % (_ilustracao(marca, _ilu_nome(spec)), F["titulo"] + 6, spec["titulo"], lam.get("deslize", "Deslize para a regra"), _rodape(marca, spec)))
    elif lam["tipo"] == "regra":
        un = ("<small>%s</small>" % lam["unidade"]) if lam.get("unidade") else ""
        corpo = (top + '<div class="mid"><div class="cl" style="margin:0">%s</div><div class="big" style="font-size:%dpx">%s%s</div>'
                 '<div class="fio" style="width:180px"></div><div class="nt" style="border:0;padding:0;font-size:40px;line-height:1.3">%s</div></div>%s%s'
                 % (lam.get("rotulo", "O que a norma diz"), 300 if fmt == "feed" else 330, lam["valor"], un, lam["texto"],
                    _fonte(spec.get("fonte")), _rodape(marca, spec)))
    elif lam["tipo"] == "fecho":
        corpo = (top + '<div class="mid"><div class="cl" style="margin:0">%s</div><div class="tx" style="font-size:%dpx">%s</div>'
                 '<div class="fio" style="width:180px"></div><div class="nt" style="border:0;padding:0;font-size:38px;line-height:1.3">%s</div></div>%s%s'
                 % (lam.get("rotulo", "Guarde para consultar"), 64 if fmt == "feed" else 72, lam["texto"], lam.get("nota", ""), pts, _rodape(marca, spec)))
    else:
        corpo = (top + '<div class="mid"><div class="cl" style="margin:0">%s</div><div class="tx" style="font-size:%dpx">%s</div></div>%s%s'
                 % (lam.get("rotulo", "O que observar"), 58 if fmt == "feed" else 66, lam["texto"], pts, _rodape(marca, spec)))
    return unicodedata.normalize("NFC", _pagina(marca, F, corpo, spec))


# ------------------------------------------------------------------------------- guarda do texto da arte
def texto_da_arte(spec, marca="innconta"):
    """Texto que aparece na arte, em ordem de leitura (vai ao frontmatter `texto_arte` e à guarda)."""
    c = spec.get("card") or {}
    nome = _cat(marca, spec["categoria"])[0]
    partes = [nome + (" · " + spec["frente_rotulo"] if spec.get("frente_rotulo") else ""), spec.get("titulo", "")]
    if c.get("tipo") == "numero":
        partes.append("%s: %s %s, %s" % (c.get("rotulo", ""), c.get("valor", ""), c.get("unidade", ""), c.get("texto", "")))
    elif c:
        partes.append("%s: %s" % (c.get("rotulo", ""), c.get("texto", "")))
    partes += ["Fonte: " + spec["fonte"] if spec.get("fonte") else "", spec.get("grande", ""), spec.get("citacao", ""), spec.get("nota_legal", "")]
    for lam in spec.get("laminas") or []:
        partes.append(" ".join(x for x in (lam.get("rotulo", ""), lam.get("valor", ""), lam.get("unidade", ""), lam.get("texto", "")) if x))
    t = re.sub(r"<[^>]+>", "", " / ".join(x for x in partes if x))
    return re.sub(r"\s+([,.:])", r"\1", re.sub(r"\s+", " ", t)).replace(" ,", ",")


def rodar(marca="innconta", filtro=None, formatos=("feed", "stories"), so_guarda=False, slugs=None):
    """`filtro` = substring do slug (uso manual); `slugs` = conjunto EXATO (render sob demanda: "-1" não pega "-10")."""
    import guarda
    base = os.path.join(RAIZ_REDES, "estoque", marca)
    with open(os.path.join(base, "_arte", "pecas-v2.json"), encoding="utf-8") as fh:
        pecas = json.load(fh)
    saida_dir = os.path.join(base, "_gerados")
    relatorio, barradas = [], []
    for slug, spec in pecas.items():
        if slug.startswith("_") or (filtro and filtro not in slug) or (slugs is not None and slug not in slugs):
            continue
        ok, motivos = guarda.checar(texto_da_arte(spec, marca), marca_nome=tema(marca)["nome"])
        if not ok:
            barradas.append((slug, motivos))
            print("BARRADA pela guarda:", slug, motivos)
    if barradas:
        raise SystemExit("guarda barrou %d peça(s); nada foi renderizado" % len(barradas))
    if so_guarda:
        return []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for spec in pecas.values():
                if (marca, _ilu_nome(spec)) not in BBOX and spec["modelo"] != "feriado":
                    _medir_bbox(browser, marca, _ilu_nome(spec))
                elif spec.get("ilustracao") and (marca, spec["ilustracao"]) not in BBOX:
                    _medir_bbox(browser, marca, spec["ilustracao"])
            for slug, spec in pecas.items():
                if slug.startswith("_") or (filtro and filtro not in slug) or (slugs is not None and slug not in slugs):
                    continue
                os.makedirs(saida_dir, exist_ok=True)
                if spec["modelo"] == "carrossel":
                    pasta = os.path.join(saida_dir, slug + "-instagram")
                    os.makedirs(pasta, exist_ok=True)
                    for i in range(len(spec["laminas"])):
                        html = html_lamina(marca, spec, i, "feed")
                        med = _renderizar(browser, html, FORMATOS["feed"], os.path.join(pasta, "quadro-%02d.png" % (i + 1)), "feed", ajustavel=(i == 0))
                        relatorio.append((slug + "#%d" % (i + 1), "feed", med))
                        print(("ok  " if med["ok"] else "AJUSTAR "), slug, "quadro", i + 1, {k: med[k] for k in ("ilu_h", "titulo_px", "estoura_y", "estoura_x")})
                for fmt in ([] if spec.get("so_quadros") else formatos):
                    html = html_peca(marca, spec, fmt)
                    med = _renderizar(browser, html, FORMATOS[fmt], os.path.join(saida_dir, "%s-instagram-%s.png" % (slug, fmt)), fmt)
                    relatorio.append((slug, fmt, med))
                    print(("ok  " if med["ok"] else "AJUSTAR "), slug, fmt, {k: med[k] for k in ("ilu_h", "titulo_px", "estoura_y", "estoura_x")})
        finally:
            browser.close()
    return relatorio


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default="innconta")
    ap.add_argument("--filtro")
    ap.add_argument("--formatos", default="feed,stories")
    ap.add_argument("--so-guarda", action="store_true")
    a = ap.parse_args()
    rodar(a.marca, a.filtro, tuple(a.formatos.split(",")), a.so_guarda)
