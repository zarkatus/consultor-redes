# -*- coding: utf-8 -*-
"""Cliente dos modelos do Conselho Editorial — CUSTO ZERO obrigatório (gratuito-sempre-mecanismos).

Por que Workers AI e não GitHub Models (23/09/2026, sessão exec-conselho): o plano original era
GitHub Models no Actions com o GITHUB_TOKEN. Verificado ao vivo: o GitHub Models foi APOSENTADO em
30/07/2026 (docs.github.com/en/github-models: "The playground, model catalog, inference API, and
BYOK are no longer available"); `models.github.ai` hoje devolve só o texto "OK" para qualquer
chamada. Substituto gratuito PRIMÁRIO: Cloudflare Workers AI da própria conta da InnConta (endpoint
compatível com OpenAI), franquia de 10.000 neurônios/dia em qualquer plano. O código tem TETO
PRÓPRIO abaixo da franquia (`TETO_NEURONIOS_DIA`, contado pelos votos gravados em
`ic_redes_revisao.neuronios`), então nunca gera cobrança mesmo que a conta esteja num plano pago.
Essa contagem de neurônios NÃO MUDA com o roteador multi-provedor abaixo (24/09/2026) — ela mede
só o gasto de Workers AI, exatamente como antes.

ROTEADOR MULTI-PROVEDOR (24/09/2026, sessão exec-conselho-capacidade): com 46+ peças na fila e
~10-13 peças/dia de capacidade só em Workers AI (10 mil neurônios/dia da CONTA, teto próprio 6.500),
a fila não esvazia no ritmo da postagem diária. Quando a franquia gratuita do dia acaba (ou falta
crédito pro dia), o Conselho passa a tentar, na ordem, outros provedores GRATUITOS já no cofre da
casa (nenhum pede cartão; nenhum risco de cobrança automática):
  1. Cloudflare Workers AI  (franquia da conta, contada por `TETO_NEURONIOS_DIA` — como já era)
  2. Groq                   (nível gratuito "Developer", limite de TAXA, sem cartão — groq-central.txt)
  3. Google AI Studio/Gemini (nível gratuito, sem cartão — gemini-api-cline.txt; dado do nível
                              gratuito pode treinar modelo do Google — nunca usar aqui dado de
                              cliente fora do que já é público na peça)
  4. OpenRouter             (chave com LIMITE DE CRÉDITO US$ 0 — openrouter-cline-free.txt; só
                              aceita modelo com sufixo ':free', checado explicitamente no código
                              abaixo — nunca um modelo pago, mesmo que o catálogo mude)
`cloudflare-workersai-cline.txt` (outro token, mesma CONTA Cloudflare) NÃO entra como fallback — é
a MESMA franquia de 10 mil neurônios/dia que o Workers AI primário já gasta (confirmado na memória
`cline-ias-gratis-e-topbar-24set.md`: "a MESMA conta/cota"); usá-lo como "reserva" seria contar a
mesma cota duas vezes, não capacidade nova.

Famílias distintas por papel, mesmo entre os provedores de fallback (Meta/OpenAI/Mistral/Qwen/
Gemma/NVIDIA/GLM), para que os 5 revisores nunca fiquem todos no mesmo modelo mesmo em fallback —
ver `FALLBACKS` abaixo. 429/limite de taxa de UM provedor só derruba aquele provedor (passa pro
próximo da cadeia); só quando TODOS os provedores configurados para o papel esgotarem é que
`conversar()` levanta `CotaEsgotada` e o Conselho ADIA a peça (nunca aprova nem escala por falta de
provedor — AOP-01c). Falha "dura" (400/401/403, resposta vazia, JSON quebrado) também passa pro
próximo provedor da cadeia (mais resiliente que falhar a peça por um provedor mal configurado), mas
fica registrada: se pelo menos uma falha na cadeia não foi de cota/credencial, o erro final é
`ErroModelo` (o revisor reprova por falha fechada), não `CotaEsgotada` (que adiaria a peça inteira
sem necessidade)."""
import json
import os
import time
import urllib.error
import urllib.request

CF_CHAVE = os.environ.get("CF_WORKERS_AI_TOKEN", "")
CF_CONTA = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
GEMINI_CHAVE = os.environ.get("GEMINI_API_KEY", "")
GROQ_CHAVE = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_CHAVE = os.environ.get("OPENROUTER_API_KEY", "")

# teto diário de neurônios (franquia gratuita = 10.000/dia na conta, plano Workers FREE — passou
# disso a API devolve 429 e NÃO cobra: confirmado ao vivo 24/09/2026).
# MEDIDO 24/09/2026: a Cloudflare cortou (HTTP 429/4006) com 7.571 neurônios somados pelo campo
# `usage.neurons` das respostas E pela análise GraphQL — a cobrança da franquia conta mais do que
# esses dois mostram (~1,3x). Por isso o teto CONTADO fica em 6.500 (~8.500 reais).
# ESTE TETO E ESTA CONTAGEM SÃO SÓ DE WORKERS AI — o roteador multi-provedor não mexe aqui.
TETO_NEURONIOS_DIA = float(os.environ.get("CONSELHO_TETO_NEURONIOS", "6500"))

# modelo PRIMÁRIO por papel (Cloudflare Workers AI) — famílias distintas por independência de viés:
# OpenAI (gpt-oss), Meta (Llama 4 Scout), Mistral (Small 3.1). Llama 4 Scout lê PNG em data URL
# (testado ao vivo 23/09/2026).
MODELOS = {
    "fato": "@cf/openai/gpt-oss-120b",
    "voz": "@cf/meta/llama-4-scout-17b-16e-instruct",
    "visual": "@cf/meta/llama-4-scout-17b-16e-instruct",
    "risco": "@cf/openai/gpt-oss-20b",
    "editorial": "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "redator": "@cf/openai/gpt-oss-120b",
}
MODELO_GEMINI = os.environ.get("GEMINI_MODELO", "gemini-3.6-flash")  # gemini-2.5-flash: HTTP 404
# "no longer available to new users" (verificado ao vivo 24/09/2026) — 3.6-flash é o substituto
# indicado pela própria API do Google na mensagem de erro.
REVISORES_GEMINI = ("visual", "editorial")  # só usado por modelo_de() (rótulo em erro) — ver docstring

MAX_SAIDA = {"@cf/openai/gpt-oss-120b": 2500, "@cf/openai/gpt-oss-20b": 1800}

# cadeia de FALLBACK por papel (depois de Workers AI): (provedor, modelo). Modelos e famílias
# conferidos ao vivo em 24/09/2026 (catálogo público de cada provedor) — não citados de memória.
# "visual" precisa de modelo com entrada de imagem nos 3 provedores de fallback (confirmado:
# Groq llama-4-scout lê até 5 imagens; Gemini é multimodal nativo; Gemma-4/OpenRouter lê imagem).
# MODELOS GROQ CONFERIDOS AO VIVO 24/09/2026 (GET /openai/v1/models desta conta) — o catálogo
# público da Groq lista mais modelos (llama-3.3-70b-versatile etc.) do que esta chave realmente
# alcança; usar só o que a conta de fato tem: openai/gpt-oss-120b, openai/gpt-oss-20b,
# qwen/qwen3.8-27b (nenhum confirmado com leitura de imagem nesta conta — "visual" não usa Groq).
FALLBACKS = {
    "fato": (
        ("groq", "openai/gpt-oss-120b"),                                  # OpenAI, conta/cota própria da Groq
        ("gemini", MODELO_GEMINI),                                        # Google
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),         # NVIDIA
    ),
    "voz": (
        ("groq", "qwen/qwen3.8-27b"),                                     # Alibaba Qwen
        ("gemini", MODELO_GEMINI),                                        # Google
        # z-ai/glm-5.2:free deixou de ser gratuito (HTTP 404 "unavailable for free", 29/09/2026); Gemma 4 26B e o
        # :free vivo que nenhum outro papel de texto usa como 3o degrau (familia Gemma, pesos distintos do Gemini).
        ("openrouter", "google/gemma-4-26b-a4b-it:free"),                 # Google Gemma
    ),
    "visual": (
        # sem modelo de visão confirmado nesta conta Groq — pula direto pros 2 provedores com
        # entrada de imagem já verificada (Gemini nativo; Gemma-4 no OpenRouter).
        ("gemini", MODELO_GEMINI),                                        # Google (multimodal nativo)
        ("openrouter", "google/gemma-4-31b-it:free"),                     # Google Gemma (vision)
    ),
    "risco": (
        ("groq", "openai/gpt-oss-20b"),                                   # OpenAI
        ("gemini", MODELO_GEMINI),                                        # Google
        ("openrouter", "qwen/qwen3.8-27b:free"),                          # Alibaba Qwen
    ),
    "editorial": (
        ("groq", "qwen/qwen3.8-27b"),                                     # Alibaba Qwen (Groq não hospeda Mistral)
        ("gemini", MODELO_GEMINI),                                        # Google
        ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),         # NVIDIA
    ),
    "redator": (
        ("groq", "openai/gpt-oss-120b"),                                  # OpenAI
        ("gemini", MODELO_GEMINI),                                        # Google
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),         # NVIDIA
    ),
    # 2o VOTO VISUAL (Conselho v2, 29/09/2026): modelo de visao de OUTRA familia/provedor que o 1o voto. Sem Workers AI
    # (o 1o voto ja e Llama 4 Scout la); o revisor exclui o provedor que votou primeiro, entao se o 1o foi Gemini este
    # cai no Gemma do OpenRouter e vice-versa. Sem os dois provedores disponiveis, o visual reprova (falha fechada).
    # TEXTO LONGO (artigo semanal de 1.500+ palavras): Gemini primeiro — 1 M de contexto e cota por MODELO (cascata);
    # Groq no fim (8.000 tokens/min do plano gratuito nao comportam texto longo). Sem Workers AI (contexto curto).
    "longo": (
        ("gemini", MODELO_GEMINI),                                        # Google
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),         # NVIDIA
        ("groq", "openai/gpt-oss-120b"),                                  # OpenAI
    ),
    "visual2": (
        ("gemini", MODELO_GEMINI),                                        # Google (multimodal nativo)
        ("openrouter", "google/gemma-4-31b-it:free"),                     # Google Gemma (vision)
    ),
}


class ErroModelo(Exception):
    pass


class CotaEsgotada(ErroModelo):
    """TODOS os provedores configurados para o papel (Workers AI + fallbacks com credencial) estão
    sem cota/indisponíveis agora. NÃO é defeito da peça (AOP-01c: cota/credencial nunca é
    "reprovou") — o conselho ADIA a peça, não escala."""


class _Indisponivel(Exception):
    """Provedor sem credencial configurada, ou modelo recusado por regra de segurança (ex.: OpenRouter
    sem sufixo ':free'). Nunca conta como "tentativa gastando cota" — passa pro próximo em silêncio."""


class _Cota(Exception):
    """429 / limite de taxa do provedor da vez. Passa pro próximo da cadeia."""


class _Erro(Exception):
    """Falha dura do provedor da vez (400/401/403, resposta vazia, JSON quebrado, rede). Passa pro
    próximo da cadeia, mas marca que a falha final não foi só cota (vira ErroModelo, não CotaEsgotada)."""


def modelo_de(papel):
    """Rótulo do modelo PRIMÁRIO — usado só para etiquetar erro (insumo falhou antes de qualquer
    chamada de rede); o modelo que de fato respondeu vem em `conversar()` (3º item da tupla)."""
    if GEMINI_CHAVE and papel in REVISORES_GEMINI:
        return "gemini:" + MODELO_GEMINI
    return MODELOS.get(papel) or "gemini:" + MODELO_GEMINI


def _post(url, corpo, cab, timeout=150):
    req = urllib.request.Request(url, method="POST", data=json.dumps(corpo).encode("utf-8"), headers=cab)
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read())


def neuronios_da_conta_hoje(data_utc):
    """Consumo REAL de Workers AI da conta inteira no dia (GraphQL de análise da Cloudflare —
    token com Account Analytics Read). Conta também uso fora do conselho. Erro -> None (quem chama
    trata como orçamento esgotado: falha fechada). SÓ Workers AI — os outros provedores não têm
    "neurônio", por isso não entram nesta conta nem no teto diário."""
    if not (CF_CHAVE and CF_CONTA):
        return None
    q = {"query": "query($a:String!,$d:Date!){viewer{accounts(filter:{accountTag:$a}){"
                  "aiInferenceAdaptiveGroups(limit:100,filter:{date:$d}){sum{totalNeurons}}}}}",
         "variables": {"a": CF_CONTA, "d": data_utc}}
    try:
        j = _post("https://api.cloudflare.com/client/v4/graphql", q,
                  {"Authorization": "Bearer " + CF_CHAVE, "Content-Type": "application/json",
                   "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"}, timeout=30)
        grupos = j["data"]["viewer"]["accounts"][0]["aiInferenceAdaptiveGroups"]
        return sum(float((g.get("sum") or {}).get("totalNeurons") or 0) for g in grupos)
    except Exception as e:
        print("análise de neurônios da conta indisponível: %s" % str(e)[:160])
        return None


def _chamar_cf(modelo, mensagens, max_saida):
    if not (CF_CHAVE and CF_CONTA):
        raise _Indisponivel("CF_WORKERS_AI_TOKEN/CLOUDFLARE_ACCOUNT_ID ausentes")
    url = "https://api.cloudflare.com/client/v4/accounts/%s/ai/v1/chat/completions" % CF_CONTA
    cab = {"Authorization": "Bearer " + CF_CHAVE, "Content-Type": "application/json",
           "User-Agent": "Mozilla/5.0 (innconta-consultor-redes)"}
    corpo = {"model": modelo, "messages": mensagens, "temperature": 0,
             "max_tokens": max_saida or MAX_SAIDA.get(modelo, 700)}
    if "gpt-oss" in modelo:
        corpo["reasoning_effort"] = "low"
    ultimo = None
    for tentativa in (1, 2):
        try:
            j = _post(url, corpo, cab)
            texto = ((j.get("choices") or [{}])[0].get("message") or {}).get("content")
            neur = float((j.get("usage") or {}).get("neurons") or 0)
            if texto is None or not str(texto).strip():  # "" também é falha (dívida do PR #55)
                raise _Erro("CF não devolveu conteúdo (usage=%s)" % j.get("usage"))
            return texto, neur
        except urllib.error.HTTPError as e:
            corpo_erro = e.read()[:300].decode("utf-8", "replace")
            ultimo = "HTTP %d: %s" % (e.code, corpo_erro[:200])
            if e.code == 429 and ("4006" in corpo_erro or "daily free allocation" in corpo_erro):
                raise _Cota("franquia gratuita diária do Workers AI esgotada (HTTP 429/4006)")
            if e.code in (400, 401, 403):
                break  # credencial/entrada ruim não melhora com retentativa (AOP-01c)
        except _Erro:
            raise
        except Exception as e:  # rede, timeout, JSON quebrado
            ultimo = "%s: %s" % (type(e).__name__, e)
        if tentativa == 1:
            time.sleep(4)
    raise _Erro("CF %s falhou: %s" % (modelo, ultimo))


_UA = "Mozilla/5.0 (innconta-consultor-redes)"

# ORÇAMENTO DE SAÍDA DOS PROVEDORES DE RESERVA (24/09/2026, dívida do PR #55 — MEDIDO, não presumido):
# o revisor FATO da adversária A1 (prompt ~3.100 tokens) com `max_tokens=700` e sem limite de
# raciocínio: Groq gpt-oss-120b gastou 698 de 700 tokens RACIOCINANDO -> finish_reason='length',
# conteúdo VAZIO; OpenRouter nemotron-3-super gastou 700/700 raciocinando e devolveu o rascunho do
# raciocínio em prosa como conteúdo. A raiz era o teto de 700 (herdado de modelo sem raciocínio)
# somado à falta de `reasoning_effort` e de formato forçado. Agora, por provedor:
#   - teto de saída = raciocínio + JSON (`MAX_SAIDA_RESERVA`, e nunca menos que o pedido + folga);
#   - raciocínio curto: Groq gpt-oss `reasoning_effort="low"` (+ `include_reasoning=false`, o
#     raciocínio não volta no corpo); Groq Qwen `reasoning_effort="none"`; Gemini
#     `reasoning_effort="low"`; OpenRouter `reasoning={"effort":"low","exclude":true}`;
#   - JSON forçado: `response_format={"type":"json_object"}` nos 3 (todos os papéis do conselho
#     respondem JSON: revisores {"passa",...} e redator {"texto"}). No OpenRouter, modelo que não
#     declara `response_format` em `supported_parameters` só ignora o campo (sem
#     `require_parameters`), e o extrator tolerante de revisores.py/redator.py segura o resto.
#   - conteúdo vazio (com ou sem finish_reason='length') = `_Erro` -> PRÓXIMO provedor da cadeia,
#     nunca uma "resposta" vazia entregue ao revisor (antes, "" passava como resposta válida porque
#     o teste era só `texto is None`).
MAX_SAIDA_RESERVA = int(os.environ.get("CONSELHO_MAX_SAIDA_RESERVA", "4000"))
_FOLGA_RACIOCINIO = 1500


def _teto_reserva(max_saida):
    return max(MAX_SAIDA_RESERVA, (max_saida or 0) + _FOLGA_RACIOCINIO)


def _corpo(provedor, modelo, mensagens, max_saida):
    """Corpo da chamada OpenAI-compatível de um provedor de RESERVA (Groq/Gemini/OpenRouter)."""
    corpo = {"model": modelo, "messages": mensagens, "temperature": 0,
             "response_format": {"type": "json_object"}}
    teto = _teto_reserva(max_saida)
    if provedor == "groq":
        corpo["max_completion_tokens"] = teto
        if "gpt-oss" in modelo:
            corpo["reasoning_effort"] = "low"
            corpo["include_reasoning"] = False
        elif "qwen" in modelo:
            corpo["reasoning_effort"] = "none"
    elif provedor == "gemini":
        corpo["max_tokens"] = teto
        corpo["reasoning_effort"] = "low"
    elif provedor == "openrouter":
        corpo["max_tokens"] = teto
        corpo["reasoning"] = {"effort": "low", "exclude": True}
    return corpo


def _texto_ou_erro(j, rotulo):
    """Conteúdo da resposta; vazio/ausente vira `_Erro` com o diagnóstico (finish_reason e tokens de
    raciocínio vs. conclusão) — nunca o conteúdo nem segredo."""
    escolha = (j.get("choices") or [{}])[0]
    texto = (escolha.get("message") or {}).get("content")
    if texto is None or not str(texto).strip():
        u = j.get("usage") or {}
        det = u.get("completion_tokens_details") or {}
        erro_corpo = j.get("error")  # OpenRouter às vezes devolve 200 com {"error": ...} e sem choices
        raise _Erro("%s devolveu conteúdo VAZIO (finish_reason=%s, completion=%s, reasoning=%s%s)" % (
            rotulo, escolha.get("finish_reason"), u.get("completion_tokens"), det.get("reasoning_tokens"),
            ", erro=%s" % str((erro_corpo or {}).get("message") if isinstance(erro_corpo, dict) else erro_corpo)[:120]
            if erro_corpo else ""))
    return texto


def _chamar_reserva(provedor, url, chave, modelo, mensagens, max_saida):
    rotulo = {"groq": "Groq", "gemini": "Gemini", "openrouter": "OpenRouter"}[provedor]
    # sem User-Agent de navegador, o Cloudflare na frente da Groq devolve 403 "error code: 1010"
    # (bot check) — verificado ao vivo 24/09/2026; o mesmo UA vai para todos.
    cab = {"Authorization": "Bearer " + chave, "Content-Type": "application/json", "User-Agent": _UA}
    corpo = _corpo(provedor, modelo, mensagens, max_saida)
    ultimo = None
    for tentativa in (1, 2):
        try:
            j = _post(url, corpo, cab)
        except urllib.error.HTTPError as e:
            corpo_erro = e.read()[:300].decode("utf-8", "replace")
            if e.code == 429:
                raise _Cota("%s: limite gratuito/taxa (HTTP 429)" % rotulo)
            if e.code in (500, 502, 503, 504):
                # sobrecarga passageira do provedor (medido 24/09: Gemini 503 "high demand") — 1
                # retentativa; persistindo, conta como indisponibilidade (como cota), não como
                # defeito: a peça é ADIADA se a cadeia inteira estiver assim, nunca escalada.
                ultimo = "HTTP %d" % e.code
                if tentativa == 1:
                    time.sleep(5)
                    continue
                raise _Cota("%s: sobrecarregado (HTTP %d, 2 tentativas)" % (rotulo, e.code))
            raise _Erro("%s HTTP %d: %s" % (rotulo, e.code, corpo_erro[:200]))
        except Exception as e:  # rede, timeout, corpo não-JSON
            raise _Erro("%s: %s: %s" % (rotulo, type(e).__name__, e))
        return _texto_ou_erro(j, rotulo), 0.0  # sem "neurônio" — não conta no teto de Workers AI
    raise _Cota("%s: %s" % (rotulo, ultimo))


def _chamar_groq(modelo, mensagens, max_saida):
    if not GROQ_CHAVE:
        raise _Indisponivel("GROQ_API_KEY ausente")
    return _chamar_reserva("groq", "https://api.groq.com/openai/v1/chat/completions", GROQ_CHAVE,
                           modelo, mensagens, max_saida)


# A cota gratuita do Gemini é POR MODELO (01/10/2026: o 3.6-flash dava 429 enquanto 3.5-flash, 3-flash-preview e os lite
# respondiam 200 na mesma chave): 429 num modelo passa para o próximo antes de a cadeia desistir do provedor.
GEMINI_EXTRAS = tuple(m for m in os.environ.get(
    "GEMINI_MODELOS_EXTRAS", "gemini-3.5-flash,gemini-3-flash-preview,gemini-3.5-flash-lite,gemini-3.1-flash-lite-preview"
).split(",") if m)


def _chamar_gemini(modelo, mensagens, max_saida):
    if not GEMINI_CHAVE:
        raise _Indisponivel("GEMINI_API_KEY ausente")
    ultimo = None
    for m in (modelo,) + tuple(x for x in GEMINI_EXTRAS if x != modelo):
        try:
            return _chamar_reserva("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                                   GEMINI_CHAVE, m, mensagens, max_saida)
        except _Cota as e:
            ultimo = e
    raise ultimo


def _chamar_openrouter(modelo, mensagens, max_saida):
    if not OPENROUTER_CHAVE:
        raise _Indisponivel("OPENROUTER_API_KEY ausente")
    if not modelo.endswith(":free"):
        # custo zero é inegociável (gratuito-sempre-mecanismos) — nunca um modelo pago do
        # OpenRouter, mesmo que a lista de FALLBACKS seja editada errado no futuro.
        raise _Indisponivel("modelo OpenRouter %r sem sufixo ':free' — recusado por segurança de custo zero" % modelo)
    return _chamar_reserva("openrouter", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_CHAVE,
                           modelo, mensagens, max_saida)


_CHAMADORES = {"cf": _chamar_cf, "groq": _chamar_groq, "gemini": _chamar_gemini, "openrouter": _chamar_openrouter}


def _cadeia(papel, cf_disponivel, excluir_provedores=None):
    """Cloudflare primeiro (se o orçamento do dia ainda cabe) + os fallbacks do papel, nessa ordem.
    `excluir_provedores` (24/09/2026, dívida do PR #54): tira da cadeia provedor(es) já tentados
    nesta MESMA rodada de conversa (ex.: o redator pede pra não repetir quem acabou de devolver JSON
    fora do formato) — não é cota nem credencial, é só "não tenta de novo o mesmo agora"."""
    excluir = set(excluir_provedores or ())
    cadeia = [("cf", MODELOS[papel])] if (cf_disponivel and "cf" not in excluir and papel in MODELOS) else []
    return cadeia + [(p, m) for (p, m) in FALLBACKS.get(papel, ()) if p not in excluir]


def conversar(papel, mensagens, max_saida=None, cf_disponivel=True, excluir_provedores=None):
    """Devolve (texto_da_resposta, neuronios_gastos, "provedor:modelo_usado"). Temperatura 0 sempre.

    `cf_disponivel=False` pula Workers AI direto (orçamento do dia já estourado — quem decide é
    `conselho.Orcamento`, passado pelo `conversar` que o conselho injeta aqui). `excluir_provedores`
    (iterável de nomes como "cf"/"groq"/"gemini"/"openrouter") tira provedores específicos da cadeia
    ANTES de tentar — usado pelo redator (redator.py) para a retentativa de JSON malformado, que
    prefere um provedor diferente do que acabou de responder fora do formato. Tenta cada provedor
    da cadeia na ordem; 429/limite de taxa ou credencial ausente passam pro próximo. Só levanta
    `CotaEsgotada` quando TODOS os provedores tentados (ou configuráveis) estavam sem cota/credencial
    — se algum deu erro "duro" (resposta malformada, 401 de credencial inválida, rede), levanta
    `ErroModelo` (o revisor reprova por falha fechada em vez de adiar a peça inteira sem necessidade)."""
    cadeia = _cadeia(papel, cf_disponivel, excluir_provedores)
    if not cadeia and excluir_provedores and _cadeia(papel, cf_disponivel):
        # a cadeia só ficou vazia porque quem chamou já excluiu todos os provedores nesta rodada
        # (ex.: todos responderam fora do formato) — isso NÃO é falta de cota; adiar a peça
        # esconderia um defeito de formato. Falha fechada do voto (24/09/2026, dívida do PR #55).
        raise ErroModelo("%r: todos os provedores já foram tentados nesta rodada (excluídos: %s)"
                         % (papel, ", ".join(sorted(excluir_provedores))))
    if not cadeia:
        raise CotaEsgotada(
            "nenhum provedor disponível para %r (Workers AI sem orçamento hoje e nenhum fallback "
            "configurado — defina GROQ_API_KEY/GEMINI_API_KEY/OPENROUTER_API_KEY)" % papel)
    todas_por_cota = True
    tentados = []
    ultimo = None
    for provedor, modelo in cadeia:
        try:
            texto, neur = _CHAMADORES[provedor](modelo, mensagens, max_saida)
            return texto, neur, "%s:%s" % (provedor, modelo)
        except _Indisponivel as e:
            ultimo = str(e)
            continue
        except _Cota as e:
            tentados.append(provedor)
            ultimo = str(e)
            continue
        except _Erro as e:
            tentados.append(provedor)
            ultimo = str(e)
            todas_por_cota = False
            continue
    if todas_por_cota:
        raise CotaEsgotada("%r: todos os provedores sem cota/credencial hoje (tentados: %s) — última: %s"
                            % (papel, ", ".join(tentados) or "nenhum com credencial", ultimo))
    raise ErroModelo("%r: todos os provedores da cadeia falharam (tentados: %s) — última: %s"
                      % (papel, ", ".join(tentados), ultimo))
