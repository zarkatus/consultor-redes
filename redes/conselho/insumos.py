# -*- coding: utf-8 -*-
"""Insumos dos revisores: texto AO VIVO da nota/página de origem em innconta.com.br e as imagens
preparadas para o revisor visual (PNG renderizado + cópia a 390 px de largura, a tela de celular).

Página de origem: baixada na hora (nunca de cache do repo) — o revisor FATO E FONTE compara a peça
com o que está publicado HOJE. Só URLs de innconta.com.br são aceitas (lista de permissão, PAR-01a);
qualquer outra é ignorada. Falha de rede = texto vazio + aviso — e o revisor, sem fonte, reprova
qualquer número (falha fechada), nunca aprova no escuro."""
import base64
import html
import io
import re
import urllib.request

DOMINIO_ORIGEM = "innconta.com.br"  # padrao legado; cada marca traz os seus em regras.json (dominios_origem)
LIMITE_CHARS_ORIGEM = 9000  # ~2,5 mil tokens por pagina — orcamento de neuronios (modelos.py)
LIMITE_CHARS_FONTE = 6000   # fontes oficiais extras (baixadas ao vivo): menores, sao varias
MAX_FONTES_AO_VIVO = 4
_CACHE = {}


def _host_ok(url, dominios):
    m = re.match(r"^(?:https?://)?([^/:?#]+)", str(url or "").strip().lower())
    if not m:
        return False
    h = m.group(1)
    return any(h == d or h.endswith("." + d) for d in dominios)


def urls_de_origem(texto, dominios=None):
    """Extrai 'dominio/nota/...' ou '/frente/...' de um campo livre (nota_origem) para os dominios da marca."""
    dominios = list(dominios or [DOMINIO_ORIGEM])
    achadas = []
    for d in dominios:
        achadas += re.findall(r"(?:https?://)?(?:www\.)?" + re.escape(d) + r"/[A-Za-z0-9/_\-]+", texto or "")
        # home da marca ("https://marca/", como o gerador semeia): sem isso a pagina nunca era baixada e o numero da arte
        # que esta no site virava "sem fonte" -> escalada eterna (30/09/2026, 8 de 70 pecas das marcas novas)
        achadas += [m.group(0) for m in re.finditer(r"(?:https?://)?(?:www\.)?" + re.escape(d) + r"/?(?=$|[\s)\],;])", texto or "")]
    # caminho sem dominio ("+ nota/demanda-contratada") tambem e do 1o dominio da marca
    for c in re.findall(r"(?<![\w./])((?:nota|frente)/[a-z0-9\-]+)", texto or ""):
        achadas.append(dominios[0] + "/" + c)
    out = []
    for a in achadas:
        u = a if a.startswith("http") else "https://" + a
        u = u.replace("://www.", "://").rstrip("/")
        if u not in out:
            out.append(u)
    return out


def texto_da_pagina(url, timeout=30, dominios=None, limite=None, inteiro=False):
    """Baixa AO VIVO o texto da pagina. Lista de permissao (PAR-01a): so dominios da marca (ou o padrao legado).
    Padrao (vai ao prompt dos revisores): so `<main>`/`<article>`, cortado em `limite`. `inteiro=True` (checagem de fato
    deterministica, sem modelo, 30/09/2026): o corpo todo, sem corte — numero do site fora do `<main>` ou alem do corte
    virava "sem fonte" e escalava a peca para sempre. O cache guarda o HTML bruto (um download por URL, os dois modos)."""
    if not _host_ok(url, list(dominios or [DOMINIO_ORIGEM])):
        return ""
    if url not in _CACHE:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"})
            _CACHE[url] = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
        except Exception as e:
            print("origem indisponivel (%s): %s" % (url, e))
            _CACHE[url] = ""
    bruto = _CACHE[url]
    if not bruto:
        return ""
    m = None if inteiro else (re.search(r"<main.*?</main>", bruto, re.S) or re.search(r"<article.*?</article>", bruto, re.S))
    s = m.group(0) if m else bruto
    # retrorreferencia `</\1>`: no repo estava o BYTE 0x01 no lugar de `\1` (ferramenta de edicao converteu) e NADA era
    # removido — CSS/JS ocupavam o corte de 9 mil caracteres e numero de codigo servia de "fonte" (30/09/2026)
    s = re.sub(r"<(script|style|nav|footer|header|svg|noscript)\b[^>]*>.*?</\1\s*>", " ", s, flags=re.S | re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"\s+", " ", s).strip()
    return s if inteiro else s[:limite or LIMITE_CHARS_ORIGEM]


def texto_das_fontes(fontes, dominios, ja_baixadas=()):
    """Texto AO VIVO das `fontes[].url` cujo dominio esta na lista permitida da marca (proprio + oficiais extras).
    Devolve [(url, texto)] — ate MAX_FONTES_AO_VIVO, sem repetir o que a pagina de origem ja trouxe."""
    out = []
    for f in fontes or []:
        u = ((f or {}).get("url") or "").strip()
        if not u or u in ja_baixadas or not _host_ok(u, dominios):
            continue
        if u not in [x[0] for x in out]:
            out.append((u, texto_da_pagina(u, dominios=dominios, limite=LIMITE_CHARS_FONTE)))
        if len(out) >= MAX_FONTES_AO_VIVO:
            break
    return out


def checar_imagem(caminho, formato="imagem", peso_max=8 * 1024 * 1024):
    """Checagem DETERMINISTICA da imagem (v2): abre, peso <= 8 MB (limite do Instagram), proporcao aceita — feed e
    carrossel de 4:5 (0,8) a 1,91:1; stories/reels/video 9:16 (0,5 a 0,6) — e largura minima de 320 px.
    Devolve lista de motivos (vazia = ok)."""
    import os
    from PIL import Image
    try:
        peso = os.path.getsize(caminho)
        with Image.open(caminho) as im:
            im.load()
            w, h = im.size
    except Exception as e:
        return ["imagem nao abre (%s): %s" % (os.path.basename(str(caminho)), str(e)[:80])]
    motivos = []
    if peso > peso_max:
        motivos.append("imagem pesa %.1f MB (maximo 8 MB do Instagram)" % (peso / 1048576))
    if w < 320:
        motivos.append("imagem com %d px de largura (minimo 320)" % w)
    razao = w / float(h)
    if formato in ("stories", "video", "reels"):
        if not 0.5 <= razao <= 0.6:
            motivos.append("proporcao %.2f fora do 9:16 (0,50 a 0,60) exigido para stories/reels" % razao)
    elif not 0.8 <= razao <= 1.91:
        motivos.append("proporcao %dx%d (%.2f) fora do que o Instagram aceita no feed (4:5 a 1,91:1)" % (w, h, razao))
    return motivos


def quadros_do_video(caminho_mp4, n=4, pasta=None):
    """Extrai n quadros espaçados do vídeo (ffmpeg) para o revisor visual conferir o vídeo como
    arte — mesmo caminho para peça de prova e peça real. Devolve lista de PNGs (vazia se falhar)."""
    import json as _json
    import os
    import subprocess
    import tempfile

    pasta = pasta or tempfile.mkdtemp(prefix="conselho-quadros-")
    try:
        info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                               caminho_mp4], capture_output=True, text=True, timeout=60)
        dur = float(_json.loads(info.stdout)["format"]["duration"])
    except Exception as e:
        print("ffprobe falhou (%s): %s" % (caminho_mp4, e))
        return []
    saida = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        png = os.path.join(pasta, "%s-q%02d.png" % (os.path.basename(caminho_mp4), i))
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % t, "-i", caminho_mp4,
                            "-frames:v", "1", png], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(png):
            saida.append(png)
    return saida


def _png_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _mosaico(imgs, largura_tile, colunas):
    from PIL import Image
    miniaturas = [im.resize((largura_tile, max(1, int(im.height * largura_tile / im.width)))) for im in imgs]
    linhas = [miniaturas[i:i + colunas] for i in range(0, len(miniaturas), colunas)]
    base = Image.new("RGB", (largura_tile * min(colunas, len(imgs)), sum(max(m.height for m in ln) for ln in linhas)),
                     (255, 255, 255))
    y = 0
    for ln in linhas:
        for j, m in enumerate(ln):
            base.paste(m, (j * largura_tile, y))
        y += max(m.height for m in ln)
    return base


def imagens_para_revisor(caminhos, largura_celular=390, largura_max=1080):
    """Devolve [data_url_renderizado, data_url_390px]. Várias imagens (carrossel, feed+stories,
    quadros de vídeo) viram mosaico — e na cópia "390 px" CADA imagem do mosaico tem 390 px de
    largura (a tela do celular mostra uma imagem por vez). Achado na prova de 24/09/2026: a 1ª versão
    reduzia o MOSAICO inteiro a 390 px, cada quadro caía para ~195 px e o revisor visual reprovava
    vídeo bom por "texto pequeno demais" — falso negativo do insumo, não da arte.
    Lista vazia se não houver imagem legível (o revisor visual reprova peça visual sem arte)."""
    from PIL import Image

    imgs = []
    for c in caminhos or []:
        try:
            imgs.append(Image.open(c).convert("RGB"))
        except Exception as e:
            print("imagem ilegível para o revisor visual (%s): %s" % (c, e))
    if not imgs:
        return []
    colunas = 1 if len(imgs) == 1 else (2 if len(imgs) <= 4 else 3)
    base = _mosaico(imgs, largura_max // colunas, colunas)
    celular = _mosaico(imgs, largura_celular, colunas)
    return [_png_b64(base), _png_b64(celular)]
