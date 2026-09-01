# Fridivo — Project Rules

## Product

Fridivo è un assistente intelligente per ottimizzare la spesa e i consumi alimentari domestici.

Obiettivi principali:
- aiutare l'utente a comprare meglio;
- ridurre la spesa alimentare;
- ridurre gli sprechi;
- suggerire cosa consumare e cosa acquistare;
- apprendere progressivamente le abitudini di consumo.

Principio:
ENTRA → CONSUMA → CONSIGLIA

Fridivo deve far risparmiare all'utente più tempo di quanto ne richieda l'utilizzo.

## Development approach

Sviluppare Fridivo modulo per modulo.

Ogni modulo deve:
1. avere responsabilità chiare;
2. essere completato prima di iniziare il successivo;
3. includere test automatici;
4. non anticipare funzionalità appartenenti a moduli futuri;
5. mantenere compatibilità con i moduli già completati.

Non procedere autonomamente al modulo successivo.

## Stack

Backend:
- Python
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x
- Pydantic v2
- Alembic
- pytest

Infrastructure:
- Docker
- Docker Compose
- Nginx in produzione

AI provider:
- OpenAI

V1:
- responsive web application / PWA
- mobile-first
- nessuna app nativa iniziale

## Backend architecture

Mantenere il backend modulare.

Separare quando appropriato:
- models
- schemas
- routers
- services
- db
- core

Non concentrare la business logic in `main.py`.

Usare `/api/v1/` per gli endpoint applicativi.

## Database

PostgreSQL è la fonte dei dati certi dell'applicazione.

Esiste una tabella `products` contenente il catalogo locale importato da Open Food Facts.

Il database di produzione contiene milioni di prodotti.

IMPORTANTE:
- non eliminare `products`;
- non ricreare `products`;
- non modificare distruttivamente `products`;
- non svuotare `products`;
- le migrazioni Alembic dell'applicazione devono preservarla.

I test devono utilizzare un database separato.

Il database di test deve avere un nome che termina con `_test`.

I test non devono poter modificare il database di produzione.

## Product catalog

Il catalogo Open Food Facts è locale in PostgreSQL.

Per le normali ricerche prodotto utilizzare il database locale.

Non effettuare chiamate live a Open Food Facts salvo futura decisione esplicita.

Il barcode/EAN/GTIN è memorizzato come testo e non deve essere convertito in numero.

## Household model

L'inventario appartiene all'household, non direttamente all'utente.

Un household può rappresentare:
- una persona;
- una coppia;
- una famiglia;
- più membri autorizzati.

Il Modulo 1 ha già implementato:
- autenticazione;
- User;
- Household;
- HouseholdMember;
- JWT Bearer;
- password Argon2.

Preservare il comportamento e i test esistenti.

## Europe-ready

Fridivo nasce Italy-first ma deve essere Europe-ready.

Non hardcodare inutilmente:
- Italia;
- italiano;
- EUR;
- timezone italiana.

Utilizzare dove necessario:
- country_code;
- language_code;
- currency_code;
- timezone.

L'interfaccia dovrà supportare più lingue.

## Security

- Nessun secret nel repository.
- Usare `.env` per i secret.
- `.env` deve restare escluso da Git.
- `.env.example` deve contenere solo placeholder.
- Validare gli input.
- Non esporre password hash.
- Proteggere gli endpoint privati.

## AI

L'AI non è la fonte autorevole dell'inventario.

Principio:

DATI CERTI → ALGORITMI → AI

PostgreSQL conserva:
- prodotti;
- inventario;
- eventi;
- storico;
- dati utente.

OpenAI può essere utilizzato successivamente per:
- riconoscimento immagini;
- interpretazione voce/testo;
- suggerimenti;
- analisi delle abitudini;
- ottimizzazione della spesa.

Le funzionalità AI appartengono a Fridivo+ e non devono essere introdotte nei moduli precedenti senza richiesta esplicita.

## Commercial model

Fridivo Free:
- gestione e controllo;
- nessuna AI.

Fridivo+:
- AI;
- automazione;
- analisi;
- suggerimenti personalizzati;
- ottimizzazione avanzata.

Non introdurre artificialmente limiti database nel piano Free senza una decisione esplicita.

## Current module sequence

1. Authentication + Household — COMPLETATO
2. Product Catalog + Barcode Lookup
3. Household Inventory
4. Inventory Events
5. Shopping List
6. Responsive UI
7. Voice / Images with OpenAI
8. Intelligent Suggestions
9. Promotions / Flyers

L'ordine può essere modificato solo su richiesta.

## General rule

Quando una richiesta riguarda un modulo specifico:
- implementare soltanto quel modulo;
- eseguire i test;
- correggere eventuali regressioni;
- riportare file modificati, endpoint, migrazioni e risultati dei test;
- fermarsi al termine del modulo.