-- O DISPARO DO CONSULTOR DE REDES SAI DO AGENDADOR DO GITHUB E VAI PARA O PG_CRON DO BANCO (30/09/2026)
--
-- Medido em 30/09: dos 5 disparos de `publicar` das 08:10-12:10 BRT, o agendador do GitHub entregou 0; `metricas` (05:00)
-- e `conselho` 2ª rodada (06:00) rodaram com 6h30 de atraso. Em 29/09, 4 de ~13. CVO 30/09: "não pode depender de um
-- aviso, uma sessão, um PC" e "mais do que nunca, precisamos diversificar" (conta a 90% dos 2.000 min do mês).
--
-- Mesmos horários de antes, agora no pg_cron (UTC), que chama o workflow_dispatch do redes-consultor.yml com
-- origem=pg_cron (run-name ganha " [agendado]": o vigia e o passo de falha tratam como rodada automática).
--   * PORTEIRO NO BANCO: `publicar` só aciona o executor quando há peça 'aprovado', sem publicado_em, com data <= hoje
--     (mesma consulta do job porteiro). Dia sem peça devida = 0 minuto (antes: 10 runs/dia do porteiro).
--   * Credenciais: vault `github_pat_redes_dispatch` (PAT fine-grained: só Actions RW + Metadata R em
--     zarkatus/innconta-site + zarkatus/consultor-redes desde 02/10/2026, expira 29/09/2027) e `gitlab_trigger_redes` (trigger token do projeto 87183546 = zarkatus-mirror/consultor-redes desde 02/10/2026; antes 86647895: só dispara
--     pipeline). Cofre: github-pat-redes-dispatch.txt, gitlab-trigger-redes.txt (INVENTARIO.md).
--   * RESERVA AUTOMÁTICA NO GITLAB (escopo do .gitlab-ci.yml: publicar, conselho_diario, metricas): `redes_disparo_conferir`
--     (a cada 10 min) acompanha cada disparo em 3 fases, porque o pg_net é assíncrono:
--       1. resposta do dispatch: 204 = aceito; outro código ou sem resposta em 30 min = RECUSADO -> reserva;
--       2. o run subiu mesmo? (GET dos runs do workflow): `startup_failure`, ou `failure` em menos de 60 s (o GitHub
--          não sobe job com minutos esgotados/orçamento US$ 0: falha sem passo nenhum), ou nenhum run em 30 min -> reserva.
--          Falha de verdade (> 60 s) NÃO vai à reserva: o passo de falha do job já avisou e rodar de novo repetiria o erro;
--       3. resposta do trigger do GitLab: 201 = pipeline criado; 403 = CI do projeto desligado ou token revogado.
--     Um job que não subiu por minutos TRAVA o GitHub por 6 h para essas 3 tarefas: os disparos seguintes vão direto à
--     reserva (sem esperar 30 min por rodada). A reserva só entra DEPOIS de o run do GitHub terminar sem subir ou de não
--     aparecer em 30 min: nunca dois `publicar` ao mesmo tempo.
--   * 401/403 do GitHub = CREDENCIAL, nunca "GitHub caiu" (AOP-01c). Um e-mail por rodada do conferidor à central técnica,
--     com o que quebrou, o valor observado e a ação; tarefa mandada direto à reserva (GitHub travado) só gera e-mail se a
--     reserva também falhar.
-- Idempotente.

create table if not exists public.ic_redes_disparo (
  id bigserial primary key,
  quando timestamptz not null default now(),
  tarefa text not null,
  opcoes text not null default '',
  executor text not null default 'github',
  req_id bigint,
  status_http int,
  resposta text,
  conferido_em timestamptz,
  pulado text            -- motivo quando o banco decidiu NÃO disparar (ex.: nada a publicar)
);
alter table public.ic_redes_disparo add column if not exists req_runs bigint;          -- GET dos runs (fase 2)
alter table public.ic_redes_disparo add column if not exists run_id bigint;
alter table public.ic_redes_disparo add column if not exists run_conclusao text;
alter table public.ic_redes_disparo add column if not exists reserva_motivo text;      -- por que foi ao GitLab
alter table public.ic_redes_disparo add column if not exists reserva_req bigint;
alter table public.ic_redes_disparo add column if not exists reserva_em timestamptz;
alter table public.ic_redes_disparo add column if not exists reserva_status int;
alter table public.ic_redes_disparo add column if not exists reserva_resposta text;
alter table public.ic_redes_disparo add column if not exists teste boolean not null default false;
create index if not exists ic_redes_disparo_quando on public.ic_redes_disparo (quando desc);
alter table public.ic_redes_disparo enable row level security;  -- sem policy: só service_role/definer
comment on table public.ic_redes_disparo is
  'Cada disparo agendado do Consultor de redes feito pelo pg_cron (sql/redes-disparo-pg-cron.sql): resposta do GitHub, run, reserva no GitLab.';

-- tarefas que a reserva do GitLab sabe rodar (.gitlab-ci.yml, `case "$TAREFA"`)
create or replace function public.redes_tarefa_tem_reserva(p_tarefa text) returns boolean
language sql immutable as $$ select p_tarefa in ('publicar', 'conselho_diario', 'metricas', 'renovar_ig') $$;

create or replace function public.redes_disparo_gitlab(p_id bigint, p_motivo text)
returns bigint language plpgsql security definer set search_path to 'public' as $$
declare v_tok text; v_req bigint; v_tarefa text;
begin
  select tarefa into v_tarefa from public.ic_redes_disparo where id = p_id;
  select decrypted_secret into v_tok from vault.decrypted_secrets where name = 'gitlab_trigger_redes';
  if v_tok is null then
    update public.ic_redes_disparo set reserva_motivo = p_motivo, reserva_status = -1,
           reserva_resposta = 'vault gitlab_trigger_redes ausente' where id = p_id;
    return null;
  end if;
  select net.http_post(
    url := 'https://gitlab.com/api/v4/projects/87183546/trigger/pipeline',
    body := jsonb_build_object('token', v_tok, 'ref', 'main', 'variables', jsonb_build_object('TAREFA', v_tarefa)),
    headers := jsonb_build_object('Content-Type', 'application/json'),
    timeout_milliseconds := 20000) into v_req;
  update public.ic_redes_disparo set reserva_motivo = p_motivo, reserva_req = v_req, reserva_em = now() where id = p_id;
  return v_req;
end $$;

create or replace function public.redes_disparar(p_tarefa text, p_opcoes text default '')
returns jsonb language plpgsql security definer set search_path to 'public' as $$
declare v_pat text; v_req bigint; v_inputs jsonb; v_hoje date := (now() at time zone 'America/Sao_Paulo')::date; v_id bigint;
begin
  if p_tarefa = 'publicar' and not exists (
      select 1 from public.ic_redes_publicacao
       where status = 'aprovado' and publicado_em is null and data_publicacao <= v_hoje) then
    -- registro só da 1ª decisão do dia (não enche a tabela com 10 linhas "nada a publicar")
    if not exists (select 1 from public.ic_redes_disparo where tarefa = 'publicar' and pulado is not null
                    and (quando at time zone 'America/Sao_Paulo')::date = v_hoje) then
      insert into public.ic_redes_disparo (tarefa, opcoes, pulado) values (p_tarefa, p_opcoes, 'nada a publicar em ' || v_hoje);
    end if;
    return jsonb_build_object('ok', true, 'pulado', 'nada a publicar');
  end if;
  -- GitHub travado (um job não subiu nas últimas 6 h): tarefa com reserva vai direto ao GitLab
  if public.redes_tarefa_tem_reserva(p_tarefa) and exists (
      select 1 from public.ic_redes_disparo where not teste and reserva_motivo like 'job não subiu%'
         and quando > now() - interval '6 hours') then
    insert into public.ic_redes_disparo (tarefa, opcoes, executor, status_http, resposta)
    values (p_tarefa, p_opcoes, 'gitlab', 0, 'GitHub travado: direto na reserva') returning id into v_id;
    perform public.redes_disparo_gitlab(v_id, 'GitHub travado (job não subiu nas últimas 6 h): direto na reserva');
    return jsonb_build_object('ok', true, 'executor', 'gitlab', 'id', v_id);
  end if;
  select decrypted_secret into v_pat from vault.decrypted_secrets where name = 'github_pat_redes_dispatch';
  if v_pat is null then
    insert into public.ic_redes_disparo (tarefa, opcoes, status_http, resposta)
    values (p_tarefa, p_opcoes, -1, 'vault github_pat_redes_dispatch ausente');
    return jsonb_build_object('ok', false, 'erro', 'sem PAT no vault');
  end if;
  v_inputs := jsonb_build_object('tarefa', p_tarefa, 'origem', 'pg_cron');
  if coalesce(p_opcoes, '') <> '' then v_inputs := v_inputs || jsonb_build_object('vigia_opcoes', p_opcoes); end if;
  select net.http_post(
    url := 'https://api.github.com/repos/zarkatus/consultor-redes/actions/workflows/redes-consultor.yml/dispatches',
    body := jsonb_build_object('ref', 'main', 'inputs', v_inputs),
    headers := jsonb_build_object('Authorization', 'Bearer ' || v_pat, 'Accept', 'application/vnd.github+json',
                                  'User-Agent', 'innconta-redes-pgcron', 'Content-Type', 'application/json'),
    timeout_milliseconds := 20000) into v_req;
  insert into public.ic_redes_disparo (tarefa, opcoes, req_id) values (p_tarefa, p_opcoes, v_req);
  return jsonb_build_object('ok', true, 'req', v_req);
end $$;

create or replace function public.redes_disparo_conferir()
returns jsonb language plpgsql security definer set search_path to 'public' as $$
declare
  r record; v_resp record; v_pat text; v_req bigint; v_run jsonb; v_seg numeric; v_st int;
  v_titulo text; v_linha text; v_ruins text := ''; v_reserva text := ''; v_cred boolean := false;
  v_n int := 0; v_nres int := 0; v_envio bigint; v_assunto text;
begin
  for r in select * from public.ic_redes_disparo
            where conferido_em is null and pulado is null and quando > now() - interval '2 days' order by id loop
    v_linha := '<code>' || r.tarefa || coalesce(' ' || nullif(r.opcoes, ''), '') || '</code> de '
               || to_char(r.quando at time zone 'America/Sao_Paulo', 'DD/MM HH24:MI') || ' BRT';

    -- fase 3: já mandada à reserva -> resposta do trigger do GitLab
    if r.reserva_req is not null or r.reserva_status is not null then
      v_resp := null;
      if r.reserva_req is not null then
        select status_code, left(coalesce(content, error_msg, ''), 400) as txt into v_resp from net._http_response where id = r.reserva_req;
      end if;
      if v_resp is null and r.reserva_status is null and r.reserva_em > now() - interval '30 minutes' then
        continue;  -- resposta do trigger ainda não chegou
      end if;
      v_st := coalesce(v_resp.status_code, r.reserva_status, 0);
      update public.ic_redes_disparo set reserva_status = v_st, reserva_resposta = coalesce(v_resp.txt, reserva_resposta),
             conferido_em = now() where id = r.id;
      if v_st = 201 then
        -- rota direta (GitHub travado) é silenciosa; a 1ª ida à reserva avisa
        if r.executor = 'github' then
          v_nres := v_nres + 1;
          v_reserva := v_reserva || '<li>' || v_linha || ': ' || r.reserva_motivo || ' -> pipeline criado no GitLab ('
                       || coalesce(substring(v_resp.txt from '"web_url":"([^"]+)"'), 'sem link') || ')</li>';
        end if;
      else
        v_n := v_n + 1;
        v_ruins := v_ruins || '<li>' || v_linha || ': a RESERVA também falhou (GitLab HTTP ' || v_st || ' — '
                   || replace(replace(coalesce(v_resp.txt, r.reserva_resposta, 'sem resposta'), '<', '&lt;'), '>', '&gt;')
                   || '). 403 = CI do projeto desligado ou token revogado: <code>python redes/reserva_gitlab.py estado</code> '
                   || 'e <code>configurar</code>. Motivo da ida à reserva: ' || coalesce(r.reserva_motivo, '?') || '</li>';
      end if;
      continue;
    end if;

    -- fase 1: resposta do dispatch do GitHub
    if r.status_http is null then
      v_resp := null;
      if r.req_id is not null then
        select status_code, left(coalesce(content, error_msg, ''), 300) as txt into v_resp from net._http_response where id = r.req_id;
      end if;
      if v_resp is null and r.quando > now() - interval '30 minutes' then continue; end if;
      v_st := coalesce(v_resp.status_code, 0);
      update public.ic_redes_disparo set status_http = v_st,
             resposta = coalesce(v_resp.txt, 'sem resposta do GitHub em 30 min') where id = r.id;
      if v_st <> 204 then
        if v_st in (401, 403) then v_cred := true; end if;
        if public.redes_tarefa_tem_reserva(r.tarefa) then
          perform public.redes_disparo_gitlab(r.id, 'GitHub recusou o disparo (HTTP ' || v_st || ')');
        else
          v_n := v_n + 1;
          v_ruins := v_ruins || '<li>' || v_linha || ': GitHub recusou o disparo, HTTP ' || v_st || ' — '
                     || replace(replace(coalesce(v_resp.txt, 'sem resposta em 30 min'), '<', '&lt;'), '>', '&gt;')
                     || ' (tarefa sem reserva no GitLab: NÃO rodou)</li>';
          update public.ic_redes_disparo set conferido_em = now() where id = r.id;
        end if;
      end if;
      continue;
    end if;

    if r.status_http <> 204 then  -- recusado sem reserva e já anunciado (não deveria chegar aqui)
      update public.ic_redes_disparo set conferido_em = now() where id = r.id;
      continue;
    end if;

    -- fase 2: o run subiu mesmo?
    if r.quando > now() - interval '4 minutes' then continue; end if;
    if r.quando < now() - interval '3 hours' then  -- teto: run preso ou API sem resposta; o vigia vê o resto
      update public.ic_redes_disparo set conferido_em = now(), run_conclusao = coalesce(run_conclusao, 'nao_conferido_3h') where id = r.id;
      continue;
    end if;
    if r.req_runs is null or not exists (select 1 from net._http_response where id = r.req_runs) then
      if r.req_runs is null then
        select decrypted_secret into v_pat from vault.decrypted_secrets where name = 'github_pat_redes_dispatch';
        select net.http_get(
          url := 'https://api.github.com/repos/zarkatus/consultor-redes/actions/workflows/redes-consultor.yml/runs?event=workflow_dispatch&per_page=20&created=%3E%3D'
                 || to_char((r.quando - interval '2 minutes') at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
          headers := jsonb_build_object('Authorization', 'Bearer ' || v_pat, 'Accept', 'application/vnd.github+json',
                                        'User-Agent', 'innconta-redes-pgcron'),
          timeout_milliseconds := 20000) into v_req;
        update public.ic_redes_disparo set req_runs = v_req where id = r.id;
      end if;
      continue;
    end if;
    select status_code, content into v_resp from net._http_response where id = r.req_runs;
    update public.ic_redes_disparo set req_runs = null where id = r.id;  -- próxima rodada consulta de novo, se preciso
    if v_resp.status_code is distinct from 200 then continue; end if;  -- consulta de novo na próxima rodada
    v_titulo := 'Consultor de redes · ' || r.tarefa || ' [agendado]';
    select x into v_run from jsonb_array_elements(v_resp.content::jsonb -> 'workflow_runs') x
     where x ->> 'display_title' = v_titulo and (x ->> 'created_at')::timestamptz >= r.quando - interval '2 minutes'
     order by (x ->> 'created_at')::timestamptz limit 1;
    if v_run is null then
      if r.quando < now() - interval '30 minutes' then
        if public.redes_tarefa_tem_reserva(r.tarefa) then
          perform public.redes_disparo_gitlab(r.id, 'nenhum run do GitHub apareceu em 30 min');
        else
          v_n := v_n + 1;
          v_ruins := v_ruins || '<li>' || v_linha || ': dispatch aceito (204) mas nenhum run apareceu em 30 min (NÃO rodou)</li>';
          update public.ic_redes_disparo set conferido_em = now(), run_conclusao = 'sem_run' where id = r.id;
        end if;
      end if;
      continue;
    end if;
    update public.ic_redes_disparo set run_id = (v_run ->> 'id')::bigint where id = r.id;
    if v_run ->> 'status' <> 'completed' then continue; end if;
    v_seg := extract(epoch from ((v_run ->> 'updated_at')::timestamptz
                                 - coalesce((v_run ->> 'run_started_at')::timestamptz, (v_run ->> 'created_at')::timestamptz)));
    update public.ic_redes_disparo set run_conclusao = v_run ->> 'conclusion' where id = r.id;
    if (v_run ->> 'conclusion') = 'startup_failure' or ((v_run ->> 'conclusion') = 'failure' and v_seg < 60) then
      if public.redes_tarefa_tem_reserva(r.tarefa) then
        perform public.redes_disparo_gitlab(r.id, 'job não subiu no GitHub (' || (v_run ->> 'conclusion') || ' em '
                                                  || round(v_seg) || ' s: minutos esgotados/orçamento US$ 0?)');
      else
        v_n := v_n + 1;
        v_ruins := v_ruins || '<li>' || v_linha || ': o job não subiu no GitHub (' || (v_run ->> 'conclusion') || ' em '
                   || round(v_seg) || ' s; minutos esgotados?) e a tarefa não tem reserva: NÃO rodou. '
                   || coalesce(v_run ->> 'html_url', '') || '</li>';
        update public.ic_redes_disparo set conferido_em = now() where id = r.id;
      end if;
    else
      update public.ic_redes_disparo set conferido_em = now() where id = r.id;
    end if;
  end loop;

  if v_n > 0 or v_nres > 0 then
    v_assunto := case when v_cred then '[ALERTA] Consultor de redes · CREDENCIAL do disparo recusada'
                      when v_n > 0 then '[ALERTA] Consultor de redes · ' || v_n || ' tarefa(s) agendada(s) NÃO rodaram'
                      else 'Consultor de redes · GitHub falhou, ' || v_nres || ' tarefa(s) rodaram na reserva do GitLab' end;
    v_envio := public.ic_email('central@innconta.com.br', v_assunto,
      case when v_n > 0 then '<p><b>O que quebrou (não rodou):</b></p><ul>' || v_ruins || '</ul>' else '' end
      || case when v_nres > 0 then '<p><b>Mandadas à reserva do GitLab (rodando lá):</b></p><ul>' || v_reserva || '</ul>'
              || '<p>Enquanto um job não sobe no GitHub, publicar/conselho/métricas vão direto à reserva por 6 h.</p>' else '' end
      || '<p><b>Ação:</b> '
      || case when v_cred then '401/403 do GitHub é credencial, não queda: o PAT fine-grained <code>github_pat_redes_dispatch</code> '
              || '(vault do banco; cofre <code>github-pat-redes-dispatch.txt</code>) venceu ou foi revogado. Gerar outro com o '
              || 'MESMO escopo (Actions RW só em zarkatus/innconta-site e zarkatus/consultor-redes) e atualizar vault e cofre (PAR-01i). '
         else '' end
      || 'Tarefa que não rodou: <code>gh workflow run redes-consultor.yml -R zarkatus/consultor-redes -f tarefa=&lt;tarefa&gt;</code> '
      || 'ou <code>python redes/reserva_gitlab.py provar &lt;tarefa&gt;</code>. Registro em <code>ic_redes_disparo</code>.</p>');
    insert into public.ic_aviso_log (fone, marca, entregue, veredito, texto, canal)
    values ('', 'consultor-redes', v_envio is not null,
            jsonb_build_object('nao_rodou', v_n, 'reserva', v_nres, 'credencial', v_cred, 'envio', v_envio),
            v_n || ' tarefa(s) sem rodar, ' || v_nres || ' na reserva do GitLab; e-mail à central', 'redes_disparo');
  end if;
  return jsonb_build_object('ok', v_n = 0, 'nao_rodou', v_n, 'reserva', v_nres);
end $$;

revoke all on function public.redes_disparar(text, text) from public, anon, authenticated;
revoke all on function public.redes_disparo_conferir() from public, anon, authenticated;
revoke all on function public.redes_disparo_gitlab(bigint, text) from public, anon, authenticated;

-- os mesmos horários que viviam no `schedule:` do redes-consultor.yml (UTC)
do $$
declare j record;
begin
  for j in select * from (values
    ('redes_publicar',          '10 11-20 * * *', $q$select public.redes_disparar('publicar')$q$),
    ('redes_conselho',          '20 0 * * *',     $q$select public.redes_disparar('conselho_diario')$q$),
    ('redes_conselho_2',        '0 9 * * *',      $q$select public.redes_disparar('conselho_diario')$q$),
    ('redes_metricas',          '0 8 * * *',      $q$select public.redes_disparar('metricas')$q$),
    ('redes_vigia',             '40 20 * * *',    $q$select public.redes_disparar('vigia')$q$),
    ('redes_vigia_rapida_noite','45 0 * * *',     $q$select public.redes_disparar('vigia', '--rapida')$q$),
    ('redes_vigia_rapida_dia',  '40 15 * * *',    $q$select public.redes_disparar('vigia', '--rapida')$q$),
    ('redes_lote',              '30 10 * * 1',    $q$select public.redes_disparar('lote')$q$),
    ('redes_informe',           '0 11 * * 1',     $q$select public.redes_disparar('informe')$q$),
    ('redes_calendario',        '0 11 5 * *',     $q$select public.redes_disparar('calendario')$q$),
    ('redes_relatorio',         '0 10 1 * *',     $q$select public.redes_disparar('relatorio')$q$),
    ('redes_renovar_ig',        '0 9 10 * *',     $q$select public.redes_disparar('renovar_ig')$q$),
    ('redes_disparo_conferir',  '*/10 * * * *',   $q$select public.redes_disparo_conferir()$q$)
  ) as t(nome, quando, cmd) loop
    perform cron.unschedule(jobid) from cron.job where jobname = j.nome;
    perform cron.schedule(j.nome, j.quando, j.cmd);
  end loop;
end $$;
