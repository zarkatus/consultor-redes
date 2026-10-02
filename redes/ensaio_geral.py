# -*- coding: utf-8 -*-
"""ENSAIO GERAL — Consultor de Redes, PLAYBOOK §7-V (23/09/2026, sessão exec-ig-video).

Para TODAS as peças `status='aprovado'` de um `mes_ref` (`ic_redes_publicacao`), faz TUDO que
`redes/publicar.py` faria num dia real de publicação — EXCETO publicar de verdade:

- **Instagram**: sobe a mídia (imagem OU vídeo) pro bucket público `redes-publico`, cria o
  container real na Graph API (`POST /media`) e, pra vídeo (Reels), espera o polling até
  `FINISHED` — exatamente o mesmo caminho de `publicar_instagram.criar_container` — mas NUNCA
  chama `media_publish`. A mídia (e a capa, se houver) subida pro bucket nesta rodada é apagada
  no final; a contagem do bucket é medida ANTES e DEPOIS pra provar resíduo zero por efeito
  observado, nunca por promessa (PAR-01e).
- **LinkedIn** (e qualquer canal sem conector de publicação real hoje): nunca fala com a rede —
  só valida texto/mídia local e reporta o mesmo estado `aguardando_api` que
  `publicar_via_linkedin` já usa quando `ic_segredo.linkedin_token` não existe (produto ainda
  não aprovado pela LinkedIn — PLAYBOOK §7-V-3).

Checks aplicados a TODA peça, além do dry-run por canal:
  - legenda <= 2200 caracteres, <= 30 hashtags;
  - peça com imagem: largura mínima 1080px e proporção entre 0.8 e 1.91 (faixa aceita pela Meta
    para feed/Reels);
  - peça de vídeo: duração <= 90s (limite de Reels).

Escopo desta sessão (23/09/2026): só o CÓDIGO/mecanismo — o ensaio roda contra o estoque ATUAL
como prova de que o mecanismo funciona; não corrige conteúdo (texto/arte) de peça nenhuma, só
reporta achados de FORMATO técnico (tamanho/proporção/codec) se algum aparecer. Uma revisão
criativa vai trocar texto/imagem/vídeo do estoque depois da aprovação do CVO — o ensaio roda de
novo nesse estoque novo.

Nunca lança exceção por causa de UMA peça só — cada linha do resultado tem seu próprio
ok/motivo, mesmo padrão de redes/video/renderizar_pendentes.py::renderizar.

- **Carrossel** (24/09/2026, PLAYBOOK §7-V-11): peça com `formato: carrossel` e lista `quadros` cria
  os N contêineres FILHOS + o contêiner PAI (`criar_container_carrossel`), espera `FINISHED` em
  todos, NUNCA `media_publish`; os N quadros subidos ao bucket são apagados no final.
- **`--peca-id`**: ensaia UMA peça direto do estoque (`redes/estoque/<marca>/<peca_id>.md`), sem
  exigir linha em `ic_redes_publicacao` nem `status='aprovado'` — é o que permite provar o mecanismo
  numa peça que ainda está na fila do Conselho (a peça da PGFN, 24/09/2026).

Uso:
    python redes/ensaio_geral.py --mes-ref 2026-10 [--marca innconta] [--qa]
    python redes/ensaio_geral.py --peca-id 2026-09-24-pgfn-transacao-carrossel-instagram
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
sys.path.insert(0, os.path.join(RAIZ, "video"))
import estoque  # noqa: E402
import publicar  # noqa: E402  — reaproveita _eh_video/_midia_da_peca, PAR-01d
import publicar_instagram  # noqa: E402
import supa  # noqa: E402

LIMITE_LEGENDA = 2200
LIMITE_HASHTAGS = 30
LARGURA_MIN_IMAGEM = 1080
PROPORCAO_MIN, PROPORCAO_MAX = 0.8, 1.91  # 4:5 a 1.91:1 (largura/altura) — faixa aceita pela Meta
DURACAO_MAX_REELS_S = 90


def _checar_texto(corpo):
    problemas = []
    texto = corpo or ""
    if len(texto) > LIMITE_LEGENDA:
        problemas.append("legenda com %d caracteres (limite %d)" % (len(texto), LIMITE_LEGENDA))
    hashtags = [w for w in texto.split() if w.startswith("#")]
    if len(hashtags) > LIMITE_HASHTAGS:
        problemas.append("%d hashtags (limite %d)" % (len(hashtags), LIMITE_HASHTAGS))
    return problemas


def _checar_imagem(caminho_imagem):
    problemas = []
    try:
        from PIL import Image
        with Image.open(caminho_imagem) as img:
            w, h = img.size
    except Exception as e:
        return ["não deu pra abrir a imagem para medir (%s)" % e]
    if w < LARGURA_MIN_IMAGEM:
        problemas.append("imagem com %dpx de largura (mínimo %d)" % (w, LARGURA_MIN_IMAGEM))
    proporcao = (w / h) if h else 0
    if not (PROPORCAO_MIN <= proporcao <= PROPORCAO_MAX):
        problemas.append("proporção %.2f fora da faixa aceita (%.2f–%.2f)" % (proporcao, PROPORCAO_MIN, PROPORCAO_MAX))
    return problemas


def _duracao_video_s(caminho_video):
    """ffprobe puro (já é dependência do render de vídeo, PLAYBOOK §7-V) — devolve segundos ou
    None se não deu pra medir (nunca derruba o ensaio por isso, só deixa de checar duração)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", caminho_video],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def _checar_video(caminho_video):
    problemas = []
    dur = _duracao_video_s(caminho_video)
    if dur is not None and dur > DURACAO_MAX_REELS_S:
        problemas.append("vídeo com %.1fs (limite Reels %ds)" % (dur, DURACAO_MAX_REELS_S))
    return problemas


def _dry_run_instagram(peca, texto, imagem, video, capa, quadros=None, nome_base=None, marca="innconta"):
    """Sobe a mídia real, cria o container real, espera FINISHED (imagem OU vídeo — achado
    23/09/2026, run 35883429884: imagem também processa assíncrono, `criar_container` agora
    espera as duas) — NUNCA chama media_publish. Devolve (ok, motivo, residuos: list[caminho_remoto]).
    MULTIMARCA (30/09/2026): usa o token/conta da `marca` e os mesmos extras de alcance do publicar
    (alt_text + collaborators) — antes caía no default "innconta" e ensaiava a peça de outra marca na
    conta da InnConta (prova falsa)."""
    if not imagem and not video and not quadros:
        return False, "sem mídia (imagem/vídeo) disponível para o dry-run", []
    extras, _parceiros = publicar._extras_de_alcance(marca, {"peca_id": nome_base}, peca, video=bool(video))
    extras.pop("primeiro_comentario", None)  # só existe depois de publicar; o ensaio nunca publica
    if extras.get("collaborators"):
        print("ensaio %s: collaborators=%s" % (nome_base, extras["collaborators"]))
    try:
        container = publicar_instagram.criar_container(
            texto, caminho_imagem=imagem, caminho_video=video, capa_local=capa,
            caminhos_carrossel=quadros, nome_arquivo=nome_base if quadros else None,
            marca=marca, **extras,
        )
    except publicar_instagram.TokenAusente as e:
        return False, "sem token do Instagram: %s" % e, []
    except publicar_instagram.PublicacaoFalhou as e:
        return False, "dry-run Instagram falhou: %s" % e, []
    residuos = container.get("residuos") or [r for r in (container.get("midia_remota"), container.get("capa_remota")) if r]
    if quadros:
        estado = "carrossel: %d contêineres filhos + contêiner pai, todos FINISHED" % len(container.get("itens_ids") or [])
    else:
        estado = "vídeo processado (FINISHED)" if video else "imagem processada (FINISHED)"
    return True, "%s — creation_id=%s, media_publish NÃO chamado" % (estado, container["creation_id"]), residuos


def ensaiar(marca="innconta", mes_ref=None, so_peca_id=None):
    if so_peca_id:
        # peça direto do estoque (pode ainda estar na fila do Conselho, sem linha no banco)
        try:
            fm = estoque.ler(estoque.caminho(marca, so_peca_id))
        except FileNotFoundError:
            raise ValueError("peça %s não existe em redes/estoque/%s" % (so_peca_id, marca))
        linhas = [{"peca_id": so_peca_id, "canal": fm.get("canal") or ""}]
        mes_ref = mes_ref or "peca:" + so_peca_id
        print("ensaio geral %s: peça única do estoque %s." % (marca, so_peca_id))
    else:
        if not mes_ref:
            raise ValueError("mes_ref é obrigatório (formato AAAA-MM) quando não há --peca-id")
        linhas = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&status=eq.aprovado&mes_ref=eq.%s&select=*&order=data_publicacao" % (marca, mes_ref),
        )
        print("ensaio geral %s/%s: %d peça(s) aprovada(s) encontrada(s) para o mês." % (marca, mes_ref, len(linhas)))

    baseline_bucket = publicar_instagram.listar_midia_supabase("instagram")
    print("bucket redes-publico/instagram ANTES do ensaio: %d arquivo(s)." % len(baseline_bucket))

    try:
        posts_antes = publicar_instagram.contar_posts_publicados(marca)
        print("posts publicados na conta Instagram ANTES do ensaio: %d." % posts_antes)
    except (publicar_instagram.TokenAusente, publicar_instagram.PublicacaoFalhou) as e:
        posts_antes = None
        print("não deu pra contar posts publicados ANTES (sem token/erro de rede — segue sem essa prova):", e)

    resultados = []
    residuos_desta_rodada = []

    for row in linhas:
        peca_id = row.get("peca_id", "")
        canal = row.get("canal") or ""
        try:
            peca = estoque.ler(estoque.caminho(marca, peca_id))
        except FileNotFoundError:
            resultados.append({"peca_id": peca_id, "canal": canal, "ok": False,
                                "motivo": "peça sem arquivo local em redes/estoque"})
            continue

        # mesma porta do publicar (publicar.py, publicar_peca): arte exigida pelo kit da marca + render sob
        # demanda do PNG que vive fora do git (marcas novas). Sem isto o ensaio de marca nova dava
        # "sem mídia" (run 36706847040, 30/09/2026) enquanto o publicar real renderizaria.
        motivos_arte = publicar.guarda.checar_arte(peca, marca)
        if motivos_arte:
            resultados.append({"peca_id": peca_id, "canal": canal, "ok": False,
                               "motivo": "arte v2 ausente: " + "; ".join(motivos_arte)})
            continue
        ausentes = publicar.arte_sob_demanda.garantir(marca, peca)
        if ausentes:
            resultados.append({"peca_id": peca_id, "canal": canal, "ok": False,
                               "motivo": "arte não renderizada: %d arquivo(s) ausente(s)" % len(ausentes)})
            continue

        texto = peca.get("_corpo", "")
        problemas = _checar_texto(texto)
        eh_video = publicar._eh_video(peca)
        quadros = None
        if publicar._eh_carrossel(peca):
            quadros, declarados = publicar._quadros_da_peca(peca)
            if len(quadros) != declarados:
                problemas.append("carrossel com quadro ausente no disco (%d de %d)" % (len(quadros), declarados))
            elif not (publicar_instagram.CARROSSEL_MIN_ITENS <= len(quadros) <= publicar_instagram.CARROSSEL_MAX_ITENS):
                problemas.append("carrossel com %d quadros (a API aceita %d a %d)" % (
                    len(quadros), publicar_instagram.CARROSSEL_MIN_ITENS, publicar_instagram.CARROSSEL_MAX_ITENS))
            for q in quadros:
                problemas += [os.path.basename(q) + ": " + x for x in _checar_imagem(q)]
            imagem = video = capa = None
            if problemas:
                quadros = None  # não tenta o dry-run de um carrossel que já está inválido
        else:
            imagem, video, capa = publicar._midia_da_peca(marca, peca_id, peca)

        if eh_video and not video:
            problemas.append("vídeo indisponível (barrado pela guarda ou erro de render — ver log acima)")
        elif eh_video and video:
            problemas += _checar_video(video)
        elif imagem:
            problemas += _checar_imagem(imagem)

        if canal == "instagram":
            if problemas and not (imagem or video or quadros):
                # sem mídia nenhuma pra sequer tentar o dry-run — reporta só os problemas já achados
                resultados.append({"peca_id": peca_id, "canal": canal, "ok": False, "motivo": "; ".join(problemas)})
                continue
            ok, motivo_dry, residuos = _dry_run_instagram(peca, texto[:2200], imagem, video, capa,
                                                          quadros=quadros, nome_base=peca_id, marca=marca)
            residuos_desta_rodada += residuos
            if problemas:
                motivo = motivo_dry + " · achados técnicos: " + "; ".join(problemas)
                resultados.append({"peca_id": peca_id, "canal": canal, "ok": False, "motivo": motivo})
            else:
                resultados.append({"peca_id": peca_id, "canal": canal, "ok": ok, "motivo": motivo_dry})
        else:
            # LinkedIn e qualquer outro canal sem conector de publicação real hoje: nunca fala
            # com a rede — mesmo estado 'aguardando_api' que publicar_via_linkedin já usa.
            if problemas:
                resultados.append({"peca_id": peca_id, "canal": canal, "ok": False, "motivo": "; ".join(problemas)})
            else:
                resultados.append({"peca_id": peca_id, "canal": canal, "ok": True, "motivo": "aguardando_api"})

    # --- limpeza com prova (PAR-01e): apaga tudo que ESTA rodada subiu, depois mede de novo.
    apagados, falhas_delete = 0, []
    for caminho_remoto in residuos_desta_rodada:
        if publicar_instagram.remover_midia_supabase(caminho_remoto):
            apagados += 1
        else:
            falhas_delete.append(caminho_remoto)

    bucket_final = publicar_instagram.listar_midia_supabase("instagram")
    residuo_limpo = len(bucket_final) == len(baseline_bucket)
    print("bucket redes-publico/instagram DEPOIS da limpeza: %d arquivo(s) (era %d antes) -> %s"
          % (len(bucket_final), len(baseline_bucket), "OK, sem resíduo" if residuo_limpo else "RESÍDUO NÃO LIMPO"))
    if falhas_delete:
        print("falhou ao apagar do bucket:", falhas_delete)

    posts_depois = None
    zero_publicado = None
    if posts_antes is not None:
        try:
            posts_depois = publicar_instagram.contar_posts_publicados(marca)
            zero_publicado = (posts_depois == posts_antes)
            print("posts publicados na conta Instagram DEPOIS do ensaio: %d (era %d antes) -> %s"
                  % (posts_depois, posts_antes, "OK, 0 publicados" if zero_publicado else "ALERTA: CONTAGEM MUDOU"))
        except (publicar_instagram.TokenAusente, publicar_instagram.PublicacaoFalhou) as e:
            print("não deu pra contar posts publicados DEPOIS (sem token/erro de rede):", e)

    print("\n%-46s %-16s %-5s %s" % ("peça", "canal", "ok", "motivo"))
    print("-" * 120)
    for r in resultados:
        print("%-46s %-16s %-5s %s" % (r["peca_id"], r["canal"], "OK" if r["ok"] else "FALHA", r["motivo"]))

    total = len(resultados)
    falhas = [r for r in resultados if not r["ok"]]
    resumo = {
        "mes_ref": mes_ref, "marca": marca, "total": total, "ok": total - len(falhas),
        "falhas": len(falhas), "residuo_limpo": residuo_limpo,
        "residuos_subidos": len(residuos_desta_rodada), "residuos_apagados": apagados,
        "posts_antes": posts_antes, "posts_depois": posts_depois, "zero_publicado": zero_publicado,
        "resultados": resultados,
    }
    print("\nensaio_geral:", {k: v for k, v in resumo.items() if k != "resultados"})
    return resumo


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default="innconta")
    ap.add_argument("--mes-ref", default=None)
    ap.add_argument("--peca-id", default=None, help="ensaia UMA peça direto do estoque (ignora status/mes_ref do banco)")
    ap.add_argument("--qa", action="store_true", help="sem efeito na seleção — o ensaio já nunca publica de verdade; existe só para simetria com as outras tarefas do workflow")
    a = ap.parse_args()
    resultado = ensaiar(a.marca, a.mes_ref, a.peca_id)
    publicou_de_verdade = resultado["zero_publicado"] is False  # None (sem token) nunca é falha por si só
    sys.exit(0 if (resultado["falhas"] == 0 and not publicou_de_verdade) else 1)
