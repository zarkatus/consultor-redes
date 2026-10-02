# -*- coding: utf-8 -*-
"""Guarda de conteúdo do Consultor de Redes — falha FECHADA, sempre.

Roda em CIMA de toda peça antes dela sair de 'rascunho' para 'aguardando' (ir ao CVO) e de novo
antes de 'aprovado' virar 'publicado' (redes/publicar.py, 23/09/2026 — publicar é tarefa do
consultor, não mais um kit ao Roveda). Nunca decide sozinho que uma peça é segura:
decide sozinho que uma peça é SUSPEITA e bloqueia — a dúvida sempre pesa para o lado de não publicar.

Cobre (ordem do coordenador, 22/09/2026):
  1. nome do dono (todas as variantes)      4. números que parecem contagem própria
  2. telefone (padrão BR)                   5. promessa financeira
  3. e-mail pessoal                         6. termos proibidos ("cesta", "loteamento",
     e "cliente nomeado" (lista da base)        "parceiro dedicado/contratado/homologado/terceirizado")

Uso:
    from guarda import checar
    ok, motivos = checar(texto, nomes_clientes=["Fulano de Tal", ...])
"""
import json
import os
import re
import unicodedata

# 1 · nome do dono — todas as variantes usadas na casa (PU-01: persona única, nunca o nome próprio).
#     02/10/2026: o repositório passou a ser PÚBLICO, e listar aqui o nome e o domínio pessoal do dono publicaria
#     justamente o que a guarda existe para esconder. Os padrões vêm do Secret GUARDA_IDENTIDADE (JSON:
#     {"nomes": [regex sobre texto normalizado], "dominios_pessoais": ["dominio"], "amostras": [texto que DEVE barrar]}).
#     Sem ele a guarda falha FECHADA: toda peça é barrada com o motivo, nunca liberada sem a checagem do nome.
def _identidade():
    try:
        d = json.loads(os.environ.get("GUARDA_IDENTIDADE") or "{}")
    except ValueError:
        d = {}
    nomes = [p for p in (d.get("nomes") or []) if isinstance(p, str) and p.strip()]
    dominios = {x.lower() for x in (d.get("dominios_pessoais") or []) if isinstance(x, str) and x.strip()}
    return nomes, dominios


_NOME_DONO, _DOMINIOS_PESSOAIS = _identidade()

# 2 · telefone BR: com/sem DDI 55, com/sem DDD entre parênteses, com/sem hífen
_TELEFONE = re.compile(
    r"(?:\+?55\s*)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}"
)

# 3 · e-mail pessoal (domínios pessoais do dono, de GUARDA_IDENTIDADE — nunca sai em peça de rede)
_EMAIL_QUALQUER = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.I)

# 4 · contagem própria disfarçada de prova social ("128 clientes", "40 contratos fechados")
_CONTAGEM_PROPRIA = re.compile(
    r"\b\d{1,6}\s*(clientes?|contratos?|projetos?|empresas atendidas?|obras?|parceiros?)\b", re.I
)

# 5 · promessa financeira — número de desempenho que a casa nunca divulga sem escala (PU-01/feedback prova social)
_PROMESSA_FINANCEIRA = re.compile(
    r"(\d+(?:[.,]\d+)?\s*%\s*(de\s+)?(economia|desconto|redução))"
    r"|(\bR\$\s*[\d.,]+\s*(recuperados?|economizados?|de\s+cr[eé]dito))",
    re.I,
)

# 6 · termos e vocabulário proibidos (feedback-vocabulario-cesta-vulgar / feedback-vocabulario-loteamento-empobrece
#     / feedback-palavra-casa-banida-usar-innconta, CVO 23/09/2026: "casa" nunca em texto que
#     terceiro lê — usar "InnConta" ou reescrever sem o sujeito. \bcasas?\b pega singular e plural
#     ("casa", "da casa", "casas") sem casar "casamento"/"casal"/"casaco" (boundary de \b exige
#     não-letra logo após); não há uso legítimo de "casas" em peça pra terceiro, então plural
#     também barra sempre, sem exceção de sentido.
_TERMOS_PROIBIDOS = [
    r"\bcestas?\b",
    r"\bloteamentos?\b",
    r"parceiro\s+(dedicado|contratado|homologado|terceirizado)",
    r"\bcasas?\b",
    r"\bbots?\b",
    r"\bagentes?\s+(virtual|virtuais|autonomos?|inteligentes?|de\s+ia|de\s+inteligencia)",
]

# mensagem clara por padrão de _TERMOS_PROIBIDOS (senão cai no genérico "termo proibido detectado (%s)")
_MENSAGEM_TERMO_PROIBIDO = {
    r"\bbots?\b": "'bot' para o servico: o nome de todo mecanismo automatizado e 'Consultor de X' (nunca agente/bot)",
    r"\bagentes?\s+(virtual|virtuais|autonomos?|inteligentes?|de\s+ia|de\s+inteligencia)":
        "'agente' de IA/virtual para o servico: usar 'Consultor de X'",
    r"\bcasas?\b": "palavra 'casa' banida em texto que terceiro lê — usar 'InnConta' ou reescrever sem o "
                    "sujeito (feedback-palavra-casa-banida-usar-innconta, CVO 23/09/2026)",
}


# 7 · link de frente do texto (25/09/2026): 17 perguntas da mesa foram materializadas com o link final
# apontando para a frente ERRADA (contas-consumo -> /frente/energia etc.) e nem o Conselho nem a prova
# pegaram. Checagem DETERMINÍSTICA: o slug de `innconta.com.br/frente/<slug>` tem de existir no
# sitemap do site e, quando a `nota_origem` da peça nomeia a frente, tem de ser a mesma.
_LINK_FRENTE = re.compile(r"innconta\.com\.br/frente/([a-z0-9\-]+)", re.I)
_FRENTES_FALLBACK = frozenset((
    "ambiental auditoria beneficios carbono comex compras concessoes conformidade construcao contabilidade "
    "contas-consumo controladoria credito energia engenharia estrategia feiras fiscal folha funding gente imagem "
    "imobiliario incentivos infra-digital juridico mercado mineracao passivo patrimonial recebiveis recovery "
    "reg-bancaria reg-imobiliaria reg-tributaria seguro sucessao-ma tecnologia territorio").split())


def frentes_validas(sitemap=None):
    """Slugs de /frente/ existentes no site: lê o sitemap.xml da raiz do repositório (fonte viva);
    sem o arquivo, usa a lista fixa (verificada em 25/09/2026)."""
    caminho = sitemap or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sitemap.xml")
    try:
        with open(caminho, encoding="utf-8") as f:
            achados = set(re.findall(r"/frente/([a-z0-9\-]+)</loc>", f.read()))
        if achados:
            return frozenset(achados)
    except OSError:
        pass
    return _FRENTES_FALLBACK


def checar_link_frente(texto, nota_origem=None):
    """Devolve lista de motivos (vazia = ok). `nota_origem`: campo do frontmatter (ou as URLs dele)."""
    motivos, validas = [], frentes_validas()
    slugs = [m.lower() for m in _LINK_FRENTE.findall(texto or "")]
    for sl in dict.fromkeys(slugs):
        if sl not in validas:
            motivos.append("link innconta.com.br/frente/%s: essa frente não existe no site" % sl)
    esperadas = [m.lower() for m in _LINK_FRENTE.findall(nota_origem or "")]
    esperadas += [m.lower() for m in re.findall(r"(?<![\w./])frente/([a-z0-9\-]+)", nota_origem or "")]
    if esperadas:
        for sl in dict.fromkeys(slugs):
            if sl in validas and sl not in esperadas:
                motivos.append("link aponta para /frente/%s mas o tema da peça (nota_origem) é /frente/%s" % (sl, esperadas[0]))
    return motivos


def _normaliza(txt):
    """minúsculo, sem acento — pra regex não perder variante por acentuação."""
    n = unicodedata.normalize("NFKD", txt or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    return n.lower()


def checar(texto, nomes_clientes=None, imagem_alt=None, marca_nome="InnConta", nota_origem=None, regras=None):
    """Devolve (ok: bool, motivos: list[str]). ok=False barra a peça — nunca publica na dúvida.

    nomes_clientes: lista de nomes reais da base (consultada por quem chama, via Supabase, nunca
    aqui dentro — este módulo não fala com o banco, só compara strings que recebe).
    marca_nome: nome da própria marca (agnóstico — quem chama passa o nome certo por marca) —
    nunca barra por ele mesmo aparecer na peça (ele SEMPRE aparece, é a própria casa falando)."""
    motivos = []
    alvo = "%s\n%s" % (texto or "", imagem_alt or "")
    norm = _normaliza(alvo)
    grupo = _nomes_do_grupo()  # citar OUTRA empresa do grupo e PERMITIDO (CVO 29/09/2026)
    dominios_ok = _dominios_do_grupo() | {"innconta.com.br"}
    if regras:
        dominios_ok |= {d.lower() for d in regras.get("dominios_origem", [])}
        mail = (regras.get("email_escalada") or "").split("@")[-1].lower()
        if mail:
            dominios_ok.add(mail)

    if not _NOME_DONO:
        motivos.append("identidade da guarda ausente (Secret GUARDA_IDENTIDADE): falha fechada, nome do dono não conferido")
    for i, pad in enumerate(_NOME_DONO, 1):
        if re.search(pad, norm):
            # o padrão em si nunca vai à mensagem: ela pode acabar num log (o repositório é público)
            motivos.append("nome do dono detectado (variante %d de GUARDA_IDENTIDADE)" % i)

    if _TELEFONE.search(alvo):
        motivos.append("padrão de telefone detectado")

    for m in _EMAIL_QUALQUER.finditer(alvo):
        dominio = m.group(0).split("@", 1)[1].lower()
        if any(dominio == d or dominio.endswith("." + d) for d in _DOMINIOS_PESSOAIS):
            motivos.append("e-mail pessoal do dono detectado")
        elif not any(dominio == d or dominio.endswith("." + d) for d in dominios_ok):
            # qualquer e-mail pessoal-parecido (fora dos domínios institucionais da casa) também barra
            motivos.append("e-mail fora do domínio institucional detectado (%s)" % dominio)

    if _CONTAGEM_PROPRIA.search(norm):
        motivos.append("número que parece contagem própria (prova social sem escala — feedback-prova-social-so-com-escala)")

    if _PROMESSA_FINANCEIRA.search(alvo):
        motivos.append("promessa financeira detectada")

    for pad in _TERMOS_PROIBIDOS:
        if re.search(pad, norm):
            msg = _MENSAGEM_TERMO_PROIBIDO.get(pad, "termo proibido detectado (%s)" % pad)
            motivos.append(msg)

    motivos += checar_link_frente(texto, nota_origem)
    motivos += checar_promessa_resultado(alvo)
    if regras:
        motivos += checar_marca(alvo, regras)

    for nome in (nomes_clientes or []):
        nome = (nome or "").strip()
        # nome curto (< 8 chars) vira falso positivo certo contra o próprio vocabulário da casa —
        # bateu de verdade em produção (22/09/2026): um registro "InnC..." na base casava com
        # "InnConta"/"innconta.com.br", presentes em toda peça. Nome de cliente real, para bloquear
        # de verdade, precisa ser específico — comprimento mínimo maior, e nunca um PREFIXO do
        # nome da própria marca (a marca sempre aparece nas peças, isso NUNCA pode barrar).
        if len(nome) < 8:
            continue
        n_norm = _normaliza(nome)
        m_norm = _normaliza(marca_nome)
        if m_norm.startswith(n_norm) or n_norm.startswith(m_norm):
            continue
        if any(g == n_norm or g in n_norm or n_norm in g for g in grupo):
            continue  # empresa do grupo na lista de clientes: collab e citacao sao permitidas
        if n_norm in norm:
            motivos.append("nome de cliente/parceiro real da base detectado (%s)" % nome)

    return (len(motivos) == 0, motivos)


def _nomes_do_grupo():
    try:
        import marcas
        return marcas.nomes_do_grupo()
    except Exception:
        return set()


def _dominios_do_grupo():
    try:
        import marcas
        return marcas.dominios_do_grupo()
    except Exception:
        return set()


# 8 · promessa de RESULTADO (v2, 29/09/2026): a v1 so pegava "% de economia"; garantia/ganho certo/sem risco
# tambem e promessa (risco juridico e reputacional).
_PROMESSA_RESULTADO = re.compile(
    r"\b(garantimos|garantia\s+de\s+(resultado|retorno|ganho|economia|lucro|aprovacao|exito)|"
    r"(resultado|retorno|lucro|ganho|exito|economia)\s+garantid[oa]s?|sem\s+risco|risco\s+zero|100\s*%\s*(seguro|garantid)|"
    r"voce\s+(vai|ira)\s+(economizar|ganhar|lucrar|recuperar)|certeza\s+de\s+(ganho|resultado|retorno))\b")


def checar_promessa_resultado(texto):
    m = _PROMESSA_RESULTADO.search(_normaliza(texto))
    return ["promessa de resultado/garantia detectada (%r): risco juridico e reputacional" % m.group(0)] if m else []


def checar_marca(texto, regras):
    """Regras da ENTIDADE (regras.json): vocabulario proibido da voz e nomes que nao podem ser citados. Comparacao por
    palavra inteira, sem acento."""
    motivos = []
    norm = _normaliza(texto)
    for termo in (regras.get("voz") or {}).get("proibidos") or []:
        t = _normaliza(str(termo)).strip()
        padrao = r"\s+".join(re.escape(w) + r"(?:s|es)?" for w in t.split())  # tolera plural em cada palavra
        if t and re.search(r"(?<![a-z0-9])" + padrao + r"(?![a-z0-9])", norm):
            motivos.append("termo proibido pela voz de %s: %r" % (regras.get("nome") or regras.get("marca"), termo))
    for nome in (regras.get("discricao") or {}).get("nao_citar") or []:
        t = _normaliza(str(nome)).strip()
        if t and re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", norm):
            motivos.append("nome que a discricao de %s manda nao citar: %r" % (regras.get("nome") or regras.get("marca"), nome))
    if (regras.get("discricao") or {}).get("sigilo"):
        motivos += checar_sigilo(texto, regras)
    return motivos


# 9 · SIGILO (marca com discricao.sigilo=true, ex.: inncorpower): nenhum numero OPERACIONAL — potencia, taxa,
# investimento, retorno, area, valor. Deterministico; o revisor de risco confere o resto (numero por extenso etc.).
_UNIDADE_OPERACIONAL = (r"mw[acph]?|gw[hp]?|kw[hp]?|mwh|gwh|twh|ha|hectares?|m2|m²|km2|km²|%|por\s*cento|"
                        r"milh(?:ao|oes)|bilh(?:ao|oes)|mil|reais|usd|us\$|dolares?|anos|meses")
_SIGILO_NUMERO = re.compile(r"\d[\d.,]*\s*(?:" + _UNIDADE_OPERACIONAL + r")(?![a-z0-9])")
_SIGILO_TERMO_NUM = re.compile(
    r"\b(tir|vpl|capex|opex|payback|ebitda|wacc|lcoe|fator\s+de\s+capacidade)\b[^.\n]{0,40}?\d|"
    r"\d[^.\n]{0,40}?\b(tir|vpl|capex|opex|payback|ebitda|wacc|lcoe)\b")
_SIGILO_MOEDA = re.compile(r"r\$\s*\d|us\$\s*\d|\busd\s*\d")


def checar_sigilo(texto, regras=None):
    norm = _normaliza(texto)
    achados = []
    for rx in (_SIGILO_MOEDA, _SIGILO_NUMERO, _SIGILO_TERMO_NUM):
        m = rx.search(norm)
        if m:
            achados.append(m.group(0).strip())
    if not achados:
        return []
    return ["sigilo operacional: numero de operacao (%s) — marca com discricao.sigilo nao publica MW/TIR/CAPEX/payback/valor/percentual"
            % "; ".join(dict.fromkeys(achados))[:120]]


def checar_fontes(fontes, regras):
    """Cada `fontes[].url` tem de ser de dominio permitido da marca (proprio + oficiais extras + base gov.br/jus.br/leg.br)."""
    import marcas
    ok = marcas.dominios_permitidos(regras)
    motivos = []
    for f in fontes or []:
        url = (f or {}).get("url") or ""
        if url and not marcas.host_permitido(url, ok):
            motivos.append("fonte de dominio nao permitido (%s): usar fonte oficial ou o site da marca" % url[:90])
    return motivos


SELOS_CATEGORIA = {"pergunta": "Pergunta da mesa", "oficio": "Ofício", "marco": "Marco", "metodo": "Método", "feriado": "Feriado"}


def _spec_da_arte(peca, marca):
    """Spec da arte v2 da peça (`estoque/<marca>/_arte/pecas-v2.json`, chave = peca_id sem `-instagram`) ou {}."""
    pid = str(peca.get("_peca_id") or "")
    if not pid:
        return {}
    slug = pid[:-len("-instagram")] if pid.endswith("-instagram") else pid
    arq = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estoque", marca, "_arte", "pecas-v2.json")
    try:
        import json
        with open(arq, encoding="utf-8") as fh:
            return json.load(fh).get(slug) or {}
    except (OSError, ValueError):
        return {}


def checar_arte(peca, marca="innconta"):
    """Trava da arte v2 (ordem do CVO, 25/09/2026: "não podemos ter postagens só com textos"; rodada 2: foto de
    fundo + categorias). Devolve a lista de motivos (vazia = ok). Toda peça estática de Instagram (imagem_feed,
    imagem, carrossel) declara no frontmatter `arte: v2`, `ilustracao:`, `foto:` (arquivo existente em
    redes/kit/<marca>/fotos/) e `categoria:` (pergunta|oficio|marco|metodo|feriado), e o `texto_arte` (o que está
    na imagem) abre com o selo da categoria; sem isso NÃO publica. Vídeo e texto (LinkedIn) ficam fora.

    Multimarca (30/09/2026): `ilustracao`/`foto` valem do frontmatter OU do spec que renderiza a arte
    (`estoque/<marca>/_arte/pecas-v2.json`, o gerador grava lá). A exigência segue o kit da marca: marca SEM pasta
    `kit/<marca>/ilustracoes/` tem o símbolo (`kit/<marca>/logo.svg`) como herói; marca SEM foto com crédito conferido
    em `kit/<marca>/fotos/` sai com fundo sólido (arte_v2._fundo). Marca que TEM o recurso continua obrigada a usá-lo
    (InnConta inalterada). Nunca é "só texto": sem ilustração nem símbolo, barra."""
    canal = str(peca.get("canal") or "").strip().lower()
    formato = str(peca.get("formato") or "").strip().lower()
    if canal != "instagram" or formato in ("video", "texto", ""):
        return []
    motivos = []
    if str(peca.get("arte") or "").strip().lower() != "v2":
        return ["peça de Instagram sem `arte: v2` no frontmatter (imagem só com texto não publica)"]
    kit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit", marca)
    spec = _spec_da_arte(peca, marca)
    ilustracao = str(peca.get("ilustracao") or spec.get("ilustracao") or "").strip()
    if not ilustracao:
        if os.path.isdir(os.path.join(kit, "ilustracoes")):
            motivos.append("`arte: v2` sem `ilustracao:` (toda peça leva a ilustração da sua frente)")
        elif not os.path.isfile(os.path.join(kit, "logo.svg")):
            motivos.append("marca sem ilustração e sem símbolo (redes/kit/%s/logo.svg): a arte seria só texto" % marca)
    foto = str(peca.get("foto") or spec.get("foto") or "").strip()
    fotos_dir = os.path.join(kit, "fotos")
    tem_fotos = os.path.isdir(fotos_dir) and any(f.endswith(".jpg") for f in os.listdir(fotos_dir))
    if not foto:
        if tem_fotos:
            motivos.append("sem `foto:` (toda peça leva foto de fundo sob película)")
    elif not os.path.isfile(os.path.join(fotos_dir, foto + ".jpg")):
        motivos.append("`foto: %s` não existe em redes/kit/%s/fotos/" % (foto, marca))
    cat = str(peca.get("categoria") or "").strip().lower()
    if cat not in SELOS_CATEGORIA:
        motivos.append("`categoria:` ausente ou fora de pergunta|oficio|marco|metodo|feriado")
    else:
        ta = _normaliza(str(peca.get("texto_arte") or "")).strip()
        if not ta.startswith(_normaliza(SELOS_CATEGORIA[cat])):
            motivos.append("o selo da arte (`texto_arte`) não bate com `categoria: %s`" % cat)
    return motivos

def clientes_da_base(url, service_role, timeout=20):
    """Consulta ic_conta/ic_lead/ic_parceiro por nomes reais — só para comparar, NUNCA loga a
    lista inteira (PAR-01: segredo/dado sensível não solto em log). Falha fechada: erro de rede
    devolve lista vazia + aviso, e quem chama decide se roda sem essa camada (nunca bloqueia
    silenciosamente a checagem inteira)."""
    import json
    import urllib.request

    nomes = []
    consultas = [
        "ic_conta?select=razao_social,nome_fantasia&limit=2000",
        "ic_lead?select=nome&limit=2000",
        "ic_parceiro?select=nome&limit=2000",
    ]
    for q in consultas:
        try:
            req = urllib.request.Request(
                url.rstrip("/") + "/rest/v1/" + q,
                headers={"apikey": service_role, "Authorization": "Bearer " + service_role, "Accept": "application/json"},
            )
            rows = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            for r in rows:
                for v in r.values():
                    if v and isinstance(v, str) and len(v) >= 4:
                        nomes.append(v)
        except Exception:
            continue  # falha fechada por consulta: segue com o que já tem, nunca derruba tudo
    return nomes


if __name__ == "__main__":
    # auto-teste rápido de fumaça (a bateria real está em redes/testar_guarda.py)
    ok, m = checar("Nota InnConta nº 08 — a regularidade não admite meio-termo.")
    print("peça limpa:", ok, m)
    ok, m = checar("Chame no WhatsApp 11 90000-0000 e garanta 30% de economia.")
    print("peça suja:", ok, m)
