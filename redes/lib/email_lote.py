# -*- coding: utf-8 -*-
"""HTML do e-mail de lote (aprovação de conteúdo OU de calendário) — 1 e-mail, N peças, prévia
renderizada + 2 (ou 3) links por peça. Tabela HTML de e-mail, sem CSS externo (compatibilidade de
cliente de e-mail), responsivo a 390px (largura máxima 380px do bloco de peça).

23/09/2026: rodapé ganhou a assinatura padrão da casa (redes/lib/assinatura.py), identidade
contato@innconta.com.br — mesmo remetente-padrão usado por todo chamador deste módulo
(kit_roveda.py, calendario.py, lote_aprovacao.py, relatorio_mensal.py, nenhum passa `remetente`
explícito pra supa.enviar_email). Como a assinatura já nasce embutida aqui, com o marcador
`<!-- assinatura-innconta -->`, `supa.enviar_email` detecta e NÃO duplica."""

import assinatura  # noqa: E402 — mesmo diretório (redes/lib), import plano

CSS = """
body{margin:0;padding:0;background:#f3f1ea;font-family:Georgia,'Cormorant Garamond',serif;color:#14110D}
.wrap{max-width:600px;margin:0 auto;padding:16px}
.cab{background:#14110D;color:#E7E2D5;padding:20px 16px;text-align:center;border-radius:8px 8px 0 0}
.cab b{color:#C29C57}
.peca{border:1px solid #ddd6c5;border-top:none;padding:16px;max-width:380px;margin:0 auto}
.peca img{width:100%;max-width:340px;display:block;margin:0 auto 12px;border-radius:4px}
.meta{font-size:12px;color:#7a7360;margin-bottom:8px}
.texto{font-size:15px;line-height:1.5;white-space:pre-wrap;margin-bottom:14px}
.botoes{text-align:center}
.btn{display:inline-block;padding:10px 20px;margin:4px;border-radius:4px;text-decoration:none;font-size:14px;font-weight:bold}
.aprovar{background:#2e8b57;color:#fff}
.recusar{background:#c0392b;color:#fff}
.rodape{text-align:center;font-size:11px;color:#999;padding:16px}
"""


def montar(titulo, intro, itens, rodape_extra=""):
    """itens: lista de dicts {titulo, meta, texto, imagem_url (opcional), link_aprovar, link_recusar}"""
    blocos = []
    for it in itens:
        img = ('<img src="%s" alt="">' % it["imagem_url"]) if it.get("imagem_url") else ""
        # botões: padrão Aprovar/Recusar; o Conselho Editorial (redes/conselho/, 23/09/2026) passa
        # `botoes=[(rotulo, url, classe)]` — "Aprovar mesmo assim"/"Descartar" nas escaladas,
        # "Retirar post" no resumo semanal, ou lista vazia (item só informativo).
        botoes = it.get("botoes")
        if botoes is None:
            botoes = [("Aprovar", it["link_aprovar"], "aprovar"), ("Recusar", it["link_recusar"], "recusar")]
        html_botoes = "".join('\n    <a class="btn %s" href="%s">%s</a>' % (c, u, r) for r, u, c in botoes)
        blocos.append("""
<div class="peca">
  <div class="meta">%s</div>
  %s
  <div class="texto">%s</div>
  <div class="botoes">%s
  </div>
</div>""" % (it["meta"], img, it["texto"].replace("<", "&lt;"), html_botoes))
    rodape = (rodape_extra or "") + assinatura.assinatura_html("contato@innconta.com.br")
    return """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><style>%s</style></head>
<body><div class="wrap">
  <div class="cab"><b>InnConta</b> · %s</div>
  <p style="padding:0 16px">%s</p>
  %s
  <div class="rodape">%s</div>
</div></body></html>""" % (CSS, titulo, intro, "".join(blocos), rodape)
