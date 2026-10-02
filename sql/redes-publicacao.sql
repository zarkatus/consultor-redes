-- Consultor de Redes — tabela de registro + RPC de decisão atômica (aprovar/recusar/publicado).
-- Agnóstico de marca (PGA-01): chaveado por `marca`, nenhum nome de marca chumbado em função.
-- RLS ligada sem policy (nega tudo a anon/authenticated) + REVOKE explícito: só service_role
-- (Pages Function e GitHub Actions) fala com esta tabela — mesmo padrão de ic_termo_assinatura.

create table if not exists public.ic_redes_publicacao (
  id            uuid primary key default gen_random_uuid(),
  marca         text not null,
  canal         text not null,                 -- linkedin_pagina | instagram | perfil_roveda | youtube | x
  peca_id       text not null unique,           -- slug do estoque (idempotência: nunca duplica linha)
  tipo          text not null,                  -- 1 artigo→post | 2 a-cena | 4 carrossel | 5 pergunta-mesa | video
  formato       text,                           -- imagem_feed | imagem_stories | video | carrossel | texto
  mes_ref       text,                           -- 'AAAA-MM', ciclo do calendário editorial
  pilar         text,
  nota_origem   text,
  status        text not null default 'rascunho'
                check (status in ('rascunho','aguardando','aprovado','recusado','expirado','publicado')),
  motivo_recusa text,
  data_publicacao date,                         -- dia agendado pelo calendário editorial do mês
  calendario_status text default null           -- null | aguardando | aprovado | recusado | aguardando_api
                check (calendario_status is null or calendario_status in ('aguardando','aprovado','recusado','aguardando_api')),
  calendario_motivo text,
  calendario_enviado_em timestamptz,
  enviado_em    timestamptz,                    -- quando entrou em 'aguardando' (base da expiração de 7d)
  aprovado_por  text,
  aprovado_em   timestamptz,
  publicado_em  timestamptz,
  url_post      text,
  publicado_por text,
  kit_enviado_em timestamptz,                   -- quando o kit de 1 clique saiu ao Roveda
  lembrete_enviado_em timestamptz,               -- lembrete único de 48h sem confirmação
  criado_em     timestamptz not null default now()
);

alter table public.ic_redes_publicacao enable row level security;
revoke all on public.ic_redes_publicacao from anon, authenticated;

create index if not exists ic_redes_publicacao_marca_status_idx on public.ic_redes_publicacao (marca, status);
create index if not exists ic_redes_publicacao_mes_ref_idx on public.ic_redes_publicacao (marca, mes_ref);

-- ATENÇÃO (23/09/2026): a versão VIGENTE de redes_decidir está em sql/redes-conselho.sql (aceita
-- 'escalado' e a ação 'retirar'). Reaplicar SÓ este arquivo reverte a função — sempre reaplicar
-- sql/redes-conselho.sql logo depois (memória "sql-mesma-funcao-em-dois-arquivos").
-- redes_decidir: transição de estado atômica (SELECT ... FOR UPDATE) — é ISTO que faz o link de
-- aprovação ser de uso único na prática: a segunda chamada com o MESMO token válido encontra o
-- status já mudado e devolve 'ja_decidida', nunca reaplica a decisão.
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
    if r.status <> 'aguardando' then
      return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'status', r.status);
    end if;
    update ic_redes_publicacao set status = 'aprovado', aprovado_por = coalesce(p_por, 'cvo'), aprovado_em = now() where id = p_id;
    return jsonb_build_object('ok', true, 'status', 'aprovado');

  elsif p_acao = 'recusar' then
    if r.status <> 'aguardando' then
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

  else
    return jsonb_build_object('ok', false, 'motivo', 'acao_invalida');
  end if;
end;
$$;
revoke all on function public.redes_decidir(uuid, text, text, text) from public, anon, authenticated;
grant execute on function public.redes_decidir(uuid, text, text, text) to service_role;

-- redes_enviar_lote: registra/atualiza uma peça como 'aguardando' (idempotente por peca_id) —
-- chamado pelo lote_aprovacao.py antes de mandar o e-mail. Upsert por peca_id nunca duplica linha
-- nem reabre decisão já tomada (se já não está em rascunho/aguardando, não mexe).
create or replace function public.redes_enviar_lote(
  p_marca text, p_canal text, p_peca_id text, p_tipo text, p_formato text,
  p_mes_ref text, p_pilar text, p_nota_origem text
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  select * into r from ic_redes_publicacao where peca_id = p_peca_id;
  if not found then
    insert into ic_redes_publicacao (marca, canal, peca_id, tipo, formato, mes_ref, pilar, nota_origem, status, enviado_em)
    values (p_marca, p_canal, p_peca_id, p_tipo, p_formato, p_mes_ref, p_pilar, p_nota_origem, 'aguardando', now());
    return jsonb_build_object('ok', true, 'novo', true);
  end if;
  if r.status not in ('rascunho', 'aguardando') then
    return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'status', r.status);
  end if;
  update ic_redes_publicacao set status = 'aguardando', enviado_em = now() where peca_id = p_peca_id;
  return jsonb_build_object('ok', true, 'novo', false);
end;
$$;
revoke all on function public.redes_enviar_lote(text, text, text, text, text, text, text, text) from public, anon, authenticated;
grant execute on function public.redes_enviar_lote(text, text, text, text, text, text, text, text) to service_role;

-- redes_calendario_decidir: aprovação item-a-item do CALENDÁRIO EDITORIAL DO MÊS (gate distinto
-- da aprovação de CONTEÚDO — uma peça pode ter conteúdo 'aprovado' e calendário ainda
-- 'aguardando'; recusar aqui NUNCA descarta o conteúdo, só desmarca a data agendada).
create or replace function public.redes_calendario_decidir(p_id uuid, p_acao text, p_motivo text default null)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  select * into r from ic_redes_publicacao where id = p_id for update;
  if not found then
    return jsonb_build_object('ok', false, 'motivo', 'nao_encontrada');
  end if;
  if r.calendario_status <> 'aguardando' then
    return jsonb_build_object('ok', false, 'motivo', 'ja_decidida', 'calendario_status', r.calendario_status);
  end if;
  if p_acao = 'aprovar' then
    update ic_redes_publicacao set calendario_status = 'aprovado' where id = p_id;
    return jsonb_build_object('ok', true, 'calendario_status', 'aprovado');
  elsif p_acao = 'recusar' then
    update ic_redes_publicacao set calendario_status = 'recusado', calendario_motivo = p_motivo, data_publicacao = null where id = p_id;
    return jsonb_build_object('ok', true, 'calendario_status', 'recusado');
  else
    return jsonb_build_object('ok', false, 'motivo', 'acao_invalida');
  end if;
end;
$$;
revoke all on function public.redes_calendario_decidir(uuid, text, text) from public, anon, authenticated;
grant execute on function public.redes_calendario_decidir(uuid, text, text) to service_role;

-- redes_expirar_vencidas: peças 'aguardando' há mais de 7 dias viram 'expirado' — chamado no
-- início de cada rodada do lote semanal, antes de montar o e-mail novo.
create or replace function public.redes_expirar_vencidas() returns int
language sql security definer set search_path = public as $$
  with u as (
    update ic_redes_publicacao set status = 'expirado'
     where status = 'aguardando' and enviado_em < now() - interval '7 days'
    returning 1
  )
  select count(*)::int from u;
$$;
revoke all on function public.redes_expirar_vencidas() from public, anon, authenticated;
grant execute on function public.redes_expirar_vencidas() to service_role;

-- 23/09/2026 (informe comercial + publicação automática pelo consultor, diretriz do CVO —
-- Roveda é Diretor Comercial, recebe informe, não publica): calendario_status ganha o valor
-- 'aguardando_api' — peça aprovada, data batida, mas sem conector de publicação para aquele
-- canal ainda (Instagram sem API, ou LinkedIn sem `ic_segredo.linkedin_token`). ALTER
-- idempotente: reaplicar este arquivo num banco que já tinha a constraint antiga (sem este
-- valor) corrige a constraint; num banco novo, o `create table` acima já nasce com o valor
-- certo e este bloco é um no-op silencioso (dropa e recria a mesma constraint).
alter table public.ic_redes_publicacao drop constraint if exists ic_redes_publicacao_calendario_status_check;
alter table public.ic_redes_publicacao add constraint ic_redes_publicacao_calendario_status_check
  check (calendario_status is null or calendario_status in ('aguardando','aprovado','recusado','aguardando_api'));

-- checagem de permissão de objeto novo (PLAYBOOK §"Permissão de objeto novo"), rodar após aplicar:
--   select has_table_privilege('anon', 'ic_redes_publicacao', 'select');       -- esperado: false
--   select has_table_privilege('authenticated', 'ic_redes_publicacao', 'select'); -- esperado: false
--   select has_function_privilege('anon', 'redes_decidir(uuid,text,text,text)', 'execute'); -- false
