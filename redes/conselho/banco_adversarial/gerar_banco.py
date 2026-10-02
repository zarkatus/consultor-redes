# -*- coding: utf-8 -*-
"""Gera `banco.json` e `kit/*/regras.json` do banco adversarial do Conselho (29/09/2026). Rodar so para RECRIAR o banco;
o resultado fica commitado. O banco e AUTOSSUFICIENTE: tem o proprio kit (3 entidades) e nao depende de redes/kit/.

Cada peca tem `esperado`: "reprovar" (UM defeito plantado, campo `defeito` o nomeia; o resto da peca e limpo, para medir
so aquele defeito) ou "passar" (limpa). A peca c02 cita outra empresa do grupo (collab) e DEVE passar (regra do CVO
29/09: citar empresa do grupo nao e defeito). As limpas seguem o padrao editorial da casa (fato na 1a frase, norma,
erro comum e metodo, fonte declarada), senao os revisores de modelo reprovam por editorial, nao pelo defeito medido."""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))


def _base(marca, nome, handle, parceiros, chaves, temas, extra=None):
    r = {"marca": marca, "tipo": "empresa", "nome": nome, "site": "https://%s.exemplo.com.br" % marca,
         "dominios_origem": ["%s.exemplo.com.br" % marca], "handle_instagram": handle, "ig_user_id": "1",
         "publicar": {"instagram": True, "linkedin": False, "horario_brt": "09:00"},
         "voz": {"tom": "Sobrio e sofisticado. Frases curtas. Autoridade sobre o que a empresa faz, nunca venda nem motivacao.",
                 "proibidos": ["cesta", "loteamento", "credito barato", "parceiro contratado"], "preferidos": [], "regras_extra": []},
         "temas": temas, "palavras_chave": chaves, "hashtags": ["#" + nome, "#regularidadefiscal", "#gestaoempresarial"],
         "fontes_oficiais_extra": [], "discricao": {"sigilo": False, "nao_citar": []},
         "collab": {"parceiros": parceiros, "min_por_semana": 0, "max_por_semana": 2}, "email_escalada": "central@innconta.com.br"}
    if extra:
        r.update(extra)
    return r


def _grava(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


TAGS = "#InnConta #regularidadefiscal #gestaoempresarial"
TAGS_IS = "#InnovaSphere #regularidadefiscal #gestaoempresarial"
CTA = "Salve este post para consultar depois."
F180 = [{"dado": "A certidão negativa de débitos federais tem validade de 180 dias",
         "norma": "Portaria Conjunta RFB/PGFN nº 1.751/2014, art. 1º", "url": "https://www.gov.br/receitafederal/pt-br"}]
FSIMPLES = [{"dado": "A opção pelo Simples Nacional é feita até o último dia útil de janeiro",
             "norma": "Lei Complementar nº 123/2006, art. 16", "url": "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm"}]
FNCM = [{"dado": "A NCM tem 8 dígitos", "norma": "Decreto nº 11.158/2022 (TIPI, que adota a NCM)",
         "url": "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2022/decreto/D11158.htm"}]
FEC132 = [{"dado": "A Emenda Constitucional nº 132/2023 criou o IBS e a CBS", "norma": "Emenda Constitucional nº 132/2023",
           "url": "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc132.htm"}]
FENERGIA = [{"dado": "A demanda contratada consta na fatura e é cobrada mesmo quando não é consumida",
             "norma": "Resolução Normativa ANEEL nº 1.000/2021", "url": "https://www.gov.br/aneel/pt-br"}]
FIBGE = [{"dado": "O Brasil tem 5.570 municípios", "norma": "IBGE, Cidades e Estados", "url": "https://www.ibge.gov.br/cidades-e-estados"}]


def P(id_, marca, texto, arte="Pergunta da mesa", fontes=None, defeito=None, esperado="passar", **kw):
    d = {"peca_id": id_, "marca": marca, "canal": "instagram", "formato": "texto", "tipo": "carrossel", "texto": texto,
         "texto_arte": arte, "fontes": fontes or [], "nota_urls": [], "defeito": defeito, "esperado": esperado}
    d.update(kw)
    return d


def L(*linhas, tags=TAGS):
    """Legenda: linhas + chamada final + hashtags."""
    return "\n".join(list(linhas) + [CTA, tags])


A1 = "A certidão negativa federal vale 180 dias."
A2 = "Erro comum: renovar só quando o edital exige. Método: um alerta antes do vencimento, para a regularidade fiscal da empresa não depender de memória."
ARTE_A = "Pergunta da mesa\nA certidão vence em 180 dias"
S1 = "A opção pelo Simples Nacional vai até o último dia útil de janeiro."
S2 = "Erro comum: descobrir o prazo em fevereiro. Método: rotina com alerta em dezembro para a empresa não esperar um ano."
R_SIMPLES = L("O prazo para optar pelo Simples Nacional termina no último dia útil de janeiro.",
              "Erro comum: deixar a opção para a última semana. Método: conferir o enquadramento da empresa em dezembro.")
R_NCM = L("A NCM tem 8 dígitos e define o tributo de cada item da nota.",
          "Erro comum: classificar pela descrição comercial. Método: conferir o código na tabela oficial antes de emitir.")
ERRO_C = "Erro comum: renovar o contrato de energia sem revisar a demanda. Método: comparar o contratado com o medido nos últimos meses."
FRASE_C = "A demanda contratada aparece na fatura e é cobrada mesmo quando não é consumida."
TAGS_P = "#InnCorPower #energia #contrato"
REFORMA1 = "A Emenda Constitucional 132/2023 criou o IBS e a CBS."
REFORMA2 = "Erro comum: tratar a reforma tributária como assunto distante. Método: revisar o cadastro de produtos e a NCM da empresa agora."


def main():
    ic = json.load(open(os.path.join(AQUI, "..", "..", "kit", "innconta", "regras.json"), encoding="utf-8"))
    ic["dominios_origem"] = ["innconta.com.br"]
    _grava(os.path.join(AQUI, "kit", "innconta", "regras.json"), ic)
    _grava(os.path.join(AQUI, "kit", "innovasphere", "regras.json"),
           _base("innovasphere", "InnovaSphere", "@innovasphere.oficial", ["innconta"],
                 ["regularidade", "prazo", "rotina", "sistema", "empresa"], ["tecnologia", "gestao", "rotina"]))
    _grava(os.path.join(AQUI, "kit", "inncorpower", "regras.json"),
           _base("inncorpower", "InnCorPower", "@inncorpower.oficial", [],
                 ["energia", "contrato", "fatura", "regularidade", "usina"], ["energia", "contratos de energia"],
                 {"discricao": {"sigilo": True, "nao_citar": []}}))
    pecas = [
        P("c01-certidao-180", "innconta", L(A1, A2), ARTE_A, F180),
        P("c02-cita-innovasphere", "innconta",
          L("Em parceria com a InnovaSphere: a certidão negativa federal vale 180 dias.", A2, tags=TAGS + " #InnovaSphere"),
          ARTE_A, F180, collab=True),
        P("c03-innovasphere-simples", "innovasphere", L(S1, S2, tags=TAGS_IS), "Método\nAlerta em dezembro", FSIMPLES),
        P("c04-inncorpower-demanda", "inncorpower", L(FRASE_C, ERRO_C, tags=TAGS_P), "Método\nDemanda contratada", FENERGIA),
        P("c05-ncm-8-digitos", "innconta",
          L("A NCM tem 8 dígitos e decide a tributação de cada item da nota.",
            "Erro comum: classificar pelo nome comercial. Método: conferir a NCM na tabela oficial antes da emissão, pela regularidade fiscal da empresa."),
          "Método\nNCM com 8 dígitos", FNCM),
        P("c06-innovasphere-imagem", "innovasphere", L(REFORMA1, REFORMA2, tags=TAGS_IS), "Marco\nEC 132/2023", FEC132,
          formato="imagem_feed", imagem={"w": 1080, "h": 1350, "linhas": ["Marco", "EC 132/2023", "IBS e CBS"]}),
        P("d01-numero-na-arte-fora-da-fonte", "innconta", L(A1, A2), "Pergunta da mesa\nReduza 72% do imposto", F180,
          "numero_arte_fora_da_fonte", "reprovar"),
        P("d02-numero-operacional-inncorpower", "inncorpower",
          L("A usina de 150 MWac tem TIR de 14% e CAPEX de R$ 800 milhões.", ERRO_C, tags=TAGS_P),
          "Método\nDemanda contratada", FENERGIA, "sigilo_numero_operacional", "reprovar"),
        P("d03-sigilo-na-arte-inncorpower", "inncorpower", L(FRASE_C, ERRO_C, tags=TAGS_P), "Marco\nUsina de 300 MW", FENERGIA,
          "sigilo_na_arte", "reprovar"),
        P("d04-quase-identico-a-publicada", "innconta",
          L("O prazo para optar pelo Simples Nacional termina no último dia útil de janeiro.",
            "Erro comum: deixar a opção para a última semana. Método: conferir o enquadramento da empresa em dezembro, sem pressa."),
          "Pergunta da mesa\nSimples Nacional: até janeiro", FSIMPLES, "quase_identico_a_publicada", "reprovar"),
        P("d05-identico-outra-marca-mesmo-dia", "innconta", R_NCM, "Método\nNCM com 8 dígitos", FNCM,
          "outra_marca_mesmo_dia", "reprovar", data_publicacao="2026-10-05"),
        P("d06-palavra-casa", "innconta",
          L(A1, "Erro comum: renovar só quando o edital exige. Método: a casa avisa antes do vencimento, pela regularidade fiscal da empresa."),
          ARTE_A, F180, "palavra_casa", "reprovar"),
        P("d07-promessa-de-resultado", "innconta",
          L(A1, "Erro comum: renovar só quando o edital exige. Método: alerta antes do vencimento, com resultado garantido e zero multa na regularidade fiscal da empresa."),
          ARTE_A, F180, "promessa_resultado", "reprovar"),
        P("d08-fonte-dominio-nao-permitido", "innconta", L(A1, A2), ARTE_A,
          [{"dado": "A certidão negativa tem validade de 180 dias", "norma": "post de blog",
            "url": "https://medium.com/@contador/certidao-negativa-180-dias"}], "fonte_dominio_nao_permitido", "reprovar"),
        P("d09-imagem-proporcao-invalida", "innovasphere", L(REFORMA1, REFORMA2, tags=TAGS_IS), "Marco\nEC 132/2023", FEC132,
          formato="imagem_feed", imagem={"w": 1080, "h": 2400, "linhas": ["Marco", "EC 132/2023", "IBS e CBS"]},
          defeito="imagem_proporcao_invalida", esperado="reprovar"),
        P("d10-nome-de-cliente", "innconta",
          L(A1, "Erro comum: renovar só quando o edital exige. Método: alerta antes do vencimento, como fez a Construtora Horizonte Azul Ltda."),
          ARTE_A, F180, "nome_de_cliente", "reprovar"),
        P("d11-sem-palavra-chave", "innconta",
          L("O Brasil tem 5.570 municípios.", "Erro comum: achar que toda cidade tem a mesma regra. Método: consultar a lei local antes de decidir.",
            tags="#InnConta #cidades #brasil"),
          "Pergunta da mesa\nBrasil: 5.570 municípios", FIBGE, "sem_palavra_chave", "reprovar"),
        P("d12-primeira-frase-sem-gancho", "innconta",
          L("A certidão negativa de débitos federais, que comprova a regularidade da empresa perante a Receita Federal e a PGFN em licitações e financiamentos, vale 180 dias contados da emissão.",
            "Método: um alerta antes do vencimento."),
          ARTE_A, F180, "primeira_frase_sem_gancho", "reprovar"),
        P("d13-trinta-hashtags", "innconta", L(A1, A2, tags=" ".join("#tag%d" % i for i in range(30))), ARTE_A, F180,
          "trinta_hashtags", "reprovar"),
        P("d14-agente-virtual", "innconta",
          L(A1, "Erro comum: renovar só quando o edital exige. Método: nosso agente virtual avisa antes do vencimento, pela regularidade fiscal da empresa."),
          ARTE_A, F180, "agente_virtual", "reprovar"),
        P("d15-parceiro-contratado", "innconta",
          L(A1, "Erro comum: renovar só quando o edital exige. Método: parceiros contratados avisam antes do vencimento, pela regularidade fiscal da empresa."),
          ARTE_A, F180, "parceiro_contratado", "reprovar"),
    ]
    banco = {"nomes_clientes": ["Construtora Horizonte Azul Ltda"],
             "referencias": [{"marca": "innconta", "peca_id": "pub-simples", "texto": R_SIMPLES, "data": None},
                             {"marca": "innovasphere", "peca_id": "pub-ncm", "texto": R_NCM, "data": "2026-10-05"}],
             "pecas": pecas}
    _grava(os.path.join(AQUI, "banco.json"), banco)
    print("pecas:", len(pecas), "com defeito:", sum(1 for p in pecas if p["esperado"] == "reprovar"),
          "limpas:", sum(1 for p in pecas if p["esperado"] == "passar"))


if __name__ == "__main__":
    main()
