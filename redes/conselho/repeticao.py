# -*- coding: utf-8 -*-
"""ANTI-REPETICAO do Conselho v2 (CVO 29/09/2026: conteudo identico em duas contas derruba o alcance).

Determinístico, sem modelo. Reprova a peca que se PARECE demais com:
  (a) qualquer das ultimas 30 pecas (aprovadas/publicadas) da MESMA marca;
  (b) uma peca de OUTRA marca marcada para o mesmo dia (+-1 dia) — exceto quando a peca e a MESMA publicacao em
      collab (`collab` na peca e a outra marca esta em `collab.parceiros`).

Semelhanca = o maior entre (1) Jaccard de trigramas de palavras e (2) razao do difflib sobre o texto normalizado
(sem acento, sem hashtags, sem links, sem chamada final). Limiar 0,60 — calibrado contra o estoque real (ver
`testar_conselho.py`, bloco anti-repeticao: o par mais parecido do estoque atual (74 pecas de Instagram) chega a 0,51)."""
import difflib
import re
import unicodedata

LIMIAR = 0.60
LIMIAR_SEM_DATA = 0.85  # peca de outra marca sem data conhecida (em uma das duas)
ULTIMAS = 30
JANELA_DIAS = 1

_HASH = re.compile(r"(?<![\w&])#\w+", re.U)
_CTA_LINHA = re.compile(r"^\s*(salve|salva|compartilhe|comente|marque|envie|guarde|mande)\b[^\n]*$", re.I | re.M)
_LINK = re.compile(r"https?://\S+|\b[\w-]+\.(?:com\.br|com|br|ia\.br)(?:/\S*)?", re.I)


def normalizar(texto):
    t = unicodedata.normalize("NFKD", _CTA_LINHA.sub(" ", texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = _LINK.sub(" ", _HASH.sub(" ", t))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _trigramas(n):
    p = n.split()
    if len(p) < 3:
        return {" ".join(p)} if p else set()
    return {" ".join(p[i:i + 3]) for i in range(len(p) - 2)}


def semelhanca(a, b):
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    ta, tb = _trigramas(na), _trigramas(nb)
    jac = len(ta & tb) / float(len(ta | tb)) if (ta | tb) else 0.0
    seq = difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()
    return max(jac, seq)


def _data(x):
    try:
        import datetime
        return datetime.date.fromisoformat(str(x)[:10])
    except Exception:
        return None


def checar(texto, marca, referencias, data_publicacao=None, collab_parceiros=(), limiar=LIMIAR):
    """referencias: [{marca, peca_id, texto, data (AAAA-MM-DD|None)}]. Devolve lista de motivos (vazia = ok)."""
    motivos = []
    propria = [r for r in referencias if r.get("marca") == marca][:ULTIMAS]
    for r in propria:
        s = semelhanca(texto, r.get("texto") or "")
        if s >= limiar:
            motivos.append("repeticao: %.0f%% igual a peca ja aprovada/publicada da mesma marca (%s)" % (s * 100, r.get("peca_id")))
    d0 = _data(data_publicacao)
    for r in referencias:
        if r.get("marca") == marca:
            continue
        if r.get("marca") in (collab_parceiros or ()):
            continue  # mesma publicacao em collab entre empresas do grupo: permitido
        d1 = _data(r.get("data"))
        if d0 is not None and d1 is not None and abs((d0 - d1).days) > JANELA_DIAS:
            continue
        s = semelhanca(texto, r.get("texto") or "")
        # data desconhecida (a agenda ainda nao fixou o dia): so texto QUASE identico conta; assim duas marcas que falam
        # do mesmo tema com a mesma estrutura nao se reprovam sem necessidade
        if s >= (limiar if (d0 is not None and d1 is not None) else LIMIAR_SEM_DATA):
            motivos.append("repeticao: %.0f%% igual a peca de OUTRA marca (%s: %s) no mesmo dia; conteudo identico em duas contas "
                           "derruba o alcance" % (s * 100, r.get("marca"), r.get("peca_id")))
    return motivos
