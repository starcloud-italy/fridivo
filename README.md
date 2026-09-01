# Fridivo backend — Modulo 1

Backend FastAPI modulare per autenticazione e household.

## Avvio locale

1. Copiare `.env.example` in `.env` e sostituire credenziali e segreto JWT.
2. Avviare API e PostgreSQL:

   ```shell
   docker compose up --build
   ```

3. OpenAPI è disponibile su `http://localhost:8000/docs`.

## Test isolati

La suite ignora `DATABASE_URL` e accetta esclusivamente `TEST_DATABASE_URL` con un nome database che termina in `_test`. Il servizio Docker usa inoltre un database PostgreSQL distinto, su `tmpfs`:

```shell
docker compose --profile test run --rm test
```

Per eseguire dal sistema host, avviare prima il database di test:

```shell
docker compose --profile test up -d db_test
pytest -v
```

## Migrazioni

```shell
alembic upgrade head
```

La revisione iniziale gestisce soltanto `users`, `households` e `household_members`. `alembic/env.py` esclude `products` e tutte le tabelle esterne riflesse dalle operazioni autogenerate.

