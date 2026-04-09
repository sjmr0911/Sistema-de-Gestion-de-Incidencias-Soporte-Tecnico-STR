# STR — Gestión de Incidencias de Soporte Técnico

> **Soft Real-Time System** para la recepción, clasificación y procesamiento concurrente de incidencias de soporte técnico. Implementado con FastAPI, `asyncio`, cola de prioridad, semáforo de concurrencia, control de tasa, deadline enforcement y métricas de latencia desglosadas.

---

## Índice

1. [Tipo de sistema](#tipo-de-sistema)
2. [Descripción general](#descripción-general)
3. [Arquitectura del sistema](#arquitectura-del-sistema)
4. [Planificador (Scheduler)](#planificador-scheduler)
5. [Restricciones temporales](#restricciones-temporales)
6. [Gestión de recursos críticos — Semáforo](#gestión-de-recursos-críticos--semáforo)
7. [Modelo de ejecución](#modelo-de-ejecución)
8. [Determinismo y comportamiento temporal](#determinismo-y-comportamiento-temporal)
9. [Funcionalidades principales](#funcionalidades-principales)
10. [Tecnologías utilizadas](#tecnologías-utilizadas)
11. [Requisitos del sistema](#requisitos-del-sistema)
12. [Ejecución local paso a paso](#ejecución-local-paso-a-paso)
13. [Ejecución con Docker](#ejecución-con-docker)
14. [Estructura del proyecto](#estructura-del-proyecto)
15. [Descripción de archivos principales](#descripción-de-archivos-principales)
16. [Archivos de configuración](#archivos-de-configuración)
17. [Endpoints del sistema](#endpoints-del-sistema)
18. [Conceptos del curso aplicados](#conceptos-del-curso-aplicados)
19. [Buenas prácticas implementadas](#buenas-prácticas-implementadas)
20. [Validación del sistema](#validación-del-sistema)
21. [Limitaciones del sistema](#limitaciones-del-sistema)
22. [Recomendaciones de entrega](#recomendaciones-de-entrega)
23. [Conclusión](#conclusión)

---

## Tipo de sistema

Este proyecto es un **Soft Real-Time System (STR Blando)**.

En un sistema de tiempo real blando, el incumplimiento de un deadline degrada la calidad del servicio pero **no produce un fallo catastrófico**. A diferencia de un sistema de tiempo real duro (hard real-time), donde una violación de deadline puede ser inaceptable, en este sistema:

- Las incidencias que superan el deadline de **50 ms** son registradas como violaciones y contabilizadas en métricas.
- El sistema continúa operando normalmente tras una violación.
- La degradación es observable (métricas, logs de errores), pero no crítica para la integridad del sistema.

Este modelo es apropiado para entornos de soporte técnico (NOC/helpdesk) donde la respuesta oportuna es deseable pero una demora no compromete la seguridad del sistema completo.

---

## Descripción general

El **STR — Sistema de Gestión de Incidencias de Soporte Técnico** es una aplicación web que modela un sistema de tiempo real para la gestión de incidencias en un entorno de soporte técnico. El sistema:

- Recibe incidencias mediante API REST con validación estricta de entrada.
- Las encola en una `asyncio.PriorityQueue` con backlog limitado a 100 items.
- Las procesa concurrentemente mediante un **pool de 3 workers** asíncronos independientes.
- Aplica restricciones temporales: intervalo mínimo entre eventos, deadline de procesamiento y retardo máximo en cola.
- Controla la concurrencia de incidencias críticas con un `asyncio.Semaphore`.
- Expone métricas de latencia desglosadas (tiempo en cola, tiempo de procesamiento, tiempo total) a través de un dashboard web con auto-refresh.

---

## Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────┐
│                   CLIENTE (Frontend)                    │
│  HTML + CSS + JavaScript (Vanilla)                      │
│  - Formulario de registro de incidencias                │
│  - Dashboard con auto-refresh (polling cada 2-3 s)      │
│  - Panel de métricas STR y estado del semáforo          │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / REST (fetch API)
┌────────────────────────▼────────────────────────────────┐
│                  SERVIDOR (FastAPI / Uvicorn)            │
│  - Validación de entrada (Pydantic v2)                  │
│  - Control de tasa (MIN_INTERVAL = 10 ms)               │
│  - Control de backlog (QUEUE_MAXSIZE = 100)             │
│  - Endpoints REST documentados con Swagger              │
└────────────────────────┬────────────────────────────────┘
                         │ asyncio.PriorityQueue (shared)
┌────────────────────────▼────────────────────────────────┐
│           MOTOR DE PROCESAMIENTO (Scheduler)            │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │             │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘             │
│       │              │              │                   │
│       └──────────────┴──────────────┘                  │
│              asyncio.Semaphore (críticas)               │
│                                                         │
│  - Deadline enforcement (50 ms)                         │
│  - Start delay control (20 ms)                          │
│  - Métricas desglosadas por fase                        │
└────────────────────────┬────────────────────────────────┘
                         │ aiosqlite (async)
┌────────────────────────▼────────────────────────────────┐
│                BASE DE DATOS (SQLite)                   │
│  - Tabla incidents: incidencias procesadas              │
│  - Tabla errors: violaciones y errores del STR          │
└─────────────────────────────────────────────────────────┘
```

**Flujo de una incidencia:**

1. El cliente envía `POST /incidents`.
2. FastAPI valida la entrada con Pydantic y verifica restricciones de tasa y backlog.
3. Se asigna un `trace_id` temporal (UUID corto) y se encola con prioridad negativa.
4. Uno de los 3 workers extrae la incidencia (por prioridad) y mide el retardo en cola.
5. Si es crítica (severity=4), el worker adquiere el semáforo antes de procesar.
6. Se determina la acción (`control_action_async`), se persiste en BD y se miden tiempos.
7. Las métricas se actualizan de forma thread-safe con `asyncio.Lock`.

---

## Planificador (Scheduler)

**Tipo:** Event-driven, priority-based, non-preemptive.

El scheduler de este sistema es un **pool de workers concurrentes** que consumen de una cola de prioridad compartida:

- **Event-driven:** los workers bloquean en `await QUEUE.get()` y se activan únicamente cuando llega una incidencia. No hay polling activo.
- **Priority-based:** la `asyncio.PriorityQueue` ordena las incidencias por severidad negativa (`-severity`). Una incidencia crítica (4) siempre es extraída antes que una alta (3), media (2) o baja (1), independientemente del orden de llegada.
- **Non-preemptive:** una vez que un worker comienza a procesar una incidencia, no puede ser interrumpido por otra de mayor prioridad. La prioridad solo actúa en el momento de extracción de la cola.
- **Concurrente:** 3 workers operan en paralelo dentro del mismo event loop de asyncio. Pueden procesar hasta 3 incidencias simultáneamente (limitado a 2 críticas por el semáforo).

```python
# Ejemplo: encolado con prioridad invertida
await QUEUE.put((-severity, timestamp, incident))
# severity=4 → prioridad=-4 (extraída primero)
# severity=1 → prioridad=-1 (extraída última)
```

---

## Restricciones temporales

Las restricciones temporales son el núcleo del comportamiento STR del sistema. Están definidas como constantes en `scheduler.py` y se verifican en cada ciclo de procesamiento.

| Constante | Valor | Descripción |
|-----------|-------|-------------|
| `MIN_INTERVAL` | 10 ms | Separación mínima entre eventos consecutivos. Rechaza con HTTP 429 si se viola. |
| `MAX_START_DELAY` | 20 ms | Retardo máximo permitido en cola antes de iniciar el procesamiento. Se registra como error SCHEDULER si se supera. |
| `DEADLINE_MS` | 50 ms | Tiempo máximo total desde encolado hasta fin de procesamiento. Se registra como error DEADLINE si se supera. |
| `QUEUE_MAXSIZE` | 100 | Backlog máximo de la cola. Rechaza con HTTP 503 si se alcanza. |

**Ciclo temporal de una incidencia:**

```
t=0ms    Recepción en /incidents (validación de tasa)
t=0ms    Encolado en PriorityQueue
         ← queue_delay_ms → (MAX_START_DELAY: 20 ms)
t=Xms    Worker extrae la incidencia
         ← proc_ms → (procesamiento + guardado en BD)
t=Yms    Fin de procesamiento
         ← total_ms → (DEADLINE_MS: 50 ms)
```

Si `total_ms > 50 ms` → violación de deadline → registro en tabla `errors` con módulo `DEADLINE`.

---

## Gestión de recursos críticos — Semáforo

```python
MAX_CRITICAL_CONCURRENT = 2
CRITICAL_SEMAPHORE = asyncio.Semaphore(MAX_CRITICAL_CONCURRENT)
```

El semáforo controla el acceso concurrente al recurso "procesamiento crítico":

- **Solo las incidencias con `severity=4`** (CRÍTICA) deben adquirir el semáforo.
- Con 3 workers activos, sin semáforo, podrían procesarse hasta 3 críticas simultáneamente, saturando el canal de escalamiento.
- El semáforo garantiza que **como máximo 2 críticas** se procesen en paralelo en cualquier instante, independientemente del número de workers.
- Las incidencias no-críticas (severity 1–3) **no pasan por el semáforo**, evitando que un pico de críticas bloquee el procesamiento de incidencias de menor urgencia.

**Estado del semáforo** expuesto en `/metrics`:
```json
{
  "semaphore": {
    "max": 2,
    "available": 1,
    "in_use": 1
  }
}
```

> **Nota técnica:** el campo `available` se lee de `CRITICAL_SEMAPHORE._value`, un atributo interno de `asyncio.Semaphore`. Se usa exclusivamente para observabilidad; `asyncio` no expone una API pública para leer el contador del semáforo. El valor no se modifica en ningún momento.

---

## Modelo de ejecución

El sistema opera sobre el **modelo de ejecución asíncrono** de Python mediante `asyncio`:

- **Un solo thread, múltiples corutinas:** `asyncio` no usa threads del sistema operativo para las corutinas. Todo ocurre en un único event loop.
- **Concurrencia cooperativa:** las corutinas ceden el control al event loop en puntos `await`. Esto permite que 3 workers "corran en paralelo" sin necesidad de threads reales ni GIL releases.
- **No hay bloqueo de CPU:** los `await asyncio.sleep()` y `await aiosqlite.connect()` son operaciones no bloqueantes que permiten al event loop atender otras corutinas mientras esperan.
- **Ventaja para STR:** en sistemas I/O-bound como este (la mayoría del tiempo se espera BD o red), la asincronía con asyncio es equivalente en rendimiento a multi-threading, sin los problemas de condiciones de carrera en datos compartidos.

```
Event Loop de asyncio
│
├── FastAPI (maneja HTTP requests)
├── Worker 1 (consume cola, procesa incidencias)
├── Worker 2 (consume cola, procesa incidencias)
└── Worker 3 (consume cola, procesa incidencias)
```

---

## Determinismo y comportamiento temporal

Este sistema es **determinista en cuanto a prioridades** pero **no determinista en cuanto a latencia exacta**, lo cual es característico de un STR blando sobre hardware de propósito general:

**Lo que es determinista:**
- El orden de procesamiento entre incidencias de diferente severidad.
- La decisión de acción (`control_action`) es una función pura y predecible.
- Los umbrales de violación (10 ms, 20 ms, 50 ms) son fijos y verificados en cada ciclo.

**Lo que no es determinista:**
- La latencia exacta de procesamiento varía según la carga del sistema operativo, SQLite y el event loop.
- Con 3 workers compitiendo por la cola, el orden entre incidencias de igual severidad depende del scheduling del event loop.
- `asyncio.sleep()` garantiza un mínimo de tiempo, no un máximo exacto.

**Consecuencia práctica:** el sistema puede operar con latencias consistentemente por debajo de 50 ms bajo carga normal. Bajo carga extrema (prueba de estrés), algunas incidencias superarán el deadline, lo cual es el comportamiento esperado y documentado de un sistema de tiempo real blando.

---

## Funcionalidades principales

- **Registro de incidencias** mediante formulario web o API REST, con validación de tipos, severidad y restricciones STR.
- **Cola de prioridad con backlog limitado** (`asyncio.PriorityQueue(maxsize=100)`) que procesa primero las incidencias más críticas.
- **Pool de 3 workers concurrentes** que consumen la cola de forma independiente y paralela.
- **Semáforo de concurrencia** (`asyncio.Semaphore(2)`) que limita el procesamiento simultáneo de incidencias críticas.
- **Control de tasa de eventos:** rechaza con HTTP 429 si el intervalo entre eventos es menor a 10 ms.
- **Control de backlog:** rechaza con HTTP 503 si la cola supera 100 items.
- **Deadline enforcement:** registra violaciones cuando el tiempo total supera 50 ms.
- **Dashboard web** con auto-refresh cada 2–3 segundos y coloreado por severidad.
- **Métricas desglosadas:** tiempo en cola, tiempo de procesamiento y tiempo total (promedio y máximo).
- **Log de errores con trazabilidad:** `trace_id` y `worker_id` en cada registro de error.
- **Reset del sistema:** limpieza de BD y métricas sin reiniciar los workers.

---

## Tecnologías utilizadas

| Componente            | Tecnología                              |
|-----------------------|-----------------------------------------|
| Backend / API         | Python 3.12 + FastAPI                   |
| Concurrencia          | asyncio (PriorityQueue, Semaphore, Lock)|
| Workers concurrentes  | asyncio.create_task (pool de 3 workers) |
| Base de datos         | SQLite + aiosqlite (acceso async)       |
| Plantillas web        | Jinja2                                  |
| Frontend              | HTML5, CSS3, JavaScript (Vanilla)       |
| Servidor ASGI         | Uvicorn                                 |
| Validación de entrada | Pydantic v2                             |
| Prueba de carga       | requests + threading                    |
| Trazabilidad          | uuid (trace_id por incidencia)          |

---

## Requisitos del sistema

- Sistema operativo: Windows 10/11, Linux o macOS
- Python 3.10 o superior
- `pip` disponible en el entorno
- Navegador web moderno (Chrome, Edge, Firefox)
- Conexión local para acceder a `http://localhost:8000`

---

## Ejecución local paso a paso

### 1. Descomprimir el proyecto

```bash
unzip STR-Gestion-Incidencias.zip
cd str_api
```

### 2. Crear y activar el entorno virtual

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Iniciar el servidor

```bash
uvicorn main:app --reload --port 8000
```

Al arrancar, el sistema inicializa la base de datos y lanza automáticamente **3 workers concurrentes** que comienzan a consumir la cola de prioridad.

### 5. Acceder al sistema

```
http://localhost:8000          ← Dashboard web
http://localhost:8000/docs     ← Documentación Swagger interactiva
http://localhost:8000/metrics  ← Métricas completas + semáforo + cola + config
```

### 6. Prueba de carga (opcional)

```bash
# En una segunda terminal con el entorno activo:
python load_test.py
```

**Qué esperar observar:**
- HTTP 200: incidencia encolada correctamente.
- HTTP 429: violación de tasa (intervalo < 10 ms).
- HTTP 503: backlog lleno (cola saturada).
- En `/api/errors`: registros de tipo DEADLINE, SCHEDULER y CAPTURE.
- En `/metrics`: violaciones incrementando, latencia promedio aumentando.

---

## Ejecución con Docker

> El proyecto no incluye configuración Docker en su versión actual. Se incluye como propuesta de mejora futura para despliegue y portabilidad.

La containerización permitiría despliegue reproducible en cualquier entorno sin dependencias locales.

**`Dockerfile` (implementación futura):**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t str-api .
docker run -p 8000:8000 str-api
```

---

## Estructura del proyecto

```
str_api/
├── main.py               # FastAPI: endpoints, startup con launch_workers()
├── models.py             # Pydantic: IncidentIn, IncidentDB, enums Severity/IncidentType
├── database.py           # aiosqlite: init_db(), save_incident(), log_error()
├── scheduler.py          # STR core: PriorityQueue, Semaphore, workers, métricas
├── control.py            # Decisión: control_action_async() con latencia por severidad
├── errors.py             # RTErrorLogger: 5 categorías con trace_id y worker_id
├── load_test.py          # Prueba de carga: 50 threads, intervalo 5 ms
├── templates/
│   └── index.html        # Dashboard Jinja2 con coloreado por severidad
├── static/
│   └── app.js            # Frontend: fetch, auto-refresh, métricas con semáforo
├── requirements.txt      # Dependencias del proyecto
├── .gitignore            # Exclusiones: venv/, __pycache__/, incidents.db
└── README.md             # Este archivo
```

---

## Descripción de archivos principales

**`scheduler.py`** — Núcleo del STR. Implementa `asyncio.PriorityQueue(maxsize=100)` para encolado limitado por prioridad, `asyncio.Semaphore(2)` para control de concurrencia crítica, `_worker()` como unidad de procesamiento concurrente, `launch_workers()` que lanza el pool de 3 workers al arrancar, y métricas desglosadas en tres fases (cola, procesamiento, total) protegidas con `asyncio.Lock`.

**`main.py`** — Punto de entrada. Llama a `launch_workers()` en startup, diferencia HTTP 429 (rate violation) de HTTP 503 (backlog full) en `POST /incidents`, y expone el endpoint `/metrics` con configuración STR completa.

**`control.py`** — Módulo de decisión con dos versiones: `control_action()` (síncrona, pura) y `control_action_async()` (asíncrona, con latencia simulada proporcional a la severidad). El scheduler usa la versión async para modelar costo real de procesamiento.

**`errors.py`** — `RTErrorLogger` con 5 categorías de error (DEADLINE, SCHEDULER, CAPTURE, PROCESSING, BACKLOG). Todos los métodos aceptan `trace_id` y `worker_id` para trazabilidad en entornos multi-worker.

**`database.py`** — Acceso asíncrono a SQLite. Constante `DB` exportada. Columnas nombradas explícitamente en todos los INSERT. Todas las operaciones usan `async with aiosqlite.connect()`.

**`models.py`** — `IncidentIn` con `Field(min_length, max_length)`. Enums `Severity` e `IncidentType` para valores controlados. `json_schema_extra` con ejemplo real para `/docs`.

**`load_test.py`** — 50 threads, intervalo de 5 ms (mitad del MIN_INTERVAL), apuntando al puerto 8000. Muestra contadores de resultados: OK (200), rate limited (429) y errores de conexión.

---

## Archivos de configuración

### `requirements.txt`

```
fastapi==0.115.0
uvicorn==0.30.6
jinja2==3.1.4
aiosqlite==0.22.1
pydantic==2.9.2
requests==2.32.3
```

### `.gitignore`

```
venv/
.venv/
__pycache__/
*.pyc
incidents.db
.vscode/
.idea/
.DS_Store
.env
```

---

## Endpoints del sistema

Todos los endpoints siguen principios REST y tienen validación automática de entrada mediante Pydantic. Documentación interactiva disponible en `/docs`.

### Interfaz web

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/`  | Dashboard principal (HTML con Jinja2) |

### API REST

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/incidents` | Registra incidencia. Retorna `trace_id`. HTTP 429 (rate) o 503 (backlog). |
| `GET`  | `/api/incidents` | Lista las últimas incidencias. Parámetro: `limit` (default: 50). |
| `GET`  | `/api/history` | Historial cronológico ascendente. |
| `GET`  | `/api/errors` | Errores STR con trace_id y worker_id. |
| `GET`  | `/api/metrics` | Métricas desglosadas: cola, procesamiento y total. |
| `GET`  | `/metrics` | Métricas + semáforo + estado de cola + configuración STR. |
| `POST` | `/api/reset` | Limpia BD y métricas. Los workers continúan activos. |

### Respuestas de `POST /incidents`

```json
// 200 — aceptada
{ "status": "accepted", "trace_id": "a3f9bc12" }

// 429 — violación de tasa
{ "detail": "Too many events (STR interval violated)" }

// 503 — backlog lleno
{ "detail": "Sistema sobrecargado: cola de prioridad llena. Reintente en instantes." }
```

---

## Conceptos del curso aplicados

### Cola de prioridad con backlog limitado

```python
QUEUE = asyncio.PriorityQueue(maxsize=100)
# Encolado con prioridad invertida:
await QUEUE.put((-severity, timestamp, incident))
# severity=4 → prioridad=-4 → extraída primero
```

`maxsize=100` actúa como control de backlog: si la cola está llena, `put_nowait()` lanza `QueueFull` en lugar de bloquear indefinidamente.

### Pool de workers concurrentes

```python
NUM_WORKERS = 3

async def launch_workers():
    for worker_id in range(1, NUM_WORKERS + 1):
        asyncio.create_task(_worker(worker_id), name=f"str-worker-{worker_id}")
```

Los 3 workers compiten por items de la misma cola. `asyncio` garantiza que cada item es entregado a exactamente un worker.

### Semáforo de concurrencia crítica

```python
CRITICAL_SEMAPHORE = asyncio.Semaphore(2)

# Solo incidencias severity=4 pasan por el semáforo:
async with CRITICAL_SEMAPHORE:
    action = await control_action(incident["severity"])
    await save_incident(incident)
```

### Control de tasa de llegada

```python
MIN_INTERVAL = 0.01  # 10 ms
if now - _last_event_time < MIN_INTERVAL:
    raise Exception("EVENT_RATE_VIOLATION")  # → HTTP 429
```

Protegido con `asyncio.Lock` para evitar condiciones de carrera entre requests concurrentes.

### Deadline enforcement con métricas desglosadas

```python
DEADLINE_MS = 50
total_ms = (time.time() - enqueue_ts) * 1000
violated = total_ms > DEADLINE_MS
# Métricas separadas por fase:
await _update_metrics(queue_ms, proc_ms, total_ms, violated)
```

### Trazabilidad multi-worker

```python
incident["trace_id"] = str(uuid.uuid4())[:8]
# Cada error incluye: trace_id + worker_id
await RTErrorLogger.deadline_missed(trace_id, elapsed_ms, worker_id)
```

---

## Buenas prácticas implementadas

- **Validación de entrada con Pydantic:** `Field(min_length, max_length)` en todos los campos de texto.
- **Enums para valores controlados:** `Severity` e `IncidentType` evitan valores arbitrarios.
- **Separación de responsabilidades:** cada módulo tiene una única función (modelos, BD, scheduler, control, errores).
- **asyncio.Lock para métricas compartidas:** evita condiciones de carrera entre workers al actualizar contadores.
- **asyncio.Lock para control de tasa:** evita que dos requests simultáneos pasen el check de MIN_INTERVAL.
- **trace_id por incidencia:** permite correlacionar logs de error con incidencias específicas sin ID de BD.
- **Diferenciación HTTP 429 vs 503:** permite al cliente distinguir entre sobrecarga de tasa y sobrecarga de capacidad.
- **control_action_async:** introduce latencia diferenciada por severidad sin bloquear el event loop.
- **Módulo de errores centralizado con contexto:** `RTErrorLogger` incluye worker_id y trace_id en cada registro.

---

## Validación del sistema

### Pruebas manuales desde el dashboard

- Registro de incidencias con distintos niveles de severidad.
- Verificación del coloreado por severidad en la tabla de incidencias.
- Observación del auto-refresh y actualización de métricas.
- Verificación del estado del semáforo en tiempo real.

### Pruebas mediante Swagger UI (`/docs`)

- Validación de todos los endpoints con entradas válidas e inválidas.
- Verificación de respuestas 422 (validación Pydantic), 429 (rate) y 503 (backlog).
- Inspección del `trace_id` retornado en respuestas exitosas.

### Prueba de carga con `load_test.py`

El script lanza 50 threads con intervalos de 5 ms (por debajo del MIN_INTERVAL de 10 ms).

**Qué se espera observar:**
- Aproximadamente el 50% de las solicitudes retornan HTTP 429 (rate limited).
- El resto retornan HTTP 200 o HTTP 503 según el estado de la cola.
- En `/api/errors`: registros de tipo `DEADLINE` y `SCHEDULER` bajo carga.
- En `/metrics`: `violations` incrementando, `avg_total_ms` aumentando bajo carga.
- En `/metrics` → `queue`: `rate_rejected` y `backlog_rejected` reflejan las incidencias rechazadas por tasa y backlog.

### Comportamientos verificados

- Prioridad funcional: incidencias severity=4 se procesan antes que severity=1 aunque lleguen después.
- Semáforo funcional: `in_use` nunca supera 2 aunque haya 3 workers activos y múltiples críticas en cola.
- Control de tasa: HTTP 429 consistente ante solicitudes rápidas consecutivas.
- Backlog: HTTP 503 cuando la cola supera 100 items bajo carga extrema.
- Métricas desglosadas: `avg_queue_ms` + `avg_proc_ms` ≈ `avg_total_ms` (con pequeñas variaciones de medición).

---

## Limitaciones del sistema

- **No preemptivo:** una vez que un worker comienza a procesar una incidencia, no puede ser interrumpido por otra de mayor prioridad que llegue mientras tanto. La prioridad solo actúa en el momento de extracción de la cola.
- **SQLite bajo alta concurrencia:** SQLite serializa las escrituras. Con 3 workers guardando simultáneamente, pueden ocurrir colas de escritura que incrementen la latencia de `proc_ms`.
- **Concurrencia cooperativa (no paralela):** asyncio opera en un solo thread. En hardware multinúcleo, el sistema no aprovecha múltiples CPUs. Para paralelismo real se requeriría `multiprocessing` o `uvicorn --workers N`.
- **Polling en el dashboard:** el frontend actualiza datos cada 2–3 segundos mediante polling HTTP. En una implementación productiva se usarían WebSockets para latencia de actualización < 100 ms.
- **Sin persistencia de métricas:** las métricas se mantienen en memoria y se pierden al reiniciar el proceso. No hay histórico entre sesiones.
- **Sin autenticación:** cualquier cliente puede enviar incidencias o invocar el reset del sistema. Apropiado para contexto académico.

Estas limitaciones son inherentes a las decisiones de diseño académico y representan áreas de mejora concretas para una versión productiva.

---

## Recomendaciones de entrega

1. **Eliminar** `venv/`, `.venv/`, `__pycache__/` y `.git/` del ZIP final.
2. **No incluir** `incidents.db` (se genera automáticamente al arrancar).
3. **Incluir** `requirements.txt` y `.gitignore`.
4. **Verificar** que `uvicorn main:app --reload --port 8000` arranca sin errores.
5. **Confirmar** que `/metrics` retorna el bloque `config` con los parámetros STR.
6. **Demostrar** en la presentación: envío de incidencias, violación de tasa (HTTP 429), métricas en tiempo real y log de errores.

---

## Conclusión

El sistema **STR — Gestión de Incidencias de Soporte Técnico** implementa un Soft Real-Time System funcional que demuestra de forma aplicada los conceptos centrales de sistemas en tiempo real: planificación por prioridad, control de concurrencia mediante semáforo, enforcement de restricciones temporales (deadline, start delay, tasa de llegada), métricas de latencia desglosadas y comportamiento predecible bajo carga. La arquitectura de pool de workers concurrentes sobre `asyncio.PriorityQueue` proporciona una base sólida y extensible, cuyas limitaciones actuales (SQLite, cooperatividad, polling) están claramente identificadas y son abordables en iteraciones futuras.
