#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_video_cena.py — Consultor de Redes, vídeo sem voz (Caminho A: Pillow + ffmpeg,
100% programático, custo zero). Porta de C:/.../video-poc/caminho-a/gerar_video_cena.py
(POC de 22/09/2026, decisão do revisor pelo Caminho A) — PARAMETRIZADO POR MARCA:
nenhuma cor/fonte/nome de marca chumbado no código (PGA-01). Toda a identidade visual
vem de redes/kit/<marca>/marca.json + os arquivos de fonte já vendorizados no kit.

ENTRADA: um roteiro em JSON —
    {
      "titulo": "opcional, aparece como kicker/rodapé (não é obrigatório)",
      "pilar": "Fiscal",
      "quadros": ["frase 1 (<=90 chars)", "frase 2", ...]   // 3 a 6 quadros
    }
Cada quadro vira 1 frame com o texto centralizado, moldura + barra de progresso +
lockup da marca no rodapé + kicker no topo — mesmo layout provado no POC (frames
conferidos a 390px, texto legível, sem corte).

SAÍDA: .mp4 h264/aac no formato pedido (feed 1080x1350 ou stories 1080x1920) + .srt
irmão. Áudio = tom sintético via ffmpeg `anoisesrc` (zero sample de terceiro).

Uso:
    python gerar_video_cena.py --marca innconta --roteiro roteiro.json \
        --formato feed --out out/feed.mp4 [--audio tone|silence] [--seg-dur 6.5]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np

HERE = Path(__file__).resolve().parent
KIT_RAIZ = HERE.parent / "kit"

FORMATS = {
    "feed": (1080, 1350),
    "stories": (1080, 1920),
}

TRANS_DUR = 0.8  # duração do crossfade entre quadros (fadeblack — ver build_video)
MAX_CARACTERES_QUADRO = 90
MIN_QUADROS, MAX_QUADROS = 3, 6


# --------------------------------------------------------------------------
# Marca (marca.json) — carregamento e validação (PGA-01: agnóstico de marca)
# --------------------------------------------------------------------------

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def carregar_marca(marca: str) -> dict:
    marca_dir = KIT_RAIZ / marca
    marca_json = marca_dir / "marca.json"
    if not marca_json.exists():
        raise FileNotFoundError(
            f"redes/kit/{marca}/marca.json não existe — cada marca precisa do próprio "
            f"arquivo de identidade (cores/fonte/lockup), nunca hex chumbado no código."
        )
    dados = json.loads(marca_json.read_text(encoding="utf-8"))
    cores = {k: _hex_to_rgb(v) for k, v in dados["cores"].items()}
    fonte_path = marca_dir / dados["fonte"]
    if not fonte_path.exists():  # fonte padrao vive so no kit da InnConta (redes/kit_comum.py)
        fonte_path = marca_dir.parent / "innconta" / dados["fonte"]
    if not fonte_path.exists():
        raise FileNotFoundError(f"fonte da marca não encontrada: {fonte_path}")
    dados["_cores_rgb"] = cores
    dados["_fonte_path"] = fonte_path
    dados["_marca_id"] = marca
    return dados


def font_at(marca_cfg, size: int, weight: float) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(marca_cfg["_fonte_path"]), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


# --------------------------------------------------------------------------
# Roteiro
# --------------------------------------------------------------------------

def carregar_roteiro(path: Path) -> dict:
    dados = json.loads(path.read_text(encoding="utf-8"))
    quadros = dados.get("quadros") or []
    if not (MIN_QUADROS <= len(quadros) <= MAX_QUADROS):
        raise ValueError(
            f"roteiro precisa ter entre {MIN_QUADROS} e {MAX_QUADROS} quadros, "
            f"achou {len(quadros)}"
        )
    for i, q in enumerate(quadros):
        frase = q if isinstance(q, str) else q.get("frase", "")
        if len(frase) > MAX_CARACTERES_QUADRO:
            raise ValueError(
                f"quadro {i + 1} tem {len(frase)} caracteres (máx {MAX_CARACTERES_QUADRO}): {frase!r}"
            )
    dados["quadros"] = [
        {"frase": (q if isinstance(q, str) else q.get("frase", "")),
         "palavra_chave": ("" if isinstance(q, str) else q.get("palavra_chave", ""))}
        for q in quadros
    ]
    return dados


# --------------------------------------------------------------------------
# Renderização de frames (Pillow)
# --------------------------------------------------------------------------

def make_background(marca_cfg, w: int, h: int) -> Image.Image:
    cores = marca_cfg["_cores_rgb"]
    top = np.array(cores["fundo"], dtype=np.float32)
    bot = np.array(cores["fundo_baixo"], dtype=np.float32)
    t = np.linspace(0, 1, h, dtype=np.float32).reshape(h, 1)
    grad = (top[None, :] * (1 - t) + bot[None, :] * t)
    arr = np.repeat(grad[:, None, :], w, axis=1).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def draw_border(draw, marca_cfg, w, h, margin):
    color = (*marca_cfg["_cores_rgb"]["destaque"], 140)
    draw.rectangle([margin, margin, w - margin, h - margin], outline=color, width=2)


def draw_progress_bar(draw, marca_cfg, w, margin, y, frac):
    destaque = marca_cfg["_cores_rgb"]["destaque"]
    track_x0, track_x1 = margin, w - margin
    draw.line([(track_x0, y), (track_x1, y)], fill=(*destaque, 55), width=4)
    fill_x1 = track_x0 + (track_x1 - track_x0) * frac
    draw.line([(track_x0, y), (fill_x1, y)], fill=(*destaque, 255), width=4)


def draw_lockup(img, marca_cfg, w, h, margin, scale=1.0):
    """Desenha o lockup da marca (partes/cores/pesos vêm 100% de marca.json — nunca
    string de marca chumbada aqui) no rodapé esquerdo, empilhado de baixo pra cima."""
    draw = ImageDraw.Draw(img, "RGBA")
    cores = marca_cfg["_cores_rgb"]
    partes = marca_cfg["lockup"]["partes"]
    x = margin
    y_bottom = h - margin
    # desenha de baixo pra cima (última parte da lista fica embaixo)
    for parte in reversed(partes):
        size = int(64 * scale)
        f = font_at(marca_cfg, size, parte.get("peso", 500))
        cor = cores[parte["cor"]]
        bbox = draw.textbbox((0, 0), parte["texto"], font=f)
        parte_h = bbox[3] - bbox[1]
        y = y_bottom - parte_h - bbox[1]
        draw.text((x, y), parte["texto"], font=f, fill=(*cor, 255))
        y_bottom = y - int(6 * scale)
    return y_bottom


def wrap_and_fit(draw, text, max_width, max_height, start_size, weight, marca_cfg,
                  max_lines=5, min_size=40, line_spacing=1.18):
    size = start_size
    while size >= min_size:
        f = font_at(marca_cfg, size, weight)
        words = text.split(" ")
        lines, cur = [], ""
        for word in words:
            trial = (cur + " " + word).strip()
            bbox = draw.textbbox((0, 0), trial, font=f)
            if bbox[2] - bbox[0] <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        line_h = int((f.getbbox("Ág")[3] - f.getbbox("Ág")[1]) * line_spacing)
        block_h = line_h * len(lines)
        if len(lines) <= max_lines and block_h <= max_height:
            return f, lines, line_h
        size -= 4
    f = font_at(marca_cfg, min_size, weight)
    words = text.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        bbox = draw.textbbox((0, 0), trial, font=f)
        if bbox[2] - bbox[0] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    line_h = int((f.getbbox("Ág")[3] - f.getbbox("Ág")[1]) * line_spacing)
    return f, lines, line_h


def normalize(s: str) -> str:
    return re.sub(r"[^\wçãõáéíóúâêôàü-]", "", s.lower())


def draw_centered_wrapped(img, marca_cfg, lines, f, canvas_w, top_y, line_h, cor_nome, keyword=""):
    draw = ImageDraw.Draw(img, "RGBA")
    cores = marca_cfg["_cores_rgb"]
    color = cores[cor_nome]
    destaque = cores["destaque"]
    kw_words = set(normalize(w) for w in keyword.split(" ") if w)
    y = top_y
    for line in lines:
        words = line.split(" ")
        space_w = draw.textbbox((0, 0), " ", font=f)[2]
        widths = [draw.textbbox((0, 0), w, font=f)[2] - draw.textbbox((0, 0), w, font=f)[0]
                  for w in words]
        total_w = sum(widths) + space_w * (len(words) - 1)
        x = (canvas_w - total_w) / 2
        for word, wwidth in zip(words, widths):
            is_kw = normalize(word) in kw_words and kw_words
            fill = (*destaque, 255) if is_kw else (*color, 255)
            draw.text((x + 2, y + 2), word, font=f, fill=(0, 0, 0, 110))
            draw.text((x, y), word, font=f, fill=fill)
            x += wwidth + space_w
        y += line_h


def render_frame(marca_cfg, w, h, idx, total, pilar, sentence, keyword, out_path: Path):
    img = make_background(marca_cfg, w, h)
    margin = int(w * 0.072)
    draw_border(ImageDraw.Draw(img, "RGBA"), marca_cfg, w, h, int(margin * 0.55))
    draw_progress_bar(ImageDraw.Draw(img, "RGBA"), marca_cfg, w, margin,
                       int(margin * 0.55) + 34, (idx + 1) / total)

    draw = ImageDraw.Draw(img, "RGBA")
    f_kicker = font_at(marca_cfg, int(w * 0.026), 560)
    kicker_tpl = marca_cfg.get("kicker", "{marca_upper}")
    kicker_txt = kicker_tpl.format(marca_upper=marca_cfg["nome"].upper(), pilar=(pilar or "").upper())
    kicker = "  ".join(list(kicker_txt))  # letter-spacing manual, igual ao POC
    kbbox = draw.textbbox((0, 0), kicker, font=f_kicker)
    draw.text(((w - (kbbox[2] - kbbox[0])) / 2, int(h * 0.10)), kicker,
              font=f_kicker, fill=(*marca_cfg["_cores_rgb"]["texto"], 165))

    lockup_top = draw_lockup(img, marca_cfg, w, h, margin, scale=1.0)

    content_top = int(h * 0.16)
    content_bottom = lockup_top - int(h * 0.05)
    content_h = content_bottom - content_top

    draw = ImageDraw.Draw(img, "RGBA")
    f, lines, lh = wrap_and_fit(draw, sentence, w - 2 * margin, content_h,
                                 start_size=int(w * 0.078), weight=460,
                                 marca_cfg=marca_cfg, max_lines=5)
    block_h = lh * len(lines)
    top_y = content_top + (content_h - block_h) / 2
    draw_centered_wrapped(img, marca_cfg, lines, f, w, top_y, lh, "texto", keyword=keyword)

    img.convert("RGB").save(out_path, "PNG")


# --------------------------------------------------------------------------
# Áudio (ffmpeg puro — sem sample de terceiro)
# --------------------------------------------------------------------------

def build_audio_filter(kind: str, duration: float) -> str:
    if kind == "silence":
        return f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{duration}"
    fade_out_start = max(duration - 1.5, 0.1)
    return (
        f"anoisesrc=color=pink:sample_rate=44100:amplitude=0.05,"
        f"lowpass=f=420,highpass=f=90,"
        f"volume=0.12,"
        f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_start:.2f}:d=1.5,"
        f"atrim=0:{duration}"
    )


# --------------------------------------------------------------------------
# Montagem do vídeo (ffmpeg)
# --------------------------------------------------------------------------

def build_video(frame_paths, w, h, audio_kind, seg_dur: float, out_path: Path, timeout=170):
    n = len(frame_paths)
    total_dur = n * seg_dur - (n - 1) * TRANS_DUR

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in frame_paths:
        cmd += ["-loop", "1", "-t", f"{total_dur + 1:.2f}", "-i", str(p)]

    filt = []
    for i in range(n):
        filt.append(f"[{i}:v]scale={w}:{h},format=yuv420p,setsar=1[v{i}]")
    cur = "v0"
    for i in range(1, n):
        offset = i * (seg_dur - TRANS_DUR)
        nxt = f"vx{i}"
        # fadeblack (não "fade" cru): com "fade" os dois blocos de texto ficam sobrepostos
        # e ilegíveis durante o crossfade — achado do POC na verificação em 390px.
        filt.append(
            f"[{cur}][v{i}]xfade=transition=fadeblack:duration={TRANS_DUR}:offset={offset:.2f}[{nxt}]"
        )
        cur = nxt
    filt.append(f"[{cur}]trim=duration={total_dur:.2f},setpts=PTS-STARTPTS[vout]")

    audio_filt = build_audio_filter(audio_kind, total_dur)
    filter_complex = ";".join(filt) + f";{audio_filt}[aout]"

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{total_dur:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout)
    return total_dur


def build_srt(quadros, seg_dur: float, srt_path: Path):
    def ts(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, q in enumerate(quadros):
        start = i * (seg_dur - TRANS_DUR)
        end = start + seg_dur
        lines.append(str(i + 1))
        lines.append(f"{ts(start)} --> {ts(end)}")
        lines.append(q["frase"])
        lines.append("")
    srt_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def gerar(marca: str, roteiro_path: Path, formato: str, out_path: Path,
          audio: str = "tone", seg_dur: float = 6.5, workdir: Path = None,
          gerar_capa: bool = True):
    """Função reutilizável (importável por redes/video/renderizar_pendentes.py, além do
    uso via CLI). Devolve dict com out_path/srt_path/capa_path/duracao."""
    marca_cfg = carregar_marca(marca)
    roteiro = carregar_roteiro(roteiro_path)
    w, h = FORMATS[formato]

    workdir = workdir or (HERE / f"_frames_{formato}")
    workdir.mkdir(parents=True, exist_ok=True)

    quadros = roteiro["quadros"]
    total = len(quadros)
    frame_paths = []
    for i, q in enumerate(quadros):
        p = workdir / f"f{i:04d}.png"
        render_frame(marca_cfg, w, h, i, total, roteiro.get("pilar", ""),
                     q["frase"], q["palavra_chave"], p)
        frame_paths.append(p)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_dur = build_video(frame_paths, w, h, audio, seg_dur, out_path)

    srt_path = out_path.with_suffix(".srt")
    build_srt(quadros, seg_dur, srt_path)

    capa_path = None
    if gerar_capa:
        capa_path = out_path.with_name(out_path.stem + "-capa.png")
        Image.open(frame_paths[0]).save(capa_path, "PNG")

    return {
        "out_path": str(out_path), "srt_path": str(srt_path),
        "capa_path": str(capa_path) if capa_path else None,
        "duracao": total_dur, "largura": w, "altura": h,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", required=True)
    ap.add_argument("--roteiro", required=True, help="Caminho para roteiro.json")
    ap.add_argument("--formato", choices=list(FORMATS), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audio", choices=["silence", "tone"], default="tone")
    ap.add_argument("--seg-dur", type=float, default=6.5, help="segundos por quadro (5-8)")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--sem-capa", action="store_true")
    args = ap.parse_args()

    r = gerar(
        marca=args.marca, roteiro_path=Path(args.roteiro), formato=args.formato,
        out_path=Path(args.out), audio=args.audio, seg_dur=args.seg_dur,
        workdir=Path(args.workdir) if args.workdir else None,
        gerar_capa=not args.sem_capa,
    )
    print(f"OK: {r['out_path']} ({r['largura']}x{r['altura']}, {r['duracao']:.1f}s, audio={args.audio})")
    print(f"SRT: {r['srt_path']}")
    if r["capa_path"]:
        print(f"CAPA: {r['capa_path']}")


if __name__ == "__main__":
    main()
