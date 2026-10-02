# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem banco, sem IA) de `redes/artigos.py` e do caminho de ARTIGO do `redes/gerador.py`
(30/09/2026, decisão do CVO: "usar o artigo semanal como fonte"). Mesmo padrão dos demais `testar_*.py`: cada regra
tem o controle negativo ao lado e os casos adversariais (sitemap vazio, URL duplicada em variantes, artigo já
consumido, site fora do ar, 403, banco fora, número inventado, cota esgotada, página do artigo removida).

Roda `python redes/testar_artigos.py` a partir da raiz do repo; sai com código != 0 se qualquer prova falhar."""
import datetime
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import artigos as a  # noqa: E402
import estoque  # noqa: E402
import gerador as g  # noqa: E402

FALHAS = []


def ok(nome, cond):
    print(("OK    " if cond else "FALHA ") + nome)
    if not cond:
        FALHAS.append(nome)


class RegFalso:
    """Mesma interface de artigos.Registro, em memória (UNIQUE marca+url como no banco)."""

    def __init__(self, estado=None, quebrado=False):
        self.rows, self.n, self.estado, self.quebrado, self.escritas = [], 0, dict(estado or {}), quebrado, 0

    def linhas(self, marca):
        if self.quebrado:
            raise RuntimeError("SELECT ic_redes_artigo HTTP 503")
        return [dict(r) for r in self.rows if r["marca"] == marca]

    def inserir(self, linhas):
        for x in linhas:
            if any(r["marca"] == x["marca"] and r["url"] == x["url"] for r in self.rows):
                continue  # ignore-duplicates
            self.n += 1
            self.escritas += 1
            self.rows.append(dict({"id": self.n, "tentativas": 0, "peca_id": None, "motivo": None, "titulo": None,
                                   "visto_em": datetime.datetime(2026, 10, 1, 12, self.n % 60, tzinfo=datetime.timezone.utc).isoformat(),
                                   "pauta_em": None, "consumido_em": None, "atualizado_em": None}, **x))

    def atualizar(self, id_, campos):
        self.escritas += 1
        for r in self.rows:
            if r["id"] == id_:
                r.update(campos)
                if "atualizado_em" not in campos:
                    r["atualizado_em"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return [id_]

    def estado_pecas(self, ids):
        return {i: self.estado[i] for i in ids if i in self.estado}

    def por_url(self, url):
        return next((r for r in self.rows if r["url"] == url), None)


# ------------------------------------------------------------------------------------------------ 1. URL normalizada
print("== 1 · normalização (a mesma URL em variantes vira UMA) ==")
variantes = ["https://www.exemplo.test/insights/a1/", "http://exemplo.test/insights/a1", "https://EXEMPLO.test/insights/a1?utm=x",
             "https://exemplo.test/insights/a1#topo", "exemplo.test/insights/a1", "https://exemplo.test/insights/a1/index.html"]
ok("6 variantes da mesma página -> 1 URL normalizada", len({a.normalizar(v) for v in variantes}) == 1)
ok("controle: páginas diferentes continuam diferentes", a.normalizar("https://exemplo.test/insights/a1") != a.normalizar("https://exemplo.test/insights/a2"))
ok("nota_origem em texto livre ('dominio/caminho (fonte: ...)') é reconhecida",
   a.urls_citadas("exemplo.test/insights/a1 (fonte: Lei nº 14.300/2022)", ["exemplo.test"]) == {"https://exemplo.test/insights/a1"})

# ------------------------------------------------------------------------------------------------ 2. índice
print("\n== 2 · leitura do índice ==")
REGRAS_IDX = {"site": "https://exemplo.test", "dominios_origem": ["exemplo.test"],
              "artigos": {"indice": "https://exemplo.test/sitemap.xml", "padrao": "^/insights/[^/]+/$"}}
SITEMAP = ("<urlset><url><loc>https://exemplo.test/</loc></url><url><loc>https://exemplo.test/insights/</loc></url>"
           "<url><loc>https://exemplo.test/insights/a1</loc></url><url><loc>https://www.exemplo.test/insights/a1/</loc></url>"
           "<url><loc>https://exemplo.test/en/insights/a1-en</loc></url><url><loc>https://outro.test/insights/x</loc></url>"
           "<url><loc>https://exemplo.test/insights/a2</loc></url><url><loc>https://exemplo.test/p1</loc></url></urlset>")
r = a.listar_indice(REGRAS_IDX, ler=lambda u: SITEMAP)
ok("sitemap: só artigos PT do domínio, sem o índice, sem /en/, sem outro domínio, duplicado 1x",
   r["estado"] == "ok" and r["urls"] == ["https://exemplo.test/insights/a1", "https://exemplo.test/insights/a2"])
HTML_IDX = '<a href="/insights/a1">A1</a><a href="/insights/a2/">A2</a><a href="/insights/">todos</a><a href="#x">x</a>'
r = a.listar_indice(dict(REGRAS_IDX, artigos={"indice": "https://exemplo.test/insights/", "padrao": "^/insights/[^/]+/$"}), ler=lambda u: HTML_IDX)
ok("página de índice HTML (sem <loc>): links relativos resolvidos", r["urls"] == ["https://exemplo.test/insights/a1", "https://exemplo.test/insights/a2"])
r = a.listar_indice(REGRAS_IDX, ler=lambda u: "<urlset></urlset>")
ok("sitemap VAZIO -> estado 'vazio', 0 URL, sem exceção", r["estado"] == "vazio" and r["urls"] == [])


def cai(codigo):
    def f(u):
        raise urllib.error.HTTPError(u, codigo, "x", {}, None)
    return f


ok("503 -> 'indisponivel' (serviço)", a.listar_indice(REGRAS_IDX, ler=cai(503))["estado"] == "indisponivel")
ok("403 -> 'negado' (credencial/WAF, não queda)", a.listar_indice(REGRAS_IDX, ler=cai(403))["estado"] == "negado")


def timeout(u):
    raise urllib.error.URLError("timed out")


r = a.listar_indice(REGRAS_IDX, ler=timeout)
ok("site fora do ar (timeout) -> 'indisponivel' com o erro observado", r["estado"] == "indisponivel" and "timed out" in r["erro"])
ok("marca sem `artigos` no kit -> 'sem_config' (empty state, sem exceção)", a.listar_indice({"site": "x", "dominios_origem": []})["estado"] == "sem_config")

# ------------------------------------------------------------------------------------------------ 3. detecção idempotente
print("\n== 3 · detecção (idempotente, base x novo) ==")
reg = RegFalso()
d1 = a.detectar("mx", REGRAS_IDX, reg, usadas={"https://exemplo.test/insights/a2"}, ler=lambda u: SITEMAP)
ok("1ª execução: a1 novo, a2 base (já usado pelo estoque por seções)",
   (d1["novos"], d1["base"], reg.por_url("https://exemplo.test/insights/a1")["status"], reg.por_url("https://exemplo.test/insights/a2")["status"]) == (1, 1, "novo", "base"))
d2 = a.detectar("mx", REGRAS_IDX, reg, usadas=set(), ler=lambda u: SITEMAP)
ok("2ª execução: 0 linha nova (idempotente)", d2["novos"] + d2["base"] == 0 and len(reg.rows) == 2)
reg2 = RegFalso()
d3 = a.detectar("mx", REGRAS_IDX, reg2, usadas=set(), ler=lambda u: SITEMAP, gravar=False)
ok("gravar=False (QA do vigia): calcula 2 novos e NÃO escreve", d3["novos"] == 2 and reg2.escritas == 0)
c3 = a.ciclo("mx", REGRAS_IDX, reg2, gravar=False, ler=lambda u: SITEMAP, usadas=set(), existe_no_estoque=lambda *_: True)
ok("ciclo em QA: 'reservadas' inclui os artigos que ENTRARIAM (conta de seções igual à de produção), sem escrever",
   c3["reservadas"] == ["https://exemplo.test/insights/a1", "https://exemplo.test/insights/a2"] and reg2.escritas == 0 and c3["novos"] == 2)
SITEMAP3 = SITEMAP.replace("</urlset>", "<url><loc>https://exemplo.test/insights/a3</loc></url></urlset>")
d4 = a.detectar("mx", REGRAS_IDX, reg, usadas=set(), ler=lambda u: SITEMAP3)
ok("artigo novo publicado depois -> só ele entra", d4["novos"] == 1 and reg.por_url("https://exemplo.test/insights/a3")["status"] == "novo")
reg.por_url("https://exemplo.test/insights/a3")["visto_em"] = "2026-10-08T12:00:00+00:00"
ok("pendentes: o artigo mais recente primeiro", [x["url"] for x in a.pendentes("mx", reg)][0] == "https://exemplo.test/insights/a3")
dv = a.detectar("mx", REGRAS_IDX, reg, usadas=set(), ler=cai(503))
ok("site fora do ar na detecção: nada muda no registro, estado indisponível", dv["indice"] == "indisponivel" and len(reg.rows) == 3)
ok("agnóstico: outra marca com a mesma URL não colide (chave marca+url)",
   a.detectar("my", REGRAS_IDX, reg, usadas=set(), ler=lambda u: SITEMAP)["novos"] == 2 and len(reg.rows) == 5)

# PGRST102 (achado na prova ao vivo de 30/09): lote com linha 'base' (tem motivo) e 'novo' (sem) era recusado com 400
import supa as _supa  # noqa: E402
_cap = {}


class _Resp:
    def __init__(self, corpo):
        self.corpo = corpo

    def read(self):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *x):
        return False


def _urlopen_falso(req, timeout=None):
    _cap["corpo"] = json.loads(req.data)
    _cap["url"] = req.full_url
    _cap["prefer"] = req.headers.get("Prefer")
    return _Resp(b"[]")


_antes = (a.urllib.request.urlopen, _supa.URL, _supa.KEY)
try:
    a.urllib.request.urlopen, _supa.URL, _supa.KEY = _urlopen_falso, "https://banco.test", "chave-falsa"
    a.Registro(qa=True).inserir([{"marca": "mx", "url": "u1", "status": "base", "motivo": "já usado"}, {"marca": "mx", "url": "u2", "status": "novo"}])
    ok("inserir em lote: TODO objeto com as mesmas chaves (PGRST102) e qa carimbado",
       len({tuple(sorted(x)) for x in _cap["corpo"]}) == 1 and all(x["qa"] is True for x in _cap["corpo"]))
    ok("inserir é idempotente no banco (on_conflict marca,url,qa + ignore-duplicates)",
       "on_conflict=marca,url,qa" in _cap["url"] and "ignore-duplicates" in (_cap["prefer"] or ""))
finally:
    a.urllib.request.urlopen, _supa.URL, _supa.KEY = _antes

# ------------------------------------------------------------------------------------------------ 4. sincronização com o Conselho
print("\n== 4 · desfecho do Conselho -> registro (todo nó tem saída) ==")
agora = datetime.datetime(2026, 10, 9, 20, 0, tzinfo=datetime.timezone.utc)
rs = RegFalso(estado={"p-ok": "aprovado", "p-pub": "publicado", "p-rec": "recusado", "p-esc": "escalado"})
rs.inserir([{"marca": "mx", "url": u, "status": "novo"} for u in ("u-ok", "u-pub", "u-rec", "u-esc", "u-orfa", "u-orfa-nova", "u-rec3")])
for url, pid, h in (("u-ok", "p-ok", 5), ("u-pub", "p-pub", 5), ("u-rec", "p-rec", 5), ("u-esc", "p-esc", 5), ("u-orfa", "p-orfa", 40), ("u-orfa-nova", "p-orfa2", 3), ("u-rec3", "p-rec3", 5)):
    rr = rs.por_url(url)
    rr.update(status="pauta", peca_id=pid, pauta_em=(agora - datetime.timedelta(hours=h)).isoformat())
rs.estado["p-rec3"] = "expirado"
rs.por_url("u-rec3")["tentativas"] = 2
mud = a.sincronizar("mx", rs, existe_no_estoque=lambda m, p: False, agora=agora)
st = {u: rs.por_url(u)["status"] for u in ("u-ok", "u-pub", "u-rec", "u-esc", "u-orfa", "u-orfa-nova", "u-rec3")}
ok("aprovado e publicado -> consumido", st["u-ok"] == st["u-pub"] == "consumido")
ok("recusado -> volta a novo, tentativa 1, sem peca_id (novo ângulo)", st["u-rec"] == "novo" and rs.por_url("u-rec")["tentativas"] == 1 and rs.por_url("u-rec")["peca_id"] is None)
ok("3ª recusa -> descartado com motivo", st["u-rec3"] == "descartado" and "recusada" in rs.por_url("u-rec3")["motivo"])
ok("escalado -> continua em pauta (o vigia cuida da escalada parada)", st["u-esc"] == "pauta")
ok("pauta órfã há 40 h (peça não chegou) -> volta a novo", st["u-orfa"] == "novo" and "não chegou" in rs.por_url("u-orfa")["motivo"])
ok("controle: pauta de 3 h sem peça ainda -> continua em pauta", st["u-orfa-nova"] == "pauta")
ok("5 transições devolvidas (as 2 que esperam não contam)", len(mud) == 5)
res = a.resumo(rs.linhas("mx"), agora=agora)
ok("resumo conta consumidos/novos/descartados", (res["consumidos"], res["novos"], res["descartados"]) == (2, 2, 1))

# ------------------------------------------------------------------------------------------------ 5. gerador: artigo como fonte PRIORITÁRIA
print("\n== 5 · gerador com artigo novo na frente ==")
TMP = tempfile.mkdtemp(prefix="testa-artigos-")
TEXTO_ART = ("O artigo explica como a certificação de ativos declara recursos e reservas em código reconhecido; o prazo citado é de 90 dias. "
             "Conteúdo técnico detalhado do artigo para compor o texto-fonte inteiro. " * 6)
PAGINAS = {
    "https://exemplo.test/sitemap.xml": "<urlset>" + "".join("<url><loc>https://exemplo.test/%s</loc></url>" % p for p in ("p1", "p2", "insights/a1", "insights/a2")) + "</urlset>",
    "https://exemplo.test/insights/a1": "<html><head><title>A1</title></head><body><h1>Artigo um</h1><h2>Parte 1</h2><p>%s</p><h2>Parte 2</h2><p>%s</p></body></html>" % (TEXTO_ART, TEXTO_ART),
    "https://exemplo.test/insights/a2": "<html><head><title>A2</title></head><body><h1>Artigo dois</h1><h2>Parte</h2><p>%s</p></body></html>" % TEXTO_ART,
}
for i in (1, 2):
    PAGINAS["https://exemplo.test/p%d" % i] = "<html><head><title>P%d</title></head><body><h1>Página %d</h1>%s</body></html>" % (i, i, "".join(
        "<h2>Seção %d</h2><p>%s</p>" % (k, "A certificação de ativos declara recursos e reservas em código reconhecido; o prazo citado é de 90 dias. " * 5) for k in range(1, 4)))


def leitor(url):
    if url in PAGINAS:
        return PAGINAS[url]
    if url.endswith("/insights/sumiu"):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    raise FileNotFoundError(url)


PROMPTS = []


def motor_mock(prompt):
    PROMPTS.append(prompt)
    return json.dumps({"gancho": "Certificação de ativos: o prazo de 90 dias começa pela leitura do código.", "legenda": "A certificação de ativos declara recursos e reservas em código reconhecido.",
                       "cta": "Salve para consultar e compartilhe com quem decide.", "titulo": "Certificação de <em>ativos</em>", "rotulo": "Certificação",
                       "laminas": [{"rotulo": "Código", "texto": "Recursos e reservas em código reconhecido."}, {"rotulo": "Prazo", "texto": "Prazo citado: 90 dias.", "valor": "90", "unidade": "dias"},
                                   {"rotulo": "Leitura", "texto": "A leitura vem antes."}, {"rotulo": "Fonte", "texto": "Tudo conferido no artigo."}, {"rotulo": "Método", "texto": "Passo a passo."}],
                       "roteiro": ["Primeiro o código.", "Depois a leitura.", "Então o prazo.", "Salve e compartilhe.", "Leia na fonte."],
                       "alt_text": "Cartaz de texto sobre certificação de ativos.", "palavra_chave": "certificação de ativos"})


def monta_kit(marca):
    kit = os.path.join(TMP, "kit", marca)
    os.makedirs(kit)
    reg_kit = {"marca": marca, "tipo": "empresa", "nome": "Marca Teste", "site": "https://exemplo.test", "dominios_origem": ["exemplo.test"],
               "artigos": {"indice": "https://exemplo.test/sitemap.xml", "padrao": "^/insights/[^/]+/$"},
               "handle_instagram": "@marca.teste", "ig_user_id": None, "publicar": {"instagram": False, "linkedin": False, "horario_brt": "08:00"},
               "voz": {"tom": "sóbrio", "proibidos": [], "preferidos": ["método"]}, "temas": ["certificação"], "palavras_chave": ["certificação de ativos"],
               "hashtags": ["#certificacao", "#ativos", "#mineracao"], "fontes_oficiais_extra": [], "discricao": {"sigilo": False, "nao_citar": []},
               "collab": {"parceiros": [], "min_por_semana": 0, "max_por_semana": 0}, "email_escalada": "central@innconta.com.br"}
    json.dump(reg_kit, open(os.path.join(kit, "regras.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"nome": "Marca Teste", "arte_v2": {"categorias": {"marco": {"nome": "Marco"}, "metodo": {"nome": "Método"}}}},
              open(os.path.join(kit, "marca.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return reg_kit


ANTES = (g.RAIZ, estoque.RAIZ)
HOJE = datetime.date(2026, 10, 1)
try:
    g.RAIZ = TMP
    estoque.RAIZ = os.path.join(TMP, "estoque")
    rk = monta_kit("mx")
    reg = RegFalso()
    a.detectar("mx", rk, reg, usadas=a.usadas_do_estoque("mx", rk), ler=leitor)
    ok("detecção no kit temporário: 2 artigos novos", len(a.pendentes("mx", reg)) == 2)
    feitas, _ = g.gerar_lote("mx", 3, motor_mock, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg)
    pecas = sorted(estoque.listar("mx"), key=lambda p: int(p["_peca_id"].split("-")[-2]))
    ok("3 peças: as 2 PRIMEIRAS são dos artigos (prioridade), a 3ª de seção antiga",
       len(pecas) == 3 and [p.get("origem") for p in pecas] == ["artigo", "artigo", None] and "/insights/" not in pecas[2]["nota_origem"])
    ok("peça de artigo: nota_origem = URL do artigo e link na legenda",
       {p["nota_origem"] for p in pecas[:2]} == {"https://exemplo.test/insights/a1", "https://exemplo.test/insights/a2"}
       and all(re.sub(r"^https?://", "", p["nota_origem"]) in p["_corpo"] for p in pecas[:2]))
    ok("prompt do artigo pede RESUMO FIEL do artigo inteiro (as duas partes do texto chegam)",
       "RESUME FIELMENTE" in PROMPTS[0] and PROMPTS[0].count("Conteúdo técnico detalhado do artigo") >= 6)
    ok("controle: prompt de seção NÃO é de resumo de artigo", "RESUME FIELMENTE" not in PROMPTS[2])
    ok("registro: os 2 artigos em 'pauta' com o peca_id da peça gravada",
       all(reg.por_url(u)["status"] == "pauta" and os.path.isfile(estoque.caminho("mx", reg.por_url(u)["peca_id"]))
           for u in ("https://exemplo.test/insights/a1", "https://exemplo.test/insights/a2")))
    ok("seção de página de artigo NÃO vira peça (o texto do artigo nunca sai duas vezes)",
       sum(1 for p in pecas if "/insights/" in p["nota_origem"]) == 2)
    # 2ª execução: nada repete
    PROMPTS.clear()
    feitas2, _ = g.gerar_lote("mx", 2, motor_mock, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg, so_artigos=True)
    ok("2ª execução só de artigos: 0 peça (nenhum artigo novo; não recorre a seção)", feitas2 == [] and PROMPTS == [])
    feitas3, _ = g.gerar_lote("mx", 2, motor_mock, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg)
    ok("2ª execução normal: só seções, nenhuma de /insights/",
       len(feitas3) == 2 and all("/insights/" not in estoque.ler(estoque.caminho("mx", pid))["nota_origem"] for pid, _f, _c in feitas3))
    # Conselho aprova -> consumido; depois o artigo não volta nem por detecção nem por pendência
    reg.estado = {reg.por_url(u)["peca_id"]: "aprovado" for u in ("https://exemplo.test/insights/a1", "https://exemplo.test/insights/a2")}
    a.sincronizar("mx", reg, agora=datetime.datetime.now(datetime.timezone.utc))
    ok("Conselho aprovou -> 'consumido'", all(r["status"] == "consumido" for r in reg.rows))
    ok("artigo consumido: re-detecção não cria linha, não volta a pendente",
       a.detectar("mx", rk, reg, usadas=a.usadas_do_estoque("mx", rk), ler=leitor)["novos"] == 0 and a.pendentes("mx", reg) == [])

    # adversarial: número inventado -> sem peça, tentativa +1, continua novo; 3ª -> descartado
    rk2 = monta_kit("mz")
    reg2 = RegFalso()
    a.detectar("mz", rk2, reg2, usadas=set(), ler=leitor)

    def motor_mente(prompt):
        d = json.loads(motor_mock(prompt))
        d["legenda"] = "A certificação de ativos leva 45 dias e custa 12 milhões."
        return json.dumps(d)
    f, rec = g.gerar_lote("mz", 1, motor_mente, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg2, so_artigos=True)
    alvo = reg2.rows[0]["url"] if reg2.rows[0]["tentativas"] else reg2.rows[1]["url"]
    ok("artigo + motor que inventa número: nada gravado, tentativa 1, continua 'novo'",
       f == [] and estoque.listar("mz") == [] and reg2.por_url(alvo)["tentativas"] == 1 and reg2.por_url(alvo)["status"] == "novo")
    for _ in range(2):
        g.gerar_lote("mz", 1, motor_mente, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg2, so_artigos=True)
    ok("3 tentativas barradas -> 'descartado' com o motivo do gerador",
       any(r["status"] == "descartado" and "gerador" in (r["motivo"] or "") for r in reg2.rows))

    # adversarial: cota esgotada -> adia, o artigo continua 'novo' e sem tentativa gasta
    rk3 = monta_kit("mc")
    reg3 = RegFalso()
    a.detectar("mc", rk3, reg3, usadas=set(), ler=leitor)

    def sem_cota(prompt):
        raise g.CotaAdiada("429 em todos")
    g.gerar_lote("mc", 1, sem_cota, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg3)
    ok("sem cota gratuita: adiado, artigo segue 'novo' sem tentativa gasta", all(r["status"] == "novo" and r["tentativas"] == 0 for r in reg3.rows))

    # adversarial: página do artigo removida (404) -> descartado definitivo
    reg3.inserir([{"marca": "mc", "url": "https://exemplo.test/insights/sumiu", "status": "novo"}])
    reg3.por_url("https://exemplo.test/insights/sumiu")["visto_em"] = "2026-10-09T00:00:00+00:00"
    g.gerar_lote("mc", 1, motor_mock, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=reg3, so_artigos=True)
    ok("página do artigo saiu do site (404) -> 'descartado' com motivo", reg3.por_url("https://exemplo.test/insights/sumiu")["status"] == "descartado"
       and "saiu do site" in reg3.por_url("https://exemplo.test/insights/sumiu")["motivo"])

    # adversarial: banco fora -> artigo espera e NÃO é consumido por seção
    rk4 = monta_kit("mb")
    f4, _ = g.gerar_lote("mb", 6, motor_mock, hoje=HOJE, log=lambda *_: None, leitor=leitor, artigos_reg=RegFalso(quebrado=True))
    ok("banco fora: gera de seções e NENHUMA peça sai de página de artigo",
       len(f4) == 6 and all("/insights/" not in estoque.ler(estoque.caminho("mb", pid))["nota_origem"] for pid, _f, _c in f4))
    # controle: sem registro (chamada antiga), comportamento anterior intacto
    rk5 = monta_kit("ma")
    f5, _ = g.gerar_lote("ma", 3, motor_mock, hoje=HOJE, log=lambda *_: None, leitor=leitor)
    ok("controle: sem registro de artigos, o gerador segue como antes (seções, nenhuma peça 'origem: artigo')",
       len(f5) == 3 and not any(estoque.ler(estoque.caminho("ma", p)).get("origem") for p, _f, _c in f5))
finally:
    g.RAIZ, estoque.RAIZ = ANTES
    shutil.rmtree(TMP, ignore_errors=True)

# ------------------------------------------------------------------------------------------------ 6. contrato dos kits + agnosticidade
print("\n== 6 · contrato `artigos` em TODOS os kits e zero marca chumbada ==")
kits = sorted(glob.glob(os.path.join(RAIZ, "kit", "*", "regras.json")))
for caminho in kits:
    m = os.path.basename(os.path.dirname(caminho))
    rj = json.load(open(caminho, encoding="utf-8"))
    conf = rj.get("artigos") or {}
    host = re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", conf.get("indice") or "")
    try:
        re.compile(conf.get("padrao") or "")
        compila = bool(conf.get("padrao"))
    except re.error:
        compila = False
    ok("%s: artigos.indice no domínio da marca e artigos.padrao válido" % m,
       compila and any(host == d or host.endswith("." + d) for d in rj["dominios_origem"]))
fonte = open(os.path.join(RAIZ, "artigos.py"), encoding="utf-8").read().lower()
marcas_nomes = [os.path.basename(os.path.dirname(c)) for c in kits]
ok("artigos.py não cita nenhuma marca (PGA-01)", not [m for m in marcas_nomes if re.search(r"\b%s\b" % m, fonte)])
ok("artigos.py não chama IA nem provedor pago", "anthropic" not in fonte and "claude-" not in fonte)

print("\n%s" % ("TODAS AS PROVAS PASSARAM" if not FALHAS else "%d FALHA(S): %s" % (len(FALHAS), FALHAS)))
sys.exit(1 if FALHAS else 0)
