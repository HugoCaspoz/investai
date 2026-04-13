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
- scanner live-first con CoinGecko para cripto
- motor inicial de senales explicables con recomendaciones de compra y venta/revision
- endpoint interno para Cloud Scheduler (`/api/jobs/scan`)

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
- `COINGECKO_API_KEY`: opcional; si no existe, se usa la API publica de CoinGecko
- `COINGECKO_API_PLAN`: `demo` por defecto; usa `pro` si tu clave es del plan Pro de CoinGecko
- `TWELVEDATA_API_KEY`: recomendado como proveedor gratuito inicial para acciones USA
- `TWELVEDATA_SCAN_LIMIT`: `8` por defecto para respetar mejor el free tier de Twelve Data
- `POLYGON_API_KEY`: proveedor alternativo de equities; en muchos planes gratuitos no permite snapshot de acciones
- `INTERNAL_JOB_TOKEN`: protege el endpoint interno usado por Cloud Scheduler

## Endpoints principales

- `GET /api/health`
- `POST /api/profile/bootstrap`
- `GET /api/profile/by-chat/{telegram_chat_id}`
- `POST /api/positions`
- `POST /api/positions/close`
- `GET /api/positions`
- `GET /api/catalog/demo-candidates`
- `POST /api/discovery/rank`
- `POST /api/signals/evaluate`
- `GET /api/diagnostics/live`
- `GET /api/analytics/signals`
- `POST /api/jobs/scan`
- `POST /api/jobs/scan-demo` (compatibilidad con el endpoint anterior)
- `POST /webhooks/telegram`

## Comandos de Telegram disponibles en el MVP

- `/profile`
- `/seed BTC ETH PLTR OKLO`
- `/buy PLTR 21.5 qty=20 thesis="AI gov software"`
- `/close PLTR 30 note="salida manual"`
- `/portfolio`
- `/scan`
- `/analyze BTC`
- `/stats`
- `/alerts`

Tambien entiende frases como `he comprado PLTR a 21.5`, `he vendido PLTR a 30` o `analiza PLTR`.

## Comportamiento actual de recomendaciones

- Discovery: envia oportunidades nuevas como `compra potencial manual` o `vigilar`, con datos live de CoinGecko para cripto y Twelve Data o Polygon para acciones.
- Cartera: si registras una compra manual, el job puede enviarte `revisar venta o reducir manualmente` o `revision urgente manual` cuando detecta deterioro, objetivo alcanzado o sobreextension.
- Historico real: cada alerta de compra enviada se mide de dos formas:
  una a horizonte fijo para tener una lectura live-forward comparable,
  y otra como `paper trade` del bot, que se cierra cuando el sistema detecta una salida razonable.
- Ejecucion: no ejecuta operaciones; solo analiza y te manda alertas razonadas por Telegram para que decidas tu.

## Nota sobre acciones en plan gratuito

- Twelve Data encaja mejor como proveedor gratuito inicial para equities USA, pero su free tier tiene limite de creditos por minuto.
- Por eso el scanner rota automaticamente por bloques pequenos de simbolos en cada barrido cuando usa Twelve Data.
- Polygon puede mantenerse como proveedor secundario, pero segun el plan puede devolver `403` en endpoints de snapshot.

## Siguiente capa recomendada

1. Ampliar el scanner real a equities con Polygon y eventos SEC.
2. Anadir workers de ingestion y feature store.
3. Conectar el mismo motor al backtester event-driven.
4. Incorporar panel historico y shadow mode.

## Documento principal

La propuesta completa esta en [docs/investment-alert-assistant-blueprint.md](docs/investment-alert-assistant-blueprint.md).
