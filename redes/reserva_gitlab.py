"""Reserva do Consultor de redes no GitLab CI (decisão do CVO 30/09/2026: "enxugar + GitLab reserva").

Roda LOCAL (nunca no Actions): lê o PAT do GitLab e os segredos pelo helper do cofre (~/.claude/tools/cofre.py,
porta única) e fala com a API do gitlab.com. Só imprime status HTTP, nomes e impressões digitais (sha8).

  python redes/reserva_gitlab.py estado       # CI ligado?, variáveis (só nomes), agendas, últimos pipelines
  python redes/reserva_gitlab.py configurar   # 1ª vez e a cada rotação: variáveis mascaradas, CI ligado, agendas INATIVAS
  python redes/reserva_gitlab.py ligar        # GitHub fora do ar: RESERVA_REDES=1 + agendas ativas
  python redes/reserva_gitlab.py desligar     # GitHub de volta: RESERVA_REDES=0 + agendas inativas
  python redes/reserva_gitlab.py provar [tarefa]  # pipeline manual (default metricas); log do job vai para arquivo

NUNCA ligar com o GitHub rodando o publicar: duas rodadas simultâneas podem postar a mesma peça duas vezes.
"""
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
import cofre  # noqa: E402  (porta única do cofre)

API = "https://gitlab.com/api/v4"
PROJETO = "zarkatus-mirror%2Fconsultor-redes"  # caminho codificado vale como id na API (02/10/2026; antes 86647895 = innconta-site)

# variável do CI -> (arquivo do cofre, campo). Mapa de interferência no INVENTARIO (adendo 30/09/2026).
SEGREDOS = {
    "SB_SERVICE_ROLE": ("supabase-innconta-service-role.txt", "servicerole"),
    "CF_WORKERS_AI_TOKEN": ("cloudflare-workers-ai-conselho-editorial.txt", None),
    "GEMINI_API_KEY": ("gemini-api-cline.txt", None),
    "GROQ_API_KEY": ("groq-central.txt", None),
    "OPENROUTER_API_KEY": ("openrouter-cline-free.txt", None),
    "RESEND_API_KEY": ("resend-innconta-site.key", None),
    "REDES_APROVACAO_SECRET": ("redes-aprovacao-secret-innconta.txt", None),
    # 02/10/2026 (repo público): o que o .gitlab-ci.yml não pode trazer escrito
    "DADOS_DEPLOY_KEY_B64": ("github-deploy-key-consultor-redes-dados-02out2026.txt", None),  # já em base64 de 1 linha
    "CVO_EMAIL": ("consultor-redes-cvo-email.txt", None),
}
# identidade da guarda (JSON com amostras, dominios_pessoais, nomes): o GitLab só mascara 1 linha sem chaves/aspas,
# então vai remontada em JSON e codificada em base64 (o job decodifica para GUARDA_IDENTIDADE).
ARQ_GUARDA = "guarda-identidade-consultor-redes.json"


def _guarda_b64():
    import ast
    import base64
    d = {}
    for campo in ("amostras", "dominios_pessoais", "nomes"):
        bruto = str.__str__(cofre.valor(ARQ_GUARDA, campo))
        d[campo] = ast.literal_eval(bruto)  # o helper devolve str(lista); volta a ser lista
    return base64.b64encode(json.dumps(d, ensure_ascii=False).encode("utf-8")).decode("ascii")

# agendas (UTC; BRT = UTC-3): publicar 08:10, 12:10, 16:10 BRT; conselho 21:20 BRT (franquia do Workers AI renovada)
AGENDAS = [
    ("reserva publicar 08:10 BRT", "10 11 * * *", "publicar"),
    ("reserva publicar 12:10 BRT", "10 15 * * *", "publicar"),
    ("reserva publicar 16:10 BRT", "10 19 * * *", "publicar"),
    ("reserva conselho 21:20 BRT", "20 0 * * *", "conselho_diario"),
]


def _cabecalho():
    return {"PRIVATE-TOKEN": cofre.valor("gitlab-mirror-pat.txt")}


def api(metodo, caminho, dados=None):
    """Devolve (status, json). Em erro devolve (status, None): o corpo de erro nunca volta ao chamador."""
    corpo = urllib.parse.urlencode(dados).encode() if dados is not None else None
    req = urllib.request.Request(API + caminho, data=corpo, method=metodo, headers=_cabecalho())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            bruto = r.read()
            return r.status, (json.loads(bruto) if bruto else None)
    except urllib.error.HTTPError as e:
        return e.code, None


CF_ACCOUNT_ID = "95be61c3c8f6535dfc835369b7d32fda"  # conta Cloudflare do grupo (não é segredo)


def _account_id_cloudflare():
    """O token do Workers AI não lista contas (escopo mínimo): prova que a conta é a dele chamando o Workers AI nela."""
    cab = {"Authorization": "Bearer " + cofre.valor(SEGREDOS["CF_WORKERS_AI_TOKEN"][0])}
    url = "https://api.cloudflare.com/client/v4/accounts/%s/ai/models/search?per_page=1" % CF_ACCOUNT_ID
    with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=20) as r:
        if r.status != 200:
            raise SystemExit("Workers AI recusou a conta %s" % CF_ACCOUNT_ID)
    return CF_ACCOUNT_ID


def _gravar_variavel(chave, valor, mascarar=True):
    dados = {"key": chave, "value": valor, "protected": "true", "masked": "true" if mascarar else "false", "raw": "true"}
    st, _ = api("PUT", "/projects/%s/variables/%s" % (PROJETO, chave), dados)
    if st == 404:
        st, _ = api("POST", "/projects/%s/variables" % PROJETO, dados)
    return st


def _agendas():
    st, r = api("GET", "/projects/%s/pipeline_schedules?per_page=50" % PROJETO)
    return r if st == 200 else []


def configurar():
    # projeto novo no gitlab.com nasce com variáveis de pipeline proibidas ("no_one_allowed"): a agenda não recebe TAREFA
    # (403) e rodaria como publicar. Só maintainer (a conta do espelho é a única membra) pode definir.
    # tópico `reserva-ci`: o espelho do notebook (espelho-gitlab.py) desligava o CI de todo projeto a cada execução
    # (30/09 16:13 UTC); ele agora poupa quem tem esse tópico.
    st, _ = api("PUT", "/projects/%s" % PROJETO, {"builds_access_level": "enabled", "shared_runners_enabled": "true",
                                                 "ci_pipeline_variables_minimum_override_role": "maintainer",
                                                 "topics": "reserva-ci"})
    print("CI ligado + variáveis de pipeline para maintainer + tópico reserva-ci: HTTP", st)
    # protegida (variável protegida só chega a ramo protegido) E com push forçado liberado (o espelho da VM força o push;
    # antes de 30/09 ele apagava a proteção para conseguir, e a reserva rodava sem segredo nenhum).
    st, _ = api("POST", "/projects/%s/protected_branches" % PROJETO, {"name": "main", "allow_force_push": "true"})
    if st == 409:
        st, _ = api("PATCH", "/projects/%s/protected_branches/main" % PROJETO, {"allow_force_push": "true"})
    print("main protegida com push forçado liberado: HTTP", st)
    for chave, (arquivo, campo) in SEGREDOS.items():
        status = _gravar_variavel(chave, str.__str__(cofre.valor(arquivo, campo)))
        print("variável %-24s HTTP status %s" % (chave, status), "sha8", cofre.impressao(arquivo, campo))
    g = _guarda_b64()
    print("variável GUARDA_IDENTIDADE_B64   HTTP status %s" % _gravar_variavel("GUARDA_IDENTIDADE_B64", g),
          "sha8", __import__("hashlib").sha256(g.encode()).hexdigest()[:8])
    status = _gravar_variavel("CLOUDFLARE_ACCOUNT_ID", _account_id_cloudflare(), mascarar=False)
    print("variável CLOUDFLARE_ACCOUNT_ID    HTTP status", status)
    print("variável RESERVA_REDES (desligada) HTTP", _gravar_variavel("RESERVA_REDES", "0", mascarar=False))
    atual = {a["description"]: a for a in _agendas()}
    for desc, cron, tarefa in AGENDAS:
        if desc in atual:
            a, st = atual[desc], "já existia"
        else:
            st, a = api("POST", "/projects/%s/pipeline_schedules" % PROJETO,
                        {"description": desc, "ref": "main", "cron": cron, "cron_timezone": "UTC", "active": "false"})
            if st != 201:
                print("agenda NÃO criada:", desc, "HTTP", st)
                continue
        base = "/projects/%s/pipeline_schedules/%s/variables" % (PROJETO, a["id"])
        st2, _ = api("PUT", base + "/TAREFA", {"value": tarefa})
        if st2 == 404:
            st2, _ = api("POST", base, {"key": "TAREFA", "value": tarefa})
        print("agenda", desc, "(%s)" % st, "| TAREFA=%s HTTP" % tarefa, st2, "|", "ATIVA" if a.get("active") else "inativa")


def _alternar(ligado):
    print("RESERVA_REDES ->", "ligada" if ligado else "desligada", "HTTP",
          _gravar_variavel("RESERVA_REDES", "1" if ligado else "0", mascarar=False))
    for a in _agendas():
        if a["description"].startswith("reserva "):
            st, _ = api("PUT", "/projects/%s/pipeline_schedules/%s" % (PROJETO, a["id"]), {"active": "true" if ligado else "false"})
            print("agenda", a["description"], "->", "ATIVA" if ligado else "inativa", "HTTP", st)


def estado():
    st, p = api("GET", "/projects/%s" % PROJETO)
    print("projeto HTTP", st, "| CI:", (p or {}).get("builds_access_level"), "| runners:", (p or {}).get("shared_runners_enabled"),
          "| tópicos:", ",".join((p or {}).get("topics") or []) or "(nenhum — o espelho do notebook desliga o CI; rodar `configurar`)")
    st, pb = api("GET", "/projects/%s/protected_branches" % PROJETO)
    main = next((b for b in (pb if st == 200 else []) if b["name"] == "main"), None)
    print("main protegida:", "sim (push forçado: %s)" % main["allow_force_push"] if main
          else "NÃO — variáveis protegidas não chegam ao job; rodar `configurar`")
    st, vs = api("GET", "/projects/%s/variables?per_page=50" % PROJETO)
    vs = vs if st == 200 else []
    print("variáveis:", ", ".join(sorted(v["key"] for v in vs)) or "(nenhuma)")
    ligada = any(v["key"] == "RESERVA_REDES" and v["value"] == "1" for v in vs)
    print("RESERVA_REDES:", "LIGADA" if ligada else "desligada")
    for a in _agendas():
        _, det = api("GET", "/projects/%s/pipeline_schedules/%s" % (PROJETO, a["id"]))
        tarefa = next((v["value"] for v in (det or {}).get("variables", []) if v["key"] == "TAREFA"), "(SEM TAREFA)")
        print("agenda: %-28s %-12s %-8s TAREFA=%s" % (a["description"], a["cron"], "ATIVA" if a["active"] else "inativa", tarefa))
    st, pls = api("GET", "/projects/%s/pipelines?per_page=5" % PROJETO)
    for pl in (pls if st == 200 else []):
        print("pipeline %s %s %s %s" % (pl["id"], pl["source"], pl["status"], pl["created_at"]))


def provar(tarefa="metricas"):
    st, pl = api("POST", "/projects/%s/pipeline" % PROJETO,
                 {"ref": "main", "variables[][key]": "TAREFA", "variables[][value]": tarefa})
    if st != 201:
        raise SystemExit("pipeline não criado: HTTP %s" % st)
    print("pipeline", pl["id"], "TAREFA", tarefa)
    for _ in range(120):
        time.sleep(10)
        st, pl = api("GET", "/projects/%s/pipelines/%s" % (PROJETO, pl["id"]))
        if pl and pl["status"] in ("success", "failed", "canceled", "skipped"):
            break
    st, jobs = api("GET", "/projects/%s/pipelines/%s/jobs" % (PROJETO, pl["id"]))
    for j in jobs or []:
        with urllib.request.urlopen(urllib.request.Request(API + "/projects/%s/jobs/%s/trace" % (PROJETO, j["id"]),
                                                           headers=_cabecalho()), timeout=30) as r:
            log = r.read()
        destino = os.path.join(tempfile.gettempdir(), "reserva-gitlab-job-%s.log" % j["id"])
        with open(destino, "wb") as f:
            f.write(log)
        print("job", j["name"], j["status"], "%.0fs" % (j.get("duration") or 0), "| log:", destino, len(log), "bytes")
    return pl["status"]


if __name__ == "__main__":
    acao = sys.argv[1] if len(sys.argv) > 1 else "estado"
    if acao == "configurar":
        configurar()
    elif acao == "ligar":
        _alternar(True)
    elif acao == "desligar":
        _alternar(False)
    elif acao == "provar":
        provar(sys.argv[2] if len(sys.argv) > 2 else "metricas")
    else:
        estado()
