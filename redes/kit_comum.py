# -*- coding: utf-8 -*-
"""Arquivo do kit de uma marca com herança da InnConta (PAR-01d, 29/09/2026: um recurso, uma raiz).

As fontes padrão (Cormorant Garamond + Jost, estáticas e a variável) são as MESMAS em todas as marcas: vivem só em
`redes/kit/innconta/`. Uma marca só guarda no próprio kit o que é dela (logo, marca.json, regras.json, fotos) e, se
tiver tipografia própria, os arquivos que declarar. `arquivo(marca, ...)` devolve o do kit da marca quando existe e,
senão, o da InnConta."""
import os

RAIZ_KIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit")
KIT_BASE = "innconta"


def arquivo(marca, *partes):
    proprio = os.path.join(RAIZ_KIT, marca, *partes)
    if os.path.exists(proprio):
        return proprio
    return os.path.join(RAIZ_KIT, KIT_BASE, *partes)
