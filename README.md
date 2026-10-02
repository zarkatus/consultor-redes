# Consultor de Redes

Rotina automática que prepara, revisa (Conselho Editorial com IA gratuita), agenda e publica as peças de redes sociais das marcas do grupo (Instagram e LinkedIn), e vigia o próprio funcionamento.

- Código: este repositório (público). Dados (`kit/`, `estoque/`): repositório privado, lido pelo workflow com deploy key.
- Disparo: `workflow_dispatch` feito pelo `pg_cron` do banco (ver `sql/redes-disparo-pg-cron.sql`); não há `schedule` aqui.
- Log público: cada passo roda dentro de `redes/quieto.py`, que só imprime o código de saída; a saída vai por e-mail à central técnica quando falha.
- Como funciona e onde morde: `PLAYBOOK.md`.
