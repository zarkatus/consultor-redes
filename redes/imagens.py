# -*- coding: utf-8 -*-
"""Gera a imagem de uma peça de "a cena" / carrossel / pergunta a partir da moldura do kit
(redes/kit/<marca>/post-1080x1350.png, moldura vazia — lockup só no rodapé) + fonte Cormorant
Garamond do próprio kit. Determinístico, sem IA: quebra de linha por largura, sem geração de
texto livre — o texto já vem pronto da peça do estoque.

CORREÇÃO 24/09/2026 (achado ao gerar as 36 peças de "pergunta da mesa", PLAYBOOK): a fonte
VARIÁVEL do kit (`CormorantGaramond-Variable.ttf`) com `set_variation_by_axes` solta o acento de
letras minúsculas com circunflexo/til em corpo grande — comprovado visualmente em
'2026-09-22-cena-passivo-fornecedores-instagram-feed.png' ("silêncio" saiu com o ^ desconectado
do e). Fix: usar as fontes ESTÁTICAS já corrigidas (mesmas do kit-midia-roveda, "acentos das
minúsculas assentados na letra" — ver render_util.py da sessão calendario-diario-v1), uma por
peso, em vez de setar eixo de peso na variável. `redes/kit/<marca>/fonts-estaticas/` é o novo
local; a variável continua no kit só para compatibilidade retroativa (nada mais a lê)."""
import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

RAIZ_KIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit")
COR_TEXTO = (231, 226, 213, 255)   # "Inn" branco-quente do kit
COR_VELATURA = (20, 17, 13, 150)   # fundo quase-preto do kit, semitransparente

_ARQUIVO_POR_PESO = {400: "Cormorant-normal-400.ttf", 500: "Cormorant-normal-500.ttf", 600: "Cormorant-normal-600.ttf"}


def _fonte(marca, tamanho, peso=500):
    nome = _ARQUIVO_POR_PESO.get(peso, "Cormorant-normal-500.ttf")
    import kit_comum  # do kit da marca se existir, senao a unica copia (kit da InnConta)
    caminho = kit_comum.arquivo(marca, "fonts-estaticas", nome)
    if not os.path.exists(caminho):
        # fallback: fonte variável antiga (nunca deve faltar a estática numa marca com kit completo)
        caminho = kit_comum.arquivo(marca, "fonts", "CormorantGaramond-Variable.ttf")
        if not os.path.exists(caminho):
            return ImageFont.load_default()
        f = ImageFont.truetype(caminho, tamanho)
        try:
            f.set_variation_by_axes([peso])
        except Exception:
            pass
        return f
    return ImageFont.truetype(caminho, tamanho)


def _ajustar_bloco(marca, texto, w_disponivel, h_disponivel, tam_inicial=64, tam_minimo=40):
    """Guarda de overflow (achado 24/09/2026, geração das 36 perguntas da mesa): a versão antiga
    fixava tam_fonte=64 e largura de quebra=26 sem checar se o bloco cabia no quadro — pergunta
    longa cortava ou sobrepunha o rodapé da marca. Reduz o tamanho até o bloco (altura real medida
    por textbbox, não estimada) caber em h_disponivel; textwrap.width acompanha o tamanho (fonte
    menor cabe mais caractere por linha). Nunca desce de tam_minimo — se ainda não couber nesse
    piso, quem chama decide quebrar em carrossel (isto aqui só devolve o melhor ajuste possível e
    um alerta 'nao_coube', nunca corta em silêncio)."""
    tam = tam_inicial
    while tam >= tam_minimo:
        fonte = _fonte(marca, tam, peso=500)
        largura_chars = max(12, int(w_disponivel / (tam * 0.52)))
        linhas = textwrap.wrap(texto, width=largura_chars) or [texto]
        alt_linha = int(tam * 1.35)
        bloco_alt = alt_linha * len(linhas) + 80
        if bloco_alt <= h_disponivel:
            return fonte, linhas, alt_linha, bloco_alt, tam, True
        tam -= 4
    # piso atingido — devolve mesmo assim (não corta o texto, só ultrapassa a área reservada)
    return fonte, linhas, alt_linha, bloco_alt, tam, False


def gerar_cena(marca, texto, saida, quadrado=False):
    """Post tipo 'a cena' / 'pergunta da mesa': moldura do kit + frase, sem foto de terceiro."""
    nome_base = "post-quadrado-1080.png" if quadrado else "post-1080x1350.png"
    base = Image.open(os.path.join(RAIZ_KIT, marca, nome_base)).convert("RGBA")
    W, H = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    y0 = int(H * 0.30)
    margem_rodape = int(H * 0.16)  # reserva pro lockup "Inn/Conta" no rodapé (nunca sobrepor)
    h_disponivel = H - margem_rodape - y0
    fonte, linhas, alt_linha, bloco_alt, tam_usado, coube = _ajustar_bloco(
        marca, texto, int(W * 0.86), h_disponivel)
    if not coube:
        print("AVISO: bloco de texto ultrapassa a área reservada mesmo no tamanho mínimo (%s): %r" % (saida, texto[:60]))
    draw.rectangle([0, max(0, y0 - 40), W, y0 + bloco_alt], fill=COR_VELATURA)
    y = y0
    for linha in linhas:
        bbox = draw.textbbox((0, 0), linha, font=fonte)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), linha, font=fonte, fill=COR_TEXTO)
        y += alt_linha

    out = Image.alpha_composite(base, overlay).convert("RGB")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    out.save(saida, "PNG")
    return saida


def gerar_stories(marca, texto, saida):
    """1080×1920 — não há moldura própria de stories no kit; monta por letterbox (barra da cor de
    fundo da marca acima/abaixo do quadro 1080×1350) em vez de esticar/cortar o lockup."""
    quadro = Image.open(os.path.join(RAIZ_KIT, marca, "post-1080x1350.png")).convert("RGBA")
    W, H = 1080, 1920
    fundo = Image.new("RGBA", (W, H), (20, 17, 13, 255))
    y = (H - quadro.height) // 2
    fundo.alpha_composite(quadro, (0, y))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    y0 = y + int(quadro.height * 0.30)
    margem_rodape = int(quadro.height * 0.16)
    h_disponivel = (y + quadro.height) - margem_rodape - y0
    fonte, linhas, alt_linha, bloco_alt, tam_usado, coube = _ajustar_bloco(
        marca, texto, int(W * 0.86), h_disponivel)
    if not coube:
        print("AVISO: bloco de texto (stories) ultrapassa a área reservada mesmo no tamanho mínimo (%s): %r" % (saida, texto[:60]))
    draw.rectangle([0, max(0, y0 - 40), W, y0 + bloco_alt], fill=COR_VELATURA)
    yy = y0
    for linha in linhas:
        bbox = draw.textbbox((0, 0), linha, font=fonte)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, yy), linha, font=fonte, fill=COR_TEXTO)
        yy += alt_linha
    out = Image.alpha_composite(fundo, overlay).convert("RGB")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    out.save(saida, "PNG")
    return saida


def gerar_carrossel(marca, quadros, pasta_saida):
    """quadros: lista de strings, um post PNG por quadro (1080x1350, quadrado=False)."""
    caminhos = []
    for i, texto in enumerate(quadros, start=1):
        p = os.path.join(pasta_saida, "quadro-%02d.png" % i)
        gerar_cena(marca, texto, p, quadrado=False)
        caminhos.append(p)
    return caminhos


if __name__ == "__main__":
    import sys
    marca = sys.argv[1] if len(sys.argv) > 1 else "innconta"
    p = gerar_cena(marca, "A conta de luz é o contrato que ninguém leu.", "/tmp/teste-cena.png")
    print("gerado:", p, os.path.getsize(p), "bytes")
