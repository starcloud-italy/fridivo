# Fridivo backend — Moduli 1–2

Backend FastAPI modulare per autenticazione, household e catalogo prodotti locale.

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

## Catalogo prodotti

Gli endpoint, protetti da JWT Bearer, interrogano esclusivamente la tabella PostgreSQL locale:

- `GET /api/v1/products/barcode/{barcode}` — lookup GTIN/EAN/UPC esatto;
- `GET /api/v1/products/search?q=...&limit=20&offset=0` — ricerca testuale per nome;
- `GET /api/v1/products/{barcode}` — dettaglio prodotto.

Il catalogo è read-only per l'applicazione. L'adapter riconosce sia i nomi di colonna Open Food Facts (`code`, `product_name`) sia le varianti normalizzate (`barcode`, `name`).
