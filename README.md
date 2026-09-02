# Fridivo backend — Moduli 1–3

Backend FastAPI modulare per autenticazione, household e catalogo prodotti locale.

## Avvio locale

1. Copiare `.env.example` in `.env` e sostituire credenziali e segreto JWT.
2. Avviare API e PostgreSQL:

   ```shell
   docker compose up --build
   ```

3. OpenAPI è disponibile su `http://localhost:8000/docs`.

L'interfaccia web mobile-first è disponibile su `http://localhost:8000/`. Per impostazione
predefinita usa le API sullo stesso host. Se il frontend viene pubblicato dietro un host
API differente, configurare `FRONTEND_API_BASE_URL` (senza slash finale).

La sessione dell'interfaccia viene conservata in `sessionStorage`: il token non viene
inserito nel codice, nei log o in storage persistente.

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

## Household inventory

Gli endpoint inventory sono protetti da JWT e operano sempre sull'household dell'utente:

- `POST /api/v1/inventory`;
- `GET /api/v1/inventory`;
- `PATCH /api/v1/inventory/{id}`;
- `DELETE /api/v1/inventory/{id}`.

Ogni prodotto può comparire una sola volta per household. Il catalogo viene consultato in sola lettura per validare il barcode e arricchire le risposte con nome, brand, formato e immagine.

## Interfaccia V1

Il frontend statico non richiede una build Node o dipendenze JavaScript. Offre login,
visualizzazione dispensa, ricerca nel catalogo, aggiunta manuale e scansione barcode
multipla. FastAPI serve i file statici e una piccola configurazione runtime; tutte le
operazioni sui dati passano dagli endpoint `/api/v1` esistenti.

Lo scanner usa `getUserMedia` e richiede HTTPS (eccetto `localhost`). Sfrutta la Barcode
Detection API nativa quando presente e usa la copia locale di ZXing Browser 0.2.1 (licenza
MIT in `frontend/vendor/ZXING-LICENSE.txt`) come fallback sugli altri browser moderni. Se il
permesso è negato, la fotocamera non è disponibile o il browser non è compatibile,
l'interfaccia mostra un messaggio dedicato e lascia disponibile la ricerca manuale. Le
scansioni restano nel frontend fino alla conferma: i prodotti nuovi usano
`POST /api/v1/inventory`, mentre quelli già presenti vengono incrementati con
`PATCH /api/v1/inventory/{id}`.
