#!/usr/bin/env bash
# Abre o banco com a credencial do job ANTES de qualquer tarefa (03/10/2026: o secret SUPABASE_SERVICE_ROLE_KEY foi
# regravado inválido; por 15 h toda tarefa saiu "success" sem gravar nada, e o e-mail de falha à central usava a mesma
# chave). Distingue credencial recusada (401/403) de banco fora (AOP-01c). Nunca imprime a chave.
set -u
URL="${SB_URL:-${SUPABASE_URL:-}}"
KEY="${SB_SERVICE_ROLE:-${SB_SERVICE:-}}"
if [ -z "$URL" ] || [ -z "$KEY" ]; then
  echo "::error::credencial do banco ausente (SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY vazios no repo)"; exit 1
fi
CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${URL%/}/rest/v1/ic_redes_disparo?select=id&limit=1" \
       -H "apikey: $KEY" -H "Authorization: Bearer $KEY") || CODE=000
case "$CODE" in
  200) echo "credencial do banco: ok (HTTP 200)" ;;
  401|403) echo "::error::credencial do banco RECUSADA (HTTP $CODE): o secret SUPABASE_SERVICE_ROLE_KEY é inválido; não é queda do Supabase. Ação: regravar o secret com a service_role (legacy JWT) do projeto, testada antes (PLAYBOOK)."; exit 1 ;;
  *) echo "::error::banco indisponível (HTTP $CODE): Supabase fora ou rede; a credencial não foi julgada."; exit 1 ;;
esac
