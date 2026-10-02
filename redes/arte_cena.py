# -*- coding: utf-8 -*-
"""Arte "Cena" das redes da InnConta: carrossel narrativo de foto cheia (uma ideia por quadro).

Referência de forma (CVO, 26/09/2026): carrossel de 10 quadros com foto cinematográfica, frase única em
serifa grande com o fecho em cor de acento, caixa-soco, numeração "n/N" e seta de deslizar. Aqui a paleta é a
da InnConta (preto quente, creme, dourado) e as fotos são as do kit (`redes/kit/<marca>/fotos`, com crédito
na Privacidade). O texto vem da especificação da peça (já aprovado pelo Conselho), nada é inventado aqui.

Uso:  python redes/arte_cena.py <arquivo.json> [--saida pasta] [--marca innconta|inncorporate]
Especificação: {"handle": "@innconta.oficial", "quadros": [ {tema: "escuro"|"claro", foto: "energia",
  titulo: "HTML com <em>", texto: "...", caixa: "...", itens: ["..."], numero: {"valor":"60","unidade":"meses"},
  fonte: "Lei nº 14.300/2022, art. 13", url: "innconta.com.br/frente/energia"} ]}
Rodar de um caminho SEM acento (ex.: `subst R:`): com acento o Chromium não acha foto nem fonte e ainda renderiza.
"""
import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
W, H = 1080, 1350

# paleta por marca: lida de kit/<marca>/marca.json; o que faltar cai no padrao da InnConta
PADRAO = {"fundo": "#14110D", "texto": "#F1EADB", "titulo": "#F6F0E2", "papel": "#F4EDDF", "tinta": "#1B1712",
          "destaque": "#C29C57", "ouro_claro": "#E3BD6C", "ouro_prof": "#9A7428", "caixa_a": "#EBCB8B", "claro_ini": "50%", "claro_veu": ".72"}


def _hex_rgb(h):
    h = h.lstrip("#")
    return "%d,%d,%d" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def paleta(marca):
    p = dict(PADRAO)
    try:
        m = json.load(open(os.path.join(RAIZ, "kit", marca, "marca.json"), encoding="utf-8"))
        p.update(m.get("arte", {}))
    except (OSError, ValueError):
        pass
    p["fundo_rgb"] = _hex_rgb(p["fundo"])
    p["destaque_rgb"] = _hex_rgb(p["destaque"])
    return p


def css(marca):
    p = paleta(marca)
    out = CSS
    for k in ("fundo_rgb", "destaque_rgb", "titulo", "texto", "papel", "tinta", "ouro_claro", "ouro_prof", "caixa_a", "claro_ini", "claro_veu", "fundo", "destaque"):
        out = out.replace("@%s@" % k, p[k])
    return out


def _tema_fontes(marca):
    """Fontes declaradas em marca.json (arte_v2.fontes) valem também na cena; sem elas, Cormorant + Jost do kit."""
    try:
        import arte_v2
        return arte_v2.tema(marca)
    except Exception:  # noqa: BLE001 - a cena nunca cai por causa do tema; volta ao padrão
        return None


def handle_da_marca(marca):
    """@ do Instagram da marca: kit/<marca>/regras.json (handle_instagram) > marca.json (arte_v2.handle) > padrão legado da InnConta."""
    try:
        r = json.load(open(os.path.join(RAIZ, "kit", marca, "regras.json"), encoding="utf-8"))
        if r.get("handle_instagram"):
            return r["handle_instagram"]
        dominio = (r.get("dominios_origem") or [""])[0]  # sem @ conhecido: o domínio, nunca o @ de outra marca
    except (OSError, ValueError):
        dominio = ""
    t = _tema_fontes(marca)
    if t and t.get("handle"):
        return t["handle"]
    return dominio or "@innconta.oficial"  # padrão legado (só a InnConta chega aqui sem regras.json)


def _fontes(marca):
    t = _tema_fontes(marca)
    if t and t.get("fontes"):
        import arte_v2
        return arte_v2._font_css(marca)
    import kit_comum
    f = lambda n: "file:///" + kit_comum.arquivo(marca, "fonts-estaticas", n).replace("\\", "/")
    faces = [("Cormorant Garamond", "normal", 500, "Cormorant-normal-500.ttf"),
             ("Cormorant Garamond", "normal", 600, "Cormorant-normal-600.ttf"),
             ("Cormorant Garamond", "italic", 500, "Cormorant-italic-500.ttf"),
             ("Cormorant Garamond", "normal", 400, "Cormorant-normal-400.ttf"),
             ("Jost", "normal", 400, "Jost-normal-400.ttf"), ("Jost", "normal", 500, "Jost-normal-500.ttf"),
             ("Jost", "normal", 600, "Jost-normal-600.ttf")]
    return "".join("@font-face{font-family:'%s';font-style:%s;font-weight:%d;src:url(%s) format('truetype')}"
                   % (a, s, w, f(n)) for a, s, w, n in faces)


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1350px;overflow:hidden;font-family:'Jost',sans-serif}
.q{position:relative;width:1080px;height:1350px;overflow:hidden}
.foto{position:absolute;inset:0;background-size:cover;background-position:center}
.q.escuro{background:@fundo@;color:@texto@}
.q.claro{background:@papel@;color:@tinta@}
.q.escuro .foto:after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(@fundo_rgb@,.86) 0%,rgba(@fundo_rgb@,.55) 40%,rgba(@fundo_rgb@,.42) 62%,rgba(@fundo_rgb@,.92) 100%)}
.q.claro .foto{top:46%;-webkit-mask-image:linear-gradient(180deg,transparent 0,#000 34%)}
.q.claro .foto:after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(@fundo_rgb@,0) @claro_ini@,rgba(@fundo_rgb@,@claro_veu@) 100%)}
.in{position:absolute;inset:0;padding:78px 84px 84px;display:flex;flex-direction:column}
.topo{display:flex;justify-content:space-between;align-items:center;font-size:27px;letter-spacing:.14em}
.topo b{display:block;width:70px;height:3px;background:@destaque@}
.topo span{font-weight:500;opacity:.85}
.t{font-family:'Cormorant Garamond',serif;font-weight:600;line-height:.98;letter-spacing:-.012em;margin-top:44px}
.q.escuro .t{color:@titulo@}
.t em{font-style:normal;color:@destaque@}
.q.escuro .t em{color:@ouro_claro@}
.q.claro .t em{color:@ouro_prof@}
.tx{font-family:'Cormorant Garamond',serif;font-weight:500;font-size:54px;line-height:1.14;margin-top:34px;max-width:860px}
.cx{margin-top:34px;max-width:860px;padding:28px 36px;border-radius:24px;background:linear-gradient(135deg,@caixa_a@,@destaque@);color:@tinta@;font-family:'Cormorant Garamond',serif;font-weight:600;font-size:52px;line-height:1.1}
.q.escuro .cx{background:rgba(@destaque_rgb@,.94)}
.itens{margin-top:38px;display:flex;flex-direction:column;gap:24px;max-width:900px}
.itens div{display:flex;align-items:center;gap:22px;font-size:44px;font-weight:500}
.itens i{flex:none;width:52px;height:52px;border-radius:50%;background:@destaque@;color:@fundo@;display:flex;align-items:center;justify-content:center;font-style:normal;font-weight:600;font-size:30px}
.num{display:flex;align-items:baseline;gap:18px;margin-top:20px;font-family:'Cormorant Garamond',serif;font-weight:600;color:@destaque@;line-height:.8}
.num b{font-size:300px;letter-spacing:-.03em}
.num small{font-size:110px;font-weight:500}
.mola{flex:1}
.q.claro .rod{color:@titulo@;text-shadow:0 1px 8px rgba(0,0,0,.55)}
.rod{display:flex;justify-content:space-between;align-items:flex-end;font-size:27px;letter-spacing:.16em;text-transform:uppercase}
.rod .f{font-size:30px;letter-spacing:.02em;text-transform:none;opacity:.9;line-height:1.3}
.rod .f b{letter-spacing:.14em;text-transform:uppercase;font-weight:600;margin-right:12px;font-size:26px}
.rod .u{letter-spacing:.02em;text-transform:none;font-size:32px}
.seta{font-size:64px;line-height:1;color:@destaque@;letter-spacing:0}
.lock{font-family:'Cormorant Garamond',serif;font-size:46px;line-height:.86;text-transform:none;letter-spacing:0}
.lock i{display:block;font-style:normal;font-weight:600}.lock u{display:block;text-decoration:none;color:@destaque@;font-weight:500}
"""


def lockup(marca):
    """Assinatura do rodape: duas linhas (Inn/Conta) ou uma palavra-marca em caixa alta espacada (marca.json: lockup.linha)."""
    try:
        m = json.load(open(os.path.join(RAIZ, "kit", marca, "marca.json"), encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    linha = m.get("lockup", {}).get("linha")
    partes = [x["texto"] for x in m.get("lockup", {}).get("partes", [])]
    if len(partes) >= 2 and not linha:
        return '<div class="lock"><i>%s</i><u>%s</u></div>' % (partes[0], partes[1])
    if linha:
        return '<div class="lock" style="font-size:34px;letter-spacing:.30em;font-weight:500;line-height:1">%s</div>' % linha
    return '<div class="lock"><i>Inn</i><u>Conta</u></div>'


def _familias(html, marca):
    t = _tema_fontes(marca)
    if t and t.get("fontes"):
        html = html.replace("'Cormorant Garamond'", "'%s'" % t["fam_titulo"]).replace("'Jost'", "'%s'" % t["fam_corpo"])
    return html


def html_quadro(marca, spec, i, n, handle):
    q = spec
    tema = q.get("tema", "escuro")
    fdir = os.path.join(RAIZ, "kit", marca, "fotos", q["foto"] + ".jpg")
    foto = "file:///" + fdir.replace("\\", "/")
    partes = ['<div class="topo"><b></b><span>%d/%d</span></div>' % (i + 1, n)]
    tam = q.get("tam", 112)
    partes.append('<div class="t" style="font-size:%dpx;max-width:%dpx">%s</div>' % (tam, q.get("larg", 800), q["titulo"]))
    if q.get("numero"):
        partes.append('<div class="num"><b>%s</b><small>%s</small></div>' % (q["numero"]["valor"], q["numero"].get("unidade", "")))
    if q.get("texto"):
        partes.append('<div class="tx">%s</div>' % q["texto"])
    if q.get("itens"):
        partes.append('<div class="itens">%s</div>' % "".join("<div><i>&#10003;</i>%s</div>" % t for t in q["itens"]))
    if q.get("caixa"):
        partes.append('<div class="cx">%s</div>' % q["caixa"])
    partes.append('<div class="mola"></div>')
    if q.get("fonte") or q.get("url"):
        rod = ('<div class="rod">' + lockup(marca) + '<div style="text-align:right">'
               + ('<div class="f"><b>Fonte</b>%s</div>' % q["fonte"] if q.get("fonte") else "")
               + ('<div class="u">%s</div>' % q["url"] if q.get("url") else "") + "</div></div>")
    else:
        rod = '<div class="rod"><span>%s</span><span class="seta">&rarr;</span></div>' % handle
    partes.append(rod)
    return _familias('<!doctype html><html><head><meta charset="utf-8"><style>%s%s</style></head><body>'
            '<div class="q %s"><div class="foto" style="background-image:url(%s)"></div>%s<div class="in">%s</div></div></body></html>'
            % (_fontes(marca), css(marca), tema, foto, ('<div style="position:absolute;inset:0;background:rgba(%s,%s)"></div>' % (paleta(marca)["fundo_rgb"], q["veu"])) if q.get("veu") else "", "".join(partes)), marca)


def rodar(caminho, saida=None, marca="innconta"):
    from playwright.sync_api import sync_playwright
    spec = json.load(open(caminho, encoding="utf-8"))
    saida = saida or os.path.splitext(caminho)[0]
    os.makedirs(saida, exist_ok=True)
    qs = spec["quadros"]
    with sync_playwright() as p:
        b = p.chromium.launch()
        for i, q in enumerate(qs):
            tmp = os.path.join(saida, "_q.html")
            open(tmp, "w", encoding="utf-8").write(html_quadro(marca, q, i, len(qs), spec.get("handle", handle_da_marca(marca))))
            pg = b.new_page(viewport={"width": W, "height": H})
            pg.goto("file:///" + os.path.abspath(tmp).replace("\\", "/"))
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(250)
            estoura = pg.evaluate("(()=>{const r=document.querySelector('.in');return r.scrollHeight>r.clientHeight+2})()")
            pg.screenshot(path=os.path.join(saida, "quadro-%02d.jpg" % (i + 1)), type="jpeg", quality=84)
            pg.close()
            print("ok  quadro %02d%s" % (i + 1, "  ESTOURA" if estoura else ""))
        b.close()
    os.remove(tmp)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--saida")
    ap.add_argument("--marca", default="innconta")
    a = ap.parse_args()
    rodar(a.json, a.saida, a.marca)
