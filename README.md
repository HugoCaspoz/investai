# InvestAI

Asistente de alertas de inversion por Telegram orientado a descubrimiento de oportunidades, seguimiento de posiciones y validacion historica.

## Estado actual

Este repositorio ya incluye un scaffold funcional del MVP:

- API en FastAPI
- webhook base para Telegram
- Dockerfile listo para Cloud Run
- persistencia local con SQLite por defecto
- perfil de usuario inferido por semillas
- registro manual de posiciones
- ranking demo de discovery
- motor inicial de senales explicables
- endpoint interno para Cloud Scheduler (`/api/jobs/scan-demo`)

El objetivo no es tener un trader automatico, sino un asistente que descubra, vigile y explique.

## Estructura

```text
apps/
  api/
    main.py
    investai_api/
      api/
      services/
      models.py
      schemas.py
docs/
  investment-alert-assistant-blueprint.md
```

## Arranque rapido

1. Crea un entorno virtual.
2. Instala dependencias con `pip install -e .`
3. Copia `.env.example` a `.env`
4. Arranca la API con `uvicorn apps.api.main:app --reload`

Para Cloud Run:

1. Copia `env.cloudrun.yaml.example` a `env.cloudrun.yaml`
2. Rellena los valores reales
3. Ejecuta `gcloud run deploy ... --env-vars-file env.cloudrun.yaml`

Variables utiles:

- `DATABASE_URL`: por defecto `sqlite:///./investai.db`
  - Para Neon, si te dan `postgresql://...`, la app ahora lo adapta automaticamente a `postgresql+psycopg://...`
- `TELEGRAM_BOT_TOKEN`: necesario para enviar mensajes reales a Telegram
- `TELEGRAM_WEBHOOK_SECRET`: opcional para validar el webhook
- `INTERNAL_JOB_TOKEN`: protege el endpoint interno usado por Cloud Scheduler

## Endpoints principales

- `GET /api/health`
- `POST /api/profile/bootstrap`
- `GET /api/profile/by-chat/{telegram_chat_id}`
- `POST /api/positions`
- `GET /api/positions`
- `GET /api/catalog/demo-candidates`
- `POST /api/discovery/rank`
- `POST /api/signals/evaluate`
- `POST /api/jobs/scan-demo`
- `POST /webhooks/telegram`

## Comandos de Telegram disponibles en el MVP

- `/profile`
- `/seed BTC ETH PLTR OKLO`
- `/buy PLTR 21.5 qty=20 thesis="AI gov software"`
- `/portfolio`
- `/scan`
- `/why MSTR`
- `/alerts`

Tambien entiende frases como `he comprado PLTR a 21.5`.

## Siguiente capa recomendada

1. Sustituir el scanner demo por datos reales de Polygon, CoinGecko y SEC.
2. Anadir workers de ingestion y feature store.
3. Conectar el mismo motor al backtester event-driven.
4. Incorporar panel historico y shadow mode.

## Documento principal

La propuesta completa esta en [docs/investment-alert-assistant-blueprint.md](docs/investment-alert-assistant-blueprint.md).
