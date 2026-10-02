# -*- coding: utf-8 -*-
"""Prova SEM REDE do gerador de peças (redes/gerador.py) e dos kits por marca. `python redes/testar_gerador.py` a partir
da raiz do repo; sai com código != 0 se qualquer prova falhar (gate real, mesmo padrão de testar_guarda.py).

Cobre: leitura do site (só português, seções, sitemap), regra dura número-só-se-está-na-página (com controle negativo),
sigilo (número operacional barrado, número de norma passa), alcance (gancho, palavra-chave, CTA, hashtags, alt text),
collab (>=1 e <=2 a cada 7 peças, parceiro rodiza, tema por afinidade), mix de formatos, cota esgotada (adia e registra),
zero token de provedor pago (o texto do gerador não cita provedor pago) e o contrato dos regras.json de todos os kits."""
import datetime
import glob
import json
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import estoque  # noqa: E402
import gerador as g  # noqa: E402

FALHAS = []


def ok(nome, cond):
    print(("OK    " if cond else "FALHA ") + nome)
    if not cond:
        FALHAS.append(nome)


# ------------------------------------------------------------------------------------------------ 1. leitura do site
HTML = """<html><head><title>Marca Teste · Página</title><meta name="description" content="Descrição da marca."></head><body>
<nav>menu que não entra</nav><h1>Certificação de ativos</h1>
<h2><span lang-pt>Como funciona</span><span lang-en>How it works</span></h2>
<p><span lang="pt">A certificação declara recursos e reservas em código reconhecido. O prazo médio citado é de 90 dias na etapa inicial. %(x)s</span><span lang="en">English text must not enter.</span></p>
<h2>Segunda seção</h2><p>Texto da segunda seção com bastante conteúdo para passar do mínimo de caracteres. %(x)s</p>
<footer>rodapé que não entra</footer></body></html>""" % {"x": "Detalhe técnico repetido para dar corpo ao texto. " * 8}
pg = g.extrair_pagina(HTML, "https://exemplo.test/p")
ok("menu, rodapé e inglês ficam fora do texto-fonte", "menu que" not in pg["texto"] and "rodapé" not in pg["texto"] and "English" not in pg["texto"] and "How it works" not in pg["texto"])
ok("seções lidas com título (português)", [s["titulo"] for s in pg["secoes"]][:2] == ["Como funciona", "Segunda seção"])
ok("números da página são reconhecidos e normalizados", "90" in g.numeros_do_texto("prazo de 90 dias e 1.000 itens") and "1000" in g.numeros_do_texto("1.000"))

# ------------------------------------------------------------------------------------------------ 2. validação (alcance + regra dura)
REGRAS = g.carregar_regras("incorpmine")
SEC = {"titulo": "Como funciona", "slug": "como-funciona", "texto": "A certificação declara recursos e reservas em código reconhecido. O prazo médio citado é de 90 dias na etapa inicial. " * 3}
PAG = {"titulo": "Certificação de ativos", "descricao": "", "url": "https://exemplo.test/p"}


def peca(**kw):
    d = {"gancho": "Certificação de ativos minerais começa pelo código reconhecido pelo comprador.", "legenda": "A certificação declara recursos e reservas no código do mercado de destino.",
         "cta": "Salve para consultar e compartilhe com quem avalia ativos.", "titulo": "Recurso não é <em>reserva</em>", "rotulo": "Certificação",
         "laminas": [{"rotulo": "a", "texto": "um"}, {"rotulo": "b", "texto": "dois"}, {"rotulo": "c", "texto": "três"}, {"rotulo": "d", "texto": "quatro"}],
         "roteiro": [], "alt_text": "Cartaz com o título da peça.", "palavra_chave": "certificação de ativos minerais"}
    d.update(kw)
    return d


ok("peça boa passa", g.validar(peca(), PAG, SEC, REGRAS, "carrossel") == [])
ok("gancho > 125 caracteres é barrado", any("gancho" in m for m in g.validar(peca(gancho="x" * 130), PAG, SEC, REGRAS, "carrossel")))
ok("sem palavra-chave é barrada (controle: com palavra passa)", any("palavra-chave" in m for m in g.validar(peca(gancho="Um gancho qualquer sem o termo", legenda="Texto sem o termo."), PAG, SEC, REGRAS, "carrossel")))
ok("sem chamada para salvar/compartilhar é barrada", any("chamada" in m for m in g.validar(peca(cta="Leia mais.", legenda="A certificação de ativos minerais explica."), PAG, SEC, REGRAS, "carrossel")))
ok("sem texto alternativo é barrada", any("alternativo" in m for m in g.validar(peca(alt_text=""), PAG, SEC, REGRAS, "carrossel")))
ok("NÚMERO INVENTADO é barrado (controle negativo)", any("número" in m for m in g.validar(peca(legenda="A certificação de ativos minerais leva 45 dias."), PAG, SEC, REGRAS, "carrossel")))
ok("número que ESTÁ na página passa (controle positivo)", g.validar(peca(legenda="A certificação de ativos minerais leva 90 dias."), PAG, SEC, REGRAS, "carrossel") == [])
ok("palavra 'casa' é barrada", any("proibido" in m for m in g.validar(peca(legenda="Na casa, a certificação de ativos minerais segue o código."), PAG, SEC, REGRAS, "carrossel")))
ok("'agente' e 'bot' são barrados", len([m for m in g.validar(peca(legenda="Um agente e um bot cuidam da certificação de ativos minerais."), PAG, SEC, REGRAS, "carrossel") if "proibido" in m]) >= 2)
ok("emoji é barrado", any("emoji" in m for m in g.validar(peca(legenda="Certificação de ativos minerais \U0001F680"), PAG, SEC, REGRAS, "carrossel")))
ok("hashtag dentro da legenda é barrada", any("hashtag" in m for m in g.validar(peca(legenda="Certificação de ativos minerais #jorc"), PAG, SEC, REGRAS, "carrossel")))
ok("carrossel com menos de 4 lâminas é barrado", any("lâminas" in m for m in g.validar(peca(laminas=[{"rotulo": "a", "texto": "b"}]), PAG, SEC, REGRAS, "carrossel")))
ok("reels sem roteiro é barrado", any("roteiro" in m for m in g.validar(peca(roteiro=[]), PAG, SEC, REGRAS, "reels")))
ok("citação vedada pela discrição é barrada", any("discrição" in m for m in g.validar(peca(legenda="A certificação de ativos minerais da jazida X segue nome de jazida."), PAG, SEC, REGRAS, "carrossel")))

RSIG = g.carregar_regras("inncorpower")
SEC2 = {"titulo": "Marco legal", "slug": "marco", "texto": "A Lei 14.300/2022 é o marco legal da geração distribuída. Uma usina de 40 MW opera em Recife. " * 3}
ps = peca(gancho="A energia como patrimônio começa pelo marco legal da geração distribuída.", legenda="A geração distribuída tem marco legal na Lei 14.300/2022.")
ok("sigilo: número de norma (Lei 14.300/2022) passa", g.validar(ps, PAG, SEC2, RSIG, "carrossel") == [])
ok("sigilo: número OPERACIONAL (40 MW) é barrado mesmo estando na página",
   any("sigilo" in m for m in g.validar(peca(gancho=ps["gancho"], legenda="A geração distribuída de energia como patrimônio soma 40 MW."), PAG, SEC2, RSIG, "carrossel")))

# ------------------------------------------------------------------------------------------------ 3. zero provedor pago
fonte = open(os.path.join(RAIZ, "gerador.py"), encoding="utf-8").read().lower()
ok("gerador.py não cita provedor pago (anthropic / claude-)", "anthropic" not in fonte and "claude-" not in fonte)
ok("motor do conselho só usa a cadeia gratuita de conselho/modelos.py", "modelos.conversar" in fonte and "excluir_provedores" in fonte)

# ------------------------------------------------------------------------------------------------ 4. lote completo com motor MOCK (site e kit temporários)
TMP = tempfile.mkdtemp(prefix="testa-gerador-")


def monta_kit(marca="marca-teste", parceiros=("parceiro-a", "parceiro-b"), sigilo=False):
    kit = os.path.join(TMP, "kit", marca)
    os.makedirs(kit)
    reg = {"marca": marca, "tipo": "empresa", "nome": "Marca Teste", "site": "https://exemplo.test", "dominios_origem": ["exemplo.test"], "handle_instagram": "@marca.teste",
           "ig_user_id": None, "publicar": {"instagram": False, "linkedin": False, "horario_brt": "08:00"}, "voz": {"tom": "sóbrio", "proibidos": ["revolucionário"], "preferidos": ["método"]},
           "temas": ["certificação"], "palavras_chave": ["certificação de ativos"], "hashtags": ["#certificacao", "#ativos", "#mineracao", "#duediligence"], "fontes_oficiais_extra": [],
           "discricao": {"sigilo": sigilo, "nao_citar": []}, "collab": {"parceiros": list(parceiros), "min_por_semana": 1, "max_por_semana": 2}, "email_escalada": "central@innconta.com.br"}
    json.dump(reg, open(os.path.join(kit, "regras.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"nome": "Marca Teste", "arte_v2": {"categorias": {"marco": {"nome": "Marco", "icone": "marco"}, "metodo": {"nome": "Método", "icone": "metodo"}}}},
              open(os.path.join(kit, "marca.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"parceiro-a": ["terraplen", "brita", "areia"], "parceiro-b": ["plataforma", "observabilidade", "governan"]}, open(os.path.join(kit, "afinidades.json"), "w", encoding="utf-8"))
    for p in parceiros:
        os.makedirs(os.path.join(TMP, "kit", p), exist_ok=True)
        json.dump({"nome": p.upper()}, open(os.path.join(TMP, "kit", p, "marca.json"), "w", encoding="utf-8"))
        json.dump({"handle_instagram": "@" + p}, open(os.path.join(TMP, "kit", p, "regras.json"), "w", encoding="utf-8"))
    return marca


def pagina_html(i, extra=""):
    corpo = "".join("<h2>Seção %d da página %d</h2><p>%s A certificação de ativos declara recursos e reservas em código reconhecido; o prazo citado é de 90 dias. %s</p>"
                    % (k, i, "Conteúdo técnico detalhado para compor o texto-fonte. " * 9, extra if k % 2 == 0 else "") for k in range(1, 5))
    return "<html><head><title>Página %d</title></head><body><h1>Página %d</h1>%s</body></html>" % (i, i, corpo)


PAGINAS = {"https://exemplo.test/sitemap.xml": "<urlset>" + "".join("<url><loc>https://exemplo.test/p%d</loc></url>" % i for i in range(1, 6)) + "</urlset>"}
for i in range(1, 6):
    PAGINAS["https://exemplo.test/p%d" % i] = pagina_html(i, "A obra exige terraplenagem, brita e areia do parceiro; a plataforma oferece observabilidade e governança. " if i % 2 else "")


def leitor(url):
    if url in PAGINAS:
        return PAGINAS[url]
    raise FileNotFoundError(url)


def motor_mock(prompt):
    return json.dumps({"gancho": "Certificação de ativos: o prazo de 90 dias começa pela leitura do código.", "legenda": "A certificação de ativos declara recursos e reservas em código reconhecido.",
                       "cta": "Salve para consultar e compartilhe com quem decide.", "titulo": "Certificação de <em>ativos</em>", "rotulo": "Certificação",
                       "laminas": [{"rotulo": "Código", "texto": "Recursos e reservas em código reconhecido."}, {"rotulo": "Prazo", "texto": "Prazo citado: 90 dias.", "valor": "90", "unidade": "dias"},
                                   {"rotulo": "Leitura", "texto": "A leitura vem antes."}, {"rotulo": "Fonte", "texto": "Tudo conferido na página."}, {"rotulo": "Método", "texto": "Passo a passo."}],
                       "roteiro": ["Primeiro o código.", "Depois a leitura.", "Então o prazo.", "Salve e compartilhe.", "Leia na fonte."],
                       "alt_text": "Cartaz de texto sobre certificação de ativos.", "palavra_chave": "certificação de ativos"})


ANTES = (g.RAIZ, estoque.RAIZ)
try:
    g.RAIZ = TMP
    estoque.RAIZ = os.path.join(TMP, "estoque")
    marca = monta_kit()
    logs = []
    feitas, recusadas = g.gerar_lote(marca, 14, motor_mock, site=None, hoje=datetime.date(2026, 9, 29), gravar=True, log=logs.append, leitor=leitor)
    ok("gerou as 14 peças pedidas", len(feitas) == 14)
    pecas = estoque.listar(marca)
    ok("todas nascem como rascunho, com nota_origem, fontes, alt_text, arte v2 e formato", all(p["status"] == "rascunho" and p["nota_origem"].startswith("https://exemplo.test/") and p["fontes"] and p["alt_text"]
                                                                                       and p["arte"] == "v2" and p["formato"] in g.FORMATOS for p in pecas))
    ok("3 a 5 hashtags do regras.json em toda peça", all(3 <= len(p["hashtags"]) <= 5 and set(p["hashtags"]) <= set(json.load(open(os.path.join(TMP, "kit", marca, "regras.json")))["hashtags"]) for p in pecas))
    ok("primeira linha da legenda é gancho <= 125", all(len(p["_corpo"].split("\n")[0]) <= 125 for p in pecas))
    ok("mix: tem carrossel e feed (e reels quando o texto permite)", {"carrossel", "feed"} <= {p["formato"] for p in pecas})
    ok("carrossel traz `quadros` (capa + lâminas + fecho) e reels traz `roteiro`", all((p["formato"] != "carrossel" or len(p["quadros"]) >= 6) and (p["formato"] != "reels" or (p["roteiro"] and p["tipo"] == "video")) for p in pecas))
    ok("peca_id leva a marca (UNIQUE global na tabela: mesma seção em 2 marcas no mesmo dia não colide)",
       all(p["_peca_id"].startswith("2026-09-29-%s-" % marca) for p in pecas))
    pecas_ord = sorted(pecas, key=lambda p: p["_peca_id"])
    collab = [(i, p["collab"]) for i, p in enumerate(sorted(pecas, key=lambda p: int(p["_peca_id"].split("-")[-2]))) if p.get("collab")]
    ok("collab: >= 1 em cada bloco de 7 e <= 2 (14 peças => 2 a 4)", 2 <= len(collab) <= 4 and len([c for c in collab if c[0] < 7]) in (1, 2) and len([c for c in collab if c[0] >= 7]) in (1, 2))
    ok("collab rodiza entre os parceiros", len({c[1] for c in collab}) == 2)
    ok("legenda de collab diz 'Em colaboração com' + @ do parceiro; peça sem collab não diz", all(("Em colaboração com" in p["_corpo"]) == bool(p.get("collab")) for p in pecas))
    ok("spec de arte gravado para toda peça (carrossel com N lâminas, so_quadros)", len(json.load(open(os.path.join(TMP, "estoque", marca, "_arte", "pecas-v2.json"), encoding="utf-8"))) == 14)
    # não repete seção já usada: segunda rodada GRAVANDO; nenhuma (nota_origem, secao) pode aparecer duas vezes
    feitas2, _ = g.gerar_lote(marca, 3, motor_mock, hoje=datetime.date(2026, 9, 30), gravar=True, log=lambda *_: None, leitor=leitor)
    todas = estoque.listar(marca)
    pares = [(p["nota_origem"], p["secao"]) for p in todas]
    ok("segunda rodada não reutiliza seção já usada (17 peças, 17 pares únicos)", len(feitas2) == 3 and len(todas) == 17 and len(set(pares)) == 17)

    # peça com número inventado é DESCARTADA (não vira rascunho)
    def motor_mente(prompt):
        d = json.loads(motor_mock(prompt))
        d["legenda"] = "A certificação de ativos leva 45 dias e custa 12 milhões."
        return json.dumps(d)
    marca2 = monta_kit("marca-mente")
    f3, r3 = g.gerar_lote(marca2, 2, motor_mente, hoje=datetime.date(2026, 9, 29), gravar=True, log=lambda *_: None, leitor=leitor)
    ok("motor que inventa número não gera nenhuma peça (todas descartadas, nada gravado)", len(f3) == 0 and len(r3) >= 1 and estoque.listar(marca2) == [])

    # cota esgotada: adia e registra, sem cair para provedor pago
    def motor_sem_cota(prompt):
        raise g.CotaAdiada("todos os provedores gratuitos em 429")
    marca3 = monta_kit("marca-sem-cota")
    f4, _ = g.gerar_lote(marca3, 3, motor_sem_cota, hoje=datetime.date(2026, 9, 29), gravar=True, log=lambda *_: None, leitor=leitor)
    reg = os.path.join(TMP, "estoque", marca3, "_arte", "adiadas.json")
    ok("429 em todos os provedores gratuitos: lote adiado e registrado em adiadas.json", len(f4) == 0 and os.path.isfile(reg) and len(json.load(open(reg, encoding="utf-8"))) >= 1)

    # discrição: seção com termo vedado no título nem chega a ser redigida
    kit3 = json.load(open(os.path.join(TMP, "kit", marca, "regras.json"), encoding="utf-8"))
    kit3["discricao"]["nao_citar"] = ["seção 1 da página 1"]
    fila = g.unidades_disponiveis(g.Site("https://exemplo.test", leitor=leitor), kit3, set())
    ok("discricao.nao_citar tira a seção do título vedado da fila", not any(s["titulo"] == "Seção 1 da página 1" for _p, s in fila) and any(s["titulo"] == "Seção 1 da página 2" for _p, s in fila))
finally:
    g.RAIZ, estoque.RAIZ = ANTES
    shutil.rmtree(TMP, ignore_errors=True)

ok("planejar_slots: 14 peças => obrigatórios nos índices 2 e 9; 7 peças => 1", g.planejar_slots(14)[0] == [2, 9] and g.planejar_slots(7)[0] == [2])
ok("artigo semanal é esqueleto documentado (NotImplementedError explícito)", "artigo" in (g.gerar_artigo.__doc__ or "").lower())

# ------------------------------------------------------------------------------------------------ 5. contrato dos kits (regras.json de TODAS as marcas)
CHAVES = ["marca", "tipo", "nome", "site", "dominios_origem", "handle_instagram", "ig_user_id", "publicar", "voz", "temas", "palavras_chave", "hashtags",
          "fontes_oficiais_extra", "discricao", "collab", "email_escalada"]
kits = sorted(glob.glob(os.path.join(RAIZ, "kit", "*", "regras.json")))
print("\n== contrato dos %d regras.json ==" % len(kits))
for caminho in kits:
    m = os.path.basename(os.path.dirname(caminho))
    r = json.load(open(caminho, encoding="utf-8"))
    d = os.path.dirname(caminho)
    ok("%s: campos do contrato, hashtags 3-5, e-mail da central, marca.json e logo" % m,
       all(k in r for k in CHAVES) and r["marca"] == m and 3 <= len(r["hashtags"]) <= 5 and r["email_escalada"] == "central@innconta.com.br"
       and set(r["voz"]) >= {"tom", "proibidos", "preferidos"} and {"instagram", "linkedin", "horario_brt"} <= set(r["publicar"])
       and os.path.isfile(os.path.join(d, "marca.json")) and os.path.isfile(os.path.join(d, "logo.svg")))
    ok("%s: collab com min/max (min 1 quando há >= 2 parceiros)" % m,
       {"parceiros", "min_por_semana", "max_por_semana"} <= set(r["collab"]) and (len(r["collab"]["parceiros"]) < 2 or (r["collab"]["min_por_semana"] == 1 and r["collab"]["max_por_semana"] == 2)))
    ok("%s: sem a palavra 'casa' nem 'agente' em voz/temas/palavras-chave" % m,
       not any(__import__("re").search(r"\bcasas?\b|\bagentes?\b", t, __import__("re").I) for t in [r["voz"]["tom"]] + r["temas"] + r["palavras_chave"] + r["voz"]["preferidos"]))

print("\n%s" % ("TODAS AS PROVAS PASSARAM" if not FALHAS else "%d FALHA(S): %s" % (len(FALHAS), FALHAS)))
sys.exit(1 if FALHAS else 0)
