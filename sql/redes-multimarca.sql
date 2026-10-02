-- Consultor de Redes MULTIMARCA + Conselho v2 (CVO 29/09/2026). ADITIVO e IDEMPOTENTE — nada existente e removido ou
-- alterado de forma incompativel; pode ser reaplicado. Aplicar depois de sql/redes-publicacao.sql e sql/redes-conselho.sql.
--   1. ic_redes_revisao.marca (default 'innconta': todo voto anterior era da InnConta) + indice.
--   2. ic_redes_publicacao.collab_planejada / collab_com (regra de collab semanal: quem foi promovida, com quem saiu).
--   3. ic_redes_metrica: 1 linha por post por dia (insights do Instagram) para o relatorio de alcance.
--   4. ic_redes_consumo: consumo diario de IA gratuita por marca/provedor/papel (plano de cota, medicao).
--   5. ic_redes_cache_revisao: voto por hash do conteudo (peca inalterada nao gasta modelo de novo).
--   6. redes_conselho_registrar: alem da decisao, carimba a MARCA nos votos da peca em ic_redes_revisao.
--   7. redes_consumo_somar: soma atomica em ic_redes_consumo.
-- RLS ligada sem policy + REVOKE: so service_role (GitHub Actions), igual as demais tabelas de redes.

alter table public.ic_redes_revisao add column if not exists marca text not null default 'innconta';
create index if not exists ic_redes_revisao_marca_idx on public.ic_redes_revisao (marca, criado_em);

alter table public.ic_redes_publicacao add column if not exists collab_planejada text;
alter table public.ic_redes_publicacao add column if not exists collab_com text;

create table if not exists public.ic_redes_metrica (
  id                bigserial primary key,
  marca             text not null,
  peca_id           text,                       -- null = post fora do estoque (ou permalink nao casou)
  media_id          text not null,
  dia               date not null default current_date,
  coletado_em       timestamptz not null default now(),
  formato           text,                       -- IMAGEM | CAROUSEL | REELS
  publicado_em      timestamptz,
  alcance           int,                        -- reach
  impressoes        int,                        -- impressions (midia antiga) ou views
  curtidas          int,
  comentarios       int,
  salvos            int,
  compartilhamentos int,
  plays             int                         -- views, so em Reels (plays foi substituida por views na API)
);
alter table public.ic_redes_metrica enable row level security;
revoke all on public.ic_redes_metrica from anon, authenticated;
revoke all on sequence public.ic_redes_metrica_id_seq from anon, authenticated;
create unique index if not exists ic_redes_metrica_post_dia_uq on public.ic_redes_metrica (marca, media_id, dia);
create index if not exists ic_redes_metrica_marca_idx on public.ic_redes_metrica (marca, coletado_em);

create table if not exists public.ic_redes_consumo (
  dia       date not null,
  marca     text not null,
  provedor  text not null,                      -- cf | groq | gemini | openrouter
  papel     text not null,                      -- fato | voz | visual | visual2 | risco | editorial | redator | longo
  chamadas  int not null default 0,
  falhas    int not null default 0,
  cache_hit int not null default 0,
  primary key (dia, marca, provedor, papel)
);
alter table public.ic_redes_consumo enable row level security;
revoke all on public.ic_redes_consumo from anon, authenticated;

create table if not exists public.ic_redes_cache_revisao (
  hash      text primary key,                   -- sha256(papel + marca + conteudo revisado)
  papel     text not null,
  marca     text not null,
  voto      jsonb not null,
  criado_em timestamptz not null default now()
);
alter table public.ic_redes_cache_revisao enable row level security;
revoke all on public.ic_redes_cache_revisao from anon, authenticated;
create index if not exists ic_redes_cache_revisao_criado_idx on public.ic_redes_cache_revisao (criado_em);

create or replace function public.redes_consumo_somar(
  p_dia date, p_marca text, p_provedor text, p_papel text, p_chamadas int, p_falhas int, p_cache int default 0
) returns void
language sql security definer set search_path = public as $$
  insert into ic_redes_consumo (dia, marca, provedor, papel, chamadas, falhas, cache_hit)
  values (p_dia, p_marca, p_provedor, p_papel, p_chamadas, p_falhas, p_cache)
  on conflict (dia, marca, provedor, papel) do update
     set chamadas = ic_redes_consumo.chamadas + excluded.chamadas,
         falhas = ic_redes_consumo.falhas + excluded.falhas,
         cache_hit = ic_redes_consumo.cache_hit + excluded.cache_hit;
$$;
revoke all on function public.redes_consumo_somar(date,text,text,text,int,int,int) from public, anon, authenticated;
grant execute on function public.redes_consumo_somar(date,text,text,text,int,int,int) to service_role;

-- redes_conselho_registrar: mesma decisao de sql/redes-conselho.sql + carimbo da marca nos votos da peca.
create or replace function public.redes_conselho_registrar(
  p_marca text, p_canal text, p_peca_id text, p_tipo text, p_formato text,
  p_mes_ref text, p_pilar text, p_nota_origem text,
  p_decisao text, p_motivos jsonb, p_texto text, p_rodadas int
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  if p_decisao not in ('aprovado', 'escalado') then
    return jsonb_build_object('ok', false, 'motivo', 'decisao_invalida');
  end if;
  select * into r from ic_redes_publicacao where peca_id = p_peca_id for update;
  if found and r.status not in ('rascunho', 'aguardando') then
    return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'status', r.status);
  end if;
  if not found then
    insert into ic_redes_publicacao (marca, canal, peca_id, tipo, formato, mes_ref, pilar, nota_origem, status)
    values (p_marca, p_canal, p_peca_id, p_tipo, p_formato, p_mes_ref, p_pilar, p_nota_origem, 'rascunho');
  end if;
  update ic_redes_publicacao
     set status = p_decisao,
         conselho_motivos = coalesce(p_motivos, '[]'::jsonb),
         conselho_rodadas = p_rodadas,
         texto_aprovado = case when p_decisao = 'aprovado' then p_texto else null end,
         aprovado_por = case when p_decisao = 'aprovado' then 'conselho' else null end,
         aprovado_em = case when p_decisao = 'aprovado' then now() else null end,
         enviado_em = now()
   where peca_id = p_peca_id;
  update ic_redes_revisao set marca = p_marca where peca_id = p_peca_id and marca is distinct from p_marca;
  return jsonb_build_object('ok', true, 'status', p_decisao);
end;
$$;
revoke all on function public.redes_conselho_registrar(text,text,text,text,text,text,text,text,text,jsonb,text,int) from public, anon, authenticated;
grant execute on function public.redes_conselho_registrar(text,text,text,text,text,text,text,text,text,jsonb,text,int) to service_role;

-- conferencia pos-aplicacao (esperado: true, true, true, true, e false, false, false nos privilegios):
--   select exists(select 1 from information_schema.columns where table_name='ic_redes_revisao' and column_name='marca'),
--          to_regclass('public.ic_redes_metrica') is not null, to_regclass('public.ic_redes_consumo') is not null,
--          to_regclass('public.ic_redes_cache_revisao') is not null;
--   select has_table_privilege('anon','ic_redes_metrica','select'), has_table_privilege('authenticated','ic_redes_metrica','select'),
--          has_function_privilege('anon','redes_consumo_somar(date,text,text,text,int,int,int)','execute');
