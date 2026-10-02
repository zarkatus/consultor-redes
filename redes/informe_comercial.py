# -*- coding: utf-8 -*-
"""Informe comercial semanal ao Roveda (Diretor Comercial) — SÓ LEITURA, nunca pedido de ação.

Diretriz do CVO (23/09/2026): "Roveda é Diretor Comercial, não operador de redes; ele pode
acessar e postar se quiser, mas esse papel compete ao consultor; ele só deve receber as
informações do que está acontecendo na área comercial, não tem obrigação de alimentar."

Fecha o "kit de 1 clique ao Roveda" (ex-`redes/kit_roveda.py`, PLAYBOOK §7-V) como pedido de
publicação — publicar é responsabilidade do consultor (ver `redes/publicar.py`). Este arquivo é
o rename desse módulo (git mv), com a lógica de envio de kit e o lembrete de 48h removidos: sem
botão "confirmar publicação", sem "publique", sem link nenhum — um e-mail semanal com o que já
aconteceu e o que vem a seguir.

Conteúdo do informe (semana corrente, segunda a domingo):
- o que foi publicado na semana (peça, canal, data, url_post quando houver);
- o que está agendado para a semana que vem;
- contatos que chegaram por rede/origem na semana (`ic_parceiro_candidatura`,
  `ic_inn_host_candidatura`, `ic_lead` com `origem` — contagem por origem, nunca dado pessoal
  completo; nome de empresa, quando houver no registro, pode aparecer);
- pendências que dependem da direção (peça aprovada sem canal definido, ou canal aguardando
  acesso a uma API que a casa ainda não tem — `calendario_status='aguardando_api'`, marcado por
  `redes/publicar.py`).

Roda segunda 08:00 BRT, junto do lote semanal (.github/workflows/redes-consultor.yml, tarefa
'informe'). --qa manda para central+qa-roveda@innconta.com.br em vez do e-mail real do Roveda —
nunca ao Roveda real fora de uma rodada de verdade."""
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "lib"))
import supa  # noqa: E402

ROVEDA_EMAIL = os.environ.get("ROVEDA_EMAIL", "")
PEDIDO_BASES_ATE = datetime.date(2026, 10, 12)  # pedido das bases ao Roveda (CVO 25/09); some depois  # descoberto na base se ausente

TABELAS_COM_ORIGEM = ("ic_parceiro_candidatura", "ic_inn_host_candidatura", "ic_lead")


def email_roveda():
    if ROVEDA_EMAIL:
        return ROVEDA_EMAIL
    try:
        r = supa.select("ic_parceiro", "nome=ilike.*roveda*&select=email&limit=1")
        if r and r[0].get("email"):
            return r[0]["email"]
    except Exception:
        pass
    return None


def semana_de(data_ref=None):
    """Segunda a domingo da semana de data_ref (default: hoje). Devolve (inicio, fim_exclusivo)."""
    data_ref = data_ref or datetime.date.today()
    inicio = data_ref - datetime.timedelta(days=data_ref.weekday())
    fim = inicio + datetime.timedelta(days=7)
    return inicio, fim


def contatos_de_rede_na_semana(inicio, fim):
    """Mesma lógica de redes/relatorio_mensal.py::contatos_de_rede_no_mes, janela SEMANAL em
    vez de mensal. Contagem por origem, nunca dado pessoal completo (só id/origem)."""
    linhas, por_origem = [], {}
    for tabela in TABELAS_COM_ORIGEM:
        try:
            achadas = supa.select(
                tabela,
                "origem=ilike.rede:*&criado_em=gte.%s&criado_em=lt.%s&select=id,origem&limit=2000"
                % (inicio.isoformat(), fim.isoformat()),
            )
        except Exception:
            achadas = []
        for linha in achadas:
            linha["_tabela"] = tabela
            chave = linha.get("origem") or "rede:?"
            por_origem[chave] = por_origem.get(chave, 0) + 1
        linhas.extend(achadas)
    return linhas, por_origem


def publicadas_na_semana(marca, inicio, fim):
    """Baseado em publicado_em (quando de fato saiu), não em data_publicacao (quando estava
    agendada) — as duas podem divergir se a publicação atrasou esperando conector de API."""
    return supa.select(
        "ic_redes_publicacao",
        "marca=eq.%s&status=eq.publicado&publicado_em=gte.%sT00:00:00&publicado_em=lt.%sT00:00:00&select=*&order=publicado_em"
        % (marca, inicio.isoformat(), fim.isoformat()),
    )


def agendadas_semana_que_vem(marca, inicio_prox, fim_prox):
    return supa.select(
        "ic_redes_publicacao",
        "marca=eq.%s&status=eq.aprovado&data_publicacao=gte.%s&data_publicacao=lt.%s&select=*&order=data_publicacao"
        % (marca, inicio_prox.isoformat(), fim_prox.isoformat()),
    )


def fila_linkedin_aguardando_api(marca):
    """Contagem NEUTRA de peças `canal='linkedin_pagina'` com `calendario_status='aguardando_api'`
    (devolvidas à fila por `redes/publicar.py`, sem `data_publicacao`/`mes_ref` — ver
    PLAYBOOK §7-V-8). Só o número, sem apontar responsável nem pedir ação — Roveda é Diretor
    Comercial, recebe informe, não opera redes (memória da casa, CVO 23/09/2026)."""
    try:
        r = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&canal=eq.linkedin_pagina&calendario_status=eq.aguardando_api&select=peca_id" % marca,
        )
    except Exception:
        r = []
    return len(r)


def pendencias_de_direcao(marca):
    """Peças que dependem de uma decisão/acesso da direção: sem canal definido, ou aguardando
    acesso a uma API que a casa ainda não tem (marcado por redes/publicar.py)."""
    itens = []
    try:
        sem_canal = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&status=eq.aprovado&or=(canal.is.null,canal.eq.a_definir)&select=peca_id,canal" % marca,
        )
    except Exception:
        sem_canal = []
    for p in sem_canal:
        itens.append("peça %s sem canal definido" % p["peca_id"])
    try:
        aguardando_api = supa.select(
            "ic_redes_publicacao",
            "marca=eq.%s&calendario_status=eq.aguardando_api&select=peca_id,canal" % marca,
        )
    except Exception:
        aguardando_api = []
    for p in aguardando_api:
        itens.append("aguardando acesso à API de %s (peça %s pronta para publicar)" % (p.get("canal") or "?", p["peca_id"]))
    return itens


def _fmt_peca(p):
    base = "%s · %s · %s" % (p.get("canal", ""), p.get("data_publicacao") or "sem data", p["peca_id"])
    if p.get("url_post"):
        base += " · " + p["url_post"]
    return base


# ══ Prospecção (Consultor SDR, passo 2 — 25/09/2026) ═══════════════════════════════════════════
# Fecha a lacuna do pedido original do CVO: "tudo precisa passar pelo Roveda, para que ele saiba
# o que está acontecendo sobre as prospecções e dados de contato" — hoje o informe não sabia nada
# do radar de CNPJ (`ic_radar`) nem do radar de originadores (`ic_radar_pessoa`). Mesma régua do
# resto do arquivo: SÓ LEITURA, contagem nunca dado pessoal (nunca telefone/e-mail em si, só a
# CONTAGEM de quem tem contato — a régua já vale para "contatos por origem de rede" acima), tom
# positivo, sem pedido de ação, sem apontar falha técnica (isso vai à central, nunca ao Roveda —
# AOP-01). `ic_radar` é lido DIRETO pela tabela (service_role bypassa RLS — mesmo mecanismo já
# usado por `contatos_de_rede_na_semana`/`publicadas_na_semana` acima), porque a única RPC que
# calcula a dor (`ic_radar_dor`) é a peça nova que faz a leitura pesada; reimplementar os pesos em
# Python duplicaria a régua da casa em dois lugares — por isso o informe CHAMA a mesma função SQL
# (`ic_radar_dor`, que aceita chamada de máquina/service_role, ver sql/radar-dor.sql) em vez de
# reescrever os pesos aqui.

# rótulo estável por CATEGORIA de dor — a frase completa de `ic_radar_dor` carrega valor em R$
# variável (ex.: "Dívida ativa da União acima de R$ 1 milhão (R$ 2.500.000,00)"); contar por frase
# inteira fragmentaria a MESMA dor em N contagens de 1. O prefixo é o bastante para reconhecer a
# categoria sem precisar mudar a régua sempre que a régua em sql/radar-dor.sql mudar um peso.
_CATEGORIAS_DOR = (
    ("Dívida ativa da União", "Dívida ativa da União"),
    ("Lucro Real", "Lucro Real"),
    ("Lucro Presumido", "Lucro Presumido"),
    ("CNAE de energia", "CNAE de energia"),
    ("CNAE de indústria", "CNAE de indústria"),
    ("Situação cadastral", "Situação cadastral fora de ATIVA"),
    ("Sanção vigente", "Sanção vigente"),
    ("Sem registro nos cadastros de sanções", "Sem registro nos cadastros de sanções"),
)


def categoria_dor(frase):
    """Mapeia a frase de `ic_radar_dor` para um rótulo estável de contagem. Frase sem prefixo
    conhecido usa ela mesma — nunca descarta uma dor por não reconhecer a categoria."""
    for prefixo, rotulo in _CATEGORIAS_DOR:
        if (frase or "").startswith(prefixo):
            return rotulo
    return frase


def entradas_radar_semana(inicio, fim):
    """Linhas novas em `ic_radar` na semana (`criado_em`) — inclui quem passou para o perfil da
    InnConta e quem ficou fora: as duas informam o volume real que passou pela triagem, e um
    informe que só mostrasse quem passou estaria escondendo o trabalho da triagem, não só sendo
    positivo. Nunca lê e-mail/telefone em texto — só para decidir a CONTAGEM de quem tem contato."""
    try:
        return supa.select(
            "ic_radar",
            "criado_em=gte.%sT00:00:00&criado_em=lt.%sT00:00:00&select=cnpj,estado,email,telefone"
            % (inicio.isoformat(), fim.isoformat()),
        )
    except Exception:
        return []


def dores_e_contato_das_entradas(linhas):
    """Para cada linha nova do radar já classificada DENTRO do perfil da InnConta (na_fila,
    em_contato, virou_lead, sem_interesse — não fora_do_perfil, nem novo/buscando ainda sem
    enriquecimento), chama `ic_radar_dor` (RPC, mesma régua da tela) e agrega por CATEGORIA.
    Devolve (contagem_por_categoria, quantas_tem_contato). Erro numa linha não derruba as outras —
    cada CNPJ é uma chamada independente, e o informe nunca falha por causa de uma dor que não
    computou."""
    contagem = {}
    com_contato = 0
    dentro_do_perfil = ("na_fila", "em_contato", "virou_lead", "sem_interesse")
    for linha in linhas:
        if linha.get("email") or linha.get("telefone"):
            com_contato += 1
        if linha.get("estado") not in dentro_do_perfil:
            continue
        try:
            dor = supa.rpc("ic_radar_dor", {"p_cnpj": linha["cnpj"]})
        except Exception:
            continue
        for frase in (dor or {}).get("dores") or []:
            rotulo = categoria_dor(frase)
            contagem[rotulo] = contagem.get(rotulo, 0) + 1
    return contagem, com_contato


def movimentacao_radar_semana(inicio, fim):
    """O que a equipe MOVEU na semana — por `atualizado_em`, independente de quando a linha
    entrou no radar (pode ter entrado semanas atrás e só ter sido trabalhada agora). Métrica
    distinta de `entradas_radar_semana` (que é sobre ENTRADA, não sobre trabalho)."""
    def contar(estado):
        try:
            r = supa.select(
                "ic_radar",
                "estado=eq.%s&atualizado_em=gte.%sT00:00:00&atualizado_em=lt.%sT00:00:00&select=id"
                % (estado, inicio.isoformat(), fim.isoformat()),
            )
        except Exception:
            r = []
        return len(r)
    return {"em_contato": contar("em_contato"), "virou_lead": contar("virou_lead")}


def originadores_novos_semana(inicio, fim):
    """Novos nomes em `ic_radar_pessoa` na semana — o radar de originadores é 100% manual (nunca
    scraper), então esta contagem é sempre trabalho humano registrado, nunca automação."""
    try:
        r = supa.select(
            "ic_radar_pessoa",
            "criado_em=gte.%sT00:00:00&criado_em=lt.%sT00:00:00&select=id"
            % (inicio.isoformat(), fim.isoformat()),
        )
    except Exception:
        r = []
    return len(r)


def captacao_da_semana(inicio, fim):
    """Convites e candidaturas de parceiros na semana (CVO 30/09/2026, funil de captação). SÓ contagem
    do que aconteceu: convites gerados, convites abertos, candidaturas recebidas e parceiros criados.
    Zero não entra no e-mail (montar_html omite a linha), e nada aqui vira pedido ou cobrança ao Roveda."""
    janela = "%sT00:00:00" % inicio.isoformat(), "%sT00:00:00" % fim.isoformat()

    def contar(tabela, campo, extra=""):
        try:
            r = supa.select(tabela, "%s=gte.%s&%s=lt.%s%s&select=id" % (campo, janela[0], campo, janela[1], extra))
        except Exception:
            r = []
        return len(r)
    return {
        "convites_gerados": contar("ic_convite", "criado_em", "&revogado=eq.false"),
        "convites_abertos": contar("ic_convite", "ultimo_uso"),
        "candidaturas": contar("ic_parceiro_candidatura", "criado_em"),
        "parceiros_criados": contar("ic_parceiro_candidatura", "atualizado_em", "&estado=eq.parceiro_criado"),
    }


def prospeccao_da_semana(inicio, fim, link_crm=None):
    """Monta o bloco de dados da seção Prospecção — uma função só, pra `montar()` ficar legível e
    pra `montar_html` poder ser testada com um dict fixo, sem rede (mesmo padrão de
    `fila_linkedin` no resto do arquivo)."""
    entradas = entradas_radar_semana(inicio, fim)
    dores, com_contato = dores_e_contato_das_entradas(entradas)
    mov = movimentacao_radar_semana(inicio, fim)
    na_fila = sum(1 for l in entradas if l.get("estado") in ("na_fila", "em_contato", "virou_lead", "sem_interesse"))
    return {
        "entradas": len(entradas),
        "na_fila": na_fila,
        "fora_do_perfil": len(entradas) - na_fila,
        "dores": dores,
        "com_contato": com_contato,
        "em_contato_semana": mov["em_contato"],
        "virou_lead_semana": mov["virou_lead"],
        "originadores_novos": originadores_novos_semana(inicio, fim),
        "captacao": captacao_da_semana(inicio, fim),
        "link_crm": link_crm or "https://crm.innconta.com.br/",
    }


def montar_html(inicio, fim, publicadas, agendadas, por_origem, total_contatos, pendencias, fila_linkedin=0, prospeccao=None):
    html = ["<h2>InnConta · informe comercial da semana (%s a %s)</h2>"
            % (inicio.strftime("%d/%m"), (fim - datetime.timedelta(days=1)).strftime("%d/%m"))]

    html.append("<p><b>Publicado nesta semana (%d):</b></p>" % len(publicadas))
    if publicadas:
        html.append("<ul>" + "".join("<li>%s</li>" % _fmt_peca(p) for p in publicadas) + "</ul>")
    else:
        html.append("<p>Nenhuma peça publicada nesta semana.</p>")

    html.append("<p><b>Agendado para a semana que vem (%d):</b></p>" % len(agendadas))
    if agendadas:
        html.append("<ul>" + "".join("<li>%s</li>" % _fmt_peca(p) for p in agendadas) + "</ul>")
    else:
        html.append("<p>Nada agendado ainda para a semana que vem.</p>")

    detalhe = ", ".join("%s: %d" % (k, v) for k, v in sorted(por_origem.items())) or "nenhum na semana"
    html.append("<p><b>Contatos por origem de rede nesta semana:</b> %d (%s).</p>" % (total_contatos, detalhe))

    html.append("<p>%d peças do LinkedIn em fila aguardando acesso à API.</p>" % fila_linkedin)

    html.append("<p><b>Pendências que dependem da direção:</b></p>")
    if pendencias:
        html.append("<ul>" + "".join("<li>%s</li>" % p for p in pendencias) + "</ul>")
    else:
        html.append("<p>Nenhuma pendência no momento.</p>")

    # ── Prospecção (Consultor SDR, passo 2) — tom positivo e informativo, SÓ contagem, nunca o
    # contato em si; nunca "nada aconteceu" quando a semana ficou parada, e nunca cita falha
    # técnica (isso é assunto da central técnica, AOP-01, nunca do informe ao Roveda).
    p = prospeccao or {}
    tem_movimento = bool(
        p.get("entradas", 0) or p.get("em_contato_semana", 0) or p.get("virou_lead_semana", 0) or p.get("originadores_novos", 0)
        or any((p.get("captacao") or {}).values())
    )
    html.append("<h3>Prospecção</h3>")
    if tem_movimento:
        html.append(
            "<p><b>%d empresa(s) nova(s) na fila do radar nesta semana</b> "
            "(%d dentro do perfil da InnConta, %d fora do perfil).</p>"
            % (p.get("entradas", 0), p.get("na_fila", 0), p.get("fora_do_perfil", 0))
        )
        # 25/09 (revisão): "sem registro de sanções" não é dor (fato neutro); e linha zerada não entra —
        # a quem não é o CVO só chega o que aconteceu, nunca uma contagem de nada.
        dores = {k: v for k, v in (p.get("dores") or {}).items() if not k.lower().startswith("sem registro")}
        if dores:
            dores_txt = ", ".join(
                "%s: %d" % (k, v) for k, v in sorted(dores.items(), key=lambda kv: (-kv[1], kv[0]))
            )
            html.append("<p><b>Dores mais frequentes:</b> %s.</p>" % dores_txt)
        if p.get("com_contato", 0):
            html.append(
                "<p><b>%d</b> com contato corporativo encontrado (o dado fica na fila do CRM, "
                "não neste e-mail).</p>" % p.get("com_contato", 0)
            )
        mov = []
        if p.get("em_contato_semana", 0):
            mov.append("%d em contato" % p["em_contato_semana"])
        if p.get("virou_lead_semana", 0):
            mov.append("%d viraram lead" % p["virou_lead_semana"])
        if mov:
            html.append("<p><b>Movimentação da equipe na semana:</b> %s.</p>" % ", ".join(mov))
        if p.get("originadores_novos", 0):
            html.append("<p><b>%d</b> originador(es) novo(s) no radar de pessoas.</p>" % p["originadores_novos"])
        cap = p.get("captacao") or {}
        cap_txt = ", ".join(
            "%d %s" % (cap[k], rot) for k, rot in (
                ("convites_gerados", "convite(s) individual(is) gerado(s)"),
                ("convites_abertos", "convite(s) aberto(s)"),
                ("candidaturas", "candidatura(s) recebida(s)"),
                ("parceiros_criados", "parceiro(s) criado(s)"),
            ) if cap.get(k)
        )
        if cap_txt:
            html.append("<p><b>Captação de parceiros na semana:</b> %s.</p>" % cap_txt)
    else:
        html.append("<p>A fila está pronta para a próxima semana.</p>")
    html.append('<p><a href="%s">Ver a fila completa no CRM</a>.</p>' % (p.get("link_crm") or "https://crm.innconta.com.br/"))
    # CVO 25/09/2026: "tem que solicitar ao Roveda os bancos de dados para mineração do consultor".
    # Pedido com prazo (não vira cobrança eterna): some sozinho depois de PEDIDO_BASES_ATE.
    if datetime.date.today() <= PEDIDO_BASES_ATE:
        html.append(
            "<p><b>Para acelerar a prospecção:</b> o Consultor SDR da InnConta passa a minerar também as bases "
            "que você tiver — listas de empresas, planilhas de contatos, exportações de CRM ou de eventos. "
            "Basta responder este e-mail com os arquivos; cada empresa entra na fila com a dor mapeada.</p>"
        )

    html.append("<p style='font-size:12px;color:#999'>Consultor de Redes · informe automático.</p>")
    return "".join(html)


def montar(marca="innconta", modo_qa=False, data_ref=None, destino_email=None):
    inicio, fim = semana_de(data_ref)
    inicio_prox, fim_prox = fim, fim + datetime.timedelta(days=7)

    publicadas = publicadas_na_semana(marca, inicio, fim)
    agendadas = agendadas_semana_que_vem(marca, inicio_prox, fim_prox)
    contatos, por_origem = contatos_de_rede_na_semana(inicio, fim)
    pendencias = pendencias_de_direcao(marca)
    fila_linkedin = fila_linkedin_aguardando_api(marca)
    prospeccao = prospeccao_da_semana(inicio, fim)

    html = montar_html(inicio, fim, publicadas, agendadas, por_origem, len(contatos), pendencias, fila_linkedin, prospeccao)

    destino = destino_email or ("central+qa-roveda@innconta.com.br" if modo_qa else (email_roveda() or os.environ.get("ROVEDA_EMAIL_FALLBACK", "")))
    if not destino:
        print("sem e-mail do Roveda (nem env ROVEDA_EMAIL/FALLBACK, nem achado na base) — abortando informe.")
        return {"enviado": False, "motivo": "sem_destino"}

    assunto = "InnConta · informe comercial da semana (%s a %s)" % (
        inicio.strftime("%d/%m"), (fim - datetime.timedelta(days=1)).strftime("%d/%m"))
    resp = supa.enviar_email(assunto, destino, html)
    print("informe comercial enviado a", destino, ":", resp)
    return {
        "enviado": True, "destino": destino, "publicadas": len(publicadas), "agendadas": len(agendadas),
        "contatos_semana": len(contatos), "por_origem": por_origem, "pendencias": len(pendencias),
        "fila_linkedin": fila_linkedin, "prospeccao": prospeccao,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca", default="innconta")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--email", default=None)
    a = ap.parse_args()
    print(montar(a.marca, a.qa, destino_email=a.email))
