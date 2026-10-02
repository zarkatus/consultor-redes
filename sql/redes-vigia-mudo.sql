-- QUEM VIGIA O VIGIA DAS REDES (30/09/2026, CVO: consultores autônomos, "pra que a gente não tenha que ficar lembrando").
--
-- O vigia diário do Consultor de Redes (redes/vigia.py, job `vigia` do redes-consultor.yml, 20:40 UTC) roda no
-- agendador do GitHub Actions, que ATRASA e PULA disparos (medido em 29/09: 4 de ~13 disparos do dia rodaram). Se o
-- próprio vigia for pulado, nada avisa. Este dead-man roda FORA do GitHub (pg_cron do banco): todo dia 12:00 UTC
-- (09:00 BRT) confere se há registro do vigia (`ic_aviso_log.canal = 'redes_vigia'`) nas últimas 30 h; se não houver,
-- manda UM e-mail à central técnica (AOP-01: nunca caixa pessoal, nunca WhatsApp) com o valor observado e a ação.
-- Uma vez por dia no máximo (trava: registro `redes_vigia_mudo` nas últimas 20 h).
-- Healthchecks não serviu: a conta está no teto de 20 checks do plano gratuito (POST /api/v3/checks -> 403, 30/09).
-- Idempotente.

create or replace function public.redes_vigia_mudo()
returns jsonb language plpgsql security definer set search_path to 'public' as $$
declare v_ultimo timestamptz; v_horas numeric; v_envio bigint;
begin
  select max(quando) into v_ultimo from public.ic_aviso_log where canal = 'redes_vigia';
  if v_ultimo is not null and v_ultimo > now() - interval '30 hours' then
    return jsonb_build_object('ok', true, 'ultimo', v_ultimo);
  end if;
  if exists (select 1 from public.ic_aviso_log where canal = 'redes_vigia_mudo' and quando > now() - interval '20 hours') then
    return jsonb_build_object('ok', false, 'ja_avisado', true, 'ultimo', v_ultimo);
  end if;
  v_horas := round(extract(epoch from (now() - coalesce(v_ultimo, now() - interval '999 hours'))) / 3600.0, 1);
  v_envio := public.ic_email('central@innconta.com.br',
    'Consultor de Redes · o VIGIA diário não rodou (' || coalesce(v_horas::text, '?') || ' h sem registro)',
    '<p>O vigia diário do Consultor de Redes não deixou registro em <code>ic_aviso_log</code> (canal '
    || '<code>redes_vigia</code>) nas últimas 30 h.</p><p><b>Valor observado:</b> último registro em '
    || coalesce(to_char(v_ultimo at time zone 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI'), 'nunca') || ' (BRT), há '
    || coalesce(v_horas::text, '?') || ' h.</p><p><b>Ação:</b> abrir o GitHub Actions do consultor-redes, workflow '
    || '"Consultor de redes": se não há run "vigia" desde então, o agendador do GitHub pulou o disparo; rodar à mão '
    || '(<code>gh workflow run redes-consultor.yml -R zarkatus/consultor-redes -f tarefa=vigia</code>). Se há run vermelho, '
    || 'ler o log do passo "Vigiar".</p>');
  insert into public.ic_aviso_log (fone, marca, entregue, veredito, texto, canal)
  values ('', 'consultor-redes', v_envio is not null,
          jsonb_build_object('ultimo_vigia', v_ultimo, 'horas', v_horas, 'envio', v_envio),
          'vigia das redes mudo há ' || coalesce(v_horas::text, '?') || ' h; e-mail à central', 'redes_vigia_mudo');
  return jsonb_build_object('ok', false, 'avisado', true, 'ultimo', v_ultimo, 'horas', v_horas);
end $$;

comment on function public.redes_vigia_mudo() is
  'Dead-man do vigia das redes (redes/vigia.py): sem registro redes_vigia em 30 h, avisa a central. Uma vez por dia.';

revoke all on function public.redes_vigia_mudo() from public, anon, authenticated;

select cron.unschedule('redes_vigia_mudo')
 where exists (select 1 from cron.job where jobname = 'redes_vigia_mudo');
select cron.schedule('redes_vigia_mudo', '0 12 * * *', $$select public.redes_vigia_mudo();$$);
