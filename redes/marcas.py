# -*- coding: utf-8 -*-
"""Registro de ENTIDADES do Consultor de Redes (PGA-01: perfil novo = so configuracao).

Uma entidade e uma empresa do grupo OU um empreendimento (bairro planejado, condominio...):
`redes/kit/<marca>/regras.json` e a unica fonte. Contrato (campo ausente = default seguro):
  marca, tipo ("empresa"|"empreendimento"), pai (opcional, empresa dona), nome, site,
  dominios_origem[], handle_instagram, ig_user_id,
  publicar{instagram, linkedin, horario_brt}, voz{tom, proibidos[], preferidos[]},
  temas[], palavras_chave[], hashtags[], fontes_oficiais_extra[],
  discricao{sigilo, nao_citar[]}, collab{parceiros[], max_por_semana}, email_escalada.

Defaults seguros: publicar.* = false (nada publica sem declarar), sigilo = false,
collab.parceiros = [] (sem collab), email_escalada = central tecnica (AOP-01).
Token do Instagram: `ic_segredo.ig_access_token_<marca>` (a InnConta le tambem a chave legada
`ig_access_token` se a nova faltar)."""
import json
import os
import re

RAIZ = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(RAIZ, "kit")
CENTRAL = "central@innconta.com.br"
_VALIDA = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
HORARIO_PADRAO = "09:00"

_PADRAO = {
    "marca": "", "tipo": "empresa", "pai": None, "nome": "", "site": "", "dominios_origem": [],
    "handle_instagram": "", "ig_user_id": "",
    "publicar": {"instagram": False, "linkedin": False, "horario_brt": HORARIO_PADRAO},
    "voz": {"tom": "", "proibidos": [], "preferidos": []},
    "temas": [], "palavras_chave": [], "hashtags": [], "fontes_oficiais_extra": [],
    "discricao": {"sigilo": False, "nao_citar": []},
    "collab": {"parceiros": [], "max_por_semana": 0},
    "email_escalada": CENTRAL,
}


def _mescla(base, extra):
    out = json.loads(json.dumps(base))
    for k, v in (extra or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _mescla(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def carregar(marca, kit=None):
    """Devolve as regras da entidade (com defaults). Marca sem regras.json = regras padrao seguras
    (nome = a propria chave, nada publica)."""
    marca = str(marca or "").strip().lower()
    if not _VALIDA.match(marca):
        raise ValueError("marca invalida: %r" % marca)
    caminho = os.path.join(kit or KIT, marca, "regras.json")
    dados = {}
    if os.path.isfile(caminho):
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    r = _mescla(_PADRAO, dados)
    r["marca"] = marca
    r["nome"] = r["nome"] or marca
    r["_tem_regras"] = bool(dados)
    return r


def todas(kit=None):
    """{marca: regras} de toda pasta com regras.json em redes/kit/."""
    base = kit or KIT
    out = {}
    if not os.path.isdir(base):
        return out
    for nome in sorted(os.listdir(base)):
        if os.path.isfile(os.path.join(base, nome, "regras.json")) and _VALIDA.match(nome):
            out[nome] = carregar(nome, base)
    return out


def instagram_ativas(kit=None):
    """Marcas com publicar.instagram=true, na ordem alfabetica."""
    return [m for m, r in todas(kit).items() if r["publicar"].get("instagram")]


def chave_token(marca):
    return "ig_access_token_" + marca


def chave_expira(marca):
    return "ig_token_expira_em_" + marca


def nomes_do_grupo(kit=None):
    """Nomes e handles de TODAS as entidades: citar outra empresa do grupo e PERMITIDO (CVO 29/09)."""
    nomes = set()
    for r in todas(kit).values():
        for v in (r["nome"], r["marca"], (r["handle_instagram"] or "").lstrip("@")):
            if v:
                nomes.add(v.lower())
    return nomes


def dominios_do_grupo(kit=None):
    out = set()
    for r in todas(kit).values():
        out.update(d.lower() for d in r["dominios_origem"])
    return out


def dominios_permitidos(regras):
    """Dominios de fonte aceitos para a entidade: os dela + fontes oficiais extras + base do grupo."""
    base = {"gov.br", "jus.br", "leg.br", "mp.br", "legisweb.com.br"}  # legisweb: compilador ja usado em pecas de 28/09
    return base | {d.lower() for d in regras.get("dominios_origem", [])} | \
        {d.lower() for d in regras.get("fontes_oficiais_extra", [])}


def host_permitido(url, dominios):
    m = re.match(r"^(?:https?://)?([^/:?#]+)", str(url or "").strip().lower())
    if not m:
        return False
    host = m.group(1)
    return any(host == d or host.endswith("." + d) for d in dominios)


def instagram_ativas_regras(kit=None):
    return {m: r for m, r in todas(kit).items() if r["publicar"].get("instagram")}


if __name__ == "__main__":
    # fumaca do gate: o registro le, cada entidade tem nome e defaults seguros
    t = todas()
    assert "innconta" in t and t["innconta"]["handle_instagram"], "innconta sem regras.json"
    for m, r in t.items():
        assert r["nome"] and isinstance(r["publicar"], dict) and r["email_escalada"], m
    print("registro OK:", {m: ("IG" if r["publicar"].get("instagram") else "-") + ("/LI" if r["publicar"].get("linkedin") else "")
                          for m, r in t.items()})
