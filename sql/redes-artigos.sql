-- ARTIGO NOVO DO SITE -> PAUTA DE POST (30/09/2026, fio redes-consultor-multimarca-merge; decisão do CVO:
-- "usar o artigo semanal como fonte" de conteúdo inédito para o Consultor de Redes).
--
-- Um registro por (marca, url de artigo) que o detector (`redes/artigos.py`) viu no índice público do site da marca
-- (`regras.json` -> `artigos.indice` + `artigos.padrao`, PGA-01: nada chumbado por marca). É ISTO que impede repetir:
-- artigo que já virou pauta nunca volta, e 2ª execução do detector não cria linha nova (UNIQUE + ignore-duplicates).
--
-- Estados (todo nó tem saída, PJC-01c):
--   base        o artigo já tinha sido usado pelo estoque (seções) antes de o detector existir: nunca vira pauta.
--   novo        ainda não virou peça; fonte PRIORITÁRIA do gerador (antes de seção antiga).
--   pauta       o gerador redigiu a peça (`peca_id`), que está na fila do Conselho.
--   consumido   o Conselho aprovou a peça (ic_redes_publicacao aprovado/publicado). Final.
--   descartado  MAX tentativas sem peça aprovada (validação ou Conselho recusou) ou o artigo saiu do site. Final,
--               com `motivo`; o vigia avisa a central no dia (AOP-01).
--   Saídas: pauta recusada -> novo (tentativa +1, novo ângulo); pauta órfã (peça não chegou ao estoque) -> novo.
-- `qa=true`: linhas da prova (`artigos.py provar --qa`), separadas das reais pelo UNIQUE; removidas com prova de
-- contagem zero ao fim da prova (`artigos.py limpar-qa`).
--
-- RLS ligada sem policy + REVOKE: só service_role (GitHub Actions), igual às demais tabelas de redes.
-- Idempotente. ROLLBACK (tabela nova, nenhum dado vivo alterado): `drop table if exists public.ic_redes_artigo;`

create table if not exists public.ic_redes_artigo (
  id            bigserial primary key,
  marca         text not null,
  url           text not null,                -- normalizada: https://host/caminho (sem www, query, âncora, barra final)
  titulo        text,
  status        text not null default 'novo'
                check (status in ('base', 'novo', 'pauta', 'consumido', 'descartado')),
  peca_id       text,                          -- peça do estoque gerada a partir do artigo (status pauta/consumido)
  tentativas    int not null default 0,        -- peças recusadas/descartadas a partir deste artigo
  motivo        text,                          -- último motivo de transição (recusa, órfã, descarte, base)
  qa            boolean not null default false,
  visto_em      timestamptz not null default now(),   -- 1ª vez que o detector viu o artigo no índice
  pauta_em      timestamptz,
  consumido_em  timestamptz,
  atualizado_em timestamptz not null default now(),
  constraint ic_redes_artigo_marca_url_qa_key unique (marca, url, qa)
);

alter table public.ic_redes_artigo enable row level security;
revoke all on public.ic_redes_artigo from anon, authenticated;
revoke all on sequence public.ic_redes_artigo_id_seq from anon, authenticated;

create index if not exists ic_redes_artigo_marca_status_idx on public.ic_redes_artigo (marca, qa, status);

comment on table public.ic_redes_artigo is
  'Consultor de Redes: artigo do site da marca -> pauta de post (redes/artigos.py). status base|novo|pauta|consumido|descartado; qa=true só na prova.';
