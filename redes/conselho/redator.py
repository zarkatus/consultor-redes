# -*- coding: utf-8 -*-
"""Redator automático do Conselho Editorial: recebe a peça + os motivos/trechos dos revisores que
reprovaram e reescreve SÓ o apontado. Nunca inventa fato: número ou afirmação sem fonte é CORTADO
(memória do CVO: "número/fato comercial sem fonte pública é cortado, não escalado"); a referência
à fonte (link da nota) é mantida. Só mexe em TEXTO — arte e vídeo não são reescritos aqui (o
conselho escala direto quando o problema é visual).

Resposta JSON {"texto": "..."}; JSON malformado (não parseia, ou sem campo 'texto' de string não
vazia) -- dívida do PR #54 (24/09/2026: "conselho.avaliar() não expõe qual modelo do redator
devolveu JSON malformado"): 1 retentativa só, com instrução de formato reforçada e evitando (quando
dá pra saber quem foi) o MESMO provedor que acabou de sair do formato, ANTES de contar como falha.
Resposta grande demais (sanidade de conteúdo, não é defeito de FORMATO) não retenta -- retentar não
muda um modelo que respondeu dentro do contrato, só extrapolou o tamanho.
Devolve sempre (texto|None, neuronios, modelo, erro_parse|None): `modelo` é "provedor:modelo" de
quem por fim respondeu (ou "modelo1 -> modelo2" quando houve retentativa); `erro_parse` é None em
sucesso, senão um RESUMO curto do defeito (nunca a resposta bruta inteira — só um trecho, pra
auditoria em `ic_redes_revisao.motivos` sem vazar conteúdo de modelo no log/banco).
Inválida = None (e o conselho segue para a próxima volta sem reescrita, contando a volta — falha
fechada, nunca aprova por falta de redator)."""
import json
import re

import marcas
import modelos
import revisores

PROMPT = (
    "Voce e o redator da %(nome)s. Reescreva a peca corrigindo APENAS os problemas apontados pelos "
    "revisores e deixe todo o resto IGUAL, palavra por palavra. Regras: nao invente numero, data, "
    "norma nem fato; se um numero ou fato nao tem fonte, CORTE a frase inteira; nao acrescente citacao, "
    "link, markdown, aspas de norma nem explicacao nova; mantenha o link da nota de origem e as "
    "hashtags; mantenha o tom (%(tom)s), as frases curtas e o tamanho; sem emoji, sem a palavra 'casa' "
    "(use o nome da empresa ou frase sem sujeito), nunca 'agente'/'bot', no maximo um travessao. "
    "SEMPRE, qualquer que seja o apontamento: a 1a frase fica com no maximo 125 caracteres (nunca a alongue ao corrigir "
    "outro ponto; se precisar acrescentar algo, vai para a 2a frase; nunca ponha link nem nome de norma na 1a frase). "
    "Se o apontamento for de ALCANCE: a 1a frase tem de trazer o fato concreto em ate 125 caracteres (mova o fato para o "
    "inicio, sem inventar nada); a legenda precisa conter uma palavra-chave da marca (%(chaves)s) usada de forma natural; "
    "3 a 5 hashtags; e termine com UMA chamada curta para salvar, compartilhar ou comentar. Se o apontamento for de "
    "SIGILO, corte toda frase com numero de operacao. Citar outra empresa do grupo e permitido. "
    'Responda SOMENTE com JSON: {"texto": "peca reescrita completa, texto puro"}.')

PROMPT_REFORCO = (
    "Sua resposta anterior NÃO era um JSON válido. Responda ESTRITAMENTE com um único objeto JSON, "
    "nada antes, nada depois, sem markdown, sem cerca ```, sem comentário: "
    '{"texto": "peça reescrita completa, texto puro"}.')


def _parsear(bruto, original):
    """Devolve (texto|None, resumo_do_erro|None). O resumo NUNCA carrega a resposta inteira — só um
    trecho curto (<=80 car.) do início dela, suficiente pra auditoria sem guardar o conteúdo todo."""
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (bruto or "").strip())
    try:
        obj = json.loads(s)
    except Exception as e:
        # extrator tolerante (dívida do PR #55): o 1º objeto com "texto" embutido em prosa vale
        obj = revisores.extrair_json(bruto, exige_chave="texto")
        if obj is None:
            preview = (bruto or "")[:80].replace("\n", " ")
            return None, "%s: %s (resposta começa com %r)" % (type(e).__name__, str(e)[:120], preview)
    texto = obj.get("texto") if isinstance(obj, dict) else None
    if not isinstance(texto, str) or not texto.strip():
        return None, "JSON válido mas sem campo 'texto' (string não vazia)"
    texto = texto.strip()
    limite = int(len(original) * 1.5 + 300)
    if len(texto) > limite:
        return None, "texto reescrito grande demais (%d car., limite %d) — não é falha de formato" % (
            len(texto), limite)
    return texto, None


def _chamar(conversar, msgs, excluir=None):
    """Uma chamada ao redator (cadeia inteira de provedores, já roteada por modelos.conversar).
    bruto=None só quando NENHUM provedor da cadeia respondeu de fato (cadeia inteira falhou) —
    `CotaEsgotada` sobe direto pra quem chamou (a peça é adiada, não é defeito do redator)."""
    try:
        return conversar("redator", msgs, excluir_provedores=excluir)
    except modelos.CotaEsgotada:
        raise
    except Exception as e:
        print("redator indisponível:", str(e)[:200])
        # cadeia inteira falhou (24/09/2026, roteador multi-provedor) -- nenhum provedor
        # respondeu de fato, então o rótulo não pode sugerir que o primário escreveu algo.
        return None, 0.0, "(nenhum — todos os provedores falharam)"


def reescrever(peca, votos_reprovados, conversar=None, regras=None):
    """Devolve (texto_novo|None, neuronios, modelo, erro_parse|None) — ver docstring do módulo."""
    conversar = conversar or modelos.conversar
    apontamentos = []
    for papel, v in votos_reprovados.items():
        for m in v.get("motivos", []):
            apontamentos.append("- [%s] %s" % (papel, m))
        for t in v.get("trechos", []):
            apontamentos.append("  trecho: \"%s\"" % t)
    original = peca.get("texto") or ""
    regras = regras or marcas.carregar(peca.get("marca") or "innconta")
    prompt = PROMPT % {"nome": regras.get("nome") or regras.get("marca"), "tom": (regras.get("voz") or {}).get("tom") or "sobrio",
                       "chaves": ", ".join((regras.get("palavras_chave") or [])[:6]) or "os temas da marca"}
    msgs = [{"role": "system", "content": prompt},
            {"role": "user", "content": "PROBLEMAS APONTADOS:\n%s\n\n%s\n\n=====\n\nPEÇA ATUAL:\n%s" % (
                "\n".join(apontamentos), revisores._bloco_fontes(peca), original)}]

    bruto, neur, modelo = _chamar(conversar, msgs)
    if bruto is None:
        # a cadeia inteira já foi tentada nesta 1ª chamada (modelos.conversar já percorre todos os
        # provedores configurados) -- retentar do zero não muda nada, conta como falha direto.
        return None, neur, modelo, "nenhum provedor respondeu (cadeia inteira falhou)"
    texto, erro = _parsear(bruto, original)
    if texto is not None:
        return texto, neur, modelo, None
    if erro.startswith("texto reescrito grande demais"):
        print("redator (%s) devolveu resposta inválida — volta sem reescrita (%s)" % (modelo, erro))
        return None, neur, modelo, erro

    # JSON malformado de verdade (não parseou, ou faltou o campo 'texto') -- 1 retentativa só, com
    # instrução de formato mais estrita e evitando (quando dá pra saber quem foi) o MESMO provedor
    # que acabou de sair do formato, antes de contar como falha (dívida do PR #54).
    print("redator (%s) devolveu JSON malformado (%s) — 1 nova tentativa" % (modelo, erro))
    provedor_falho = (modelo or "").split(":", 1)[0]
    bruto2, neur2, modelo2 = _chamar(conversar, msgs + [{"role": "user", "content": PROMPT_REFORCO}],
                                     excluir={provedor_falho} if provedor_falho else None)
    neur_total = neur + neur2
    if bruto2 is None:
        resumo = "1ª tentativa (%s): %s | retry (%s): nenhum provedor respondeu" % (modelo, erro, modelo2)
        print("redator — retentativa sem resposta de texto; sem reescrita:", resumo)
        return None, neur_total, "%s -> %s" % (modelo, modelo2), resumo
    texto2, erro2 = _parsear(bruto2, original)
    if texto2 is not None:
        return texto2, neur_total, modelo2, None
    resumo = "1ª tentativa (%s): %s | retry (%s): %s" % (modelo, erro, modelo2, erro2)
    print("redator devolveu resposta inválida nas 2 tentativas — volta sem reescrita:", resumo)
    return None, neur_total, "%s -> %s" % (modelo, modelo2), resumo
