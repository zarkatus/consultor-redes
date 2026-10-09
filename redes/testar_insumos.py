# -*- coding: utf-8 -*-
"""Bateria dos insumos do revisor FATO (sem rede, 09/10/2026): recorte em volta do artigo citado e charset.
Por que: o Codigo Civil compilado tem ~630 mil caracteres e o revisor recebia so os primeiros 6 mil (todo artigo alem
disso era "nao esta na fonte"); o planalto serve windows-1252 sem declarar charset e todo acento virava U+FFFD."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "conselho"))
import insumos  # noqa: E402

falhas = []


def ok(cond, nome):
    print(("OK   - " if cond else "FALHA- ") + nome)
    if not cond:
        falhas.append(nome)


enchimento = "x" * 20000
pagina = ("Art. 1º Disposicao inicial. " + enchimento + " Art. 104. A validade do negocio juridico requer agente capaz. "
          + enchimento + " Art. 397. O inadimplemento da obrigacao, positiva e liquida, no seu termo. " + enchimento)
r = insumos.recorte_dos_artigos(pagina, "Código Civil, art. 104, III")
ok("Art. 104. A validade" in r, "artigo alem dos 6 mil caracteres entra no recorte")
ok("Art. 104" not in pagina[:insumos.LIMITE_CHARS_FONTE], "controle: o comeco da pagina NAO tem o artigo")
r2 = insumos.recorte_dos_artigos(pagina, "arts. 104 e 397")
ok("Art. 104." in r2 and "Art. 397." in r2, "dois artigos citados, os dois no recorte")
ok(len(r2) <= insumos.LIMITE_CHARS_FONTE, "recorte respeita o limite")
ok(insumos.recorte_dos_artigos(pagina, "Lei nº 10.406/2002") == pagina[:insumos.LIMITE_CHARS_FONTE],
   "norma sem artigo = comeco da pagina (comportamento antigo)")
ok(insumos.recorte_dos_artigos(pagina, "art. 999") == pagina[:insumos.LIMITE_CHARS_FONTE], "artigo inexistente = comeco")
ok("Art. 1º Disposicao" in insumos.recorte_dos_artigos(pagina, "art. 1º"), "art. 1º (ordinal) casa")
ok(insumos._decodificar("três dias úteis".encode("cp1252")) == "três dias úteis", "windows-1252 sem charset declarado")
ok(insumos._decodificar("três dias úteis".encode("utf-8")) == "três dias úteis", "utf-8 sem charset declarado")
ok(insumos._decodificar("ção".encode("latin-1"), "iso-8859-1") == "ção", "charset do cabecalho vale")
ok(insumos._decodificar(b'<meta charset="iso-8859-1">\xe7') .endswith("ç"), "charset do <meta> vale")
print("%d falha(s)" % len(falhas))
sys.exit(1 if falhas else 0)
