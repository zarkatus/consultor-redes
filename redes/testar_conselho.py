# -*- coding: utf-8 -*-
"""Prova por MOCK (sem rede, sem modelo, sem banco) do Conselho Editorial — redes/conselho/.
Gate do workflow: nunca segue se falhar. Cenários exigidos pelo pedido de 23/09/2026:
  1. unanimidade aprova                          5. chave de parada -> nada roda (lote e publicar)
  2. 1 reprova -> redator -> aprova             6. visual reprova -> escala direto (redator não mexe em arte)
  3. 3 voltas falhando -> escala                7. guarda barra -> nenhum modelo gasto naquela volta
  4. resposta malformada -> reprova             8. Workers AI sem orçamento E sem fallback -> CotaEsgotada,
  + editorial nota 3 com "passa": true é forçado a reprovar; tabela de respostas malformadas.  zero chamada de rede
Roteador multi-provedor (24/09/2026, capacidade — 46+ peças na fila, ~10-13/dia só em Workers AI):
  8b. Workers AI 429 -> revisor cai no fallback (Groq) e a decisão sai normalmente
  8c. TODOS os provedores (Workers AI + Groq + Gemini + OpenRouter) em 429/indisponível -> ADIADO
      (controle negativo do 8b: nenhum provedor sobrando -> nunca aprova/escala por engano)
  8d. OpenRouter só aceita modelo com sufixo ':free' — modelo pago é recusado (custo zero, PAR-01)
Provedores de reserva (24/09/2026, dívida do PR #55 — A1 sem voto do fato: Groq vazio, OpenRouter prosa):
  11a. vazio com finish_reason=length -> próximo provedor; corpo leva reasoning low + JSON forçado + teto >=4000
  11b. todos vazios -> ErroModelo (controle negativo)   11c. prosa com JSON embutido -> extrator pega
  11d. prosa sem JSON -> outro provedor vota             11e. prosa sem JSON em todos -> falha de formato, não voto
  11f. 503 passageiro: 1 retentativa; persistente conta como indisponível (adiado), não defeito
Roda `python redes/testar_conselho.py` na raiz do repo; sai != 0 se qualquer prova falhar."""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
AQUI = os.path.dirname(os.path.abspath(__file__))
for p in (AQUI, os.path.join(AQUI, "lib"), os.path.join(AQUI, "conselho"), os.path.join(AQUI, "video")):
    sys.path.insert(0, p)
import conselho  # noqa: E402
import revisores  # noqa: E402

FALHAS = []


def checar(nome, got, esperado):
    print(("OK  " if got == esperado else "FALHA") + " - %s -> %r (esperado %r)" % (nome, got, esperado))
    if got != esperado:
        FALHAS.append(nome)


OK = json.dumps({"passa": True, "nota": 5, "motivos": [], "trechos": []})
NAO = json.dumps({"passa": False, "nota": 2, "motivos": ["número sem fonte"], "trechos": ["68%"]})
EDIT3 = json.dumps({"passa": True, "nota": 3, "motivos": [], "trechos": []})


class Mock:
    """conversar(papel, msgs) roteirizado: respostas[papel] = lista (uma por chamada; repete a última).
    `redator` aceita string única (sempre a mesma resposta) OU lista (uma por chamada ao redator,
    inclusive as retentativas de JSON malformado — 24/09/2026, PR #54); repete a última."""
    def __init__(self, respostas, redator='{"texto": "texto reescrito limpo"}'):
        self.respostas = respostas
        self.redator = redator
        self.chamadas = []
        self.excluidos_redator = []  # excluir_provedores recebido em CADA chamada ao redator, em ordem

    def __call__(self, papel, msgs, max_saida=None, excluir_provedores=None):
        self.chamadas.append(papel)
        if papel == "redator":
            self.excluidos_redator.append(excluir_provedores)
            lista = self.redator if isinstance(self.redator, list) else [self.redator]
            n = sum(1 for c in self.chamadas if c == "redator")
            bruto = lista[min(n, len(lista)) - 1]
            modelo = "mock-redator" if n == 1 else "mock-redator-retry"
            return bruto, 1.0, modelo
        lista = self.respostas.get(papel, [OK])
        n = sum(1 for c in self.chamadas if c == papel)
        return lista[min(n, len(lista)) - 1], 1.0, "mock-" + papel


def peca(**extra):
    base = {"peca_id": "qa-mock", "canal": "linkedin_pagina", "texto": "Cento e oitenta dias. A certidão vence.",
            "texto_arte": "", "imagens": [], "nota_urls": [], "fontes": [], "formato": "texto"}
    base.update(extra)
    return base


votos_gravados = []
gravar = lambda pid, rodada, papel, v: votos_gravados.append((pid, rodada, papel, v["passa"]))  # noqa: E731

print("== 1. unanimidade aprova na 1ª volta, sem redator ==")
m = Mock({})
r = conselho.avaliar(peca(), gravar=gravar, conversar=m)
checar("decisão", r["decisao"], "aprovado")
checar("voltas", r["rodadas"], 1)
checar("aprovado na 1ª volta", r["aprovado_primeira_volta"], True)
checar("redator não chamado", "redator" in m.chamadas, False)
checar("4 revisores de modelo chamados (visual de peça só-texto não gasta modelo)", len(m.chamadas), 4)
checar("5 votos gravados", len([v for v in votos_gravados if v[1] == 1]), 5)

print("\n== 2. 1 reprova (fato) -> redator reescreve -> aprova na 2ª volta ==")
m = Mock({"fato": [NAO, OK]})
r = conselho.avaliar(peca(), conversar=m)
checar("decisão", r["decisao"], "aprovado")
checar("voltas", r["rodadas"], 2)
checar("redator chamado 1x", m.chamadas.count("redator"), 1)
checar("texto final é o do redator", r["texto_final"], "texto reescrito limpo")
checar("não conta como 1ª volta", r["aprovado_primeira_volta"], False)
checar("histórico expõe o redator (modelo + sem erro, dívida do PR #54)",
       r["votos_por_rodada"][0].get("redator"),
       {"passa": True, "nota": None, "motivos": [], "trechos": [], "modelo": "mock-redator", "invalida": False})

print("\n== 3. 3 voltas falhando -> escala ==")
m = Mock({"voz": [NAO]})
r = conselho.avaliar(peca(), conversar=m)
checar("decisão", r["decisao"], "escalado")
checar("voltas", r["rodadas"], 3)
checar("redator chamado 2x (entre as voltas)", m.chamadas.count("redator"), 2)
checar("motivo do revisor na escalada", any(x.startswith("voz:") for x in r["motivos"]), True)

print("\n== 4. resposta de modelo malformada -> reprova (falha fechada) ==")
for bruto, rotulo in [("isto não é json", "texto solto"), ("", "vazio"), ('{"passa": "sim", "nota": 5}', "passa string"),
                      ('{"passa": true, "nota": 7, "motivos": [], "trechos": []}', "nota fora da faixa"),
                      ('{"passa": true, "nota": true, "motivos": [], "trechos": []}', "nota booleana"),
                      ('{"passa": true, "nota": 5, "motivos": "x", "trechos": []}', "motivos não-lista"),
                      ('[{"passa": true}]', "lista em vez de objeto")]:
    v, erro = revisores.validar(bruto)
    checar("validar(%s) rejeita" % rotulo, v is None and bool(erro), True)
v, erro = revisores.validar('```json\n{"passa": true, "nota": 4, "motivos": [], "trechos": []}\n```')
checar("cerca ```json``` aceita", erro, None)
m = Mock({"risco": ["{quebrado"]})
r = conselho.avaliar(peca(), conversar=m)
checar("malformado nunca aprova", r["decisao"], "escalado")
v1 = r["votos_por_rodada"][0]["risco"]
checar("voto malformado = reprova inválida", (v1["passa"], v1["invalida"]), (False, True))
checar("malformado sozinho não chama redator (nada de conteúdo a corrigir)", m.chamadas.count("redator"), 0)

print("\n== 4b. editorial nota 3 com passa=true é forçado a reprovar ==")
m = Mock({"editorial": [EDIT3]})
r = conselho.avaliar(peca(), conversar=m)
checar("nota 3 não passa", r["votos_por_rodada"][0]["editorial"]["passa"], False)

print("\n== 4c. redator: JSON malformado na 1ª chamada -> 1 retentativa evita o MESMO provedor e resolve "
      "(dívida do PR #54, 24/09/2026) ==")
chamadas_redator_c = []


def _conversar_redator_retry_ok(papel, msgs, max_saida=None, excluir_provedores=None):
    chamadas_redator_c.append(excluir_provedores)
    if len(chamadas_redator_c) == 1:
        return "isto não é json, o modelo saiu do formato", 2.0, "groq:openai/gpt-oss-120b"
    return '{"texto": "peça corrigida pelo retry"}', 3.0, "gemini:gemini-3.6-flash"


texto, neur, modelo, erro = conselho.redator.reescrever(
    peca(), {"fato": {"passa": False, "motivos": ["número sem fonte"], "trechos": ["68%"]}},
    conversar=_conversar_redator_retry_ok)
checar("resolveu no retry", texto, "peça corrigida pelo retry")
checar("neurônios somam as 2 chamadas", neur, 5.0)
checar("modelo final é de quem respondeu certo (2ª tentativa)", modelo, "gemini:gemini-3.6-flash")
checar("sem erro de parse quando o retry resolve", erro, None)
checar("2 chamadas ao redator (1ª + retry)", len(chamadas_redator_c), 2)
checar("retentativa excluiu o provedor que falhou na 1ª (groq)", chamadas_redator_c[1], {"groq"})

print("\n== 4d. redator: JSON malformado nas 2 tentativas -> conta como falha, mas expõe "
      "provedor:modelo + resumo do erro (NUNCA o texto inteiro) ==")
resposta_solta = "resposta solta, nada de JSON aqui, " + "x" * 500  # >80 car. de propósito


def _conversar_redator_sempre_malformado(papel, msgs, max_saida=None, excluir_provedores=None):
    return resposta_solta, 1.0, "openrouter:nvidia/nemotron-3-super-120b-a12b:free"


texto, neur, modelo, erro = conselho.redator.reescrever(
    peca(), {"fato": {"passa": False, "motivos": ["número sem fonte"], "trechos": ["68%"]}},
    conversar=_conversar_redator_sempre_malformado)
checar("sem reescrita depois das 2 tentativas", texto, None)
checar("neurônios somam as 2 chamadas", neur, 2.0)
checar("modelo grava as 2 tentativas (mesmo provedor — retry não achou outro registrado no mock)", modelo,
       "openrouter:nvidia/nemotron-3-super-120b-a12b:free -> openrouter:nvidia/nemotron-3-super-120b-a12b:free")
checar("resumo do erro NUNCA carrega a resposta inteira (bruto tem %d caracteres)" % len(resposta_solta),
       erro is not None and len(erro) < len(resposta_solta) and resposta_solta not in erro, True)
checar("resumo cita as DUAS tentativas", erro is not None and erro.count("tentativa") == 1 and "retry" in erro, True)

print("\n== 4e. integração: redator JSON malformado + retry dentro de conselho.avaliar() (histórico "
      "expõe o par de modelos e o resumo do erro, nunca perde a pista como em 24/09) ==")
m = Mock({"fato": [NAO]}, redator=["isto não é json", "ainda não é json"])
r = conselho.avaliar(peca(), conversar=m)
checar("decisão (3 voltas, redator nunca resolve, escala)", r["decisao"], "escalado")
checar("redator tentou 1ª+retry em cada uma das 2 voltas com conteúdo pra corrigir", m.chamadas.count("redator"), 4)
red = r["votos_por_rodada"][0].get("redator")
checar("histórico expõe o par de modelos tentados na 1ª volta", red is not None and "mock-redator" in red["modelo"]
       and "mock-redator-retry" in red["modelo"], True)
checar("resumo do erro de parse não é o texto inteiro (curto, auditável)",
       red is not None and len(red["motivos"][0]) < 600, True)
checar("retry da 1ª volta excluiu o mock-redator (o que falhou primeiro)", m.excluidos_redator[1], {"mock-redator"})

print("\n== 6. visual reprova -> escala direto, sem redator ==")
from PIL import Image  # noqa: E402
png = os.path.join(tempfile.mkdtemp(), "arte.png")
Image.new("RGB", (40, 50), (10, 10, 10)).save(png)
m = Mock({"visual": [NAO]})
r = conselho.avaliar(peca(formato="imagem", imagens=[png]), conversar=m)
checar("decisão", r["decisao"], "escalado")
checar("voltas", r["rodadas"], 1)
checar("redator não chamado", m.chamadas.count("redator"), 0)
m = Mock({})
r = conselho.avaliar(peca(formato="imagem", imagens=[]), conversar=m)
checar("peça visual SEM arte legível reprova no visual", r["votos_por_rodada"][0]["visual"]["passa"], False)

print("\n== 7. guarda barra -> nenhum modelo de REVISÃO naquela volta (o redator ainda é chamado pra "
      "corrigir o que a guarda apontou, e agora aparece no histórico — dívida do PR #54) ==")
m = Mock({}, redator='{"texto": "Cento e oitenta dias. A certidão vence."}')
r = conselho.avaliar(peca(texto="A casa faz a certidão."), conversar=m)
checar("volta 1 não chama nenhum REVISOR de modelo (só guarda + redator, que ela mesma aciona)",
       sorted(r["votos_por_rodada"][0].keys()), ["guarda", "redator"])
checar("redator limpou e a volta 2 aprovou", (r["decisao"], r["rodadas"]), ("aprovado", 2))

print("\n== 8. Workers AI sem orçamento hoje E nenhum fallback configurado -> CotaEsgotada, zero rede ==")
import modelos  # noqa: E402
_env_guardados = {k: os.environ.pop(k, None) for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY")}
# modelos.py lê as chaves NA IMPORTAÇÃO: tirar só do ambiente não basta quando o job tem os segredos no ambiente
# inteiro (reserva no GitLab, 30/09/2026: os 2 checks abaixo falhavam e ainda gastavam cota real de Groq/OpenRouter).
_consts_guardadas = {k: getattr(modelos, k) for k in ("GROQ_CHAVE", "GEMINI_CHAVE", "OPENROUTER_CHAVE")}
for _k in _consts_guardadas:
    setattr(modelos, _k, "")
try:
    levantou = False
    try:
        modelos.conversar("fato", [{"role": "user", "content": "x"}], cf_disponivel=False)
    except modelos.CotaEsgotada:
        levantou = True
    checar("CotaEsgotada (nenhum provedor configurado)", levantou, True)
    # mesmo cenário, mas passando por conselho.avaliar (orçamento de CF já no teto, sem fallback no
    # ambiente) — a peça inteira sai ADIADA, sem nenhum voto de modelo (só a guarda, se aplicável).
    orc = conselho.Orcamento(7900, teto=8000)
    r = conselho.avaliar(peca(), orcamento=orc)  # conversar=None -> usa o roteador de produção
    checar("decisão (sem fallback no ambiente)", r["decisao"], "adiado")
finally:
    for k, v in _env_guardados.items():
        if v is not None:
            os.environ[k] = v
    for _k, _v in _consts_guardadas.items():
        setattr(modelos, _k, _v)

print("\n== 8b. Workers AI 429 -> revisor cai no fallback (Groq) e a decisão sai normalmente ==")
_chamadores_originais = dict(modelos._CHAMADORES)


def _cf_sempre_429(modelo, mensagens, max_saida):
    raise modelos._Cota("franquia gratuita diária do Workers AI esgotada (HTTP 429/4006) [mock]")


def _groq_ok(modelo, mensagens, max_saida):
    return OK, 0.0


modelos._CHAMADORES["cf"] = _cf_sempre_429
modelos._CHAMADORES["groq"] = _groq_ok
os.environ["GROQ_API_KEY"] = "chave-mock-groq"
try:
    texto, neur, modelo_usado = modelos.conversar("fato", [{"role": "user", "content": "x"}])
    checar("texto veio do fallback", texto, OK)
    checar("modelo usado é do Groq (não do CF)", modelo_usado.startswith("groq:"), True)
    # nível conselho.avaliar inteiro, sem overrides — orçamento zerado (CF cabe), CF 429 -> Groq responde
    r = conselho.avaliar(peca(), orcamento=conselho.Orcamento(0, teto=8000))
    checar("decisão sai normalmente com CF fora do ar", r["decisao"], "aprovado")
finally:
    modelos._CHAMADORES.update(_chamadores_originais)
    os.environ.pop("GROQ_API_KEY", None)

print("\n== 8c. CONTROLE NEGATIVO — TODOS os provedores em 429/indisponível -> ADIADO (nunca aprova/escala) ==")


def _sempre_429(modelo, mensagens, max_saida):
    raise modelos._Cota("limite gratuito esgotado [mock]")


for chave_env, nome in (("GROQ_API_KEY", "groq"), ("GEMINI_API_KEY", "gemini"), ("OPENROUTER_API_KEY", "openrouter")):
    os.environ[chave_env] = "chave-mock"
    modelos._CHAMADORES[nome] = _sempre_429
modelos._CHAMADORES["cf"] = _cf_sempre_429
try:
    levantou = False
    try:
        modelos.conversar("fato", [{"role": "user", "content": "x"}])
    except modelos.CotaEsgotada:
        levantou = True
    checar("CotaEsgotada quando TODOS os provedores estão sem cota", levantou, True)
    r = conselho.avaliar(peca(), orcamento=conselho.Orcamento(0, teto=8000))
    checar("peça inteira ADIADA (nunca aprovada/escalada por falta de provedor)", r["decisao"], "adiado")
finally:
    modelos._CHAMADORES.update(_chamadores_originais)
    for chave_env in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        os.environ.pop(chave_env, None)

print("\n== 8d. OpenRouter só aceita modelo com sufixo ':free' (custo zero inegociável) ==")
os.environ["OPENROUTER_API_KEY"] = "chave-mock"
try:
    levantou_indisponivel = False
    try:
        modelos._chamar_openrouter("algum/modelo-pago", [{"role": "user", "content": "x"}], None)
    except modelos._Indisponivel:
        levantou_indisponivel = True
    checar("modelo OpenRouter sem ':free' é recusado antes de qualquer chamada de rede", levantou_indisponivel, True)
finally:
    os.environ.pop("OPENROUTER_API_KEY", None)
checar("CONTROLE POSITIVO: todo modelo em FALLBACKS[*][openrouter] termina em ':free'",
       all(m.endswith(":free") for papel, cadeia in modelos.FALLBACKS.items()
           for prov, m in cadeia if prov == "openrouter"), True)

print("\n== 9. cota gratuita esgotada (HTTP 429/4006) no meio -> ADIADO, nunca escalado nem aprovado ==")
import modelos  # noqa: E402


def _cota(papel, msgs, max_saida=None):
    if papel == "risco":
        raise modelos.CotaEsgotada("franquia esgotada (mock)")
    return OK, 1.0, "mock"


orc = conselho.Orcamento(0, teto=8000)
r = conselho.avaliar(peca(), conversar=_cota, orcamento=orc)
checar("cota esgotada -> adiado", r["decisao"], "adiado")
checar("CotaEsgotada de OUTRO provedor NÃO zera o orçamento do Workers AI (30/09/2026)", orc.cabe(), True)


def _cota_cf(papel, msgs, max_saida=None):
    raise modelos.CotaEsgotada("'risco': todos os provedores sem cota/credencial hoje (tentados: cf, groq) — última: x")


orc = conselho.Orcamento(0, teto=8000)
r = conselho.avaliar(peca(), conversar=_cota_cf, orcamento=orc)
checar("cota do PRÓPRIO Workers AI esgotada -> orçamento marcado esgotado", (r["decisao"], orc.cabe()), ("adiado", False))

print("\n== 9b. Gemini: 429 num modelo passa para o proximo modelo da cascata (cota por modelo, 01/10/2026) ==")
_orig_res, _orig_chave = modelos._chamar_reserva, modelos.GEMINI_CHAVE
_tentados = []
_primeiro_extra = modelos.GEMINI_EXTRAS[0]


def _res(prov, url, chave, modelo, msgs, ms):
    _tentados.append(modelo)
    if modelo in ("m-esgotado", _primeiro_extra):
        raise modelos._Cota("429 mock")
    return "ok", 0.0


modelos._chamar_reserva, modelos.GEMINI_CHAVE = _res, "x"
try:
    checar("1o e 2o modelo esgotados -> responde o 3o", (modelos._chamar_gemini("m-esgotado", [], 10)[0], len(_tentados)), ("ok", 3))
    _extras = modelos.GEMINI_EXTRAS
    modelos.GEMINI_EXTRAS = ()
    try:
        modelos._chamar_gemini("m-esgotado", [], 10)
        achou = False
    except modelos._Cota:
        achou = True
    modelos.GEMINI_EXTRAS = _extras
    checar("CONTROLE NEGATIVO: sem outro modelo, o 429 continua subindo como cota", achou, True)
finally:
    modelos._chamar_reserva, modelos.GEMINI_CHAVE = _orig_res, _orig_chave

print("\n== 9c. MODO ECONOMICO: 1 chamada para os 4 revisores de texto + 1 voto visual (01/10/2026) ==")
import json as _json
import revisores as _rev
_chamadas = []


def _painel(papel, msgs, max_saida=None):
    _chamadas.append(papel)
    ok = {"passa": True, "nota": 5, "motivos": [], "trechos": []}
    return _json.dumps({"fato": ok, "voz": ok, "risco": ok, "editorial": ok}), 3.0, "mock:painel"


_v = _rev.revisar_texto_economico(peca(), _painel)
checar("economico: 1 chamada devolve os 4 votos", (len(_chamadas), sorted(_v)), (1, ["editorial", "fato", "risco", "voz"]))
checar("economico: todos passam quando o painel aprova", all(x["passa"] for x in _v.values()), True)


def _painel_reprova(papel, msgs, max_saida=None):
    _chamadas.append(papel)
    ok = {"passa": True, "nota": 5, "motivos": [], "trechos": []}
    no = {"passa": False, "nota": 2, "motivos": ["numero fora da fonte"], "trechos": ["12%"]}
    return _json.dumps({"fato": no, "voz": ok, "risco": ok, "editorial": ok}), 3.0, "mock:painel"


_v = _rev.revisar_texto_economico(peca(), _painel_reprova)
checar("CONTROLE NEGATIVO: um revisor reprova e o voto dele reprova (os outros passam)", (_v["fato"]["passa"], _v["voz"]["passa"]), (False, True))


def _painel_incompleto(papel, msgs, max_saida=None):
    if papel == "fato" and msgs[0]["content"].startswith("Voce e um painel"):
        ok = {"passa": True, "nota": 5, "motivos": [], "trechos": []}
        return _json.dumps({"fato": ok, "voz": ok}), 3.0, "mock:painel"  # faltam risco e editorial
    return OK, 1.0, "mock:individual"


_v = _rev.revisar_texto_economico(peca(), _painel_incompleto)
checar("CONTROLE NEGATIVO: trecho ausente cai na revisao individual (nunca vira aprovacao no escuro)",
       (_v["risco"]["modelo"], _v["fato"]["modelo"].startswith("economico:")), ("mock:individual", True))

print("\n== 5. chave de parada -> nada roda ==")
checar("pausado('1')", conselho.pausado(lambda c: "1"), True)
checar("pausado(None)", conselho.pausado(lambda c: None), False)


def _explode(c):
    raise RuntimeError("banco fora")


checar("erro ao ler a chave = pausado (falha fechada)", conselho.pausado(_explode), True)
import lote_aprovacao  # noqa: E402
import publicar  # noqa: E402
_seg = lote_aprovacao.supa.segredo
lote_aprovacao.supa.segredo = lambda c: "1" if c == "redes_pausa" else None
m = Mock({})
tocou = []
_listar = lote_aprovacao.estoque.listar
lote_aprovacao.estoque.listar = lambda *a, **k: tocou.append("estoque") or []
try:
    r = lote_aprovacao.rodar("innconta", qa=True, conversar=m)
    checar("lote pausado", r, {"pausado": True})
    checar("lote pausado não leu estoque", tocou, [])
    checar("lote pausado não chamou modelo", m.chamadas, [])
    rp = publicar.rodar("innconta", modo_qa=True)
    checar("publicar pausado", (rp.get("pausado"), rp.get("publicadas")), (True, 0))
finally:
    lote_aprovacao.supa.segredo = _seg
    lote_aprovacao.estoque.listar = _listar

print("\n== 10. PRIORIDADE + DATA FIXA (24/09/2026, peça da PGFN) ==")
import datetime  # noqa: E402
_comum = {"_peca_id": "2026-09-22-comum", "status": "aprovado", "canal": "linkedin_pagina"}
_urgente = {"_peca_id": "2026-09-24-pgfn", "status": "aprovado", "canal": "instagram", "prioridade": "urgente",
            "data_publicacao": "2026-09-25", "mes_ref": "2026-09"}
_datada = {"_peca_id": "2026-09-23-datada", "status": "aprovado", "canal": "instagram",
           "data_publicacao": datetime.date(2026, 10, 1)}
ordem = [c[0]["_peca_id"] for c in lote_aprovacao.ordenar_por_urgencia([(_comum, None), (_datada, None), (_urgente, None)])]
checar("urgente primeiro, depois data fixa, depois o resto", ordem,
       ["2026-09-24-pgfn", "2026-09-23-datada", "2026-09-22-comum"])
_c2 = dict(_comum, _peca_id="2026-09-23-outra")
ordem = [c[0]["_peca_id"] for c in lote_aprovacao.ordenar_por_urgencia([(_comum, None), (_c2, None)])]
checar("CONTROLE NEGATIVO: sem urgência/data a ordem do estoque é preservada", ordem,
       ["2026-09-22-comum", "2026-09-23-outra"])
checar("data fixa como date do YAML vira texto ISO", lote_aprovacao._data_fixa(_datada), "2026-10-01")

_patches, _emails = [], []
_patch0, _mail0 = lote_aprovacao.supa.patch, lote_aprovacao.supa.enviar_email
lote_aprovacao.supa.patch = lambda tab, filtro, corpo, **k: _patches.append((tab, filtro, corpo)) or [{}]
lote_aprovacao.supa.enviar_email = lambda assunto, para, html, **k: _emails.append((assunto, para))
try:
    checar("fixar_data_da_peca grava", lote_aprovacao.fixar_data_da_peca("2026-09-24-pgfn", _urgente), True)
    checar("PATCH só de agendamento (data, mes_ref, calendario_status), sem status",
           _patches[-1], ("ic_redes_publicacao", "peca_id=eq.2026-09-24-pgfn",
                          {"data_publicacao": "2026-09-25", "mes_ref": "2026-09", "calendario_status": "aprovado"}))
    checar("peça sem data fixa não recebe PATCH", (lote_aprovacao.fixar_data_da_peca("x", _comum), len(_patches)), (False, 1))

    def _patch_falha(*a, **k):
        raise RuntimeError("HTTP 500")
    lote_aprovacao.supa.patch = _patch_falha
    checar("PATCH que falha 2x devolve False", lote_aprovacao.fixar_data_da_peca("2026-09-24-pgfn", _urgente), False)
    checar("e ALERTA a central técnica (AOP-01), nunca o CVO", [e[1] for e in _emails], ["central@innconta.com.br"])
finally:
    lote_aprovacao.supa.patch, lote_aprovacao.supa.enviar_email = _patch0, _mail0

# rodada inteira por mock: a peça urgente é a 1ª avaliada e a ÚNICA que ganha data; se a cota acabar
# depois dela, as comuns são adiadas e a urgente já foi decidida.
_saved = {k: getattr(lote_aprovacao, k) for k in ("estoque", "renderizar_pendentes", "conselho", "avisos")}
_saved_supa = {k: getattr(lote_aprovacao.supa, k) for k in ("segredo", "rpc", "select", "patch")}


class _Estoque:
    @staticmethod
    def listar(marca=None):
        return [dict(_comum), dict(_c2), dict(_urgente)]


class _Render:
    @staticmethod
    def renderizar(*a, **k):
        return []


class _Conselho:
    pausado = staticmethod(lambda: False)
    neuronios_hoje = staticmethod(lambda: 0.0)
    Orcamento = conselho.Orcamento
    gravador_banco = staticmethod(lambda prefixo="": None)
    avaliados = []

    @classmethod
    def avaliar(cls, peca_c, **k):
        cls.avaliados.append(peca_c["peca_id"])
        if len(cls.avaliados) > 1:  # depois da 1ª a franquia acaba
            return {"decisao": "adiado", "rodadas": 0, "neuronios": 0.0, "motivos": ["cota"], "texto_final": ""}
        return {"decisao": "aprovado", "rodadas": 1, "neuronios": 300.0, "motivos": [], "texto_final": peca_c["texto"]}


class _Avisos:
    PREFIXO_QA = "qa-conselho-"
    CENTRAL = "central@innconta.com.br"
    enviar_escaladas = staticmethod(lambda *a, **k: {"escaladas": 0})


_rpcs, _pat = [], []
lote_aprovacao.estoque, lote_aprovacao.renderizar_pendentes = _Estoque, _Render
lote_aprovacao.conselho, lote_aprovacao.avisos = _Conselho, _Avisos
lote_aprovacao.supa.segredo = lambda c: None
lote_aprovacao.supa.rpc = lambda nome, corpo=None, **k: _rpcs.append((nome, corpo)) or {"ok": True}
lote_aprovacao.supa.select = lambda tab, q, **k: []
lote_aprovacao.supa.patch = lambda tab, filtro, corpo, **k: _pat.append((filtro, corpo)) or [{}]
try:
    res = lote_aprovacao.rodar("innconta")
    checar("a peça urgente foi a 1ª avaliada (mesmo listada por último no estoque)", _Conselho.avaliados[0], "2026-09-24-pgfn")
    checar("as comuns viram 'adiado' quando a cota acaba", res["adiado"], 2)
    reg = [c for n, c in _rpcs if n == "redes_conselho_registrar"]
    checar("só a urgente foi registrada como aprovada", [(r["p_peca_id"], r["p_decisao"]) for r in reg],
           [("2026-09-24-pgfn", "aprovado")])
    checar("registro leva o mes_ref da data fixa", reg[0]["p_mes_ref"], "2026-09")
    checar("a data fixa foi gravada só para ela, sem esperar o calendário", _pat,
           [("peca_id=eq.2026-09-24-pgfn",
             {"data_publicacao": "2026-09-25", "mes_ref": "2026-09", "calendario_status": "aprovado"})])
finally:
    for k, v in _saved.items():
        setattr(lote_aprovacao, k, v)
    for k, v in _saved_supa.items():
        setattr(lote_aprovacao.supa, k, v)

# autocura: linha decidida SEM data (PATCH que falhou antes) recebe a data; controles negativos ao lado
_pat2 = []
_estoque0 = lote_aprovacao.estoque
lote_aprovacao.estoque = _Estoque
lote_aprovacao.supa.select = lambda tab, q, **k: [
    {"status": "aprovado", "data_publicacao": None, "calendario_status": None, "publicado_em": None}]
lote_aprovacao.supa.patch = lambda tab, filtro, corpo, **k: _pat2.append(filtro) or [{}]
try:
    checar("reconciliar: aprovada sem data ganha a data", lote_aprovacao.reconciliar_datas_fixas("innconta"),
           ["2026-09-24-pgfn"])
    _pat2.clear()
    lote_aprovacao.supa.select = lambda tab, q, **k: [
        {"status": "aprovado", "data_publicacao": None, "calendario_status": "aguardando_api", "publicado_em": None}]
    checar("CONTROLE NEGATIVO: devolvida à fila de propósito (aguardando_api) não é redatada",
           (lote_aprovacao.reconciliar_datas_fixas("innconta"), _pat2), ([], []))
    lote_aprovacao.supa.select = lambda tab, q, **k: [
        {"status": "aprovado", "data_publicacao": "2026-09-25", "calendario_status": "aprovado", "publicado_em": None}]
    checar("CONTROLE NEGATIVO: já com data não é tocada",
           (lote_aprovacao.reconciliar_datas_fixas("innconta"), _pat2), ([], []))
finally:
    lote_aprovacao.estoque = _estoque0
    for k, v in _saved_supa.items():
        setattr(lote_aprovacao.supa, k, v)

print("\n== 11. PROVEDORES DE RESERVA: vazio/prosa não viram voto (dívida do PR #55, 24/09/2026) ==")

_resp_por_url = {}   # trecho da URL -> lista de respostas (dict = corpo 200; int = HTTP de erro)
_corpos_enviados = []


def _post_mock(url, corpo, cab, timeout=150):
    import io
    import urllib.error
    _corpos_enviados.append((url, corpo))
    for trecho, fila in _resp_por_url.items():
        if trecho in url:
            r = fila.pop(0) if len(fila) > 1 else fila[0]
            if isinstance(r, int):
                raise urllib.error.HTTPError(url, r, "mock", {}, io.BytesIO(b'{"error":"mock"}'))
            return r
    raise AssertionError("URL não roteirizada no mock: " + url)


def _resp(conteudo, finish="stop", reasoning=0, completion=10):
    return {"choices": [{"message": {"content": conteudo}, "finish_reason": finish}],
            "usage": {"completion_tokens": completion, "completion_tokens_details": {"reasoning_tokens": reasoning}}}


VAZIO_LENGTH = _resp("", finish="length", reasoning=698, completion=700)  # o que o Groq devolveu em 24/09
PROSA = _resp("We need to verify each verifiable element in the piece against the provided sources. "
              "The piece is a LinkedIn page text.")  # o que o nemotron devolveu em 24/09 (sem JSON)
PROSA_COM_JSON = _resp('Segue a análise.\n{"passa": false, "nota": 2, "motivos": ["68% sem fonte"], '
                       '"trechos": ["68%"]}\nFim.')

_orig = {k: getattr(modelos, k) for k in ("_post", "GROQ_CHAVE", "GEMINI_CHAVE", "OPENROUTER_CHAVE", "CF_CHAVE")}
_sleep0 = modelos.time.sleep
modelos._post = _post_mock
modelos.GROQ_CHAVE = modelos.GEMINI_CHAVE = modelos.OPENROUTER_CHAVE = "chave-mock"
modelos.CF_CHAVE = ""
modelos.time.sleep = lambda s: None


def _conv_reserva(papel, msgs, max_saida=None, excluir_provedores=None):
    return modelos.conversar(papel, msgs, max_saida=max_saida, cf_disponivel=False,
                             excluir_provedores=excluir_provedores)


try:
    # 11a. vazio com finish_reason=length -> PRÓXIMO provedor (antes, "" passava como resposta)
    _resp_por_url.clear(); _corpos_enviados.clear()
    _resp_por_url.update({"groq.com": [VAZIO_LENGTH], "googleapis": [_resp(OK)], "openrouter": [_resp(OK)]})
    texto, _n, usado = modelos.conversar("fato", [{"role": "user", "content": "x"}], cf_disponivel=False)
    checar("11a vazio+length no Groq -> respondeu o próximo (Gemini)", usado.split(":")[0], "gemini")
    checar("11a texto é o do Gemini", texto, OK)
    corpo_groq = _corpos_enviados[0][1]
    checar("11a Groq gpt-oss vai com reasoning_effort=low", corpo_groq.get("reasoning_effort"), "low")
    checar("11a Groq com JSON forçado", corpo_groq.get("response_format"), {"type": "json_object"})
    checar("11a Groq com teto que cabe raciocínio + JSON (>= 4000, não 700)",
           corpo_groq.get("max_completion_tokens", 0) >= 4000, True)

    # corpo de cada provedor (parâmetros de raciocínio e formato)
    c_or = modelos._corpo("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", [], None)
    checar("11a OpenRouter: reasoning effort low + exclude", c_or.get("reasoning"), {"effort": "low", "exclude": True})
    checar("11a OpenRouter: JSON forçado e teto >= 4000",
           (c_or.get("response_format"), c_or.get("max_tokens", 0) >= 4000), ({"type": "json_object"}, True))
    c_ge = modelos._corpo("gemini", "gemini-3.6-flash", [], None)
    checar("11a Gemini: reasoning_effort low + JSON forçado", (c_ge.get("reasoning_effort"), c_ge.get("response_format")),
           ("low", {"type": "json_object"}))
    checar("11a teto cresce com o pedido (max_saida 5000 -> 6500)",
           modelos._corpo("groq", "openai/gpt-oss-120b", [], 5000)["max_completion_tokens"], 6500)

    # 11b. CONTROLE NEGATIVO: todos vazios -> ErroModelo (falha fechada), nunca sucesso nem CotaEsgotada
    _resp_por_url.update({"groq.com": [VAZIO_LENGTH], "googleapis": [VAZIO_LENGTH], "openrouter": [_resp(None)]})
    tipo = None
    try:
        modelos.conversar("fato", [{"role": "user", "content": "x"}], cf_disponivel=False)
        tipo = "sucesso"
    except modelos.CotaEsgotada:
        tipo = "CotaEsgotada"
    except modelos.ErroModelo as e:
        tipo = "ErroModelo" if "VAZIO" in str(e) else "ErroModelo sem diagnóstico"
    checar("11b todos vazios -> ErroModelo com o diagnóstico (finish_reason/tokens)", tipo, "ErroModelo")

    # 11c. prosa COM JSON embutido -> o extrator pega o objeto; voto válido na 1ª chamada
    _resp_por_url.update({"groq.com": [PROSA_COM_JSON], "googleapis": [_resp(OK)], "openrouter": [_resp(OK)]})
    _corpos_enviados.clear()
    v = revisores.revisar("fato", peca(), conversar=_conv_reserva)
    checar("11c prosa com JSON embutido vira voto válido", (v["passa"], v["nota"], v["invalida"]), (False, 2, False))
    checar("11c ... sem gastar outro provedor", len(_corpos_enviados), 1)
    checar("11c extrator: exige_chave ignora objeto de exemplo sem a chave",
           revisores.extrair_json('ex.: {"x": 1} e depois {"passa": true, "nota": 5}', exige_chave="passa"),
           {"passa": True, "nota": 5})
    checar("11c extrator: prosa sem objeto -> None", revisores.extrair_json("nada aqui {quebrado", "passa"), None)
    checar("11c redator também extrai {\"texto\"} embutido em prosa",
           conselho.redator._parsear('Pronto: {"texto": "peça limpa"} fim', "original"), ("peça limpa", None))

    # 11d. prosa SEM JSON no 1º provedor -> tenta o PRÓXIMO (excluindo quem saiu do formato) e vota
    _resp_por_url.update({"groq.com": [PROSA], "googleapis": [_resp(NAO)], "openrouter": [_resp(OK)]})
    _corpos_enviados.clear()
    v = revisores.revisar("fato", peca(), conversar=_conv_reserva)
    checar("11d prosa sem JSON no Groq -> voto do Gemini", (v["passa"], v["nota"], v["invalida"]), (False, 2, False))
    checar("11d rótulo guarda quem saiu do formato e quem votou",
           v["modelo"], "groq:openai/gpt-oss-120b -> gemini:" + modelos.MODELO_GEMINI)
    checar("11d 2 chamadas (Groq, Gemini) — OpenRouter não gasto",
           [u.split("//")[1].split("/")[0] for u, _ in _corpos_enviados],
           ["api.groq.com", "generativelanguage.googleapis.com"])

    # 11e. prosa sem JSON em TODOS -> falha de FORMATO (invalida), não voto; nem adiado, nem aprovado
    _resp_por_url.update({"groq.com": [PROSA], "googleapis": [PROSA], "openrouter": [PROSA]})
    _corpos_enviados.clear()
    v = revisores.revisar("fato", peca(), conversar=_conv_reserva)
    checar("11e todos em prosa -> reprova inválida (falha de formato, não voto)",
           (v["passa"], v["invalida"], v.get("falha_formato")), (False, True, True))
    checar("11e cada provedor tentado 1 vez só", len(_corpos_enviados), 3)
    checar("11e motivo diz 'fora do formato' com o rastro dos 3",
           "fora do formato" in v["motivos"][0] and v["motivos"][0].count("JSON inválido") == 3, True)
    r = conselho.avaliar(peca(), conversar=_conv_reserva, papeis=("fato",), max_voltas=1)
    checar("11e no conselho: escala (falha fechada), nunca adia nem aprova", r["decisao"], "escalado")

    # 11f. 503 (sobrecarga, medido no Gemini em 24/09) 2x -> conta como indisponível (cota), não defeito
    _resp_por_url.update({"groq.com": [429], "googleapis": [503], "openrouter": [429]})
    tipo = None
    try:
        modelos.conversar("fato", [{"role": "user", "content": "x"}], cf_disponivel=False)
    except modelos.CotaEsgotada:
        tipo = "CotaEsgotada"
    except modelos.ErroModelo:
        tipo = "ErroModelo"
    checar("11f 429+503+429 -> CotaEsgotada (peça ADIADA, não escalada)", tipo, "CotaEsgotada")
    _resp_por_url.update({"groq.com": [429], "googleapis": [503, _resp(OK)], "openrouter": [429]})
    texto, _n, usado = modelos.conversar("fato", [{"role": "user", "content": "x"}], cf_disponivel=False)
    checar("11f 503 passageiro: a 2ª tentativa no mesmo provedor responde", (usado.split(":")[0], texto), ("gemini", OK))
finally:
    for k, v_ in _orig.items():
        setattr(modelos, k, v_)
    modelos.time.sleep = _sleep0

print("\n== 12. ESCALADA NUNCA VAI AO CVO (ordem do CVO 25/09/2026): e-mail só à central, sem botão de aprovar ==")
import avisos  # noqa: E402
_env0 = avisos.CVO_EMAIL
_enviados = []
_mail1 = avisos.supa.enviar_email
avisos.supa.enviar_email = lambda assunto, para, html, **k: (_enviados.append((assunto, list(para), html)) or {"ok": True})
try:
    _linha = {"id": "x1", "peca_id": "2026-09-26-pergunta-energia-01-instagram", "canal": "instagram",
              "conselho_motivos": ["editorial: a primeira frase não traz fato concreto"], "conselho_rodadas": 3,
              "texto_aprovado": "texto de teste"}
    avisos.CVO_EMAIL = "cvo-teste@example.com"
    avisos.enviar_escaladas("innconta", qa=False, linhas=[_linha])
    checar("12a produção: destinatário = só a central", _enviados[-1][1], ["central@innconta.com.br"])
    checar("12b CONTROLE NEGATIVO: o CVO não está entre os destinatários", "cvo-teste@example.com" in _enviados[-1][1], False)
    checar("12c o e-mail não tem botão de aprovação humana",
           ("Aprovar mesmo assim" in _enviados[-1][2]) or ("redes-aprovar" in _enviados[-1][2]), False)
    checar("12d o e-mail traz o motivo e a ação técnica",
           ("primeira frase não traz fato" in _enviados[-1][2]) and ("AÇÃO (central técnica)" in _enviados[-1][2]), True)
    avisos.enviar_escaladas("innconta", qa=True, linhas=[_linha])
    checar("12e QA: só a caixa de prova", _enviados[-1][1], ["central+qa-conselho@innconta.com.br"])
    _r0 = avisos.enviar_escaladas("innconta", qa=False, linhas=[])
    checar("12f sem escaladas: nenhum e-mail novo", (_r0, len(_enviados)), ({"escaladas": 0}, 2))
finally:
    avisos.supa.enviar_email = _mail1
    avisos.CVO_EMAIL = _env0

# =====================================================================================================================
# CONSELHO v2 + MULTIMARCA (29/09/2026, sessao instagram-contas-grupo). Tudo por MOCK: sem rede, sem modelo, sem banco.
# =====================================================================================================================
print("\n== 13. CONSELHO v2 (multimarca): registro, prompts por marca, citacao de empresa do grupo, sigilo, fonte, imagem, "
      "repeticao, alcance, visual duplo, cota, cache ==")
import shutil  # noqa: E402
import marcas  # noqa: E402
import alcance  # noqa: E402
import checagens  # noqa: E402
import cota  # noqa: E402
import guarda  # noqa: E402
import insumos  # noqa: E402
import repeticao  # noqa: E402

_kit_original = marcas.KIT
_kit_tmp = tempfile.mkdtemp(prefix="kit-teste-")


def _regras(marca, **extra):
    base = {"marca": marca, "tipo": "empresa", "nome": marca.capitalize(), "site": "https://%s.exemplo.com.br" % marca,
            "dominios_origem": ["%s.exemplo.com.br" % marca], "handle_instagram": "@%s.oficial" % marca,
            "ig_user_id": "1" + str(abs(hash(marca)) % 10 ** 8), "publicar": {"instagram": True, "linkedin": False, "horario_brt": "09:00"},
            "voz": {"tom": "tom-de-%s-marca" % marca, "proibidos": ["palavra-x-%s" % marca], "preferidos": []},
            "temas": ["tema-%s" % marca], "palavras_chave": ["regularidade", "fiscal", "energia"],
            "hashtags": ["#Marca%s" % marca.capitalize(), "#regularidadefiscal", "#gestao"],
            "fontes_oficiais_extra": ["aneel.exemplo.gov.br"], "discricao": {"sigilo": False, "nao_citar": []},
            "collab": {"parceiros": [], "min_por_semana": 0, "max_por_semana": 2}, "email_escalada": "central@innconta.com.br"}
    for k, v in extra.items():
        base[k] = v
    return base


def _grava_kit(marca, **extra):
    d = os.path.join(_kit_tmp, marca)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "regras.json"), "w", encoding="utf-8") as f:
        json.dump(_regras(marca, **extra), f, ensure_ascii=False)


_grava_kit("innconta", nome="InnConta", dominios_origem=["innconta.com.br"], handle_instagram="@innconta.oficial",
           collab={"parceiros": ["innovasphere"], "min_por_semana": 1, "max_por_semana": 2})
_grava_kit("innovasphere", nome="InnovaSphere", temas=["tecnologia", "inovacao"], palavras_chave=["tecnologia", "regularidade"])
_grava_kit("inncorpower", nome="InnCorPower", discricao={"sigilo": True, "nao_citar": ["Fazenda Sol Nascente"]},
           handle_instagram="@inncorpower.oficial")
_grava_kit("semtoken", nome="SemToken")
marcas.KIT = _kit_tmp
try:
    print("-- registro --")
    checar("todas() le as 4 entidades do kit", sorted(marcas.todas()), ["innconta", "inncorpower", "innovasphere", "semtoken"])
    checar("carregar marca sem regras.json: defaults SEGUROS (nao publica, sem sigilo, central tecnica)",
           (marcas.carregar("naoexiste")["publicar"]["instagram"], marcas.carregar("naoexiste")["email_escalada"],
            marcas.carregar("naoexiste")["_tem_regras"]), (False, "central@innconta.com.br", False))
    checar("marca invalida (path traversal) e recusada", (lambda: [marcas.carregar("../x")])
           if False else _levanta(lambda: marcas.carregar("../x")) if "_levanta" in globals() else True, True) if False else None
    try:
        marcas.carregar("../x")
        _trav = False
    except ValueError:
        _trav = True
    checar("marca com '../' e recusada (sem path traversal)", _trav, True)
    checar("nomes do grupo incluem as outras empresas", {"innovasphere", "inncorpower"} <= marcas.nomes_do_grupo(), True)
    checar("token por marca: chave ic_segredo.ig_access_token_<marca>", marcas.chave_token("innovasphere"), "ig_access_token_innovasphere")

    print("-- citar OUTRA empresa do grupo e PERMITIDO (CVO 29/09) --")
    R_IC = marcas.carregar("innconta")
    ok_g, mot = guarda.checar("A InnovaSphere e a InnConta trabalham juntas em regularidade. Veja @innovasphere.oficial.",
                              nomes_clientes=["InnovaSphere Tecnologia Ltda"], marca_nome="innconta", regras=R_IC)
    checar("guarda: citar InnovaSphere (mesmo constando na lista de clientes) NAO barra", (ok_g, mot), (True, []))
    ok_g, mot = guarda.checar("Cliente Construtora Fictícia Teste Ltda liberou.", nomes_clientes=["Construtora Fictícia Teste Ltda"],
                              marca_nome="innconta", regras=R_IC)
    checar("CONTROLE NEGATIVO: cliente real da base continua barrado", ok_g, False)
    p_prompt = revisores.construir_prompt("risco", R_IC) + revisores.construir_prompt("voz", R_IC)
    checar("prompts dizem que citar empresa do grupo e PERMITIDO e listam o grupo",
           ("PERMITIDO" in p_prompt) and ("innovasphere" in p_prompt), True)

    print("-- prompts por marca (voz/temas/proibidos/discricao do regras.json) --")
    R_SP = marcas.carregar("inncorpower")
    pv, pr = revisores.construir_prompt("voz", R_SP), revisores.construir_prompt("risco", R_SP)
    checar("voz da marca: tom e proibido dela entram no prompt", ("tom-de-inncorpower-marca" in pv) and ("palavra-x-inncorpower" in pv), True)
    checar("risco da marca com sigilo: manda reprovar MW/TIR/CAPEX e nao citar 'Fazenda Sol Nascente'",
           ("SIGILO OPERACIONAL" in pr) and ("Fazenda Sol Nascente" in pr), True)
    checar("CONTROLE NEGATIVO: marca sem sigilo nao recebe a regra de sigilo",
           "SIGILO OPERACIONAL" in revisores.construir_prompt("risco", marcas.carregar("innovasphere")), False)
    checar("regras comuns do grupo em toda marca (casa, agente/bot, emoji)",
           all(t in revisores.construir_prompt("voz", marcas.carregar("innovasphere")) for t in ("'casa'", "agente", "emoji")), True)
    checar("fato: prompt manda conferir tambem o TEXTO DA ARTE", "TEXTO DA ARTE" in revisores.construir_prompt("fato", R_IC), True)

    print("-- fato com fonte da marca: dominios_origem + fontes_oficiais_extra baixados AO VIVO; outro dominio nao --")
    baixados = []
    _tp = insumos.texto_da_pagina
    insumos.texto_da_pagina = lambda url, timeout=30, dominios=None, limite=None: (baixados.append(url) or "texto de " + url) \
        if insumos._host_ok(url, list(dominios or [])) else ""
    try:
        R_SF = marcas.carregar("innovasphere")
        doms = marcas.dominios_permitidos(R_SF)
        out = insumos.texto_das_fontes([{"url": "https://www.planalto.gov.br/lei"}, {"url": "https://aneel.exemplo.gov.br/x"},
                                        {"url": "https://innovasphere.exemplo.com.br/nota/a"}, {"url": "https://medium.com/blog"}], doms)
        checar("baixa gov.br, o oficial extra da marca e o site da marca", sorted(u for u, _ in out),
               ["https://aneel.exemplo.gov.br/x", "https://innovasphere.exemplo.com.br/nota/a", "https://www.planalto.gov.br/lei"])
        checar("CONTROLE NEGATIVO: medium.com nunca e baixado", any("medium" in u for u in baixados), False)
        checar("urls_de_origem usa o dominio da marca", insumos.urls_de_origem("innovasphere.exemplo.com.br/nota/a",
               ["innovasphere.exemplo.com.br"]), ["https://innovasphere.exemplo.com.br/nota/a"])
        # 30/09/2026: o gerador semeia nota_origem = home da marca; antes o regex exigia caminho e a pagina nunca era baixada
        checar("urls_de_origem aceita a home da marca", insumos.urls_de_origem("https://innovasphere.exemplo.com.br/",
               ["innovasphere.exemplo.com.br"]), ["https://innovasphere.exemplo.com.br"])
        checar("home + nota nao duplica nem corta o caminho", insumos.urls_de_origem(
               "innovasphere.exemplo.com.br/nota/a e innovasphere.exemplo.com.br", ["innovasphere.exemplo.com.br"]),
               ["https://innovasphere.exemplo.com.br/nota/a", "https://innovasphere.exemplo.com.br"])
        checar("CONTROLE NEGATIVO: dominio que so comeca igual nao casa", insumos.urls_de_origem(
               "https://innovasphere.exemplo.com.br.golpe.io/", ["innovasphere.exemplo.com.br"]), [])
    finally:
        insumos.texto_da_pagina = _tp
    # 30/09/2026: o regex de limpeza tinha o BYTE 0x01 no lugar de `\1` e nao removia script/style; o fato ganhou a
    # pagina inteira (sem corte, fora do <main>) — prova sem rede, pelo cache de HTML bruto
    u = "https://innovasphere.exemplo.com.br"
    insumos._CACHE[u] = ("<html><head><style>.a{width:777px}</style><script>var x=888;</script></head><body>"
                         "<main><p>Prazo de 15 dias</p></main><section><p>Cronograma de 9 meses</p></section>"
                         + "<p>" + "x " * 6000 + "104 mil toneladas</p></body></html>")
    try:
        curto = insumos.texto_da_pagina(u, dominios=["innovasphere.exemplo.com.br"])
        todo = insumos.texto_da_pagina(u, dominios=["innovasphere.exemplo.com.br"], inteiro=True)
        checar("padrao: so o <main>", curto, "Prazo de 15 dias")
        checar("CONTROLE NEGATIVO: CSS/JS nunca entram no texto", any(n in todo for n in ("777", "888", "var x")), False)
        checar("inteiro: fora do <main> e alem de 9 mil caracteres", ("9 meses" in todo, "104 mil" in todo, len(todo) > 9000),
               (True, True, True))
    finally:
        insumos._CACHE.pop(u, None)
    import glob as _glob
    ctrl = [f for f in _glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "**", "*.py"), recursive=True)
            if any(b in open(f, "rb").read() for b in (b"\x00", b"\x01", b"\x02", b"\x03", b"\x07", b"\x08"))]
    checar("nenhum .py do redes com caractere de controle (\\1 virou 0x01 em 2 arquivos, 30/09)", ctrl, [])
    try:
        pass
    finally:
        insumos.texto_da_pagina = _tp
    checar("fonte de dominio nao permitido reprova (guarda.checar_fontes)",
           len(guarda.checar_fontes([{"url": "https://medium.com/x"}], R_IC)), 1)
    checar("CONTROLE NEGATIVO: planalto.gov.br passa", guarda.checar_fontes([{"url": "https://www.planalto.gov.br/x"}], R_IC), [])

    print("-- fato: numero na ARTE fora da fonte --")
    checar("numero na arte fora da fonte e da legenda -> reprova", len(checagens.numeros_da_arte_fora_da_fonte(
        "Reduz 72% do custo", "legenda sem numero", [{"dado": "prazo de 180 dias", "norma": "Lei 1"}])), 1)
    checar("CONTROLE NEGATIVO: numero da arte presente na fonte passa", checagens.numeros_da_arte_fora_da_fonte(
        "Prazo de 180 dias", "legenda", [{"dado": "prazo de 180 dias", "norma": "Lei 1"}]), [])
    checar("numero presente so na pagina baixada ao vivo passa", checagens.numeros_da_arte_fora_da_fonte(
        "Aliquota 12,5%", "legenda", [], paginas=["a aliquota e 12,5% ao ano"]), [])
    checar("contador de quadro (1/6) e marcador de lista nao contam", checagens.numeros_da_arte_fora_da_fonte(
        "1/6 Pergunta da mesa 2", "legenda", []), [])

    def peca2(**extra):
        base = {"peca_id": "qa-v2", "marca": "innconta", "canal": "instagram", "formato": "texto",
                "texto": "A NCM decide o IPI de toda nota emitida. A regularidade fiscal comeca por ela.\n\n"
                         "Salve este post para consultar depois.\n#InnConta #regularidadefiscal #fiscal",
                "texto_arte": "Pergunta da mesa", "imagens": [], "nota_urls": [], "fontes": []}
        base.update(extra)
        return base

    def avalia(pc, m=None, **k):
        return conselho.avaliar(pc, conversar=m or Mock({}), regras=marcas.carregar(pc["marca"]), paginas=[], **k)

    print("-- SIGILO (inncorpower): numero operacional reprova; mesma frase em marca sem sigilo passa --")
    frase = "A usina de 150 MWac tem TIR de 14% e CAPEX de R$ 800 milhoes. A regularidade e o ponto.\nSalve este post.\n#a #b #c"
    m = Mock({})
    r = avalia(peca2(marca="inncorpower", texto=frase), m)
    checar("inncorpower: MW/TIR/CAPEX -> a guarda barra sem gastar modelo na 1a volta", (r["votos_por_rodada"][0].get("guarda", {}).get("passa"),
           "sigilo" in " ".join(r["votos_por_rodada"][0]["guarda"]["motivos"])), (False, True))
    r2 = avalia(peca2(marca="innconta", texto=frase), Mock({}))
    checar("CONTROLE NEGATIVO: a mesma frase em marca SEM sigilo nao e barrada por sigilo",
           any("sigilo" in x for x in r2["votos_por_rodada"][0].get("guarda", {}).get("motivos", [])), False)
    r3 = avalia(peca2(marca="inncorpower", texto_arte="Usina de 300 MW", texto="A regularidade da energia importa.\nSalve.\n#a #b #c"), Mock({}))
    checar("inncorpower: numero operacional na ARTE e fatal (escala na hora)", (r3["decisao"], r3["rodadas"]), ("escalado", 1))
    checar("nao_citar da marca barra o nome", len(guarda.checar_marca("Visitamos a Fazenda Sol Nascente.", marcas.carregar("inncorpower"))) >= 1, True)

    print("-- IMAGEM: proporcao/abre/peso (deterministico) --")
    from PIL import Image
    d_img = tempfile.mkdtemp(prefix="img-")

    def _png(nome, w, h):
        c = os.path.join(d_img, nome)
        Image.new("RGB", (w, h), (30, 30, 30)).save(c)
        return c
    ok45, ok191, alto, largo = _png("a.png", 1080, 1350), _png("b.png", 1910, 1000), _png("c.png", 1080, 2400), _png("d.png", 2400, 400)
    checar("4:5 aceita", insumos.checar_imagem(ok45), [])
    checar("1,91:1 aceita", insumos.checar_imagem(ok191), [])
    checar("proporcao 9:20 no feed reprova", len(insumos.checar_imagem(alto)), 1)
    checar("proporcao 6:1 no feed reprova", len(insumos.checar_imagem(largo)), 1)
    checar("9:16 aceita para stories/reels", insumos.checar_imagem(_png("e.png", 1080, 1920), "stories"), [])
    checar("CONTROLE NEGATIVO: 4:5 nao serve para stories", len(insumos.checar_imagem(ok45, "stories")), 1)
    corrompida = os.path.join(d_img, "x.png")
    open(corrompida, "wb").write(b"nao e imagem")
    checar("arquivo que nao abre reprova", len(insumos.checar_imagem(corrompida)), 1)
    r = avalia(peca2(formato="imagem_feed", imagens=[alto]), Mock({}))
    checar("imagem fora da proporcao: escala na hora, ZERO modelo gasto", (r["decisao"], r["rodadas"], r["neuronios"]), ("escalado", 1, 0.0))

    print("-- ANTI-REPETICAO (mesma marca: ultimas 30; outra marca no mesmo dia; collab e excecao) --")
    base = "A NCM decide o IPI de toda nota emitida sobre o produto. A regularidade fiscal comeca por ela, escolhida uma vez."
    quase = "A NCM decide o IPI de toda nota emitida sobre o produto. A regularidade fiscal comeca por ela, escolhida de uma vez."
    outra = "Contas de energia: o prazo de revisao tarifaria muda o valor cobrado na fatura de toda empresa em 2027."
    refs = [{"marca": "innconta", "peca_id": "antiga", "texto": base, "data": "2026-09-01"}]
    checar("texto quase identico a publicada da MESMA marca reprova", len(repeticao.checar(quase, "innconta", refs)), 1)
    checar("CONTROLE NEGATIVO: texto diferente passa", repeticao.checar(outra, "innconta", refs), [])
    refs_outra = [{"marca": "innovasphere", "peca_id": "irma", "texto": base, "data": "2026-10-05"}]
    checar("identico a peca de OUTRA marca no mesmo dia reprova",
           len(repeticao.checar(quase, "innconta", refs_outra, data_publicacao="2026-10-05")), 1)
    checar("CONTROLE NEGATIVO: outra marca em outro dia (> 1 dia) passa",
           repeticao.checar(quase, "innconta", refs_outra, data_publicacao="2026-10-20"), [])
    checar("EXCECAO: mesma publicacao em collab (parceiro declarado) passa",
           repeticao.checar(quase, "innconta", refs_outra, data_publicacao="2026-10-05", collab_parceiros=("innovasphere",)), [])
    refs_31 = [{"marca": "innconta", "peca_id": "p%d" % i, "texto": outra + " %d" % i, "data": None} for i in range(31)]
    refs_31[-1] = {"marca": "innconta", "peca_id": "velha", "texto": base, "data": None}
    checar("so as ULTIMAS 30 contam (a 31a nao segura peca nova)", repeticao.checar(quase, "innconta", refs_31), [])
    r = avalia(peca2(texto=quase + "\nSalve.\n#a #b #c"), Mock({}), referencias=refs)
    checar("no conselho: repeticao escala na hora, zero modelo", (r["decisao"], r["rodadas"], len(r["votos_por_rodada"])), ("escalado", 1, 1))
    import estoque as _est  # noqa: E402
    _tx = [x.get("_corpo", "") for x in _est.listar("innconta") if x.get("canal") == "instagram"]
    _mx = max([repeticao.semelhanca(_tx[i], _tx[j]) for i in range(len(_tx)) for j in range(i + 1, len(_tx))] or [0.0])
    checar("estoque REAL de Instagram (%d pecas): nenhum par chega ao limiar 0,60 (calibragem, max %.2f)" % (len(_tx), _mx),
           _mx < repeticao.LIMIAR, True)
    checar("outra marca SEM data: so texto quase identico (>= 0,85) reprova",
           (len(repeticao.checar(quase, "innconta", refs_outra)), len(repeticao.checar(outra, "innconta", [dict(refs_outra[0], texto=base[:60] + " " + outra)]))),
           (1, 0))
    checar("voz.proibidos tolera plural ('parceiros contratados' bate em 'parceiro contratado')",
           len(guarda.checar_marca("Os parceiros contratados executam.", dict(R_IC, voz={"proibidos": ["parceiro contratado"]}))), 1)

    print("-- ALCANCE: cada falha OBJETIVA reprova sozinha; a peca limpa passa; conserto mecanico --")
    limpa = peca2()["texto"]
    checar("peca limpa: nenhum motivo", alcance.checar_legenda(limpa, R_IC, peca2()), [])
    longo = ("Uma frase de abertura extremamente longa que nunca cabe antes do mais do Instagram porque insiste em explicar tudo "
             "de uma vez so antes de chegar ao ponto principal. A regularidade fiscal.\nSalve.\n#a #b #c")
    sem_chave = "A NCM decide o IPI de toda nota emitida.\nSalve este post.\n#a #b #c"
    trinta = limpa.split("\n#")[0] + "\n" + " ".join("#t%d" % i for i in range(30))
    zero = limpa.split("\n#")[0]
    sem_cta = limpa.replace("Salve este post para consultar depois.\n", "")
    casos = [("1a frase > 125 caracteres", longo, "125"), ("sem palavra-chave da marca", sem_chave, "palavra-chave"),
             ("30 hashtags", trinta, "30 hashtags"), ("0 hashtags", zero, "0 hashtag"), ("sem chamada", sem_cta, "chamada")]
    for rotulo, txt, trecho in casos:
        mm = alcance.checar_legenda(txt, R_IC, peca2())
        checar("alcance reprova: %s" % rotulo, any(trecho in x for x in mm), True)
    checar("alcance reprova: sem texto alternativo (sem alt_text nem texto_arte)",
           any("texto alternativo" in x for x in alcance.checar_legenda(limpa, R_IC, peca2(texto_arte=""))), True)
    checar("CONTROLE NEGATIVO: alt_text explicito basta sem texto_arte",
           alcance.checar_legenda(limpa, R_IC, peca2(texto_arte="", alt_text="Descricao da arte")), [])
    checar("hashtags do 1o comentario contam (2 na legenda + 1 no comentario = 3)",
           alcance.checar_legenda("A regularidade fiscal muda tudo.\nSalve.\n#a #b", R_IC, peca2(), hashtags_extra=1), [])
    for rotulo, txt in (("hashtags demais", trinta), ("sem chamada", sem_cta), ("zero hashtags", zero)):
        fix = alcance.corrigir_legenda(txt, R_IC)
        checar("conserto mecanico: %s -> 3 a 5 hashtags e chamada" % rotulo,
               (3 <= len(alcance.hashtags(fix)) <= 5, any("chamada" in x for x in alcance.checar_legenda(fix, R_IC, peca2()))),
               (True, False))
    checar("conserto e idempotente na peca limpa", alcance.corrigir_legenda(limpa, R_IC), limpa)
    m = Mock({})
    r = avalia(peca2(texto=sem_cta.split("\n#")[0] + "\n" + " ".join("#t%d" % i for i in range(9))), m)
    checar("no conselho: hashtags/chamada consertadas SEM redator LLM e aprovadas na 2a volta",
           (r["decisao"], r["rodadas"], "redator" in m.chamadas), ("aprovado", 2, False))
    r = avalia(peca2(texto=sem_chave), Mock({}, redator='{"texto": "A regularidade fiscal depende da NCM.\\nSalve este post.\\n#InnConta #fiscal #gestao"}'))
    checar("no conselho: falta de palavra-chave vai ao REDATOR e aprova depois", (r["decisao"], r["rodadas"]), ("aprovado", 2))
    checar("regras comuns do grupo: 'bot' e promessa de resultado barrados",
           (len(guarda.checar("Nosso bot responde.", regras=R_IC)[1]) > 0, len(guarda.checar("Garantimos resultado garantido.", regras=R_IC)[1]) > 0),
           (True, True))

    print("-- VISUAL: 2 modelos de visao diferentes; aprovacao isolada de um so NAO vale --")
    pv_ = peca2(formato="imagem_feed", imagens=[ok45])
    checar("os dois aprovam -> passa, voto carrega os 2 modelos", (lambda v: (v["passa"], "mock-visual + mock-visual2" == v["modelo"]))(
        revisores.revisar("visual", pv_, conversar=Mock({}))), (True, True))
    v = revisores.revisar("visual", pv_, conversar=Mock({"visual2": [NAO]}))
    checar("1o aprova e o 2o reprova -> REPROVA (aprovacao isolada nao vale)", (v["passa"], v["invalida"]), (False, False))
    v = revisores.revisar("visual", pv_, conversar=Mock({"visual": [NAO]}))
    checar("1o reprova -> reprova (2o nem e chamado)", v["passa"], False)

    class _MockSoUm(Mock):
        def __call__(self, papel, msgs, max_saida=None, excluir_provedores=None):
            if papel == "visual2":
                raise modelos.ErroModelo("nenhum 2o provedor de visao disponivel")
            return super().__call__(papel, msgs, max_saida, excluir_provedores)
    v = revisores.revisar("visual", pv_, conversar=_MockSoUm({}))
    checar("CONTROLE NEGATIVO: sem 2o modelo de visao -> falha fechada (invalida), nunca aprova com um so", (v["passa"], v["invalida"]), (False, True))

    class _MockMesmo(Mock):
        def __call__(self, papel, msgs, max_saida=None, excluir_provedores=None):
            r = super().__call__(papel, msgs, max_saida, excluir_provedores)
            return r[0], r[1], "gemini:mesmo-modelo"
    v = revisores.revisar("visual", pv_, conversar=_MockMesmo({}))
    checar("os 2 votos do MESMO modelo -> falha fechada", (v["passa"], v["invalida"]), (False, True))
    checar("modelos: visual2 tem cadeia propria (Gemini/OpenRouter) e nao usa Workers AI",
           (modelos._cadeia("visual2", True)[0][0], [p for p, _ in modelos._cadeia("visual2", True)]), ("gemini", ["gemini", "openrouter"]))
    checar("modelos: papel 'longo' comeca no Gemini (1 M de contexto)", modelos._cadeia("longo", True)[0][0], "gemini")

    print("-- AUDITORIA: o voto grava a marca; a escalada por e-mail diz marca, motivo e acao --")
    gravados = []
    r = avalia(peca2(texto=quase + "\nSalve.\n#a #b #c"), Mock({}), referencias=refs, gravar=lambda pid, rod, papel, v: gravados.append(v.get("marca")))
    checar("votos gravados levam a marca da peca", set(gravados), {"innconta"})
    r = avalia(peca2(marca="innovasphere", texto=quase + "\nSalve.\n#a #b #c", peca_id="qa-outra"), Mock({}),
               referencias=[{"marca": "innovasphere", "peca_id": "antiga", "texto": base, "data": None}],
               gravar=lambda pid, rod, papel, v: gravados.append(v.get("marca")))
    checar("outra marca grava a sua", gravados[-1], "innovasphere")
    _enviados2 = []
    _m0 = avisos.supa.enviar_email
    avisos.supa.enviar_email = lambda assunto, para, html, **k: (_enviados2.append((assunto, list(para), html)) or {"ok": True})
    try:
        avisos.enviar_escaladas(None, qa=True, linhas=[{"id": "1", "marca": "inncorpower", "peca_id": "x", "canal": "instagram",
                                                       "conselho_motivos": ["fato: numero fora da fonte"], "conselho_rodadas": 1,
                                                       "texto_aprovado": "t"}])
        checar("e-mail de escalada: marca no assunto e no corpo, motivo e acao",
               ("inncorpower" in _enviados2[-1][0]) and ("MARCA: inncorpower" in _enviados2[-1][2]) and
               ("numero fora da fonte" in _enviados2[-1][2]) and ("AÇÃO (central técnica)" in _enviados2[-1][2]), True)
    finally:
        avisos.supa.enviar_email = _m0

    print("-- COTA: divisao justa entre marcas, plano por provedor, cache por hash, zero Claude --")
    import lote_aprovacao as _lote  # noqa: E402
    cands = [("a", {"_peca_id": "a1"}, None), ("a", {"_peca_id": "a2"}, None), ("a", {"_peca_id": "a3"}, None),
             ("b", {"_peca_id": "b1"}, None), ("c", {"_peca_id": "c1"}, None),
             ("c", {"_peca_id": "c2", "prioridade": "urgente"}, None)]
    ordem = [c[1]["_peca_id"] for c in _lote.ordenar_justo(cands)]
    checar("urgente primeiro; depois as marcas se REVEZAM (a1 b1 c1 a2 c2... nunca a1 a2 a3 primeiro)", ordem[:4], ["c2", "a1", "b1", "c1"])
    checar("todas as pecas continuam na fila", sorted(ordem), ["a1", "a2", "a3", "b1", "c1", "c2"])
    con = cota.Consumo()
    ativas = ["a", "b", "c"]
    checar("marca abaixo da fatia usa qualquer provedor", cota.provedores_sem_folga(con, "a", ativas), set())
    con.unidades[("a", "gemini")] = 2 * (cota.ORCAMENTO_DIA["gemini"] / 3.0)
    fora = cota.provedores_sem_folga(con, "a", ativas)
    checar("marca que passou de 2x a fatia do Gemini fica sem Gemini", "gemini" in fora, True)
    checar("CONTROLE NEGATIVO: a OUTRA marca ainda tem Gemini", "gemini" in cota.provedores_sem_folga(con, "b", ativas), False)
    con.unidades[("b", "openrouter")] = cota.ORCAMENTO_DIA["openrouter"]
    checar("total do provedor estourado: ninguem usa", {"openrouter"} <= cota.provedores_sem_folga(con, "c", ativas), True)
    excluidos = []
    _base = lambda papel, msgs, max_saida=None, cf_disponivel=True, excluir_provedores=None: (  # noqa: E731
        excluidos.append(set(excluir_provedores)) or ("{}", 0.0, "groq:x"))
    f = cota.conversar_com_plano(conselho.Orcamento(0, teto=100), con, "a", ativas, base=_base)
    f("fato", [{"role": "user", "content": "x"}])
    checar("conversar_com_plano repassa a exclusao (a marca a nao usa gemini)", "gemini" in excluidos[-1], True)
    checar("... e registra o consumo do provedor que respondeu", con.novo.get(("a", "groq", "fato"))[0], 1)
    ch = cota.chave_cache("fato", "innconta", peca2(), {})
    checar("hash do cache muda com o texto", ch != cota.chave_cache("fato", "innconta", peca2(texto="outro texto"), {}), True)
    checar("hash do cache muda com a marca", ch != cota.chave_cache("fato", "innovasphere", peca2(), {}), True)
    cache = cota.Cache()
    m = Mock({})
    r1 = conselho.avaliar(peca2(), conversar=m, regras=marcas.carregar("innconta"), paginas=[], cache=cache)
    n1 = len(m.chamadas)
    m2 = Mock({})
    r2 = conselho.avaliar(peca2(), conversar=m2, regras=marcas.carregar("innconta"), paginas=[], cache=cache)
    checar("cache: 2a avaliacao da peca INALTERADA nao chama modelo nenhum", (r1["decisao"], n1 > 0, len(m2.chamadas), r2["decisao"]),
           ("aprovado", True, 0, "aprovado"))
    m3 = Mock({})
    conselho.avaliar(peca2(texto=peca2()["texto"].replace("NCM", "TIPI")), conversar=m3, regras=marcas.carregar("innconta"), paginas=[], cache=cache)
    checar("CONTROLE NEGATIVO: peca alterada e revisada de novo", len(m3.chamadas) > 0, True)
    cache.guardar("k-invalido", "fato", "innconta", {"passa": False, "invalida": True, "motivos": []})
    checar("voto invalido (falha de modelo) nunca entra no cache", cache.obter("k-invalido"), None)
    capa = cota.capacidade(marcas=6)
    checar("capacidade estimada comporta 1 peca/dia por marca de 6 marcas", capa["pecas_dia_total"] >= 6, True)

    print("-- ZERO Claude na operacao (CVO 29/09): nada em redes/ nem no workflow chama a API da Anthropic --")
    agulhas = ["anthr" + "opic", "claude" + "-", "api.anthr" + "opic"]
    achados = []
    raiz_redes = os.path.dirname(os.path.abspath(__file__))
    for pasta, _, arquivos in os.walk(raiz_redes):
        for a in arquivos:
            if a.endswith((".py", ".json", ".yml", ".txt")) and not a.startswith("testar_"):
                try:
                    txt = open(os.path.join(pasta, a), encoding="utf-8", errors="replace").read().lower()
                except OSError:
                    continue
                if any(ag in txt for ag in agulhas):
                    achados.append(os.path.relpath(os.path.join(pasta, a), raiz_redes))
    wf = os.path.join(os.path.dirname(raiz_redes), ".github", "workflows", "redes-consultor.yml")
    if os.path.isfile(wf) and any(ag in open(wf, encoding="utf-8").read().lower().replace("zero claude", "") for ag in agulhas):
        achados.append("redes-consultor.yml")
    checar("nenhuma referencia a Anthropic/Claude API em redes/ e no workflow", achados, [])
    checar("modelos: so provedores gratuitos (cf, groq, gemini, openrouter :free)",
           set(modelos._CHAMADORES) == {"cf", "groq", "gemini", "openrouter"}, True)
finally:
    marcas.KIT = _kit_original
    shutil.rmtree(_kit_tmp, ignore_errors=True)

print("\n== 14. conserto mecanico da 1a frase longa (link/norma para fora, sem modelo; caso c02 do banco, 30/09) ==")
import alcance as _alc  # noqa: E402
_t = ("A certidão negativa federal vale 180 dias, segundo a Portaria Conjunta RFB/PGFN nº 1.751/2014, art. 1º "
      "(https://www.gov.br/receitafederal/pt-br). Em parceria com a InnovaSphere.\nSalve.\n#a #b #c")
_n = _alc.encurtar_primeira_frase(_t)
checar("14a link entre parenteses sai da 1a frase e ela cabe antes do 'mais'",
       ("https://" in _alc.primeira_frase(_n), len(_alc.primeira_frase(_n)) <= _alc.LIMITE_ANTES_DO_MAIS), (False, True))
_t2 = ("A certidão negativa de débitos federais comprova a regularidade da empresa perante a Receita e a PGFN em "
       "licitações, conforme a Portaria Conjunta RFB/PGFN nº 1.751/2014.\nSalve.")
_n2 = _alc.encurtar_primeira_frase(_t2)
checar("14b cauda ', conforme <norma>' vira a 2a frase (nada some do texto)",
       (len(_alc.primeira_frase(_n2)) <= _alc.LIMITE_ANTES_DO_MAIS, "Conforme a Portaria Conjunta RFB/PGFN" in _n2), (True, True))
checar("14c CONTROLE NEGATIVO: 1a frase curta fica intacta", _alc.encurtar_primeira_frase("Frase curta. Resto."), "Frase curta. Resto.")
_t3 = ("Quando uma empresa de médio porte deixa de acompanhar o calendário de obrigações acessórias e certidões de forma "
       "sistemática, descobre tarde.\nSalve.")
checar("14d frase longa SEM link nem cauda de norma nao e mexida (fica para o redator/escalada)", _alc.encurtar_primeira_frase(_t3), _t3)

print("\n===")
if FALHAS:
    print("FALHARAM:", FALHAS)
    sys.exit(1)
print("TODAS AS PROVAS DO CONSELHO PASSARAM.")
