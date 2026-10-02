# -*- coding: utf-8 -*-
"""PROVA "o Conselho v2 e melhor que o atual" (CVO 29/09/2026, PQV-02): roda o BANCO ADVERSARIAL
(`redes/conselho/banco_adversarial/banco.json`: pecas com defeito plantado + pecas limpas, uma delas citando outra empresa
do grupo) em duas versoes do Conselho, com MODELOS REAIS (cota gratuita), e imprime a tabela de pegos e de falsos positivos:

  v1 = o Conselho ATUAL, extraido de `origin/main` (git archive) numa pasta temporaria (nunca o codigo desta branch);
  v2 = o codigo desta branch, com o kit proprio do banco (`banco_adversarial/kit/`, 3 entidades).

Aceite: v2 pega ESTRITAMENTE mais pecas com defeito que v1 E nao reprova mais pecas limpas que v1.
Custo: so IA gratuita (Workers AI, Groq, Gemini, OpenRouter :free). As chaves vem do ambiente ou, na maquina do dono, do
cofre via `cofre.mjs` (lidas por subprocesso e passadas por ambiente; nunca impressas). Sem chave, o modelo cai no
proximo provedor; sem nenhuma, a peca volta "adiado" e a tabela diz isso (nao inventa resultado).

Uso (a partir da raiz do repo):
  python redes/conselho/avaliar_banco.py                    # v1 x v2, tabela final
  python redes/conselho/avaliar_banco.py --so v2            # so a v2
  python redes/conselho/avaliar_banco.py --base origin/main # de onde sai a v1 (padrao)
  python redes/conselho/avaliar_banco.py --json saida.json  # grava o resultado bruto
Modo interno (subprocesso): --driver v1|v2 --raiz <pasta> --saida <arquivo>."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
BANCO = os.path.join(AQUI, "banco_adversarial", "banco.json")
KIT_BANCO = os.path.join(AQUI, "banco_adversarial", "kit")
PAUSA_ENTRE_PECAS_S = 4  # a cota gratuita do Groq e por minuto (8K TPM): respira entre pecas
ESPERA_ADIADO_S = 65

COFRE_CHAVES = [  # (variavel de ambiente, arquivo do cofre) — lidas so pelo node+cofre.mjs, nunca impressas
    ("GROQ_API_KEY", "groq-central.txt"), ("GEMINI_API_KEY", "gemini-api-cline.txt"),
    ("OPENROUTER_API_KEY", "openrouter-cline-free.txt"), ("CF_WORKERS_AI_TOKEN", "cloudflare-workersai-cline.txt"),
]
CF_CONTA = "95be61c3c8f6535dfc835369b7d32fda"  # id de conta (nao e segredo)


def chaves_do_ambiente():
    """Ambiente ja preenchido vence; o que falta vem do cofre (so nesta maquina). Devolve {var: valor}; nunca imprime."""
    env = {}
    faltam = [(v, a) for v, a in COFRE_CHAVES if not os.environ.get(v)]
    if faltam:
        helper = os.path.join(os.path.expanduser("~"), ".claude", "tools", "cofre.mjs")
        if os.path.isfile(helper):
            js = ("import {valor} from 'file:///" + helper.replace("\\", "/") + "';"
                  "const o={};for(const [v,a] of JSON.parse(process.argv[1])){try{o[v]=valor(a)}catch(e){}}"
                  "process.stdout.write(JSON.stringify(o));")
            try:
                r = subprocess.run(["node", "--input-type=module", "-e", js, json.dumps(faltam)],
                                   capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout.strip():
                    env.update({k: v for k, v in json.loads(r.stdout).items() if v})
            except Exception:
                pass
    if not os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        env["CLOUDFLARE_ACCOUNT_ID"] = CF_CONTA
    return env


# ------------------------------------------------------------------ driver (roda DENTRO do subprocesso, v1 ou v2)

def _imagem(spec, pasta, nome):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (spec["w"], spec["h"]), (18, 32, 52))
    d = ImageDraw.Draw(img)
    y = spec["h"] // 5
    # fonte GRANDE (legivel a 390 px): com a fonte padrao minuscula o revisor visual reprovava a arte limpa com razao
    tamanhos = [96, 120, 72]
    for i, linha in enumerate(spec.get("linhas") or []):
        fonte = ImageFont.load_default(size=tamanhos[i % len(tamanhos)])
        d.text((spec["w"] // 10, y + i * 170), linha, fill=(235, 235, 235), font=fonte)
    caminho = os.path.join(pasta, nome + ".png")
    img.save(caminho)
    return caminho


def driver(motor, raiz, saida):
    r = os.path.join(raiz, "redes")
    for p in (r, os.path.join(r, "lib"), os.path.join(r, "conselho")):
        sys.path.insert(0, p)
    import conselho  # noqa: E402
    banco = json.load(open(BANCO, encoding="utf-8"))
    pasta = tempfile.mkdtemp(prefix="banco-img-")
    marcas = None
    if motor == "v2":
        import marcas  # noqa: E402
        marcas.KIT = KIT_BANCO
    resultados = []
    if os.path.isfile(saida):  # RETOMADA: a cota gratuita acaba no meio do banco; o que ja tem decisao nao se refaz
        try:
            resultados = [r for r in json.load(open(saida, encoding="utf-8")) if r["decisao"] in ("aprovado", "escalado")]
        except Exception:
            resultados = []
    feitas = {r["peca_id"] for r in resultados}
    esgotada = False
    for i, p in enumerate(banco["pecas"]):
        if p["peca_id"] in feitas:
            continue
        pc = {k: v for k, v in p.items() if k not in ("defeito", "esperado", "imagem")}
        pc["imagens"] = [_imagem(p["imagem"], pasta, p["peca_id"])] if p.get("imagem") else []
        nome = json.load(open(os.path.join(KIT_BANCO, p["marca"], "regras.json"), encoding="utf-8"))["nome"]
        kw = {"nomes_clientes": banco.get("nomes_clientes"), "marca_nome": nome}
        if motor == "v1":  # o v1 nao conhece marca/kit/repeticao: recebe a peca como o lote de hoje a entregaria
            for k in ("marca", "data_publicacao", "collab", "fontes_extra"):
                pc.pop(k, None)
        else:
            kw.update(regras=marcas.carregar(p["marca"]), referencias=banco.get("referencias"), paginas=[])
        r = None
        for tentativa in range(4):
            try:
                r = conselho.avaliar(pc, **kw)
            except Exception as e:  # nunca derruba o lote: registra o erro como peca sem resultado
                r = {"decisao": "erro", "rodadas": 0, "motivos": ["%s: %s" % (type(e).__name__, str(e)[:160])],
                     "aprovado_primeira_volta": False, "neuronios": 0.0}
            if r["decisao"] != "adiado":
                break
            if tentativa == 3 or esgotada:
                break
            print("  [%s] %s adiado (cota) — espera %ds e tenta de novo" % (motor, p["peca_id"], ESPERA_ADIADO_S), flush=True)
            time.sleep(ESPERA_ADIADO_S)
        if r["decisao"] == "adiado":  # cota gratuita do dia acabou: a peca fica para a proxima execucao (retoma)
            esgotada = True  # as demais so rodam se decididas sem modelo (checagem deterministica); sem espera
            print("  [%s] COTA GRATUITA ESGOTADA em %s — fica para a proxima execucao (reexecutar retoma)." % (motor, p["peca_id"]), flush=True)
            continue
        resultados.append({"peca_id": p["peca_id"], "marca": p["marca"], "esperado": p["esperado"], "defeito": p.get("defeito"),
                           "decisao": r["decisao"], "rodadas": r["rodadas"], "primeira": bool(r.get("aprovado_primeira_volta")),
                           "motivos": [m[:140] for m in (r.get("motivos") or [])[:3]],
                           "neuronios": round(float(r.get("neuronios") or 0), 1)})
        print("  [%s] %-38s -> %s (voltas=%s)" % (motor, p["peca_id"], r["decisao"], r["rodadas"]), flush=True)
        json.dump(resultados, open(saida, "w", encoding="utf-8"), ensure_ascii=False)  # grava a cada peca
        if r.get("neuronios"):
            time.sleep(PAUSA_ENTRE_PECAS_S)
    ordem = {p["peca_id"]: i for i, p in enumerate(banco["pecas"])}
    resultados.sort(key=lambda r: ordem[r["peca_id"]])
    json.dump(resultados, open(saida, "w", encoding="utf-8"), ensure_ascii=False)


# ------------------------------------------------------------------ orquestracao e tabela

def _raiz_repo():
    return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=AQUI, text=True).strip()


def extrair_v1(base):
    """`git archive <base> redes` numa pasta temporaria: a versao ATUAL do Conselho, sem tocar a branch."""
    destino = tempfile.mkdtemp(prefix="conselho-v1-")
    arq = os.path.join(destino, "v1.tar")
    subprocess.check_call(["git", "archive", "-o", arq, base, "redes"], cwd=_raiz_repo())
    subprocess.check_call(["tar", "-xf", arq, "-C", destino])
    os.remove(arq)
    return destino


def rodar_motor(motor, raiz, env_extra, estado):
    os.makedirs(estado, exist_ok=True)
    saida = os.path.join(estado, motor + ".json")
    env = dict(os.environ, **env_extra)
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.check_call([sys.executable, os.path.abspath(__file__), "--driver", motor, "--raiz", raiz, "--saida", saida], env=env)
    return json.load(open(saida, encoding="utf-8"))


def tabela(v1, v2):
    por1 = {r["peca_id"]: r for r in v1 or []}
    por2 = {r["peca_id"]: r for r in v2 or []}
    ids = [r["peca_id"] for r in (v2 or v1)]

    def cel(r, defeito):
        if not r:
            return "-"
        if r["decisao"] in ("adiado", "erro"):
            return r["decisao"].upper()
        pego = (not r["primeira"]) if defeito else False
        marca = ("PEGO" if pego else "passou") if defeito else ("reprovou" if r["decisao"] != "aprovado" else "aprovou")
        return "%s (%s)" % (marca, r["decisao"])
    linhas = ["| peca | esperado | defeito plantado | v1 (atual) | v2 |", "|---|---|---|---|---|"]
    for i in ids:
        ref = por2.get(i) or por1.get(i)
        d = ref["esperado"] == "reprovar"
        linhas.append("| %s | %s | %s | %s | %s |" % (i, ref["esperado"], ref.get("defeito") or "-", cel(por1.get(i), d), cel(por2.get(i), d)))

    def contar(res):
        if not res:
            return None
        defeitos = [r for r in res if r["esperado"] == "reprovar"]
        limpas = [r for r in res if r["esperado"] == "passar"]
        return {"defeitos": len(defeitos), "pegos_1a_volta": sum(1 for r in defeitos if not r["primeira"] and r["decisao"] != "adiado"),
                "pegos_final": sum(1 for r in defeitos if r["decisao"] == "escalado"),
                "limpas": len(limpas), "fp_1a_volta": sum(1 for r in limpas if not r["primeira"] and r["decisao"] not in ("adiado", "erro")),
                "fp_final": sum(1 for r in limpas if r["decisao"] == "escalado"),
                "sem_resultado": sum(1 for r in res if r["decisao"] in ("adiado", "erro"))}
    c1, c2 = contar(v1), contar(v2)
    linhas += ["", "| metrica | v1 (atual) | v2 |", "|---|---|---|"]
    for chave, rot in (("pegos_1a_volta", "defeitos pegos (reprovados na 1a volta)"), ("pegos_final", "defeitos que terminaram ESCALADOS (nunca publicariam)"),
                       ("fp_1a_volta", "falsos positivos: limpas reprovadas na 1a volta"), ("fp_final", "falsos positivos: limpas escaladas no fim"),
                       ("sem_resultado", "sem resultado (adiado/erro)")):
        linhas.append("| %s | %s | %s |" % (rot, ("%d/%d" % (c1[chave], c1["defeitos"] if "pegos" in chave else c1["limpas"])) if c1 and chave != "sem_resultado" else (c1 or {}).get(chave, "-"),
                                            ("%d/%d" % (c2[chave], c2["defeitos"] if "pegos" in chave else c2["limpas"])) if c2 and chave != "sem_resultado" else (c2 or {}).get(chave, "-")))
    total = len(json.load(open(BANCO, encoding="utf-8"))["pecas"])
    if c1 and c2 and (len(v1) < total or len(v2) < total):
        linhas += ["", "INCOMPLETO: v1 %d/%d e v2 %d/%d pecas decididas (cota gratuita do dia acabou); reexecute depois do reset."
                   % (len(v1), total, len(v2), total)]
    elif c1 and c2:
        ok = c2["pegos_1a_volta"] > c1["pegos_1a_volta"] and c2["fp_final"] <= c1["fp_final"] and c2["fp_1a_volta"] <= c1["fp_1a_volta"] + 0
        linhas.append("")
        linhas.append("ACEITE (v2 pega estritamente mais E nao reprova mais limpas): %s" % ("APROVADO" if ok else "NAO ATENDIDO"))
    return "\n".join(linhas), c1, c2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--so", choices=("v1", "v2"))
    ap.add_argument("--json")
    ap.add_argument("--estado", default=os.path.join(tempfile.gettempdir(), "conselho-banco-estado"),
                    help="pasta do resultado parcial por motor; reexecutar retoma de onde a cota acabou (apague para recomecar)")
    ap.add_argument("--driver", choices=("v1", "v2"))
    ap.add_argument("--raiz")
    ap.add_argument("--saida")
    a = ap.parse_args()
    if a.driver:
        driver(a.driver, a.raiz, a.saida)
        return 0
    env = chaves_do_ambiente()
    print("chaves disponiveis (so os nomes): %s" % sorted(k for k in list(env) + [v for v, _ in COFRE_CHAVES if os.environ.get(v)] if k != "CLOUDFLARE_ACCOUNT_ID"))
    v1 = v2 = None
    if a.so != "v2":
        print("== v1: Conselho de %s ==" % a.base)
        v1 = rodar_motor("v1", extrair_v1(a.base), env, a.estado)
    if a.so != "v1":
        print("== v2: esta branch ==")
        v2 = rodar_motor("v2", _raiz_repo(), env, a.estado)
    texto, c1, c2 = tabela(v1, v2)
    print("\n" + texto)
    if a.json:
        json.dump({"v1": v1, "v2": v2, "contagem": {"v1": c1, "v2": c2}}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
