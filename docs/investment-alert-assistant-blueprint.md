# Blueprint: Asistente de Alertas de Inversion por Telegram

## 1. Que estamos construyendo

Un asistente de inversion que:

- descubre oportunidades nuevas sin depender de una watchlist cerrada
- vigila posiciones registradas manualmente
- envia alertas razonadas por Telegram
- explica cada senal con factores observables
- demuestra con backtesting si su logica habria funcionado historicamente

No es un bot de trading. No envia ordenes al broker. No compra ni vende.

## 2. Principios de diseno

1. Explainable first
   Cada alerta debe nacer de features y reglas observables, no solo de una opinion del modelo.
2. Backtest first
   La misma logica de scoring que produce alertas en vivo debe poder reproducirse historicamente.
3. Quality over quantity
   Mejor 2 alertas al dia que 20 alertas ruidosas.
4. Discovery, no solo seguimiento
   El sistema debe encontrar candidatos nuevos alineados con el perfil del usuario.
5. Point-in-time correctness
   Todos los datos usados en backtest deben respetar el momento real en que estaban disponibles.

## 3. Arquitectura recomendada

### 3.1 Vista de alto nivel

```text
Telegram
   |
   v
Bot Gateway / Webhook
   |
   v
Control API (perfil, cartera, comandos, consultas)
   |
   +--> PostgreSQL / TimescaleDB
   +--> Redis
   |
   +--> Scheduler / Workers
           |
           +--> Ingestion de mercado y eventos
           +--> Universe Builder
           +--> Feature Store
           +--> Signal Engine
           +--> Reasoning / Explanation Engine
           +--> Alert Router
           +--> Backtest Engine
           |
           +--> Streamlit Panel / API de analitica
```

### 3.2 Componentes

#### A. Bot Gateway

Responsabilidades:

- recibir mensajes de Telegram
- parsear comandos y lenguaje natural
- responder consultas rapidas
- disparar workflows asincronos

Recomendacion:

- webhook HTTP en produccion
- polling solo para desarrollo local

#### B. Control API

Responsabilidades:

- CRUD de perfil, semillas y posiciones
- estado de alertas
- consultas de backtest
- endpoints para panel web

Recomendacion:

- FastAPI
- autenticacion simple para panel interno

#### C. Ingestion Layer

Responsabilidades:

- descargar OHLCV, volumen, snapshots, referencia, noticias y eventos
- normalizar timestamps
- guardar datos crudos y derivados
- mantener universe point-in-time

Workers separados:

- `market-ingestor`
- `news-ingestor`
- `filings-ingestor`
- `reference-sync`

#### D. Universe Builder

Responsabilidades:

- construir el universo invertible real
- aplicar filtros de liquidez, capitalizacion, precio y calidad
- expandir automaticamente desde semillas del usuario

#### E. Feature Store

Responsabilidades:

- calcular features tecnicas, de riesgo, contexto y narrativa
- versionar features con `as_of_timestamp`
- servir las mismas features al motor live y al backtester

#### F. Signal Engine

Responsabilidades:

- generar scores de compra, venta, vigilancia y noticia critica
- separar candidatos prometedores de ruido
- registrar la foto exacta del razonamiento

#### G. Reasoning Engine

Responsabilidades:

- resumir noticias y filings
- clasificar impacto positivo, negativo o neutro
- convertir features estructuradas en explicaciones legibles

Regla clave:

- la IA redacta y clasifica
- la decision sale del scoring y de reglas observables

#### H. Alert Router

Responsabilidades:

- deduplicar alertas
- aplicar prioridad
- respetar limite maximo diario
- enviar mensajes a Telegram con formato consistente

#### I. Backtest Engine

Responsabilidades:

- reproducir la generacion historica de alertas
- simular ejecucion razonable
- calcular metricas
- comparar contra benchmarks

#### J. Panel web

Responsabilidades:

- configurar perfil y limites
- revisar cartera y alertas
- inspeccionar razones historicas
- ver resultados de backtesting

Recomendacion:

- MVP: Streamlit
- V2: panel dedicado si quieres multiusuario o UX mas pulida

## 4. Stack propuesto

### 4.1 Backend y datos

- FastAPI para API y webhook
- PostgreSQL + TimescaleDB para series temporales, posiciones y alertas
- Redis para colas, cache, locks y rate limiting
- Celery para jobs periodicos y backtests
- Parquet en disco u object storage para datasets historicos y features offline

### 4.2 Integraciones externas

- Telegram Bot API para comandos y notificaciones
- Polygon para acciones USA, reference data y noticias
- CoinGecko para cobertura amplia de cripto y categorias
- SEC EDGAR para filings y company facts
- Benzinga opcional para earnings/news/eventos premium
- OpenAI u otro LLM para resumen, clasificacion y explicacion estructurada

### 4.3 Por que esta combinacion es realista

- `Polygon` te da acciones USA, noticias y datos de referencia en una sola familia de APIs.
- `CoinGecko` da mucha mas amplitud en cripto y categorias que suelen ayudar al descubrimiento tematico.
- `SEC EDGAR` aporta filings y fundamentals oficiales gratis.
- `Benzinga` encaja como capa premium para earnings, guidance y catalizadores mas limpios.
- `Telegram` cubre muy bien el canal principal sin obligarte a construir una app movil.

## 5. Fuentes de datos y uso recomendado

| Capa | Fuente | Uso |
| --- | --- | --- |
| Acciones USA | Polygon | OHLCV, snapshots, tickers activos/inactivos, company overview, corporate actions, news |
| Cripto | CoinGecko | market cap, volumen, categorias, trending, historial, metadata |
| Filings | SEC EDGAR | 8-K, 10-Q, 10-K, company facts, timestamps oficiales |
| Earnings y eventos | Benzinga opcional | calendario de resultados, guidance, eventos estructurados |
| Macro opcional | FRED u otra fuente macro | regimen de tipos, liquidez y contexto |

## 6. Universo de activos: como evitar una watchlist cerrada

La solucion no debe escanear "solo BTC, ETH, SOL, TSLA, PLTR, COIN, OKLO, CRCL, LCID". Debe usarlos como semillas.

### 6.1 Construccion del universo

#### Equities

Universo inicial recomendado:

- acciones USA comunes (`type=CS`)
- sin OTC en MVP
- excluyendo warrants, rights, funds y ETFs en el scanner principal

Filtros por defecto:

- precio > 3 USD
- market cap > 300M USD
- ADTV en dolares > 10M USD
- spread y liquidez aceptables
- excluir activos con estructura de "penny stock basura"

#### Crypto

Universo inicial recomendado:

- top coins/tokens por market cap y volumen
- categorias relevantes para tu perfil: L1, infra cripto, exchanges, stablecoin infra, AI-crypto
- excluir tokens con liquidez insuficiente o mercados dudosos

Filtros por defecto:

- market cap > 500M USD
- volumen diario suficiente
- listado en exchanges de confianza

### 6.2 Expansion automatica desde semillas

El sistema debe transformar tus semillas en un vector de perfil:

- `BTC`, `ETH`, `SOL` -> crypto beta, L1s, infra cripto, narrativa Web3
- `COIN`, `CRCL` -> crypto infra, on/off ramps, stablecoins, fintech regulado
- `TSLA`, `LCID` -> EV, industrial growth, narrativa de adopcion
- `PLTR` -> software growth, AI, government/defense data stack
- `OKLO`, uranio/nuclear -> nuclear, energia, small-mid caps con catalizador

Ese vector se convierte en pesos tematicos:

- crypto
- crypto infra
- AI software
- growth de narrativa fuerte
- EV / movilidad electrica
- nuclear / uranio / energia
- small-mid caps de alto beta, pero liquidas

### 6.3 Como encontrar candidatos nuevos

Usa 4 caminos en paralelo:

1. Similaridad semantica
   Embeddings sobre descripcion de compania, negocio, tags y noticias recientes.
2. Similaridad estructural
   Sector, subindustria, market cap bucket, volatilidad, revenue exposure, correlacion tematica.
3. Event-driven discovery
   Earnings sorpresa, guidance, filings, nuevos contratos, aprobaciones, partnerships, emisiones, dilucion.
4. Price-action discovery
   Relative strength, breakout, pullback controlado, volumen anomalo, reaceleracion tras consolidacion.

Resultado:

- no dependes de una watchlist cerrada
- tampoco abres la puerta a miles de tickers basura

## 7. Diseno del perfil de usuario

### 7.1 Campos recomendados

- horizonte temporal: swing / position / multiweek
- sesgo: growth agresivo
- temas favoritos
- tolerancia al riesgo
- maximo de alertas por dia
- tipos de activo permitidos
- exclusion de activos iliquidos
- buckets preferidos por market cap
- buckets preferidos por volatilidad

### 7.2 Aprendizaje del perfil

El perfil no debe ser estatico. Debe ajustarse por:

- semillas iniciales
- compras registradas manualmente
- activos sobre los que pides mas info
- alertas que aceptas o descartas

Esto permite pasar de "me gustan PLTR y COIN" a "me interesan software de AI, crypto infra y growth con catalizador".

## 8. Modulo de cartera

### 8.1 Lo que debe guardar cada posicion

- ticker o asset_id
- fecha de entrada
- precio de entrada
- cantidad opcional
- tesis breve
- objetivo opcional
- stop opcional
- tema principal
- etiqueta de riesgo

### 8.2 Lo que debe vigilar

- rentabilidad vs entrada
- cambios en momentum
- ruptura de estructura
- deterioro de narrativa
- eventos negativos nuevos
- distancia a objetivo
- sobreextension despues de subida fuerte

## 9. Tipos de alertas

### 9.1 Tipos funcionales

- `compra`
- `venta`
- `vigilar`
- `noticia_critica`

### 9.2 Niveles de prioridad

- `informacion`
- `atencion`
- `accion_revision_urgente`

### 9.3 Reglas para no spamear

- cooldown por activo y tipo de senal
- enviar solo si cambia el estado o cruza un umbral nuevo
- maximo diario configurable
- ranking top-N por score final

## 10. Formato recomendado de alerta de Telegram

```text
[ATENCION] PLTR en zona interesante

Tipo: compra
Confianza: media-alta
Riesgo: alto
Bucket: AI / growth software

Resumen:
Correccion controlada dentro de tendencia, volumen estable y noticias recientes favorables.

Por que salta:
- Relative strength sigue por encima del grupo
- Retroceso hacia zona de soporte sin venta agresiva
- Catalizador reciente positivo mantiene la narrativa viva

Puntos en contra:
- Volatilidad alta
- Cercania a evento que puede aumentar el riesgo

Accion sugerida:
Revisar entrada escalonada, no perseguir si rompe demasiado arriba.
```

### 10.1 Formato para posicion abierta

```text
[REVISION] AAPL va +14.3% desde tu entrada en 210

Tipo: venta parcial / revisar
Confianza: media
Riesgo: medio

Resumen:
La posicion ha alcanzado una zona razonable de objetivo y el momentum empieza a perder fuerza.

Por que salta:
- Cumplimiento parcial de objetivo
- Divergencia de momentum
- Volumen vendedor creciente en las ultimas sesiones

Puntos a favor de mantener:
- Tendencia primaria aun intacta
- Sin noticia negativa estructural

Accion sugerida:
Considerar venta parcial o subida de stop de seguimiento.
```

## 11. Comandos de Telegram

### 11.1 Comandos base

- `/start`
- `/help`
- `/profile`
- `/prefs`
- `/portfolio`
- `/alerts`
- `/scan`
- `/why PLTR`
- `/watch BTC`
- `/unwatch BTC`

### 11.2 Comandos de cartera

- `/buy PLTR 21.50 qty=100 thesis="AI gov software"`
- `/sell PLTR 28.00 qty=50`
- `/position BTC 64250 qty=0.20 thesis="ciclo cripto"`
- `/target PLTR 30`
- `/stop PLTR 19.80`
- `/note OKLO "Catalizador nuclear y alta volatilidad"`

### 11.3 Lenguaje natural soportado

Ejemplos:

- "he comprado PLTR a 21.5"
- "anade BTC a cartera a 64250"
- "por que me has alertado de CRCL"
- "quiero menos alertas de small caps"

El parsing debe mezclar regex + LLM con salida estructurada. Nunca dependas solo de texto libre sin schema.

## 12. Logica del sistema de scoring

La mejor arquitectura es de dos etapas:

### 12.1 Etapa 1: candidate generation

Objetivo:

- reducir miles de activos a una lista pequena y manejable

Mecanismos:

- filtros de liquidez y calidad
- anomalas de precio/volumen
- noticias nuevas
- eventos y filings
- expansion por similitud a semillas

### 12.2 Etapa 2: deep scoring

Cada candidato recibe varios subscores.

#### Buy score

```text
buy_score =
  0.30 * technical_setup +
  0.25 * catalyst_score +
  0.15 * narrative_strength +
  0.15 * liquidity_quality +
  0.10 * profile_fit +
  0.05 * regime_alignment
```

#### Sell / review score

```text
sell_score =
  0.30 * technical_deterioration +
  0.25 * thesis_break_risk +
  0.20 * target_or_extension_score +
  0.15 * event_risk +
  0.10 * portfolio_concentration_risk
```

#### Confidence

No es lo mismo que el score. Se calcula por:

- acuerdo entre modulos
- frescura de datos
- claridad del evento
- consistencia multi-timeframe

#### Risk

Se calcula por:

- volatilidad
- market cap
- liquidez
- gap risk
- evento binario cercano
- fragilidad de narrativa

## 13. Features recomendadas

### 13.1 Tecnicas

- retornos 5d / 20d / 60d
- distancia a MM20 / MM50 / MM200
- relative strength vs benchmark y vs bucket tematico
- ATR
- drawdown desde maximos
- breakout / base / pullback classification
- volumen relativo y z-score

### 13.2 Fundamentales y de contexto

- market cap
- ADTV en dolares
- crecimiento de ingresos si existe
- sorpresa en earnings
- guidance beat/miss
- dilucion o emisiones
- insider/filings/eventos corporativos

### 13.3 Narrativa y noticias

- sentimiento agregado reciente
- novedad del catalizador
- persistencia narrativa del bucket
- fuerza del sector o tema
- impacto regulatorio

## 14. Explicabilidad: como evitar la "caja negra"

Cada alerta debe guardar un `signal_snapshot` con:

- timestamp
- universo y proveedor de datos
- features numericas relevantes
- subscores
- razones a favor
- razones en contra
- articulo o filing principal que actuo como catalizador
- plantilla de explicacion generada

Esto sirve para:

- auditoria
- depuracion
- backtest
- comparacion futura entre decision live y decision historica

### 14.1 Regla de producto

Si no puedes explicar una alerta con 3-5 razones concretas, no deberia enviarse.

## 15. Esquema de datos minimo

Tablas recomendadas:

- `users`
- `user_profiles`
- `profile_seeds`
- `assets`
- `asset_tags`
- `positions`
- `position_lots`
- `watch_items`
- `raw_bars`
- `raw_news_events`
- `raw_filings`
- `derived_features`
- `signal_snapshots`
- `alerts`
- `alert_deliveries`
- `backtest_runs`
- `backtest_signals`
- `backtest_trades`
- `benchmarks`

Campos importantes:

- `as_of_timestamp`
- `source_timestamp`
- `ingested_at`
- `data_vendor`
- `signal_version`
- `feature_version`

## 16. Frecuencia operativa recomendada

### 16.1 Live / near real time

- equities: cada 5 a 15 minutos intradia y barrido fuerte al cierre
- crypto: cada 5 minutos para majors y cada 15 minutos para resto
- noticias: continuo o cada 2-5 minutos
- filings SEC: continuo o cada pocos minutos

### 16.2 Jobs diarios

- refresh de universo
- recalculo de profile-fit
- ranking de temas
- limpieza y compaction de datos

## 17. MVP serio y util

### 17.1 Lo que construiria primero

1. Single-user
2. Telegram como interfaz principal
3. Perfil con semillas y preferencias
4. Registro manual de posiciones
5. Scanner sobre:
   - 500 a 1000 equities liquidas USA
   - 50 a 150 activos crypto liquidos
6. Senales `compra`, `vigilar`, `revision` y `noticia_critica`
7. Explicaciones estructuradas
8. Backtest sobre universo limitado pero point-in-time
9. Panel simple de resultados historicos

### 17.2 Lo que no meteria en MVP

- tiempo real full tick-by-tick
- multiusuario
- machine learning complejo para prediccion
- app movil propia
- demasiadas fuentes premium al principio
- cientos de features exoticas

### 17.3 Por que asi

El riesgo mayor no es tecnico. Es construir un sistema aparatoso que luego no genera alertas utiles. El MVP debe probar:

- que descubre candidatos interesantes
- que las alertas son accionables
- que el backtest no desmonta la tesis

## 18. Version 2

- mas proveedores premium
- transcripts y conference calls
- deteccion de cambios de guidance y tono de management
- alertas por narrativa sectorial
- panel web mas rico
- scoring adaptativo por regimen
- clustering automatico de themes
- feedback loop del usuario para recalibrar pesos

## 19. Backtesting: como hacerlo bien

### 19.1 Regla central

El backtester no debe "adivinar" el pasado con informacion futura. Debe vivir el tiempo como si estuviera en ese dia.

### 19.2 Motor recomendado

Backtester event-driven:

- avanza barra a barra y evento a evento
- recalcula features solo con datos disponibles hasta ese instante
- genera alertas historicas con la misma logica del sistema live
- simula ejecucion en la siguiente barra, siguiente apertura o delay configurado

### 19.3 Reglas de disponibilidad de datos

- precio y volumen: disponibles al cierre de cada barra o con delay definido
- noticias: disponibles a partir del `published_utc` real, no antes
- filings SEC: disponibles a partir de `acceptance datetime`
- company facts: solo cuando el filing que los contiene ya es publico
- earnings: usar la hora real del anuncio cuando exista

### 19.4 Como evitar errores tipicos

#### No lookahead bias

- todas las features deben tener `as_of_timestamp`
- nada de usar "ultimo dato anual" si aun no estaba publicado

#### No survivorship bias

- usa universe point-in-time
- incluye tickers delisted e inactivos

#### No overfitting

- muy pocos hiperparametros libres
- reglas robustas por buckets
- no optimizar veinte thresholds a la vez

#### Separar desarrollo y validacion

Ejemplo serio:

- entrenamiento/desarrollo: 2021-01-01 a 2023-12-31
- validacion: 2024-01-01 a 2024-12-31
- out-of-sample: 2025-01-01 a 2026-03-31

#### Walk-forward

- recalibrar pesos solo al cambiar de ventana
- probar que la estrategia aguanta distintos regimes

#### Costes y slippage

- equities liquidas: 10 a 35 bps segun bucket
- crypto majors: 5 a 20 bps
- crypto mid caps: 20 a 60 bps
- incluir fees del exchange/broker si son relevantes

## 20. Metricas que debe sacar el panel

- rentabilidad total
- rentabilidad anualizada
- max drawdown
- porcentaje de acierto
- profit factor
- ratio beneficio/riesgo
- numero de operaciones
- retorno medio por senal
- tiempo medio en posicion
- rendimiento por categoria
- rendimiento por tipo de alerta
- rendimiento por fuente de catalizador
- comparacion contra buy and hold
- comparacion contra benchmarks como SPY, QQQ, IWM, BTC, ETH

## 21. Preguntas que el backtest debe contestar

1. Si hubiera seguido solo las alertas de compra y revision, habria batido al buy and hold ajustado por riesgo?
2. El sistema gana por unos pocos outliers o por consistencia?
3. Funciona mejor en crypto, AI growth, EV o nuclear?
4. Funciona igual en mercados alcistas y bajistas?
5. El valor extra viene del discovery, del seguimiento de posiciones o de ambos?

## 22. Criterios para pasar a paper trading

Yo no pasaria a paper trading hasta cumplir estas condiciones:

- out-of-sample positivo y no marginal
- profit factor > 1.2 o 1.3 de forma consistente
- max drawdown asumible para tu perfil
- numero de operaciones suficiente para que la muestra valga
- rendimiento razonable tambien despues de costes
- alertas comprensibles y no espameadoras
- 1 a 3 meses de shadow mode live sin dinero real

## 23. Flujo de usuario recomendado

1. Configuras perfil y semillas
2. Registras posiciones manuales
3. El scanner corre de forma periodica
4. El motor detecta candidatos y riesgos en cartera
5. Solo las mejores alertas llegan a Telegram
6. Si una alerta te interesa, preguntas `/why`
7. Ejecutas backtests desde panel o comando
8. Revisas si discovery y exits son realmente utiles

## 24. Panel historico minimo

Vistas recomendadas:

- resumen general de rendimiento
- curva de capital
- drawdowns
- tabla de trades simulados
- tabla de alertas historicas
- breakdown por bucket tematico
- breakdown por activo
- comparacion contra benchmark
- inspeccion de una alerta concreta con sus razones

## 25. Repositorio recomendado

```text
investAI/
  apps/
    api/
    panel/
  services/
    bot/
    ingestion/
    universe/
    features/
    signals/
    alerts/
    backtest/
  shared/
    models/
    scoring/
    prompts/
  infra/
    docker/
  docs/
    investment-alert-assistant-blueprint.md
```

## 26. Recomendacion final de enfoque

Si tuviera que optimizar por utilidad real, construiria esto en este orden:

1. Perfil + semillas + posiciones manuales
2. Universo invertible serio y limpio
3. Discovery + scoring explicable
4. Alertas de Telegram con muy buen formato
5. Backtest event-driven con point-in-time data
6. Shadow mode
7. Solo despues, mejoras sofisticadas

La clave del producto no es "usar mucha IA". Es combinar:

- buenos datos
- universo limpio
- scoring explicable
- disciplina para no mirar el futuro
- alertas con contexto

## 27. Decisiones concretas que yo tomaria

- Telegram como canal principal desde el dia 1
- sin broker integration
- scanner amplio pero filtrado, no watchlist cerrada
- score hibrido reglas + IA para explicacion
- backtest usando la misma logica que live
- panel ligero en MVP
- thresholds conservadores para evitar ruido

## 28. Referencias consultadas

- Telegram Bot API: https://core.telegram.org/bots/api
- Polygon stocks overview/tickers/news: https://polygon.io/stocks , https://polygon.io/docs/stocks/get_v3_reference_tickers , https://polygon.io/docs/rest/stocks/news/
- Polygon y delisted tickers: https://polygon.io/knowledge-base/article/what-does-polygon-do-with-delisted-tickers
- CoinGecko API docs: https://docs.coingecko.com/
- SEC EDGAR API overview: https://www.sec.gov/file/api-overview
- Benzinga API overview y earnings: https://docs.benzinga.com/ , https://docs.benzinga.com/api-reference/calendar_api/earnings/returns-the-earnings-data
- OpenAI API overview y structured outputs: https://platform.openai.com/docs , https://platform.openai.com/docs/guides/structured-outputs/supported-types
