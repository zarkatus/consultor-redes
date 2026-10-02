# -*- coding: utf-8 -*-
"""Assinatura padrão da casa InnConta — 23/09/2026 (PLAYBOOK §1: entrada datada).

Uma só assinatura HTML, agnóstica de pessoa: a logo (120px, hospedada em
img/assinatura/innconta-assinatura-240.png, servida em 2x para telas retina) à esquerda; à
direita, o nome da CONTA (não da pessoa por trás dela — nunca o nome do CVO; raphael@ mostra só
"InnConta"), a frase da casa, o domínio e o e-mail da própria conta. Cores: texto geral #14110D,
dourado #C29C57 reservado À PALAVRA "InnConta"/"Conta" ou, quando o nome não a contém (Roveda,
Ética, Privacidade), ao nome inteiro — nunca fora da linha do nome. Fonte do nome em
Georgia/serif (mesma família do site); o resto em Arial, porque e-mail não carrega Google Fonts.
Sem telefone solto: o WhatsApp da casa (47 99919-0401, já público na ficha do Roveda) só aparece
na conta roveda@, como link de texto "WhatsApp", nunca como número solto.

Usado por `supa.py::enviar_email` (aplica automaticamente quando o corpo ainda não tem assinatura,
detectado pelo marcador HTML) e por `email_lote.py` (rodapé dos e-mails de lote/aprovação)."""

MARCADOR = "<!-- assinatura-innconta -->"
LOGO_URL = "https://innconta.com.br/img/assinatura/innconta-assinatura-240.png"

NOMES = {
    "central": "Central InnConta",
    "contato": "Contato InnConta",
    "roveda": "Eduardo Roveda · Diretor Comercial",
    "raphael": "InnConta",
    "etica": "Ética",
    "privacidade": "Privacidade",
}


def _nome_html(nome):
    if "InnConta" in nome:
        pre, _, pos = nome.partition("InnConta")
        return (
            ('<span style="color:#14110D">%s</span>' % pre if pre else "")
            + '<span style="color:#14110D">Inn</span><span style="color:#C29C57">Conta</span>'
            + ('<span style="color:#14110D">%s</span>' % pos if pos else "")
        )
    return '<span style="color:#C29C57">%s</span>' % nome


def _whatsapp_linha(email_conta):
    if email_conta == "roveda@innconta.com.br":
        return ('<div style="margin-top:2px">'
                 '<a href="https://wa.me/5547999190401" style="color:#14110D;text-decoration:none">'
                 'WhatsApp</a></div>')
    return ""


def nome_da_conta(email_conta):
    local = (email_conta or "").split("@")[0].strip().lower()
    return NOMES.get(local, "InnConta")


def assinatura_html(email_conta):
    nome = nome_da_conta(email_conta)
    return (
        MARCADOR + "\n"
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin-top:24px;border-top:1px solid #ddd6c5;padding-top:16px">\n'
        "<tr>\n"
        '<td style="padding-right:16px;vertical-align:middle">'
        '<img src="%s" width="120" alt="InnConta" '
        'style="display:block;width:120px;height:auto;border:0"></td>\n'
        '<td style="vertical-align:middle;font-family:Arial,Helvetica,sans-serif;font-size:13px;'
        'color:#14110D;line-height:1.5">'
        '<div style="font-family:Georgia,\'Times New Roman\',serif;font-size:15px;margin-bottom:2px">%s</div>'
        "<div>InnConta &middot; gestão de contas para empresas</div>"
        '<div><a href="https://innconta.com.br" style="color:#14110D;text-decoration:none">innconta.com.br</a>'
        ' &middot; <a href="https://www.instagram.com/innconta.oficial/" style="color:#14110D;text-decoration:none">instagram.com/innconta.oficial</a></div>'
        '<div><a href="mailto:%s" style="color:#14110D;text-decoration:none">%s</a></div>'
        "%s</td>\n</tr>\n</table>"
    ) % (LOGO_URL, _nome_html(nome), email_conta, email_conta, _whatsapp_linha(email_conta))


def assinatura_texto(email_conta):
    return "%s | InnConta | innconta.com.br | instagram.com/innconta.oficial" % nome_da_conta(email_conta)


def tem_assinatura(html):
    html = html or ""
    return MARCADOR in html or "innconta-assinatura-240.png" in html


def aplicar_assinatura(html, texto_alt, email_conta):
    """Acrescenta a assinatura ao HTML (e ao texto alternativo, se houver) só quando o corpo
    ainda não carrega uma — nunca duplica quem já monta a própria (ex.: email_lote.py)."""
    novo_html = html
    if not tem_assinatura(html):
        novo_html = (html or "") + assinatura_html(email_conta)
    novo_texto = texto_alt
    if texto_alt and "InnConta | innconta.com.br" not in texto_alt:
        novo_texto = texto_alt + "\n\n" + assinatura_texto(email_conta)
    return novo_html, novo_texto
