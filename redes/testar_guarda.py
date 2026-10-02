# -*- coding: utf-8 -*-
"""Bateria de prova da guarda.checar(): TODAS as peças reais do estoque, status aprovado (devem
PASSAR) + peças
adversárias (todas devem BARRAR). Roda local, sem rede — `python3 redes/testar_guarda.py` a partir da raiz do
repo. Sai com código != 0 se qualquer prova falhar (gate real para o workflow, não decorativo).
Identidade do dono (02/10/2026, repositório público): com o Secret GUARDA_IDENTIDADE no ambiente (Actions), as
`amostras` dele têm de barrar; sem ele (local), roda com uma identidade SINTÉTICA, que prova o mecanismo."""
import glob
import json
import os
import sys

SINTETICA = {"nomes": [r"fulano\s+exemplar", r"\bexemplar\b"], "dominios_pessoais": ["exemplar.com.br"],
             "amostras": ["Fale direto com Fulano Exemplar sobre sua conta.",
                          "Manda um e-mail pra fulano@exemplar.com.br que eu respondo."]}
IDENTIDADE_REAL = bool(os.environ.get("GUARDA_IDENTIDADE"))
if not IDENTIDADE_REAL:
    os.environ["GUARDA_IDENTIDADE"] = json.dumps(SINTETICA)
AMOSTRAS = json.loads(os.environ["GUARDA_IDENTIDADE"]).get("amostras") or []

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import estoque  # noqa: E402
import guarda  # noqa: E402

FALHAS = []
print("identidade da guarda: %s, %d amostra(s)" % ("Secret GUARDA_IDENTIDADE" if IDENTIDADE_REAL else "SINTÉTICA (local)",
                                                   len(AMOSTRAS)))
if len(AMOSTRAS) < 2:
    FALHAS.append("GUARDA_IDENTIDADE sem ao menos 2 amostras (nome e e-mail): a checagem do dono ficaria sem prova")

reais = [p for p in estoque.listar("innconta") if p.get("status") == "aprovado"]
print("== %d peças reais do estoque (devem PASSAR) ==" % len(reais))
if len(reais) < 1:
    FALHAS.append("esperava pelo menos 1 peça aprovada no estoque, achou %d" % len(reais))
for p in reais:
    ok, motivos = guarda.checar(p["_corpo"], nota_origem=str(p.get("nota_origem") or ""))
    print(("PASSOU " if ok else "BARROU ") + p["_peca_id"], motivos if not ok else "")
    if not ok:
        FALHAS.append("peça real barrada indevidamente: %s -> %s" % (p["_peca_id"], motivos))

ADVERSARIAS = [("identidade do dono, amostra %d" % i, a) for i, a in enumerate(AMOSTRAS, 1)] + [
    ("telefone", "Chame no WhatsApp 11 90000-0000 e resolvemos hoje."),
    ("vocabulário proibido", "Temos a melhor cesta de loteamentos da região."),
    ("contagem própria/prova social", "Já são 128 clientes fechados só este mês."),
    ("promessa financeira", "Garantimos 30% de economia e R$ 50.000 recuperados em créditos."),
]
print("\n== %d peças adversárias (devem BARRAR) ==" % len(ADVERSARIAS))
for nome, texto in ADVERSARIAS:
    ok, motivos = guarda.checar(texto)
    print(("BARROU (ok)" if not ok else "PASSOU (FALHA)") + " - " + nome, motivos)
    if ok:
        FALHAS.append("peça adversária passou sem ser barrada: %s" % nome)

print("\n== link de frente (25/09/2026): slug tem de existir no site e casar com o tema (nota_origem) ==")
FRENTE = [
    # (nome, texto, nota_origem, deve_passar)
    ("controle positivo: link certo", "Texto.\n\ninnconta.com.br/frente/contas-consumo\n#telecom",
     "innconta.com.br/frente/contas-consumo (fonte: Resolução Anatel 765/2023)", True),
    ("adversária: frente errada (o defeito real, contas-consumo -> energia)",
     "Texto.\n\ninnconta.com.br/frente/energia\n#telecom", "innconta.com.br/frente/contas-consumo (fonte: x)", False),
    ("adversária: frente que não existe no site", "Texto.\n\ninnconta.com.br/frente/telecomunicacoes", None, False),
    ("sem nota_origem e slug válido passa (só a existência é checada)", "Texto.\n\ninnconta.com.br/frente/fiscal", None, True),
    ("texto sem link de frente passa", "Texto sem link nenhum.", "innconta.com.br/frente/fiscal", True),
]
for nome, texto, origem, deve in FRENTE:
    ok, motivos = guarda.checar(texto, nota_origem=origem)
    certo = (ok == deve)
    print(("OK   " if certo else "FALHA") + " - " + nome, motivos)
    if not certo:
        FALHAS.append("link de frente: %s" % nome)
print("=" * 3 + " arte v2 (25/09/2026): peça estática de Instagram sem `arte: v2` + `ilustracao:` NÃO publica ==")
OK_ = {"canal": "instagram", "formato": "imagem_feed", "arte": "v2", "ilustracao": "energia", "foto": "energia", "categoria": "pergunta",
       "texto_arte": "Pergunta da mesa · Energia / ..."}
ARTE = [
    # (nome, peça, deve_passar)
    ("controle positivo: imagem_feed completa", OK_, True),
    ("controle positivo: carrossel completo", dict(OK_, formato="carrossel"), True),
    ("adversária: sem `arte` (só texto, o defeito real)", {"canal": "instagram", "formato": "imagem_feed"}, False),
    ("adversária: `arte: v1`", dict(OK_, arte="v1"), False),
    ("adversária: sem ilustração", {k: v for k, v in OK_.items() if k != "ilustracao"}, False),
    ("adversária: sem foto", {k: v for k, v in OK_.items() if k != "foto"}, False),
    ("adversária: foto inexistente", dict(OK_, foto="nao-existe"), False),
    ("adversária: sem categoria", {k: v for k, v in OK_.items() if k != "categoria"}, False),
    ("adversária: categoria inválida", dict(OK_, categoria="novidade"), False),
    ("adversária: selo não bate com a categoria", dict(OK_, categoria="oficio"), False),
    ("adversária: carrossel sem arte", {"canal": "instagram", "formato": "carrossel"}, False),
    ("vídeo fica fora da regra", {"canal": "instagram", "formato": "video"}, True),
    ("LinkedIn fica fora da regra", {"canal": "linkedin_pagina", "formato": "imagem_feed"}, True),
]
for nome, peca, deve in ARTE:
    motivos = guarda.checar_arte(peca)
    certo = ((not motivos) == deve)
    print(("OK   " if certo else "FALHA") + " - " + nome, motivos)
    if not certo:
        FALHAS.append("arte v2: %s" % nome)
# estoque real: toda peça estática de Instagram a publicar de 28/09/2026 em diante declara arte v2 + ilustração
sem_arte = [p["_peca_id"] for p in estoque.listar("innconta")
            if str(p.get("data_publicacao") or "") >= "2026-09-28" and guarda.checar_arte(p)]
print("peças de Instagram do estoque (>= 28/09/2026) sem arte v2: %d %s" % (len(sem_arte), sem_arte[:5]))
if sem_arte:
    FALHAS.append("peça(s) do estoque sem arte v2: %s" % sem_arte)

if guarda.frentes_validas() != guarda._FRENTES_FALLBACK:
    print("aviso: o sitemap.xml do repo difere da lista fixa:", sorted(guarda.frentes_validas() ^ guarda._FRENTES_FALLBACK))
if not guarda.frentes_validas() >= {"energia", "fiscal", "contas-consumo", "reg-tributaria"}:
    FALHAS.append("sitemap.xml não trouxe as frentes esperadas")

print("\n== controle negativo: cliente real da base ==")
ok, motivos = guarda.checar("Fizemos a folha da Construtora Fictícia Teste Ltda este mês.",
                             nomes_clientes=["Construtora Fictícia Teste Ltda"])
print(("BARROU (ok)" if not ok else "PASSOU (FALHA)"), motivos)
if ok:
    FALHAS.append("nome de cliente da base não foi barrado")

print("\n== regressão real (22/09/2026, GitHub Actions): fragmento curto da base não pode barrar a marca ==")
ok, motivos = guarda.checar("Nota InnConta nº 08 — innconta.com.br/nota/uma-certidao",
                             nomes_clientes=["InnC", "InnConta Contabilidade"], marca_nome="innconta")
print(("PASSOU (ok)" if ok else "BARROU (FALHA)"), motivos)
if not ok:
    FALHAS.append("regressão: fragmento curto/prefixo da própria marca voltou a barrar peça legítima -> %s" % motivos)

print("\n== controle positivo/negativo do próprio gate: com a guarda LIGADA vs. sem checagem ==")
texto_sujo = (AMOSTRAS[0] if AMOSTRAS else "") + " 11 90000-0000."
sem_guarda = True  # 'sem checagem' sempre deixaria passar -> prova que a guarda tem efeito real
com_guarda, _ = guarda.checar(texto_sujo)
if sem_guarda == com_guarda:
    FALHAS.append("controle negativo falhou: a guarda não fez diferença nenhuma (inócua)")
else:
    print("guarda tem efeito real: sem checagem passaria, com checagem barra.")

print("\n== falha FECHADA: sem GUARDA_IDENTIDADE, peça limpa é barrada (nunca liberada sem conferir o nome) ==")
salvo = (guarda._NOME_DONO, guarda._DOMINIOS_PESSOAIS)
guarda._NOME_DONO, guarda._DOMINIOS_PESSOAIS = [], set()
ok_sem, motivos_sem = guarda.checar("Nota InnConta nº 08 — a regularidade não admite meio-termo.")
guarda._NOME_DONO, guarda._DOMINIOS_PESSOAIS = salvo
ok_com, _ = guarda.checar("Nota InnConta nº 08 — a regularidade não admite meio-termo.")
print(("BARROU (ok)" if not ok_sem else "PASSOU (FALHA)"), motivos_sem, "| com identidade:", "PASSOU" if ok_com else "BARROU")
if ok_sem or not ok_com:
    FALHAS.append("falha fechada: sem identidade %s, com identidade %s (esperado BARRA/PASSA)"
                  % ("PASSOU" if ok_sem else "BARROU", "PASSOU" if ok_com else "BARROU"))
if any(p.lower() in " ".join(motivos_sem + guarda.checar(texto_sujo)[1]).lower() for p in guarda._NOME_DONO):
    FALHAS.append("o padrão do nome do dono vazou para a mensagem de motivo (iria ao log)")

print("\n== controle negativo do roteiro de VÍDEO (redes/video/renderizar_pendentes.py): "
      "termo proibido no roteiro barra ANTES de renderizar, nada é gerado ==")
roteiro_sujo = "Nota InnConta\nTemos a melhor cesta de loteamentos da região.\nFale com a mesa."
ok, motivos = guarda.checar(roteiro_sujo, marca_nome="innconta")
print(("BARROU (ok)" if not ok else "PASSOU (FALHA)"), motivos)
if ok:
    FALHAS.append("roteiro de vídeo com termo proibido não foi barrado pela guarda")

print("\n== controle 'casa' banida (feedback-palavra-casa-banida-usar-innconta, CVO 23/09/2026): "
      "'a casa faz' barra, 'casamento'/'casal' passam ==")
CASA_ADVERSARIAS = [
    ("'a casa faz' deve barrar", "A casa faz sua contabilidade com regularidade.", False),
    ("'da casa' deve barrar", "Fale com o time da casa sobre sua conta.", False),
    ("'casas' plural deve barrar", "Atendemos duas casas de investimento este mês.", False),
    ("'casamento' não deve barrar", "Ajudamos a planejar as finanças antes do casamento.", True),
    ("'casal' não deve barrar", "O casal fechou o plano de regularização hoje.", True),
]
for nome, texto, deve_passar in CASA_ADVERSARIAS:
    ok, motivos = guarda.checar(texto, marca_nome="innconta")
    certo = ok == deve_passar
    print(("OK " if certo else "FALHA ") + nome, "->", ("PASSOU" if ok else "BARROU"), motivos if not ok else "")
    if not certo:
        FALHAS.append("controle 'casa': %s -> esperava %s, obteve %s (%s)" % (
            nome, "PASSOU" if deve_passar else "BARROU", "PASSOU" if ok else "BARROU", motivos))

print("\n===")
if FALHAS:
    print("FALHOU (%d):" % len(FALHAS))
    for f in FALHAS:
        print(" -", f)
    sys.exit(1)
print("TODAS AS PROVAS PASSARAM (%d reais liberadas, %d adversárias + 1 cliente-real + 1 roteiro de vídeo barrados, "
      "falha fechada provada)." % (len(reais), len(ADVERSARIAS)))
