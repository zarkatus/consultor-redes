# -*- coding: utf-8 -*-
"""Leitura/escrita das peças do estoque: redes/estoque/<marca>/<AAAA-MM-DD>-<slug>.md
Frontmatter YAML + corpo em Markdown puro. Agnóstico de marca (PGA-01) — a marca é sempre um
campo do frontmatter e um segmento de pasta, nunca uma constante no código."""
import glob
import os

import yaml

RAIZ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "estoque")


def caminho(marca, peca_id):
    return os.path.join(RAIZ, marca, peca_id + ".md")


def listar(marca=None):
    padrao = os.path.join(RAIZ, marca or "*", "*.md")
    out = []
    for p in sorted(glob.glob(padrao)):
        out.append(ler(p))
    return out


def ler(caminho_arquivo):
    with open(caminho_arquivo, "r", encoding="utf-8") as f:
        txt = f.read()
    partes = txt.split("---\n")
    # formato: '---\n<yaml>\n---\n<corpo>'  → split produz ['', '<yaml>', '<corpo>']
    fm = yaml.safe_load(partes[1]) or {}
    corpo = "---\n".join(partes[2:]).strip()
    fm["_arquivo"] = caminho_arquivo
    fm["_peca_id"] = os.path.splitext(os.path.basename(caminho_arquivo))[0]
    fm["_corpo"] = corpo
    return fm


def escrever(marca, peca_id, frontmatter, corpo):
    d = os.path.join(RAIZ, marca)
    os.makedirs(d, exist_ok=True)
    fm = {k: v for k, v in frontmatter.items() if not k.startswith("_")}
    txt = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n" + (corpo or "").strip() + "\n"
    caminho_arquivo = os.path.join(d, peca_id + ".md")
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        f.write(txt)
    return caminho_arquivo


def atualizar_status(marca, peca_id, **campos):
    p = caminho(marca, peca_id)
    fm = ler(p)
    corpo = fm.pop("_corpo")
    fm.pop("_arquivo", None)
    fm.pop("_peca_id", None)
    fm.update(campos)
    return escrever(marca, peca_id, fm, corpo)


def remover(marca, peca_id):
    p = caminho(marca, peca_id)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False
