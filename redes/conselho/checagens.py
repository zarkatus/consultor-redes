# -*- coding: utf-8 -*-
"""CHECAGENS DETERMINISTICAS do Conselho v2 (29/09/2026) — custo zero de modelo, rodam ANTES dos revisores.

Cada checagem devolve motivos; `executar()` separa:
  - CORRIGIVEIS (o redator/`alcance.corrigir_legenda` mexe so no TEXTO): alcance da legenda, sigilo na legenda,
    guarda da marca;
  - FATAIS (so um novo render/troca de fonte/de data resolve — o redator nao mexe em arte): imagem fora do que o
    Instagram aceita, numero na ARTE fora da fonte, fonte de dominio nao permitido, repeticao, numero operacional na
    arte de marca com sigilo. Fatal escala na hora (mesmo criterio do revisor visual da v1).

So roda para peca que declara `marca` (a peca real sempre declara; testes antigos sem marca seguem a v1)."""
import os
import re
import sys
import unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))
REDES = os.path.dirname(AQUI)
for p in (AQUI, REDES, os.path.join(REDES, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)
import alcance  # noqa: E402
import guarda  # noqa: E402
import insumos  # noqa: E402
import marcas  # noqa: E402
import repeticao  # noqa: E402

_NUM = re.compile(r"\d[\d.,]*")
_UNIDADE = re.compile(r"^\s*(%|por\s*cento|mw\w*|gw\w*|kw\w*|milh\w+|bilh\w+|mil\b|reais|anos?|dias?|meses|mes\b|horas?|ha\b|m2|km2)", re.I)


def _norm(t):
    n = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower()


def _digitos(tok):
    return re.sub(r"[^\d]", "", tok)


def numeros_verificaveis(texto):
    """Numeros da ARTE que precisam de fonte: com unidade/percentual/R$, com 3+ digitos, decimais/milhares ou
    logo depois de art./lei/decreto/n. Ignora marcador de lista (1, 2) e contador de quadro (1/6)."""
    out = []
    t = texto or ""
    for m in _NUM.finditer(t):
        tok = m.group(0).rstrip(".,")
        d = _digitos(tok)
        if not d:
            continue
        depois = t[m.end():m.end() + 14]
        antes = _norm(t[max(0, m.start() - 12):m.start()])
        if len(d) <= 2 and re.match(r"^/\d{1,2}(?!\d)", depois):
            continue  # contador de quadro (1/6)
        verificavel = (bool(_UNIDADE.match(depois)) or "r$" in antes or len(d) >= 3 or bool(re.search(r"[.,]\d", tok))
                       or bool(re.search(r"(art|arts|lei|decreto|n|no|resolucao|portaria)\.?\s*$", antes)))
        if verificavel and d not in out:
            out.append(d)
    return out


def numeros_da_arte_fora_da_fonte(texto_arte, legenda, fontes, paginas=()):
    """Motivos: numero/afirmacao da ARTE que nao aparece na legenda aprovada, nas fontes declaradas (dado/norma) nem
    no texto baixado ao vivo (`paginas`). Sem fonte que o sustente = reprova."""
    if not (texto_arte or "").strip():
        return []
    corpus = " ".join([legenda or ""] + ["%s %s" % ((f or {}).get("dado", ""), (f or {}).get("norma", "")) for f in fontes or []]
                      + list(paginas or []))
    presentes = {_digitos(m.group(0)) for m in _NUM.finditer(corpus)}
    faltam = [n for n in numeros_verificaveis(texto_arte) if n not in presentes]
    if not faltam:
        return []
    return ["fato: a arte traz numero(s) que nao estao na fonte nem na legenda: %s (a arte precisa de novo render sem o dado, "
            "ou a fonte tem de sustentar)" % ", ".join(faltam[:6])]


def imagens_invalidas(peca):
    """Checagem deterministica de cada imagem declarada (proporcao, abre, peso). Formato da peca decide 4:5-1,91:1 x 9:16."""
    formato = str(peca.get("formato") or "imagem").lower()
    tipo = "stories" if ("video" in formato or "stories" in formato or "reels" in formato) else "imagem"
    motivos = []
    for c in peca.get("imagens") or []:
        for m in insumos.checar_imagem(c, tipo):
            motivos.append("visual: " + m)
    return motivos


def paginas_ao_vivo(peca, regras):
    """Texto ao vivo da pagina de origem (dominios da marca) + fontes oficiais permitidas."""
    doms = marcas.dominios_permitidos(regras)
    textos = []
    baixadas = []
    for u in peca.get("nota_urls") or []:
        t = insumos.texto_da_pagina(u, dominios=doms, inteiro=True)  # checagem de fato: pagina toda, sem corte
        baixadas.append(u)
        if t:
            textos.append(t)
    for u, t in insumos.texto_das_fontes(peca.get("fontes"), doms, ja_baixadas=baixadas):
        if t:
            textos.append(t)
    return textos


def executar(peca, texto, regras, referencias=None, paginas=None):
    """Devolve (corrigiveis, fatais): listas de motivos 'revisor: motivo'. `paginas` injetavel (teste/prova)."""
    corrigiveis, fatais = [], []
    if str(peca.get("canal") or "") == "instagram":
        hashtags_extra = len(alcance.hashtags(alcance.primeiro_comentario(peca) or ""))
        for m in alcance.checar_legenda(texto, regras, peca, hashtags_extra=hashtags_extra):
            corrigiveis.append(m)
    arte = peca.get("texto_arte") or ""
    if (regras.get("discricao") or {}).get("sigilo") and arte:
        for m in guarda.checar_sigilo(arte, regras):
            fatais.append(m + " [na ARTE]")
    for m in guarda.checar_fontes(peca.get("fontes"), regras):
        fatais.append("fato: " + m)
    fatais += imagens_invalidas(peca)
    if arte.strip():
        pg = paginas if paginas is not None else paginas_ao_vivo(peca, regras)
        fatais += numeros_da_arte_fora_da_fonte(arte, texto, peca.get("fontes"), pg)
    parceiros = tuple((regras.get("collab") or {}).get("parceiros") or ()) if peca.get("collab") else ()
    fatais += repeticao.checar(texto, regras["marca"], referencias or [], peca.get("data_publicacao"), parceiros)
    return corrigiveis, fatais
