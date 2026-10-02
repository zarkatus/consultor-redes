# -*- coding: utf-8 -*-
"""Arte SOB DEMANDA (30/09/2026) — renderiza, na hora, a imagem de UMA peça estática de Instagram cujo PNG não está no
disco. Chamado por `lote_aprovacao` (antes da revisão visual do Conselho) e por `publicar` (antes de subir a mídia).

Por quê: o checkout do Actions é efêmero e os PNGs das marcas novas NÃO vão para o git (~300 MB/mês; decisão de
29/09, fio redes-consultor-multimarca-merge). A InnConta tem os PNGs commitados: nada falta, nada renderiza, nenhum
Playwright é instalado. A arte sai do spec commitado (`estoque/<marca>/_arte/pecas-v2.json`) + kit da marca + fontes
do repo: o render é determinístico, então o PNG que o Conselho aprovou na segunda é o mesmo que sai no dia de publicar.

Contrato: `garantir(marca, peca)` devolve a lista de caminhos declarados que CONTINUAM ausentes depois da tentativa
(vazia = pronto). Nunca levanta. Playwright + Chromium só são instalados quando falta PNG E o ambiente é o runner
(`GITHUB_ACTIONS=true`); fora dele, falta de Playwright vira motivo, sem instalar nada na máquina de ninguém."""
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(RAIZ)
SUFIXO = "-instagram"


def declarados(peca):
    """Caminhos (relativos ao repo) de imagem que a peça estática declara: `quadros` (carrossel) ou `imagem`.
    Vídeo, texto e peça sem imagem declarada = [] (nada a renderizar aqui; vídeo tem o render dele)."""
    formato = str(peca.get("formato") or "")
    if "video" in formato or str(peca.get("tipo") or "") == "video" or formato == "texto":
        return []
    quadros = peca.get("quadros")
    if isinstance(quadros, list) and quadros:
        return [str(q) for q in quadros]
    img = peca.get("imagem")
    if img and not str(img).startswith(("http", "_gerar")):
        return [str(img)]
    return []


def faltando(peca):
    return [r for r in declarados(peca) if not os.path.isfile(os.path.join(REPO, r))]


def _slug(peca):
    pid = str(peca.get("_peca_id") or "")
    return pid[:-len(SUFIXO)] if pid.endswith(SUFIXO) else pid


def _playwright_pronto(instalar):
    try:
        import playwright.sync_api  # noqa: F401
        return True, ""
    except ImportError:
        if not instalar:
            return False, "playwright ausente (fora do runner não instalo nada)"
    cmds = ([sys.executable, "-m", "pip", "install", "-q", "playwright"],
            [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"])
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode != 0:
            return False, "falhou: %s (%s)" % (" ".join(c[2:]), (r.stderr or r.stdout)[-200:].strip())
    import importlib
    importlib.invalidate_caches()
    return True, "instalado"


def garantir(marca, peca, renderizar=None, instalar=None):
    """Renderiza o que falta da peça. `renderizar(marca, slugs)` e `instalar` são injetáveis (teste por mock).
    Devolve os caminhos ainda ausentes (vazia = pronto)."""
    antes = faltando(peca)
    if not antes:
        return []
    slug = _slug(peca)
    if not slug:
        print("arte sob demanda: peça sem _peca_id, não renderiza")
        return antes
    if renderizar is None:
        if instalar is None:
            instalar = os.environ.get("GITHUB_ACTIONS") == "true"
        ok, nota = _playwright_pronto(instalar)
        if nota:
            print("arte sob demanda: playwright", nota)
        if not ok:
            return antes
        import arte_v2
        renderizar = lambda m, s: arte_v2.rodar(m, formatos=("feed",), slugs=s)  # noqa: E731
    print("arte sob demanda: %s/%s — %d arquivo(s) ausente(s), renderizando" % (marca, slug, len(antes)))
    depois = antes
    for tentativa in range(2):  # 2ª tentativa: o Chromium às vezes falha o 1º screenshot ("Unable to capture", 30/09)
        try:
            renderizar(marca, {slug})
        except (Exception, SystemExit) as e:  # arte_v2 usa SystemExit quando a guarda barra
            print("arte sob demanda: render falhou (%s, tentativa %d): %s: %s" % (slug, tentativa + 1, type(e).__name__, str(e)[:200]))
            if isinstance(e, SystemExit):
                break  # guarda barrou: repetir não muda nada
        depois = faltando(peca)
        if not depois:
            break
    if depois:
        print("arte sob demanda: ainda faltam %d de %d em %s: %s" % (len(depois), len(declarados(peca)), slug, depois[:3]))
    return depois


def _achar_marca(peca_id):
    base = os.path.join(RAIZ, "estoque")
    for m in sorted(os.listdir(base)):
        if os.path.isfile(os.path.join(base, m, peca_id + ".md")):
            return m
    return None


if __name__ == "__main__":
    # Operação/QA (tarefa `arte` do redes-consultor.yml): renderiza UMA peça sob demanda. Sai != 0 se o PNG não sair.
    import argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, RAIZ)
    sys.path.insert(0, os.path.join(RAIZ, "lib"))
    import estoque
    ap = argparse.ArgumentParser()
    ap.add_argument("--peca-id", required=True)
    ap.add_argument("--marca", default=None, help="sem isso, acha a marca pelo arquivo no estoque")
    a = ap.parse_args()
    marca = a.marca or _achar_marca(a.peca_id)
    if not marca:
        raise SystemExit("peça %s não existe em redes/estoque/*/" % a.peca_id)
    peca = estoque.ler(estoque.caminho(marca, a.peca_id))
    faltam = garantir(marca, peca)
    print("arte sob demanda [%s/%s]: %d declarado(s), %d ausente(s)" % (marca, a.peca_id, len(declarados(peca)), len(faltam)))
    sys.exit(1 if faltam else 0)