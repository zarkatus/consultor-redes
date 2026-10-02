# -*- coding: utf-8 -*-
"""Orquestra o render das peças de VÍDEO do estoque que já estão 'aprovado' (roteiro
curado, ver PLAYBOOK §7-V) mas ainda não têm arquivo_mp4 (nunca renderizadas). Chamado
por redes/lote_aprovacao.py (mesma rodada semanal, agora cobrindo as vagas de vídeo do
calendário) e também disponível como tarefa própria do workflow (`video`) para
render/QA manual.

GATE, sempre antes de renderizar (nunca depois): redes/guarda.checar() no roteiro
inteiro (título + quadros). Se a guarda BARRAR, a peça é pulada — NADA é renderizado,
NADA é registrado. Isso é o controle negativo de PQV-02 (ver redes/testar_guarda.py e
o item (c) da prova desta entrega)."""
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
REDES = os.path.dirname(RAIZ)
sys.path.insert(0, REDES)
sys.path.insert(0, os.path.join(REDES, "lib"))
sys.path.insert(0, RAIZ)
import estoque  # noqa: E402
import guarda  # noqa: E402
import gerar_video_cena  # noqa: E402

GERADOS_DIRNAME = "_gerados"


def _roteiro_da_peca(p):
    """Monta o roteiro.json que gerar_video_cena.py espera a partir do frontmatter da
    peça do estoque. Campos 'titulo'/'roteiro' (lista de quadros) e 'pilar' já fazem
    parte do schema de peça de vídeo — ver PLAYBOOK §7-V / redes/estoque/<marca>/*.md."""
    quadros = p.get("roteiro") or []
    if not quadros:
        raise ValueError("peça de vídeo sem 'roteiro' (lista de quadros) no frontmatter")
    return {"titulo": p.get("titulo", ""), "pilar": p.get("pilar", ""), "quadros": quadros}


def _texto_para_guarda(roteiro):
    return roteiro.get("titulo", "") + "\n" + "\n".join(
        q if isinstance(q, str) else q.get("frase", "") for q in roteiro["quadros"]
    )


def renderizar(marca="innconta", nomes_clientes=None, so_peca_id=None, workdir_base=None):
    """Devolve lista de resultados, um por peça de vídeo processada nesta rodada:
    {"peca_id", "ok": bool, "motivo": str|None, "arquivo_mp4", "arquivo_stories",
     "legenda_srt", "capa", "tamanho_feed_bytes"} — 'ok'=False é a peça barrada pela
     guarda (ou já sem roteiro), nunca uma exceção que derruba o lote inteiro."""
    resultados = []
    pecas = [p for p in estoque.listar(marca)
             if (p.get("tipo") == "video" or "video" in str(p.get("formato") or ""))
             and p.get("status") == "aprovado" and not p.get("arquivo_mp4")]
    if so_peca_id:
        pecas = [p for p in pecas if p["_peca_id"] == so_peca_id]

    for p in pecas:
        peca_id = p["_peca_id"]
        try:
            roteiro = _roteiro_da_peca(p)
        except ValueError as e:
            resultados.append({"peca_id": peca_id, "ok": False, "motivo": str(e)})
            continue

        texto = _texto_para_guarda(roteiro)
        ok, motivos = guarda.checar(texto, nomes_clientes=nomes_clientes, marca_nome=marca)
        if not ok:
            print("BARRADA pela guarda, NÃO renderizada:", peca_id, motivos)
            resultados.append({"peca_id": peca_id, "ok": False, "motivo": "guarda: " + "; ".join(motivos)})
            continue

        gerados_dir = os.path.join(REDES, "estoque", marca, GERADOS_DIRNAME)
        os.makedirs(gerados_dir, exist_ok=True)
        roteiro_json_path = os.path.join(gerados_dir, peca_id + "-roteiro.json")
        import json
        with open(roteiro_json_path, "w", encoding="utf-8") as f:
            json.dump(roteiro, f, ensure_ascii=False, indent=2)

        from pathlib import Path
        workdir = Path(workdir_base) if workdir_base else None
        try:
            feed = gerar_video_cena.gerar(
                marca=marca, roteiro_path=Path(roteiro_json_path), formato="feed",
                out_path=Path(gerados_dir) / (peca_id + "-feed.mp4"),
                workdir=(workdir / (peca_id + "-feed")) if workdir else None,
            )
            stories = gerar_video_cena.gerar(
                marca=marca, roteiro_path=Path(roteiro_json_path), formato="stories",
                out_path=Path(gerados_dir) / (peca_id + "-stories.mp4"),
                gerar_capa=False,
                workdir=(workdir / (peca_id + "-stories")) if workdir else None,
            )
        except Exception as e:
            print("ERRO ao renderizar", peca_id, ":", e)
            resultados.append({"peca_id": peca_id, "ok": False, "motivo": "erro de render: %s" % e})
            continue

        rel_feed = os.path.relpath(feed["out_path"], os.path.dirname(REDES))
        rel_stories = os.path.relpath(stories["out_path"], os.path.dirname(REDES))
        rel_srt = os.path.relpath(feed["srt_path"], os.path.dirname(REDES))
        rel_capa = os.path.relpath(feed["capa_path"], os.path.dirname(REDES)) if feed["capa_path"] else None

        # Schema documentado (PLAYBOOK §7-V) só tem 4 campos de vídeo no frontmatter
        # (roteiro/arquivo_mp4/legenda_srt/capa) — o caminho do stories.mp4 nunca é
        # persistido: é sempre "<arquivo_mp4 sem -feed>-stories.mp4" por convenção,
        # resolvido a partir de arquivo_mp4 por quem precisar dele (ex.: anexar no
        # e-mail do lote só se o feed.mp4 não couber no limite do Resend).
        estoque.atualizar_status(
            marca, peca_id,
            arquivo_mp4=rel_feed, legenda_srt=rel_srt, capa=rel_capa,
        )

        resultados.append({
            "peca_id": peca_id, "ok": True, "motivo": None,
            "arquivo_mp4": feed["out_path"], "arquivo_stories": stories["out_path"],
            "legenda_srt": feed["srt_path"], "capa": feed["capa_path"],
            "tamanho_feed_bytes": os.path.getsize(feed["out_path"]),
            "duracao_feed": feed["duracao"], "pilar": p.get("pilar", ""),
            "canal": p.get("canal", ""), "nota_origem": p.get("nota_origem", ""),
            "tipo": p.get("tipo", "video"), "formato": p.get("formato", "video"),
            "mes_ref": p.get("mes_ref"),
        })
        print("renderizado:", peca_id, "(%.1fs, %d bytes)" % (feed["duracao"], os.path.getsize(feed["out_path"])))

    return resultados


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default="innconta")
    ap.add_argument("--peca-id", default=None)
    a = ap.parse_args()
    r = renderizar(a.marca, so_peca_id=a.peca_id)
    for item in r:
        print(item)
