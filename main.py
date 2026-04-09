from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import aiosqlite
from datetime import datetime

from models import IncidentIn
from database import init_db, DB
from scheduler import (
    submit_incident,
    launch_workers,
    METRICS,
    reset_metrics,
    get_semaphore_status,
    get_queue_status,
    NUM_WORKERS,
    DEADLINE_MS,
    MAX_START_DELAY,
    MIN_INTERVAL,
    QUEUE_MAXSIZE,
)

app = FastAPI(
    title="STR – Gestión de Incidencias de Soporte Técnico",
    description=(
        "Sistema de Tiempo Real (Soft Real-Time) para recepción, clasificación "
        "y procesamiento concurrente de incidencias de soporte técnico. "
        "Implementa cola de prioridad, semáforo de concurrencia, control de tasa, "
        "deadline enforcement y métricas de latencia en tiempo real."
    ),
    version="2.0.0",
)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────

@app.on_event("startup")
async def start():
    """
    Inicializa la base de datos y lanza el pool de workers del STR.

    Se crean NUM_WORKERS tareas asyncio independientes que consumen
    de la cola de prioridad compartida de forma concurrente.
    """
    await init_db()
    await launch_workers()


# ──────────────────────────────────────────────
# VISTA WEB
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, tags=["Web"])
async def home(request: Request):
    """Retorna el dashboard principal del sistema STR."""
    return templates.TemplateResponse("index.html", {"request": request})


# ──────────────────────────────────────────────
# ENDPOINTS DE INCIDENCIAS
# ──────────────────────────────────────────────

@app.post("/incidents", tags=["Incidencias"])
async def create_incident(i: IncidentIn):
    """
    Registra una nueva incidencia en la cola de prioridad del STR.

    Restricciones STR aplicadas:
    - Control de tasa: mínimo MIN_INTERVAL (10 ms) entre eventos consecutivos.
    - Control de backlog: rechaza si la cola supera QUEUE_MAXSIZE (100 items).

    Respuestas:
    - 200: incidencia aceptada y encolada.
    - 429: violación de intervalo mínimo (EVENT_RATE_VIOLATION).
    - 503: cola saturada, sistema bajo sobrecarga (BACKLOG_FULL).
    """
    data = i.model_dump()
    data["created_at"] = datetime.utcnow().isoformat()
    data["status"] = "RECEIVED"

    try:
        await submit_incident(-i.severity, data)
    except Exception as exc:
        msg = str(exc)
        if msg == "BACKLOG_FULL":
            raise HTTPException(
                status_code=503,
                detail="Sistema sobrecargado: cola de prioridad llena. Reintente en instantes.",
            )
        raise HTTPException(
            status_code=429,
            detail="Too many events (STR interval violated)",
        )

    return {"status": "accepted", "trace_id": data.get("trace_id")}


@app.get("/api/incidents", tags=["Incidencias"])
async def list_incidents(limit: int = 50):
    """
    Retorna las últimas incidencias registradas, ordenadas por ID descendente.

    Parámetro `limit`: cantidad máxima de registros (default: 50).
    """
    async with aiosqlite.connect(DB) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT id, user, type, severity, description, created_at, status
            FROM incidents
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {
            "id":          r["id"],
            "user":        r["user"],
            "type":        r["type"],
            "severity":    r["severity"],
            "description": r["description"],
            "created_at":  r["created_at"],
            "status":      r["status"],
        }
        for r in rows
    ]


@app.get("/api/history", tags=["Incidencias"])
async def history(limit: int = 50):
    """
    Retorna incidencias en orden cronológico ascendente (más antiguas primero).
    Útil para análisis temporal del comportamiento del sistema.
    """
    async with aiosqlite.connect(DB) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT id, user, type, severity, description, created_at, status
            FROM incidents
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()

    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# ENDPOINTS DE ERRORES
# ──────────────────────────────────────────────

@app.get("/api/errors", tags=["Errores"])
async def list_errors(limit: int = 50):
    """
    Retorna los errores internos registrados por el STR.

    Categorías: DEADLINE, SCHEDULER, CAPTURE, PROCESSING, BACKLOG.
    Cada registro incluye el worker_id y trace_id para trazabilidad.
    """
    async with aiosqlite.connect(DB) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT module, message, created_at
            FROM errors
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {"module": r["module"], "message": r["message"], "created_at": r["created_at"]}
        for r in rows
    ]


# ──────────────────────────────────────────────
# ENDPOINTS DE MÉTRICAS
# ──────────────────────────────────────────────

@app.get("/api/metrics", tags=["Métricas"])
async def api_metrics():
    """
    Retorna las métricas acumuladas del sistema STR, desglosadas por fase:

    - avg/max_total_ms: tiempo total enqueue → fin de procesamiento.
    - avg/max_queue_ms: tiempo de espera en cola (start delay).
    - avg/max_proc_ms:  tiempo de procesamiento puro.
    - violations:       incidencias que superaron el deadline de 50 ms.
    - rate_rejected:    rechazos por violación de tasa (MIN_INTERVAL).
    - backlog_rejected: rechazos por cola llena (QUEUE_MAXSIZE).
    """
    return METRICS


@app.get("/metrics", tags=["Métricas"])
async def metrics_full():
    """
    Endpoint de observabilidad completa del sistema STR.

    Retorna métricas de latencia, estado del semáforo, estado de la cola
    y parámetros de configuración actuales del sistema.
    """
    return {
        "metrics":    METRICS,
        "semaphore":  get_semaphore_status(),
        "queue":      get_queue_status(),
        "config": {
            "num_workers":      NUM_WORKERS,
            "deadline_ms":      DEADLINE_MS,
            "max_start_delay":  MAX_START_DELAY,
            "min_interval_ms":  MIN_INTERVAL * 1000,
            "queue_maxsize":    QUEUE_MAXSIZE,
        },
    }


# ──────────────────────────────────────────────
# RESET DEL SISTEMA
# ──────────────────────────────────────────────

@app.post("/api/reset", tags=["Sistema"])
async def reset_system():
    """
    Elimina todas las incidencias y errores de la base de datos y reinicia métricas.

    Uso recomendado: entre sesiones de prueba o demostraciones.
    No detiene ni reinicia los workers del scheduler.
    """
    async with aiosqlite.connect(DB) as conn:
        await conn.execute("DELETE FROM incidents")
        await conn.execute("DELETE FROM errors")
        await conn.commit()

    await reset_metrics()
    return {"status": "system reset", "workers_active": NUM_WORKERS}
