# -*- coding: utf-8 -*-
"""PLANO DE COTA da IA gratuita do Consultor de Redes (CVO 29/09/2026: "o Consultor e os artigos devem gastar o MINIMO de
tokens do Claude — na operacao, ZERO"). Nenhum caminho de `redes/` chama a API paga do modelo de topo (gate em
`testar_conselho.py`, bloco "zero Claude"). Toda IA de runtime e gratuita: Workers AI, Groq, Gemini, OpenRouter (:free).

LIMITES GRATUITOS DOCUMENTADOS (conferidos em 29/09/2026):
  Workers AI (Cloudflare, plano Free)  10.000 neuronios/dia na CONTA; corta com HTTP 429/4006 e nao cobra. Teto proprio
                                        6.500 (modelos.TETO_NEURONIOS_DIA): a franquia conta ~1,3x o que a resposta informa.
  Groq (plano Free, por ORGANIZACAO)   gpt-oss-120b/20b e qwen: 30 req/min, 1.000 req/dia, 8.000 tokens/min, 200.000 tokens/dia
                                        (console.groq.com/docs/rate-limits). O que trava primeiro e o TOKEN/DIA e o TOKEN/MIN.
  Gemini (AI Studio, camada gratuita)  limite por PROJETO e por MODELO, RPM/TPM/RPD; a doc nao publica os numeros (so o painel
                                        aistudio.google.com/rate-limit). ASSUMIDO: cerca de 250 req/dia no flash. Contexto de 1 milhao
                                        de tokens: e o provedor dos textos LONGOS (artigo semanal de 2.000+ palavras).
  OpenRouter (modelos :free)           20 req/min; 50 req/dia sem credito comprado (1.000/dia com US$ 10 em creditos).

ORCAMENTO (o que o Consultor se permite por dia, com folga para o resto da conta): Groq 150.000 tokens estimados, Gemini 200
chamadas, OpenRouter 40 chamadas, Workers AI 6.500 neuronios (contados como antes, em `conselho.Orcamento`). Cada MARCA tem
fatia igual do orcamento de cada provedor; pode tomar emprestado o que as outras nao usaram ate 2x a sua fatia — assim
uma marca nunca consome a franquia inteira e nenhuma fica sem revisao. Estourou tudo = ADIAR (CotaEsgotada), nunca escalar
nem cair para modelo pago.

PAPEIS: revisoes curtas (fato, voz, risco, editorial) ficam em Workers AI/Groq; visual em Workers AI + Gemini/OpenRouter;
`longo` (texto de 1.500+ palavras) comeca no Gemini (`modelos.FALLBACKS["longo"]`).

CACHE por hash do conteudo: voto valido de peca inalterada nao gasta modelo de novo (peca adiada, peca reavaliada).
CONSUMO por dia/marca/provedor/papel em `ic_redes_consumo` (medicao; RPC `redes_consumo_somar`)."""
import datetime
import hashlib
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
for p in (AQUI, os.path.dirname(AQUI), os.path.join(os.path.dirname(AQUI), "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)
import modelos  # noqa: E402

# limites gratuitos DOCUMENTADOS (referencia; o relatorio usa estes numeros)
LIMITES_GRATIS = {
    "cf": {"neuronios_dia": 10000, "teto_proprio": 6500},
    "groq": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000},
    "gemini": {"rpd_assumido": 250, "nota": "numeros so no painel do AI Studio; por projeto e por modelo"},
    "openrouter": {"rpm": 20, "rpd": 50, "rpd_com_10usd": 1000},
}
# o que o Consultor se permite por dia (unidade por provedor: groq = tokens estimados; gemini/openrouter = chamadas)
ORCAMENTO_DIA = {"groq": 150000, "gemini": 200, "openrouter": 40}
EMPRESTIMO_MAX = 2.0  # uma marca pode ir a 2x a sua fatia se o total do provedor ainda tem folga
CHARS_POR_TOKEN = 3.5
CACHE_DIAS = 14
PALAVRAS_LONGO = 1500


def estimar_tokens(mensagens, max_saida=700):
    """Estimativa barata de tokens de uma chamada (entrada + saida) — o que a Groq conta contra o TPD."""
    n = 0
    for m in mensagens or []:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            n += sum(len(x.get("text", "")) for x in c if isinstance(x, dict) and x.get("type") == "text")
    return int(n / CHARS_POR_TOKEN) + int(max_saida or 700)


def papel_para(texto, papel="editorial"):
    """Texto longo (>= 1.500 palavras) vai ao papel `longo` (Gemini primeiro, 1 M de contexto); o resto segue o papel."""
    return "longo" if len((texto or "").split()) >= PALAVRAS_LONGO else papel


def _custo(provedor, mensagens, max_saida):
    return estimar_tokens(mensagens, max_saida) if provedor == "groq" else 1


class Consumo:
    """Contadores do dia (UTC) por (marca, provedor, papel): em memoria + persistencia em `ic_redes_consumo`."""

    def __init__(self, dia=None, base=None):
        self.dia = dia or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        self.unidades = {}   # (marca, provedor) -> unidades gastas hoje (tokens p/ groq, chamadas p/ os demais)
        self.novo = {}       # (marca, provedor, papel) -> [chamadas, falhas, cache]
        for (m, pv), v in (base or {}).items():
            self.unidades[(m, pv)] = v

    @classmethod
    def carregar(cls, supa, dia=None):
        """Le o consumo de HOJE ja gravado (duas rodadas no mesmo dia somam). Falha = comeca do zero (log)."""
        c = cls(dia)
        try:
            for r in supa.select("ic_redes_consumo", "dia=eq.%s&select=marca,provedor,chamadas" % c.dia):
                k = (r["marca"], r["provedor"])
                # groq guarda so chamadas no banco: converte pela media (1.5k tokens) para nao subestimar o dia
                c.unidades[k] = c.unidades.get(k, 0) + r["chamadas"] * (1500 if r["provedor"] == "groq" else 1)
        except Exception as e:
            print("consumo do dia indisponivel (%s) — plano parte do zero." % str(e)[:100])
        return c

    def total(self, provedor):
        return sum(v for (m, pv), v in self.unidades.items() if pv == provedor)

    def da_marca(self, marca, provedor):
        return self.unidades.get((marca, provedor), 0)

    def registrar(self, marca, provedor, papel, unidades=1, falha=False, cache=False):
        k = (marca, provedor)
        if not cache:
            self.unidades[k] = self.unidades.get(k, 0) + unidades
        n = self.novo.setdefault((marca, provedor, papel), [0, 0, 0])
        if cache:
            n[2] += 1
        else:
            n[0] += 1
            n[1] += 1 if falha else 0

    def flush(self, supa):
        """Grava o que houve nesta rodada (soma atomica por RPC). Devolve quantas linhas gravou."""
        n = 0
        for (m, pv, pp), (ch, fa, ca) in list(self.novo.items()):
            try:
                supa.rpc("redes_consumo_somar", {"p_dia": self.dia, "p_marca": m, "p_provedor": pv, "p_papel": pp,
                                                 "p_chamadas": ch, "p_falhas": fa, "p_cache": ca})
                n += 1
            except Exception as e:
                print("consumo NAO gravado (%s/%s/%s): %s" % (m, pv, pp, str(e)[:100]))
        self.novo.clear()
        return n


def provedores_sem_folga(consumo, marca, marcas_ativas, mensagens=None, max_saida=700, orcamento=None):
    """Provedores que ESTA marca nao pode usar agora: acima de 2x a sua fatia, ou o total do provedor estourou."""
    orcamento = orcamento or ORCAMENTO_DIA
    n = max(1, len(marcas_ativas))
    fora = set()
    for pv, teto in orcamento.items():
        custo = _custo(pv, mensagens, max_saida)
        fatia = teto / float(n)
        if consumo.total(pv) + custo > teto or consumo.da_marca(marca, pv) + custo > fatia * EMPRESTIMO_MAX:
            fora.add(pv)
    return fora


def conversar_com_plano(orcamento_cf, consumo, marca, marcas_ativas, base=None):
    """`conversar` de producao com o plano: tira da cadeia o provedor sem folga PARA ESTA MARCA e registra o consumo do que
    respondeu. `orcamento_cf` = conselho.Orcamento (Workers AI, neuronios). Sem folga em ninguem = CotaEsgotada (adia)."""
    base = base or modelos.conversar

    def f(papel, mensagens, max_saida=None, excluir_provedores=None):
        excluir = set(excluir_provedores or ()) | provedores_sem_folga(consumo, marca, marcas_ativas, mensagens, max_saida or 700)
        texto, neur, usado = base(papel, mensagens, max_saida=max_saida, cf_disponivel=orcamento_cf.cabe(),
                                  excluir_provedores=excluir)
        provedor = usado.split(":", 1)[0]
        consumo.registrar(marca, provedor, papel, unidades=_custo(provedor, mensagens, max_saida or 700))
        return texto, neur, usado
    return f


# ---------------------------------------------------------------- cache por hash

def chave_cache(papel, marca, peca, regras=None):
    """sha256 do que o revisor VE: papel + marca + legenda + texto da arte + fontes + bytes das imagens + versao do
    prompt (regras da marca). Mudou qualquer coisa = chave nova = revisa de novo."""
    h = hashlib.sha256()
    for parte in (papel, marca, peca.get("texto") or "", peca.get("texto_arte") or "", peca.get("canal") or "",
                  json.dumps(peca.get("fontes") or [], sort_keys=True, ensure_ascii=False),
                  json.dumps(regras or {}, sort_keys=True, ensure_ascii=False)):
        h.update(str(parte).encode("utf-8"))
        h.update(b"\x00")
    for c in peca.get("imagens") or []:
        try:
            with open(c, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(str(c).encode("utf-8"))
    return h.hexdigest()


class Cache:
    """Cache de votos VALIDOS. Memoria + tabela `ic_redes_cache_revisao` (se `supa` dado). Voto invalido nunca entra."""

    def __init__(self, supa=None):
        self.supa = supa
        self.mem = {}

    def obter(self, chave):
        if chave in self.mem:
            return self.mem[chave]
        if self.supa is not None:
            try:
                r = self.supa.select("ic_redes_cache_revisao", "hash=eq.%s&select=voto&limit=1" % chave)
                if r:
                    self.mem[chave] = r[0]["voto"]
                    return r[0]["voto"]
            except Exception as e:
                print("cache de revisao indisponivel (%s)" % str(e)[:80])
        return None

    def guardar(self, chave, papel, marca, voto):
        if voto.get("invalida") or voto.get("falha_formato"):
            return
        limpo = {k: voto[k] for k in ("passa", "nota", "motivos", "trechos", "modelo", "invalida") if k in voto}
        self.mem[chave] = limpo
        if self.supa is not None:
            try:
                self.supa.upsert("ic_redes_cache_revisao", [{"hash": chave, "papel": papel, "marca": marca, "voto": limpo}], "hash")
            except Exception as e:
                print("cache nao gravado (%s)" % str(e)[:80])

    def expurgar(self):
        if self.supa is None:
            return
        limite = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=CACHE_DIAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self.supa.excluir("ic_redes_cache_revisao", "criado_em=lt.%s" % limite)
        except Exception as e:
            print("expurgo do cache falhou (%s)" % str(e)[:80])


# ---------------------------------------------------------------- capacidade (estimativa para o relatorio)

def capacidade(marcas=6, rodadas_por_peca=1.6, artigos_semana=1):
    """Estimativa (ASSUMIDA, a confirmar com ic_redes_consumo) de quantas pecas/dia e artigos/semana cabem no gratuito.
    Peca = 4 revisoes de texto (fato ~4k tokens, voz/risco/editorial ~1k) + visual (Workers AI + Gemini); 1,6 volta media."""
    tokens_peca_groq = 7000 * rodadas_por_peca
    pecas_groq = ORCAMENTO_DIA["groq"] / tokens_peca_groq
    pecas_cf = modelos.TETO_NEURONIOS_DIA / (600.0 * rodadas_por_peca / 1.0)  # ~600 neuronios por peca/volta completa
    pecas_dia = pecas_groq + pecas_cf
    return {"pecas_dia_groq": round(pecas_groq, 1), "pecas_dia_workers_ai": round(pecas_cf, 1),
            "pecas_dia_total": round(pecas_dia, 1), "necessario_dia": marcas,
            "folga_x": round(pecas_dia / float(marcas), 1),
            "artigos_semana_gemini": int(ORCAMENTO_DIA["gemini"] // 12 * 7)}  # ~12 chamadas por artigo (revisao por secao + redator)
