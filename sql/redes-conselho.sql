-- Conselho Editorial automático do Consultor de Redes (CVO 23/09/2026: "revisão e aprovação não
-- humana"). IDEMPOTENTE — pode ser reaplicado. Complementa sql/redes-publicacao.sql (aplicar depois).
--   1. ic_redes_revisao: 1 linha por voto (revisor/redator/guarda) por rodada — trilha auditável.
--   2. ic_redes_publicacao: status 'escalado' (conselho não chegou a consenso -> CVO decide) e
--      'retirado' (post retirado depois de publicado, pelo link do resumo semanal); colunas do
--      conselho (texto aprovado, motivos, voltas) e da retirada.
--   3. redes_conselho_registrar: grava a decisão do conselho (aprovado|escalado), idempotente.
--   4. redes_decidir: aprovar/recusar também a partir de 'escalado'; ação nova 'retirar'.
-- RLS ligada sem policy + REVOKE: só service_role (GitHub Actions e Pages Function).

create table if not exists public.ic_redes_revisao (
  id         bigserial primary key,
  peca_id    text not null,
  rodada     int not null,
  revisor    text not null,              -- guarda | fato | voz | visual | risco | editorial | redator
  modelo     text,
  passa      boolean not null,
  nota       int,
  motivos    jsonb not null default '[]'::jsonb,
  trechos    jsonb not null default '[]'::jsonb,
  neuronios  numeric not null default 0, -- custo Workers AI (teto diário gratuito, redes/conselho/modelos.py)
  criado_em  timestamptz not null default now()
);
alter table public.ic_redes_revisao enable row level security;
revoke all on public.ic_redes_revisao from anon, authenticated;
revoke all on sequence public.ic_redes_revisao_id_seq from anon, authenticated;
create index if not exists ic_redes_revisao_peca_idx on public.ic_redes_revisao (peca_id, rodada);
create index if not exists ic_redes_revisao_criado_idx on public.ic_redes_revisao (criado_em);

alter table public.ic_redes_publicacao add column if not exists texto_aprovado text;
alter table public.ic_redes_publicacao add column if not exists conselho_motivos jsonb;
alter table public.ic_redes_publicacao add column if not exists conselho_rodadas int;
alter table public.ic_redes_publicacao add column if not exists retirado_em timestamptz;

alter table public.ic_redes_publicacao drop constraint if exists ic_redes_publicacao_status_check;
alter table public.ic_redes_publicacao add constraint ic_redes_publicacao_status_check
  check (status in ('rascunho','aguardando','aprovado','recusado','expirado','publicado','escalado','retirado'));

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
  return jsonb_build_object('ok', true, 'status', p_decisao);
end;
$$;
revoke all on function public.redes_conselho_registrar(text,text,text,text,text,text,text,text,text,jsonb,text,int) from public, anon, authenticated;
grant execute on function public.redes_conselho_registrar(text,text,text,text,text,text,text,text,text,jsonb,text,int) to service_role;

-- redes_decidir: igual a sql/redes-publicacao.sql, com 2 mudanças: aprovar/recusar aceitam
-- 'escalado' (o CVO decide pelo e-mail semanal de escaladas) e a ação nova 'retirar'
-- ('publicado' -> 'retirado', pelo link do resumo semanal). Uso único continua vindo do estado.
create or replace function public.redes_decidir(p_id uuid, p_acao text, p_url_post text default null, p_por text default null)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare r record;
begin
  select * into r from ic_redes_publicacao where id = p_id for update;
  if not found then
    return jsonb_build_object('ok', false, 'motivo', 'nao_encontrada');
  end if;

  if p_acao = 'aprovar' then
    if r.status not in ('aguardando', 'escalado') then
      return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'status', r.status);
    end if;
    update ic_redes_publicacao set status = 'aprovado', aprovado_por = coalesce(p_por, 'cvo'), aprovado_em = now() where id = p_id;
    return jsonb_build_object('ok', true, 'status', 'aprovado');

  elsif p_acao = 'recusar' then
    if r.status not in ('aguardando', 'escalado') then
      return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'status', r.status);
    end if;
    update ic_redes_publicacao set status = 'recusado', aprovado_por = coalesce(p_por, 'cvo'), aprovado_em = now() where id = p_id;
    return jsonb_build_object('ok', true, 'status', 'recusado');

  elsif p_acao = 'publicado' then
    if r.status <> 'aprovado' then
      return jsonb_build_object('ok', false, 'motivo', 'nao_aprovada', 'status', r.status);
    end if;
    update ic_redes_publicacao
       set status = 'publicado', publicado_em = now(),
           url_post = coalesce(nullif(p_url_post, ''), url_post),
           publicado_por = coalesce(p_por, 'roveda')
     where id = p_id;
    return jsonb_build_object('ok', true, 'status', 'publicado');

  elsif p_acao = 'retirar' then
    if r.status <> 'publicado' then
      return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'status', r.status);
    end if;
    update ic_redes_publicacao set status = 'retirado', retirado_em = now() where id = p_id;
    return jsonb_build_object('ok', true, 'status', 'retirado', 'canal', r.canal, 'url_post', r.url_post);

  else
    return jsonb_build_object('ok', false, 'motivo', 'acao_invalida');
  end if;
end;
$$;
revoke all on function public.redes_decidir(uuid, text, text, text) from public, anon, authenticated;
grant execute on function public.redes_decidir(uuid, text, text, text) to service_role;

-- conferência pós-aplicação (esperado: false, false, false):
--   select has_table_privilege('anon','ic_redes_revisao','select'),
--          has_table_privilege('authenticated','ic_redes_revisao','select'),
--          has_function_privilege('anon','redes_conselho_registrar(text,text,text,text,text,text,text,text,text,jsonb,text,int)','execute');
