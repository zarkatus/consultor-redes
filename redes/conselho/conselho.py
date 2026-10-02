# -*- coding: utf-8 -*-
"""CONSELHO EDITORIAL automático do Consultor de Redes (CVO 23/09/2026: "Precisamos de revisão e
aprovação não humana, pense em uma estrutura que resolva e automatize.").

Fluxo por peça (até MAX_VOLTAS voltas):
  1. guarda.py (determinística). Barrou -> vai direto ao redator (nenhum modelo é gasto).
  2. 5 revisores independentes (revisores.py), cada voto gravado em `ic_redes_revisao`.
  3. Decisão: UNANIMIDADE + editorial >= 4 -> 'aprovado' (aprovado_por='conselho').
  4. Reprovou por conteúdo -> redator.py reescreve só o apontado -> nova volta (revisão COMPLETA,
     porque a reescrita pode quebrar o que antes passava).
  5. Reprovou no VISUAL -> escala na hora (o redator só mexe em texto; arte pede novo render).
  6. Esgotou as voltas -> 'escalado' (vai no e-mail semanal de escaladas ao CVO, com os motivos).

Chave de parada: `ic_segredo.redes_pausa = '1'` -> nada roda (nem conselho nem publicar.py). Falha
ao LER a chave também para (falha fechada).
Orçamento: teto diário de neurônios (modelos.TETO_NEURONIOS_DIA, abaixo da franquia gratuita de
10.000/dia do Workers AI) — inalterado. Quando esse orçamento acaba, o roteador multi-provedor
(modelos.py, 24/09/2026) NÃO adia de cara — tenta Groq, depois Gemini, depois OpenRouter (:free),
nessa ordem, cada um com família/host diferente. Só quando TODOS (Workers AI + fallbacks com
credencial) estiverem sem cota é que a peça é ADIADA (não registrada em ic_redes_publicacao, volta
na próxima rodada), nunca aprovada nem escalada por falta de verba.

CLI:
  python redes/conselho/conselho.py --avaliar <lote.json> [--prefixo qa-conselho-]
      modo AVALIAÇÃO (prova): lê peças de um JSON, grava os votos com peca_id prefixado e NÃO toca
      em ic_redes_publicacao nem no estoque. Imprime a tabela de resultados.
  O modo de produção é chamado por redes/lote_aprovacao.py (lote semanal) — ver lá."""
import datetime
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
AQUI = os.path.dirname(os.path.abspath(__file__))
REDES = os.path.dirname(AQUI)
for p in (AQUI, REDES, os.path.join(REDES, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)
import alcance  # noqa: E402
import checagens  # noqa: E402
import cota  # noqa: E402
import guarda  # noqa: E402
import insumos  # noqa: E402
import marcas  # noqa: E402
import modelos  # noqa: E402
import redator  # noqa: E402
import revisores  # noqa: E402

MAX_VOLTAS = 3
# MODO ECONOMICO (01/10/2026): 1 chamada para os 4 revisores de texto + 1 voto visual (em vez de 4 + 2). Liga por ambiente:
# CONSELHO_ECONOMICO=1 (workflow redes-consultor.yml e execucao local). Os criterios sao os mesmos prompts individuais.
ECONOMICO = os.environ.get("CONSELHO_ECONOMICO", "") == "1"
CUSTO_ESTIMADO_VOLTA = 600.0  # neurônios de 1 volta completa (medido 23/09: ~350-550)


def _supa():
    import supa
    return supa


def pausado(ler_segredo=None):
    """True se a chave de parada estiver ligada OU se não der para ler (falha fechada)."""
    try:
        ler = ler_segredo or _supa().segredo
        return (ler("redes_pausa") or "").strip() == "1"
    except Exception as e:
        print("não consegui ler ic_segredo.redes_pausa (%s) — tratando como PAUSADO." % e)
        return True


def neuronios_hoje():
    """Gasto do dia (UTC) = o MAIOR entre (a) o consumo real da conta Cloudflare (análise GraphQL,
    conta tudo, mas chega com atraso) e (b) a soma dos votos gravados em ic_redes_revisao (imediato,
    só o conselho). As duas fontes são limites inferiores; usar a maior é o lado seguro. Se NENHUMA
    responder -> devolve o teto (falha fechada: sem saber quanto gastou, não gasta mais)."""
    agora = datetime.datetime.now(datetime.timezone.utc)
    conta = modelos.neuronios_da_conta_hoje(agora.strftime("%Y-%m-%d"))
    banco = None
    try:
        linhas = _supa().select("ic_redes_revisao",
                                "criado_em=gte.%s&select=neuronios&limit=10000" % agora.strftime("%Y-%m-%dT00:00:00Z"))
        banco = sum(float(l.get("neuronios") or 0) for l in linhas)
    except Exception as e:
        print("não consegui somar os votos de hoje no banco: %s" % str(e)[:160])
    if conta is None and banco is None:
        print("gasto do dia desconhecido — orçamento tratado como esgotado (falha fechada).")
        return modelos.TETO_NEURONIOS_DIA
    return max(conta or 0.0, banco or 0.0)


class Orcamento:
    def __init__(self, gasto_inicial, teto=None):
        self.gasto = float(gasto_inicial)
        self.teto = float(teto if teto is not None else modelos.TETO_NEURONIOS_DIA)

    def cabe(self, estimativa=CUSTO_ESTIMADO_VOLTA):
        return self.gasto + estimativa <= self.teto

    def somar(self, n):
        self.gasto += float(n or 0)


def _marcar_cf_esgotado(orcamento, erro):
    """Só zera o orçamento do Workers AI quando o PRÓPRIO Workers AI esgotou. Antes (até 30/09/2026) qualquer CotaEsgotada
    — por exemplo Gemini+OpenRouter em 429 no revisor visual — zerava o orçamento do cf para todas as peças seguintes, e o
    Workers AI (6.500 neurônios/dia, ~425 usados) nunca mais era tentado: 0 aprovadas, 67 adiadas no 1º Conselho multimarca."""
    if re.search(r"tentados: (?:[a-z]+, )*cf\b", str(erro)):
        orcamento.gasto = orcamento.teto


def gravador_banco(prefixo=""):
    """Devolve função que grava 1 linha por voto em ic_redes_revisao."""
    def gravar(peca_id, rodada, papel, voto):
        _supa().inserir("ic_redes_revisao", [{
            "peca_id": prefixo + peca_id, "marca": voto.get("marca") or "innconta", "rodada": rodada, "revisor": papel,
            "modelo": voto.get("modelo", ""), "passa": bool(voto.get("passa")),
            "nota": voto.get("nota"), "motivos": voto.get("motivos", []),
            "trechos": voto.get("trechos", []), "neuronios": round(float(voto.get("neuronios") or 0), 3),
        }])
    return gravar


def _conversar_padrao(orcamento):
    """conversar() de produção: injeta em modelos.conversar se Workers AI ainda cabe no orçamento
    do dia (orcamento.cabe()) — se não cabe, o roteador de modelos.py pula direto pros fallbacks
    (Groq/Gemini/OpenRouter, 24/09/2026), sem tentar Workers AI e sem adiar a peça à toa.
    `excluir_provedores` (24/09/2026, dívida do PR #54) repassa pro roteador — é o que permite ao
    redator pedir pra retentativa de JSON malformado evitar o MESMO provedor que acabou de falhar."""
    def f(papel, mensagens, max_saida=None, excluir_provedores=None):
        return modelos.conversar(papel, mensagens, max_saida=max_saida, cf_disponivel=orcamento.cabe(),
                                 excluir_provedores=excluir_provedores)
    return f


def avaliar(peca, gravar=None, conversar=None, nomes_clientes=None, orcamento=None, marca_nome="InnConta",
            max_voltas=MAX_VOLTAS, papeis=None, regras=None, referencias=None, paginas=None, cache=None, consumo=None):
    """Decide uma peça. Devolve dict:
      decisao: 'aprovado' | 'escalado' | 'adiado'
      rodadas, texto_final, motivos (lista 'revisor: motivo' da última volta), votos_por_rodada,
      aprovado_primeira_volta (bool), neuronios."""
    orcamento = orcamento or Orcamento(0, teto=float("inf"))
    gravar = gravar or (lambda *a, **k: None)
    # 24/09/2026: o orçamento de Workers AI não força mais 'adiado' de cara — o roteador multi-
    # provedor (modelos.py) tenta os fallbacks quando Workers AI está sem cota. Só vira 'adiado'
    # quando TODA a cadeia (Workers AI + fallbacks configurados) estiver esgotada (CotaEsgotada
    # abaixo, levantada pelo próprio modelos.conversar).
    conversar = conversar or _conversar_padrao(orcamento)
    texto = peca.get("texto") or ""
    historico, gasto = [], 0.0
    papeis = papeis or revisores.REVISORES
    # CONSELHO v2 (29/09/2026): peca que declara `marca` passa pelas checagens deterministicas da marca (alcance,
    # sigilo, fontes, imagem, numero na arte, anti-repeticao) e pelos prompts da marca. Peca sem `marca` = v1.
    marca = peca.get("marca")
    v2 = bool(marca)
    if v2 and regras is None:
        regras = marcas.carregar(marca)
    if v2 and marca_nome == "InnConta":
        marca_nome = regras.get("nome") or marca_nome

    def conferir(txt):
        """(motivos corrigiveis, motivos fatais) da guarda + checagens v2 sobre o texto `txt`."""
        atual_ = dict(peca, texto=txt)
        ok_, mot_ = guarda.checar(txt + "\n" + (peca.get("texto_arte") or ""),
                                  nomes_clientes=nomes_clientes, marca_nome=marca_nome,
                                  nota_origem=" ".join(peca.get("nota_urls") or []), regras=regras)
        corrig_, fatais_ = list(mot_), []
        if v2:
            c2, f2 = checagens.executar(atual_, txt, regras, referencias, paginas)
            corrig_ += c2
            fatais_ += f2
        return list(dict.fromkeys(corrig_)), list(dict.fromkeys(fatais_))

    for rodada in range(1, max_voltas + 1):
        atual = dict(peca, texto=texto)
        votos = {}
        motivos_c, motivos_f = conferir(texto)
        ok_g = not motivos_c and not motivos_f
        motivos_g = motivos_f + motivos_c
        if not ok_g:
            votos["guarda"] = {"passa": False, "nota": 1, "motivos": motivos_g, "trechos": [],
                               "modelo": "guarda.py" + ("+checagens" if v2 else ""), "neuronios": 0.0, "invalida": False,
                               "fatal": bool(motivos_f)}
        else:
            try:
                texto_econ = {}
                for papel in papeis:
                    chave = cota.chave_cache(papel, marca, atual, regras) if (cache is not None and v2) else None
                    hit = cache.obter(chave) if chave else None
                    if hit:  # peca inalterada: nao gasta modelo de novo
                        votos[papel] = dict(hit, modelo="cache:" + str(hit.get("modelo")), neuronios=0.0, invalida=False)
                        if consumo is not None:
                            consumo.registrar(marca, "cache", papel, cache=True)
                        continue
                    if ECONOMICO and papel in revisores.TEXTO_ECONOMICO:
                        if not texto_econ:  # 1 chamada cobre os revisores de texto que ainda nao estao em cache
                            falta = [p for p in revisores.TEXTO_ECONOMICO if p in papeis and not (
                                cache is not None and v2 and cache.obter(cota.chave_cache(p, marca, atual, regras)))]
                            texto_econ = revisores.revisar_texto_economico(atual, conversar, papeis=tuple(falta))
                        votos[papel] = texto_econ[papel]
                    else:
                        votos[papel] = revisores.revisar(papel, atual, conversar=conversar, dois_votos=not ECONOMICO)
                    if chave:
                        cache.guardar(chave, papel, marca, votos[papel])
            except modelos.CotaEsgotada as e:
                _marcar_cf_esgotado(orcamento, e)
                return {"decisao": "adiado", "rodadas": rodada - 1, "texto_final": texto, "neuronios": gasto,
                        "motivos": ["%s — volta na próxima rodada" % e], "votos_por_rodada": historico,
                        "aprovado_primeira_volta": False}
        for papel, v in votos.items():
            if v2:
                v["marca"] = marca
            gasto += float(v.get("neuronios") or 0)
            orcamento.somar(v.get("neuronios"))
            try:
                gravar(peca["peca_id"], rodada, papel, v)
            except Exception as e:
                print("voto NÃO gravado (%s/%s): %s" % (peca["peca_id"], papel, e))
        historico.append({p: {k: v[k] for k in ("passa", "nota", "motivos", "trechos", "modelo", "invalida")
                              if k in v} for p, v in votos.items()})
        reprovados = {p: v for p, v in votos.items() if not v.get("passa")}
        motivos = ["%s: %s" % (p, m) for p, v in reprovados.items() for m in (v.get("motivos") or ["(sem motivo)"])]
        if not reprovados:
            return {"decisao": "aprovado", "rodadas": rodada, "texto_final": texto, "motivos": [],
                    "votos_por_rodada": historico, "aprovado_primeira_volta": rodada == 1, "neuronios": gasto}
        if "guarda" in reprovados and reprovados["guarda"].get("fatal"):
            return {"decisao": "escalado", "rodadas": rodada, "texto_final": texto,
                    "motivos": ["defeito que so novo render, troca de fonte ou de data resolve (o redator so reescreve texto)"] + motivos,
                    "votos_por_rodada": historico, "aprovado_primeira_volta": False, "neuronios": gasto}
        if "visual" in reprovados and not reprovados["visual"].get("invalida"):
            return {"decisao": "escalado", "rodadas": rodada, "texto_final": texto,
                    "motivos": ["arte precisa de novo render (o redator só reescreve texto)"] + motivos,
                    "votos_por_rodada": historico, "aprovado_primeira_volta": False, "neuronios": gasto}
        if rodada == max_voltas:
            return {"decisao": "escalado", "rodadas": rodada, "texto_final": texto, "motivos": motivos,
                    "votos_por_rodada": historico, "aprovado_primeira_volta": False, "neuronios": gasto}
        de_conteudo = {p: v for p, v in reprovados.items() if not v.get("invalida")}
        if v2 and "guarda" in reprovados:
            # conserto MECANICO primeiro (hashtags 3-5, chamada final): zero modelo, zero fato inventado
            det = alcance.corrigir_legenda(texto, regras)
            if det != texto:
                texto = det
                rest_c, rest_f = conferir(texto)
                historico[-1]["redator"] = {"passa": True, "nota": None, "motivos": ["conserto mecanico de alcance"],
                                            "trechos": [], "modelo": "alcance.corrigir_legenda", "invalida": False}
                try:
                    gravar(peca["peca_id"], rodada, "redator", {"passa": True, "nota": None, "marca": marca,
                           "motivos": ["conserto mecanico de alcance (hashtags/chamada)"], "trechos": [],
                           "modelo": "alcance.corrigir_legenda", "neuronios": 0.0})
                except Exception as e:
                    print("voto do redator NAO gravado:", e)
                if not rest_c and not rest_f:
                    continue  # corrigido sem gastar modelo; a proxima volta revisa TUDO de novo
                de_conteudo = {"guarda": dict(reprovados["guarda"], motivos=rest_c)}
        if de_conteudo:
            try:
                atual = dict(peca, texto=texto)
                novo, neur, modelo, erro_parse = redator.reescrever(atual, de_conteudo, conversar=conversar, regras=regras)
            except modelos.CotaEsgotada as e:
                _marcar_cf_esgotado(orcamento, e)
                return {"decisao": "adiado", "rodadas": rodada, "texto_final": peca.get("texto") or "",
                        "neuronios": gasto, "motivos": ["%s — volta na próxima rodada" % e],
                        "votos_por_rodada": historico, "aprovado_primeira_volta": False}
            gasto += neur
            orcamento.somar(neur)
            # dívida do PR #54 (24/09/2026): expõe provedor:modelo do redator + um resumo do erro de
            # parse (nunca a resposta bruta inteira) TANTO no histórico devolvido por avaliar() quanto
            # no voto gravado no banco — antes só ia pro banco, e a prova de 24/09 perdeu a pista
            # porque o resíduo QA já tinha sido apagado quando alguém foi checar.
            motivos_redator = [] if novo else [erro_parse or "redator sem reescrita válida"]
            historico[-1]["redator"] = {"passa": novo is not None, "nota": None, "motivos": motivos_redator,
                                        "trechos": [], "modelo": modelo, "invalida": False}
            try:
                gravar(peca["peca_id"], rodada, "redator", {"passa": novo is not None, "nota": None,
                       "motivos": motivos_redator, "trechos": [], "modelo": modelo, "neuronios": neur})
            except Exception as e:
                print("voto do redator NÃO gravado:", e)
            if novo:
                texto = novo
    raise AssertionError("inalcançável")


# ---------------------------------------------------------------- modo AVALIAÇÃO (prova, PQV-02)

def carregar_lote(caminho_json):
    base = os.path.dirname(os.path.abspath(caminho_json))
    with open(caminho_json, encoding="utf-8") as f:
        lote = json.load(f)
    pecas = []
    for p in lote["pecas"]:
        imagens = [os.path.join(base, c) for c in p.get("imagens", [])]
        for v in p.get("videos", []):
            imagens += insumos.quadros_do_video(os.path.join(base, v))
        pecas.append(dict(p, imagens=imagens))
    return pecas


def avaliar_lote(caminho_json, prefixo="qa-conselho-", gravar_no_banco=True, pecas_ids=None, max_voltas=MAX_VOLTAS,
                 teto=None, papeis=None):
    if pausado():
        print("CHAVE DE PARADA LIGADA (ic_segredo.redes_pausa='1') — conselho não roda.")
        return {"pausado": True}
    pecas = carregar_lote(caminho_json)
    if pecas_ids:
        pecas = [p for p in pecas if p["peca_id"] in pecas_ids]
    orc = Orcamento(neuronios_hoje(), teto=teto)
    print("orçamento: %.0f de %.0f neurônios já gastos hoje (UTC)" % (orc.gasto, orc.teto))
    gravar = gravador_banco(prefixo) if gravar_no_banco else None
    resultados = []
    for p in pecas:
        t0 = time.time()
        r = avaliar(p, gravar=gravar, orcamento=orc, max_voltas=max_voltas, papeis=papeis)
        r["segundos"] = round(time.time() - t0, 1)
        r["peca_id"] = p["peca_id"]
        resultados.append(r)
        v1 = r["votos_por_rodada"][0] if r["votos_por_rodada"] else {}
        placar = " ".join("%s=%s%s" % (k, "OK" if v["passa"] else "X", v.get("nota") or "")
                          for k, v in v1.items())
        print("PEÇA %-55s %-9s voltas=%d %5.1fs %6.1fn | 1ª volta: %s" % (
            p["peca_id"], r["decisao"], r["rodadas"], r["segundos"], r["neuronios"], placar))
        for m in r["motivos"][:6]:
            print("      - " + m[:220])
    aprov1 = sum(1 for r in resultados if r["aprovado_primeira_volta"])
    print("RESUMO: %d peças | aprovadas=%d (1ª volta=%d) escaladas=%d adiadas=%d | neurônios=%.1f" % (
        len(resultados), sum(r["decisao"] == "aprovado" for r in resultados), aprov1,
        sum(r["decisao"] == "escalado" for r in resultados), sum(r["decisao"] == "adiado" for r in resultados),
        sum(r["neuronios"] for r in resultados)))
    saida = os.environ.get("CONSELHO_SAIDA")
    if saida:
        with open(saida, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)
    return {"pecas": len(resultados), "resultados": resultados}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--avaliar", required=True, help="lote JSON de peças (modo avaliação — não toca publicação)")
    ap.add_argument("--prefixo", default="qa-conselho-")
    ap.add_argument("--sem-banco", action="store_true")
    # opções só do modo avaliação (prova): recorte de peças/revisores, voltas e teto do dia.
    # Chegam do workflow pela variável CONSELHO_OPCOES (nunca interpoladas no shell).
    ap.add_argument("--pecas", default="", help="ids separados por vírgula")
    ap.add_argument("--voltas", type=int, default=MAX_VOLTAS, choices=(1, 2, 3))
    ap.add_argument("--teto", type=float, default=None, help="teto de neurônios do dia (máx. 9500)")
    ap.add_argument("--so-revisores", default="", help="papéis separados por vírgula")
    import shlex
    a = ap.parse_args(sys.argv[1:] + shlex.split(os.environ.get("CONSELHO_OPCOES", "")))
    if a.teto is not None and not 0 < a.teto <= 9500:
        raise SystemExit("--teto fora de (0, 9500] — a franquia gratuita é 10.000/dia")
    papeis = tuple(x for x in a.so_revisores.split(",") if x) or None
    if papeis and not set(papeis) <= set(revisores.REVISORES):
        raise SystemExit("--so-revisores inválido: %s" % (papeis,))
    r = avaliar_lote(a.avaliar, a.prefixo, gravar_no_banco=not a.sem_banco,
                     pecas_ids=set(x for x in a.pecas.split(",") if x) or None,
                     max_voltas=a.voltas, teto=a.teto, papeis=papeis)
    print({k: v for k, v in r.items() if k != "resultados"})
