# -*- coding: utf-8 -*-
"""Os 5 revisores do Conselho Editorial (CVO 23/09/2026: "revisão e aprovação não humana").

Cada revisor: prompt FIXO e curto, temperatura 0, resposta JSON
    {"passa": bool, "nota": 1-5, "motivos": [str], "trechos": [str]}
validada por `validar()`. Resposta fora do formato (vazia, prosa sem objeto JSON, campos errados)
primeiro vai para OUTRO provedor da cadeia (24/09/2026, dívida do PR #55); só quando nenhum
responde no formato, ou a cadeia inteira falha, é REPROVA (falha fechada) com `invalida=True` — o
conselho nunca aprova no escuro.

Revisores (modelo por papel em modelos.MODELOS — famílias distintas):
  fato       FATO E FONTE — só vale o que está na página de origem (baixada ao vivo) ou nas fontes
             oficiais listadas na peça; número/afirmação fora delas reprova.
  voz        VOZ E RÉGUA — vocabulário e tom da InnConta (memórias de régua do CVO).
  visual     VISUAL — PNG renderizado + cópia a 390 px: legibilidade, corte, acento solto, marca
             de terceiro, rosto.
  risco      RISCO — jurídico, reputacional, político, exposição de cliente/dono.
  editorial  FORÇA EDITORIAL — gancho, autoridade, clareza; passa só com nota >= 4."""
import json
import re

import insumos
import marcas
import modelos

REVISORES = ("fato", "voz", "visual", "risco", "editorial")
NOTA_MINIMA_EDITORIAL = 4
MAX_TENTATIVAS_FORMATO = 4  # 1ª + no máximo 3 provedores a mais (cf, groq, gemini, openrouter)

_FORMATO = ('Responda SOMENTE com um objeto JSON, sem texto fora dele: '
            '{"passa": true|false, "nota": 1-5, "motivos": ["..."], "trechos": ["trecho exato da peça"]}. '
            'Se reprovar, cada motivo diz O QUE está errado e "trechos" copia o trecho exato.')

PROMPTS = {
    "fato": (
        "Você é o revisor FATO E FONTE de uma peça de rede social da InnConta. Julgue SOMENTE contra "
        "as FONTES fornecidas (texto da página de origem e fontes oficiais listadas). NÃO use seu "
        "conhecimento próprio, nem para aprovar nem para reprovar. Confira cada ELEMENTO VERIFICÁVEL da "
        "peça: número, percentual, valor, data, prazo, norma/lei/artigo, estatística, pesquisa ou "
        "levantamento citado, fato atribuído a alguém. Cada um tem de estar nas fontes (mesmo com outras "
        "palavras ou por extenso). Um único elemento verificável fora das fontes reprova — cite o trecho. "
        "Frases gerais sem número nem norma (tese, método, prática comum, opinião) NÃO são motivo de "
        "reprovação. Nota 5 = todo elemento verificável sustentado; 1 = dado inventado. " + _FORMATO),
    "voz": (
        "Você é o revisor VOZ E RÉGUA da InnConta (empresa de gestão de contas e regularidade de "
        "empresas, tom sóbrio e sofisticado). Reprove se a peça tiver QUALQUER um destes: "
        "(1) a palavra 'casa' ou qualquer disfarce dela para se referir à empresa (grafia quebrada, "
        "símbolos, sinônimos que tratem a empresa como moradia: 'lar', 'nossa morada') — 'dentro do contrato', 'dentro da empresa' e afins NÃO são disfarce — o certo é 'InnConta' "
        "ou frase sem sujeito; (2) 'agente' ou 'bot' para o serviço; (3) gíria, emoji, frase motivacional, "
        "tom de vendedor ou de manual que manda o leitor fazer algo; (4) mais de um travessão; "
        "(5) 'Nota InnConta nº' como título ou abertura (só pode aparecer como rodapé); (6) 'crédito' "
        "apresentado como bom sem qualificar (crédito barato, linha subsidiada); (7) 'cesta', "
        "'loteamento', 'parceiro contratado/homologado/terceirizado' ou revelar que terceiros executam; "
        "(8) apresentar a InnConta por uma lista curta e fechada de frentes. Frases com elipse, curtas e "
        "carregadas são o padrão. " + _FORMATO),
    "visual": (
        "Você é o revisor VISUAL de uma arte de rede social. Recebe a arte renderizada e a mesma arte "
        "reduzida a 390 px (tela de celular). Reprove se houver: texto ilegível a 390 px (pequeno demais, "
        "contraste baixo, borrado), texto cortado ou saindo da borda, letra ou acento solto/deslocado, "
        "palavras sobrepostas, logotipo ou marca de terceiros, rosto de pessoa, erro de digitação visível. "
        "Descreva o que vê antes de decidir. Nota 5 = impecável a 390 px. " + _FORMATO),
    "risco": (
        "Você é o revisor de RISCO de uma peça pública da InnConta. Reprove se houver: promessa de "
        "resultado ou garantia (economia, ganho, prazo garantido); orientação jurídica/tributária "
        "individual; acusação a pessoa, empresa ou órgão; tema partidário ou político; nome ou caso "
        "identificável de cliente; número próprio da operação (quantidade de clientes, contratos, "
        "valores negociados); nome de pessoa física da empresa ou dado pessoal (telefone, e-mail "
        "pessoal); afirmação que exponha a empresa a processo. Citar lei ou norma pública não é risco. "
        + _FORMATO),
    "editorial": (
        "Você é o revisor de FORÇA EDITORIAL. O objetivo das redes da InnConta é AUTORIDADE sobre o que "
        "faz (fiscal, energia, recebíveis, patrimônio, regularidade), não alcance nem venda. Confira 4 "
        "critérios, um a um: (A) a PRIMEIRA frase traz um fato concreto (número, prazo, data, norma ou "
        "cena reconhecível), e não uma tese abstrata ou genérica; (B) a peça cita norma, lei, resolução "
        "ou dado verificável; (C) aponta um erro comum ou um método; (D) uma ideia só, sem enchimento nem "
        "repetição. nota = 1 + número de critérios atendidos. passa = nota >= 4. Nos motivos, diga quais "
        "critérios faltaram. " + _FORMATO),
}


REGRAS_DO_GRUPO = (
    "REGRAS COMUNS DO GRUPO (valem para toda marca): (a) nunca a palavra 'casa' (nem disfarce como 'lar', 'nossa morada') "
    "para a empresa; (b) nunca 'agente' ou 'bot' para um servico automatizado (o nome e 'Consultor de X'); (c) sem emoji; "
    "(d) sem promessa de resultado ou garantia; (e) nada fabricado: numero, caso, depoimento ou pesquisa que nao esteja na "
    "fonte; (f) sem nome de cliente; (g) sem numero proprio de operacao (quantidade de clientes, contratos, valores). "
    "CITAR OUTRA EMPRESA DO GRUPO (%(grupo)s) E PERMITIDO e NAO e defeito: as empresas do grupo aparecem juntas e fazem collab.")


def _lista(xs, vazio="(nenhum)"):
    return ", ".join(str(x) for x in xs) if xs else vazio


def _contexto_marca(regras):
    grupo = sorted(marcas.nomes_do_grupo())
    voz = regras.get("voz") or {}
    return {"nome": regras.get("nome") or regras.get("marca"), "grupo": _lista(grupo),
            "tom": voz.get("tom") or "sobrio e claro",
            "proibidos": _lista(voz.get("proibidos")),
            "extras": " ".join("(%d) %s;" % (i + 5, e) for i, e in enumerate(voz.get("regras_extra") or [])),
            "temas": _lista(regras.get("temas"), "os temas da marca"),
            "nao_citar": _lista((regras.get("discricao") or {}).get("nao_citar")),
            "sigilo": bool((regras.get("discricao") or {}).get("sigilo"))}


def construir_prompt(papel, regras=None):
    """Prompt do revisor para a MARCA (voz, temas, proibidos e discricao do regras.json) + regras comuns do grupo.
    Sem regras = InnConta (compatibilidade)."""
    regras = regras or marcas.carregar("innconta")
    c = _contexto_marca(regras)
    grupo = REGRAS_DO_GRUPO % c
    if papel == "fato":
        return (
            "Voce e o revisor FATO E FONTE de uma peca de rede social da %(nome)s. Julgue SOMENTE contra "
            "as FONTES fornecidas (texto da pagina de origem, fontes oficiais baixadas ao vivo e as listadas). NAO use seu "
            "conhecimento proprio, nem para aprovar nem para reprovar. Confira cada ELEMENTO VERIFICAVEL da "
            "LEGENDA E DO TEXTO DA ARTE: numero, percentual, valor, data, prazo, norma/lei/artigo, estatistica, pesquisa ou "
            "levantamento citado, fato atribuido a alguem. Cada um tem de estar nas fontes (mesmo com outras "
            "palavras ou por extenso). Um unico elemento verificavel fora das fontes reprova, inclusive se estiver so na "
            "ARTE: cite o trecho. Frases gerais sem numero nem norma (tese, metodo, pratica comum, opiniao) NAO sao motivo de "
            "reprovacao. Nota 5 = todo elemento verificavel sustentado; 1 = dado inventado. " % c) + _FORMATO
    if papel == "voz":
        return (
            "Voce e o revisor VOZ E REGUA da %(nome)s. Tom da marca: %(tom)s "
            "Reprove se a peca tiver QUALQUER um destes: (1) palavra ou disfarce proibido pelo grupo (ver regras comuns); "
            "(2) vocabulario proibido da marca: %(proibidos)s; (3) giria, emoji, frase motivacional, tom de vendedor ou de manual "
            "que manda o leitor fazer algo (uma chamada final para salvar, compartilhar ou comentar NAO e defeito); "
            "(4) mais de um travessao; %(extras)s Frases com elipse, curtas e carregadas sao o padrao. " % c
            + grupo + " ") + _FORMATO
    if papel == "risco":
        extra = ""
        if c["sigilo"]:
            extra = ("SIGILO OPERACIONAL desta marca: reprove QUALQUER numero de operacao (potencia MW/MWac/MWp, TIR, CAPEX, OPEX, "
                     "payback, VPL, area, investimento, valor em R$, percentual de retorno), mesmo por extenso ou arredondado. ")
        return (
            "Voce e o revisor de RISCO de uma peca publica da %(nome)s. Reprove se houver: promessa de "
            "resultado ou garantia (economia, ganho, prazo garantido); orientacao juridica/tributaria "
            "individual; acusacao a pessoa, empresa ou orgao; tema partidario ou politico; nome ou caso "
            "identificavel de CLIENTE; numero proprio da operacao (quantidade de clientes, contratos, "
            "valores negociados); nome de pessoa fisica da empresa ou dado pessoal (telefone, e-mail "
            "pessoal); afirmacao que exponha a empresa a processo; nomes que a marca manda nao citar: %(nao_citar)s. " % c
            + extra + "Citar lei ou norma publica nao e risco. Citar outra empresa do grupo (%(grupo)s) tambem NAO e risco. " % c) + _FORMATO
    if papel == "editorial":
        return (
            "Voce e o revisor de FORCA EDITORIAL. O objetivo das redes da %(nome)s e AUTORIDADE sobre o que "
            "faz (%(temas)s), nao alcance nem venda. Confira 4 "
            "criterios, um a um: (A) a PRIMEIRA frase traz um fato concreto (numero, prazo, data, norma ou "
            "cena reconhecivel), e nao uma tese abstrata ou generica; (B) a peca cita norma, lei, resolucao "
            "ou dado verificavel; (C) aponta um erro comum ou um metodo; (D) uma ideia so, sem enchimento nem "
            "repeticao. Uma chamada final para salvar/compartilhar/comentar e hashtags NAO sao enchimento. nota = 1 + numero de "
            "criterios atendidos. passa = nota >= 4. Nos motivos, diga quais criterios faltaram. " % c) + _FORMATO
    if papel in ("visual", "visual2"):
        return PROMPTS["visual"]
    return PROMPTS[papel]


def extrair_json(texto, exige_chave=None):
    """Extrator TOLERANTE (24/09/2026, dívida do PR #55): devolve o PRIMEIRO objeto JSON válido
    (dict) achado no texto — resposta pura, cercada por ```json```, ou embutida em prosa ("Segue a
    análise: {...}"). Com `exige_chave`, só vale objeto que tenha essa chave (evita pegar um
    exemplo solto no meio da prosa). Nada achado = None (quem chama trata como falha de FORMATO,
    nunca como voto)."""
    if not isinstance(texto, str):
        return None
    dec = json.JSONDecoder()
    i = texto.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(texto, i)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and (exige_chave is None or exige_chave in obj):
            return obj
        i = texto.find("{", i + 1)
    return None


def validar(bruto):
    """Devolve (voto: dict, erro: str|None). Tem de haver UM objeto JSON com os 4 campos, tipos
    exatos: a resposta pura, cercada por ```json```, ou (extrator tolerante, dívida do PR #55) o
    primeiro objeto com a chave "passa" embutido em prosa. Prosa sem objeto = falha de formato."""
    if not isinstance(bruto, str) or not bruto.strip():
        return None, "resposta vazia"
    s = bruto.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        j = json.loads(s)
    except Exception:
        j = extrair_json(bruto, exige_chave="passa")
        if j is None:
            return None, "JSON inválido: %r" % bruto[:120]
    if not isinstance(j, dict):
        return None, "resposta não é objeto"
    passa, nota = j.get("passa"), j.get("nota")
    motivos, trechos = j.get("motivos", []), j.get("trechos", [])
    if not isinstance(passa, bool):
        return None, "campo 'passa' ausente ou não-booleano"
    if isinstance(nota, bool) or not isinstance(nota, int) or not 1 <= nota <= 5:
        return None, "campo 'nota' fora de 1-5 inteiro"
    if not isinstance(motivos, list) or not all(isinstance(m, str) for m in motivos):
        return None, "campo 'motivos' não é lista de texto"
    if not isinstance(trechos, list) or not all(isinstance(t, str) for t in trechos):
        return None, "campo 'trechos' não é lista de texto"
    return {"passa": passa, "nota": nota, "motivos": motivos[:8], "trechos": trechos[:8]}, None


def _reprova_invalida(motivo):
    return {"passa": False, "nota": 1, "motivos": ["[falha fechada] " + motivo], "trechos": [], "invalida": True}


def _bloco_peca(peca):
    partes = ["CANAL: %s" % peca.get("canal", ""), "TEXTO DA PEÇA:\n" + (peca.get("texto") or "")]
    if peca.get("texto_arte"):
        partes.append("TEXTO DENTRO DA ARTE/VÍDEO:\n" + peca["texto_arte"])
    return "\n\n".join(partes)


def _bloco_fontes(peca, regras=None):
    regras = regras or marcas.carregar(peca.get("marca") or "innconta")
    doms = marcas.dominios_permitidos(regras)
    linhas = []
    for f in peca.get("fontes") or []:
        linhas.append("- %s | %s | %s | %s" % (f.get("dado", ""), f.get("norma", ""), f.get("url", ""),
                                               f.get("verificado", "")))
    paginas, baixadas = [], []
    for u in peca.get("nota_urls") or []:
        t = insumos.texto_da_pagina(u, dominios=doms)
        baixadas.append(u)
        paginas.append("PAGINA DE ORIGEM %s:\n%s" % (u, t or "(indisponivel — sem fonte, nada e sustentado)"))
    for u, t in insumos.texto_das_fontes(peca.get("fontes"), doms, ja_baixadas=baixadas):
        paginas.append("FONTE OFICIAL (baixada ao vivo) %s:\n%s" % (u, t or "(indisponivel)"))
    return ("FONTES OFICIAIS PERMITIDAS:\n" + ("\n".join(linhas) or "(nenhuma listada)") + "\n\n" +
            ("\n\n".join(paginas) or "PAGINA DE ORIGEM: (nenhuma)"))


def mensagens(papel, peca, regras=None):
    if regras is None and peca.get("marca"):
        regras = marcas.carregar(peca["marca"])
    sistema = {"role": "system", "content": construir_prompt(papel, regras)}
    if papel == "fato":
        return [sistema, {"role": "user", "content": _bloco_fontes(peca, regras) + "\n\n=====\n\n" + _bloco_peca(peca)}]
    if papel in ("visual", "visual2"):
        imgs = insumos.imagens_para_revisor(peca.get("imagens"))
        if not imgs:
            return None
        conteudo = [{"type": "text", "text": "Arte renderizada e cópia a 390 px. " + _bloco_peca(peca)}]
        conteudo += [{"type": "image_url", "image_url": {"url": u}} for u in imgs]
        return [sistema, {"role": "user", "content": conteudo}]
    return [sistema, {"role": "user", "content": _bloco_peca(peca)}]


def _votar_um(papel, peca, conversar=None, papel_modelo=None, excluir_ini=None):
    """Um voto validado de UM modelo. `papel_modelo` escolhe a cadeia de provedores (ex.: 'visual2'); `excluir_ini`
    tira provedores da cadeia desde a 1a chamada (o 2o voto visual nunca usa o provedor do 1o)."""
    conversar = conversar or modelos.conversar
    papel_modelo = papel_modelo or papel
    try:
        modelo = modelos.modelo_de(papel_modelo)
    except Exception:
        modelo = "?"
    try:
        msgs = mensagens(papel, peca)
    except Exception as e:
        v = _reprova_invalida("insumo do revisor falhou: %s" % e)
        v.update(modelo=modelo, neuronios=0.0)
        return v
    if msgs is None and peca.get("formato") == "texto":  # peça só de texto: não há arte a conferir
        v = {"passa": True, "nota": 5, "motivos": ["peça só de texto — sem arte"], "trechos": [], "invalida": False}
        v.update(modelo="(não se aplica)", neuronios=0.0)
        return v
    if msgs is None:  # só o visual devolve None: peça visual sem imagem conferível
        v = {"passa": False, "nota": 1, "motivos": ["peça sem arte legível para conferir a 390 px"],
             "trechos": [], "invalida": False}
        v.update(modelo=modelo, neuronios=0.0)
        return v
    # FORMATO FORA DO CONTRATO -> OUTRO PROVEDOR (24/09/2026, dívida do PR #55): resposta sem objeto
    # JSON válido (prosa, vazio, campos errados) não é voto. Tenta de novo a cadeia SEM o provedor
    # que saiu do formato (mesmo mecanismo `excluir_provedores` do redator), até acabar a cadeia.
    # Só quando nenhum provedor respondeu no formato é que vira reprova inválida (falha fechada:
    # nunca aprova no escuro), com o rastro de cada tentativa.
    neur_total, excluir, falhas_formato = 0.0, set(excluir_ini or ()), []
    for _ in range(MAX_TENTATIVAS_FORMATO):
        try:
            if excluir:
                bruto, neur, modelo = conversar(papel_modelo, msgs, excluir_provedores=set(excluir))
            else:
                bruto, neur, modelo = conversar(papel_modelo, msgs)
        except modelos.CotaEsgotada:
            raise  # o conselho adia a peça inteira — cota não é voto
        except Exception as e:
            if falhas_formato:  # cadeia acabou depois de respostas fora do formato
                break
            v = _reprova_invalida("modelo indisponível: %s" % str(e)[:200])
            # NÃO usar o `modelo` capturado antes da chamada (rótulo do provedor PRIMÁRIO) — a cadeia
            # inteira falhou (24/09/2026, roteador multi-provedor), então nenhum provedor votou de
            # fato; o rótulo tem de deixar isso claro em vez de sugerir que o primário respondeu.
            v.update(modelo="(nenhum — todos os provedores falharam)", neuronios=0.0)
            return v
        neur_total += float(neur or 0)
        voto, erro = validar(bruto)
        if not erro:
            break
        falhas_formato.append((modelo, erro))
        print("revisor %s: %s saiu do formato (%s) — tentando outro provedor" % (papel, modelo, erro[:140]))
        provedor = (modelo or "").split(":", 1)[0]
        if not provedor or provedor in excluir:
            break  # não há como tirar esse provedor da cadeia — não repete o mesmo à toa
        excluir.add(provedor)
    else:
        voto, erro = None, "limite de tentativas"
    if voto is None:
        rastro = " | ".join("%s: %s" % (m, e[:90]) for m, e in falhas_formato) or erro
        v = _reprova_invalida("resposta do modelo fora do formato (%s)" % rastro)
        v.update(modelo=" -> ".join(m for m, _ in falhas_formato) or modelo, neuronios=neur_total,
                 falha_formato=True)
        return v
    neur = neur_total
    if falhas_formato:  # o voto é de quem respondeu no formato; o rótulo guarda quem saiu dele antes
        modelo = " -> ".join([m for m, _ in falhas_formato] + [modelo])
    if papel == "editorial" and voto["nota"] < NOTA_MINIMA_EDITORIAL and voto["passa"]:
        voto["passa"] = False
        voto["motivos"].append("nota editorial %d abaixo do mínimo %d" % (voto["nota"], NOTA_MINIMA_EDITORIAL))
    voto["invalida"] = False
    voto.update(modelo=modelo, neuronios=neur)
    return voto


def _rotulo_provedor(modelo):
    return (modelo or "").split(" -> ")[-1].split(":", 1)[0]


TEXTO_ECONOMICO = ("fato", "voz", "risco", "editorial")


def revisar_texto_economico(peca, conversar, papeis=TEXTO_ECONOMICO):
    """MODO ECONOMICO (01/10/2026): UMA chamada de IA devolve o voto dos 4 revisores de texto (fato, voz, risco, editorial) com
    os MESMOS criterios dos prompts individuais. O desenho antigo gastava 4 chamadas por volta so no texto (+2 no visual) e a
    cota gratuita nao sustentava mais que 1-2 pecas por dia. Devolve {papel: voto}; papel cujo trecho veio ausente ou fora do
    formato cai para a revisao individual (o buraco nunca vira aprovacao). `conversar` injetavel."""
    regras = marcas.carregar(peca["marca"]) if peca.get("marca") else None
    base = mensagens("fato", peca, regras)
    partes = ["%s) %s" % (p, construir_prompt(p, regras).split(_FORMATO)[0]) for p in papeis]
    sistema = ("Voce e um painel de %d revisores INDEPENDENTES de uma peca de rede social. Aplique CADA conjunto de criterios abaixo "
               "separadamente, como se fosse outro revisor, e nao deixe um criterio contaminar o outro. Responda UM unico objeto "
               "JSON, sem texto fora dele, com uma chave por revisor (%s); cada valor e um objeto "
               '{"passa": true|false, "nota": inteiro 1-5, "motivos": [texto], "trechos": [texto]}. '
               "Motivos sempre vazios quando passa=true.\n\n" % (len(papeis), ", ".join(papeis))) + "\n\n".join(partes)
    msgs = [{"role": "system", "content": sistema}, base[1]]
    votos, neur_tot, modelo = {}, 0.0, "?"
    try:
        bruto, neur, modelo = conversar("fato", msgs)
        neur_tot = float(neur or 0)
        j = extrair_json(bruto, exige_chave=papeis[0]) or {}
        for p in papeis:
            sub = j.get(p)
            v, erro = validar(json.dumps(sub)) if isinstance(sub, dict) else (None, "ausente")
            if not erro:
                votos[p] = dict(v, modelo="economico:" + str(modelo), neuronios=neur_tot / len(papeis), invalida=False)
    except modelos.CotaEsgotada:
        raise
    except Exception:
        pass
    for p in papeis:
        if p not in votos:
            votos[p] = revisar(p, peca, conversar=conversar)
    return votos


def revisar(papel, peca, conversar=None, dois_votos=True):
    """Devolve o voto validado + 'modelo' + 'neuronios'. `conversar` injetavel (mock nos testes).

    VISUAL v2 (29/09/2026): (1) checagem deterministica de cada imagem (abre, peso, proporcao aceita pelo Instagram)
    so para peca que declara `marca`; (2) DOIS modelos de visao de familias/provedores diferentes votam e os dois tem de
    aprovar — aprovacao de um so nao vale (falha fechada). Se nao ha como obter dois modelos distintos, reprova."""
    v1 = _votar_um(papel, peca, conversar)
    if not dois_votos:
        return v1
    if papel != "visual" or not v1.get("passa") or v1.get("invalida") or peca.get("formato") == "texto" and not peca.get("imagens"):
        return v1
    if v1.get("modelo") in ("(nao se aplica)", "(não se aplica)"):
        return v1
    excluir = {_rotulo_provedor(v1.get("modelo"))} - {""}
    v2 = _votar_um(papel, peca, conversar, papel_modelo="visual2", excluir_ini=excluir)
    distintos = _rotulo_provedor(v1.get("modelo")) != _rotulo_provedor(v2.get("modelo")) or v1.get("modelo") != v2.get("modelo")
    if v2.get("invalida") and not v2.get("passa"):
        motivo = "2o modelo de visao indisponivel ou fora do formato (%s): aprovacao isolada de um so modelo nao vale" % (
            "; ".join(v2.get("motivos") or [])[:160])
        v = _reprova_invalida(motivo)
        v.update(modelo="%s + (2o voto indisponivel)" % v1.get("modelo"), neuronios=float(v1.get("neuronios") or 0) + float(v2.get("neuronios") or 0))
        return v
    if not distintos:
        v = _reprova_invalida("os dois votos visuais vieram do mesmo modelo (%s)" % v1.get("modelo"))
        v.update(modelo=v1.get("modelo"), neuronios=float(v1.get("neuronios") or 0) + float(v2.get("neuronios") or 0))
        return v
    passa = bool(v1["passa"] and v2["passa"])
    return {"passa": passa, "nota": min(v1["nota"], v2["nota"]),
            "motivos": (v1.get("motivos") or []) + ["[2o modelo] " + m for m in (v2.get("motivos") or [])],
            "trechos": (v1.get("trechos") or []) + (v2.get("trechos") or []),
            "invalida": False, "modelo": "%s + %s" % (v1["modelo"], v2["modelo"]),
            "neuronios": float(v1.get("neuronios") or 0) + float(v2.get("neuronios") or 0)}
