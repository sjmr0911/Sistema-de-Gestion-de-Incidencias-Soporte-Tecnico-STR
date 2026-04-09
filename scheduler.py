import asyncio
import time
import uuid

from control import control_action_async as control_action
from database import save_incident
from errors import RTErrorLogger

# ══════════════════════════════════════════════════════════════
# PARÁMETROS DE TIEMPO REAL (STR)
# Estas constantes definen las restricciones temporales del sistema.
# Modificar con criterio: afectan directamente el comportamiento STR.
# ══════════════════════════════════════════════════════════════

DEADLINE_MS: float    = 50.0   # Deadline total por incidencia: recepción → fin de procesamiento
MAX_START_DELAY: float = 20.0  # Retardo máximo permitido en cola antes de iniciar (ms)
MIN_INTERVAL: float   = 0.01   # Separación mínima entre eventos consecutivos (10 ms)

# ══════════════════════════════════════════════════════════════
# COLA DE PRIORIDAD CON BACKLOG LIMITADO
#
# maxsize=100 actúa como control de backlog:
# si la cola está llena, asyncio.PriorityQueue.put() lanzará
# QueueFull en su versión no-bloqueante (put_nowait).
# Esto evita acumulación ilimitada de incidencias pendientes,
# que en un STR puede ocultar problemas de capacidad real.
# ══════════════════════════════════════════════════════════════

QUEUE_MAXSIZE = 100
QUEUE: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=QUEUE_MAXSIZE)

# ══════════════════════════════════════════════════════════════
# SEMÁFORO DE CONCURRENCIA PARA INCIDENCIAS CRÍTICAS
#
# Solo las incidencias con severity=4 (CRÍTICA) pasan por este
# semáforo. Limita a MAX_CRITICAL_CONCURRENT el número de
# incidencias críticas procesadas en paralelo por todos los workers.
# Esto previene saturación de recursos bajo carga extrema.
# ══════════════════════════════════════════════════════════════

MAX_CRITICAL_CONCURRENT = 2
CRITICAL_SEMAPHORE = asyncio.Semaphore(MAX_CRITICAL_CONCURRENT)

# ══════════════════════════════════════════════════════════════
# WORKERS CONCURRENTES
#
# El sistema lanza NUM_WORKERS tareas asyncio independientes,
# cada una consumiendo de la misma PriorityQueue compartida.
# Esto convierte el scheduler en un pool de workers concurrentes:
# - La cola garantiza el orden por prioridad entre todos los workers.
# - Cada worker procesa una incidencia a la vez.
# - Con 3 workers, hasta 3 incidencias no-críticas se procesan
#   en paralelo; las críticas quedan además limitadas por el semáforo.
# ══════════════════════════════════════════════════════════════

NUM_WORKERS = 3

# ══════════════════════════════════════════════════════════════
# MÉTRICAS DESGLOSADAS
#
# Se separan en tres fases del ciclo de vida de la incidencia:
#   queue_ms:   tiempo desde encolado hasta inicio de procesamiento
#   proc_ms:    tiempo de procesamiento puro (control_action + save)
#   total_ms:   tiempo completo desde encolado hasta fin
#
# Todas usan media móvil incremental para no acumular listas en RAM.
# ══════════════════════════════════════════════════════════════

METRICS: dict = {
    # Contadores generales
    "count":      0,
    "violations": 0,

    # Tiempo total (enqueue → fin)
    "avg_total_ms": 0.0,
    "max_total_ms": 0.0,

    # Tiempo en cola (enqueue → inicio procesamiento)
    "avg_queue_ms": 0.0,
    "max_queue_ms": 0.0,

    # Tiempo de procesamiento puro (inicio → fin)
    "avg_proc_ms": 0.0,
    "max_proc_ms": 0.0,

    # Estado de la cola en tiempo real
    "queue_size":    0,
    "rate_rejected": 0,   # violaciones de MIN_INTERVAL
    "backlog_rejected": 0,   # cola llena
}

# Lock para actualización atómica de métricas compartidas entre workers
_metrics_lock = asyncio.Lock()

# Timestamp del último evento recibido (para control de tasa MIN_INTERVAL)
_last_event_time: float = 0.0
_rate_lock = asyncio.Lock()


# ──────────────────────────────────────────────────────────────
# FUNCIÓN DE ENTRADA: submit_incident
# ──────────────────────────────────────────────────────────────

async def submit_incident(priority: int, incident: dict) -> None:
    """
    Intenta encolar una incidencia en la cola de prioridad del STR.

    Restricciones STR aplicadas:
    1. Control de tasa: rechaza si han pasado menos de MIN_INTERVAL (10 ms)
       desde el último evento. Protege contra ráfagas de eventos inválidas.
    2. Control de backlog: rechaza si la cola ya alcanzó QUEUE_MAXSIZE (100).
       Un backlog ilimitado oculta problemas reales de capacidad del sistema.

    Args:
        priority: valor negativo de severidad (-4 a -1). Menor valor = mayor prioridad.
        incident: diccionario con los datos de la incidencia recibida.

    Raises:
        Exception("EVENT_RATE_VIOLATION"):  violación del intervalo mínimo entre eventos.
        Exception("BACKLOG_FULL"):          cola saturada, incidencia rechazada.
    """
    global _last_event_time
    now = time.time()

    # Asignar un ID de rastreo temporal antes de cualquier validación.
    # Necesario para logging de rechazos por rate o backlog.
    incident.setdefault("trace_id", str(uuid.uuid4())[:8])

    async with _rate_lock:
        if now - _last_event_time < MIN_INTERVAL:
            async with _metrics_lock:
                METRICS["rate_rejected"] += 1
            await RTErrorLogger.rate_violation(trace_id=incident.get("trace_id"))
            raise Exception("EVENT_RATE_VIOLATION")
        _last_event_time = now

    try:
        QUEUE.put_nowait((priority, time.time(), incident))
        async with _metrics_lock:
            METRICS["queue_size"] = QUEUE.qsize()
    except asyncio.QueueFull:
        async with _metrics_lock:
            METRICS["backlog_rejected"] += 1
        await RTErrorLogger.backlog_full(trace_id=incident.get("trace_id"))
        raise Exception("BACKLOG_FULL")


# ──────────────────────────────────────────────────────────────
# ACTUALIZACIÓN DE MÉTRICAS (thread-safe entre workers)
# ──────────────────────────────────────────────────────────────

async def _update_metrics(
    queue_ms: float,
    proc_ms: float,
    total_ms: float,
    violated: bool,
) -> None:
    """
    Actualiza las métricas del sistema usando media móvil incremental.
    Protegida con asyncio.Lock para evitar condiciones de carrera
    cuando múltiples workers actualizan simultáneamente.

    Args:
        queue_ms:  tiempo de espera en cola (ms).
        proc_ms:   tiempo de procesamiento puro (ms).
        total_ms:  tiempo total desde encolado hasta fin (ms).
        violated:  True si total_ms superó DEADLINE_MS.
    """
    async with _metrics_lock:
        m = METRICS
        n = m["count"] + 1
        m["count"] = n

        # Media móvil incremental: evita almacenar historial completo
        m["avg_total_ms"] = ((m["avg_total_ms"] * (n - 1)) + total_ms) / n
        m["max_total_ms"] = max(m["max_total_ms"], total_ms)

        m["avg_queue_ms"] = ((m["avg_queue_ms"] * (n - 1)) + queue_ms) / n
        m["max_queue_ms"] = max(m["max_queue_ms"], queue_ms)

        m["avg_proc_ms"] = ((m["avg_proc_ms"] * (n - 1)) + proc_ms) / n
        m["max_proc_ms"] = max(m["max_proc_ms"], proc_ms)

        m["queue_size"] = QUEUE.qsize()

        if violated:
            m["violations"] += 1


# ──────────────────────────────────────────────────────────────
# WORKER INDIVIDUAL DEL SCHEDULER
# ──────────────────────────────────────────────────────────────

async def _worker(worker_id: int) -> None:
    """
    Worker asíncrono que consume incidencias de la cola de prioridad.

    Cada worker opera de forma independiente, compitiendo por items
    de la misma PriorityQueue. asyncio garantiza que solo un worker
    recibe cada item (FIFO entre iguales, prioridad entre distintos).

    Fases de procesamiento:
    1. Extracción de la cola (bloquea hasta que haya items).
    2. Medición del retardo en cola (queue_delay_ms).
    3. Procesamiento según severidad (con o sin semáforo).
    4. Persistencia en base de datos.
    5. Medición de tiempo de procesamiento y deadline total.
    6. Actualización de métricas.

    Args:
        worker_id: identificador numérico del worker (1, 2, 3...).
                   Incluido en logs de error para trazabilidad.
    """
    while True:
        priority, enqueue_ts, incident = await QUEUE.get()

        start_ts = time.time()
        queue_delay_ms = (start_ts - enqueue_ts) * 1000

        # Recuperar trace_id asignado en submit_incident
        trace_id = incident.get("trace_id", "?")

        # ── Restricción STR: retardo de inicio en cola ──
        if queue_delay_ms > MAX_START_DELAY:
            await RTErrorLogger.queue_delay_violation(
                delay_ms=queue_delay_ms,
                trace_id=trace_id,
                worker_id=worker_id,
            )

        # ── Procesamiento según severidad ──
        try:
            if incident["severity"] == 4:
                # Incidencias CRÍTICAS: acceso controlado por semáforo.
                # El semáforo es compartido entre todos los workers,
                # garantizando que como máximo MAX_CRITICAL_CONCURRENT=2
                # incidencias críticas se ejecuten en paralelo globalmente.
                async with CRITICAL_SEMAPHORE:
                    proc_start = time.time()
                    # control_action es control_action_async: incluye latencia simulada
                    action = await control_action(incident["severity"])
                    incident["status"] = action
                    await save_incident(incident)
                    proc_ms = (time.time() - proc_start) * 1000
            else:
                proc_start = time.time()
                action = await control_action(incident["severity"])
                incident["status"] = action
                await save_incident(incident)
                proc_ms = (time.time() - proc_start) * 1000

        except Exception as exc:
            proc_ms = (time.time() - start_ts) * 1000
            await RTErrorLogger.processing_error(
                error=exc,
                trace_id=trace_id,
                worker_id=worker_id,
            )

        # ── Restricción STR: deadline total ──
        total_ms = (time.time() - enqueue_ts) * 1000
        violated = total_ms > DEADLINE_MS

        if violated:
            await RTErrorLogger.deadline_missed(
                trace_id=trace_id,
                elapsed_ms=total_ms,
                worker_id=worker_id,
            )

        await _update_metrics(
            queue_ms=queue_delay_ms,
            proc_ms=proc_ms,
            total_ms=total_ms,
            violated=violated,
        )

        QUEUE.task_done()


# ──────────────────────────────────────────────────────────────
# LANZADOR DEL POOL DE WORKERS
# ──────────────────────────────────────────────────────────────

async def launch_workers() -> None:
    """
    Lanza NUM_WORKERS tareas asyncio independientes que consumen
    de la cola de prioridad compartida.

    Reemplaza el scheduler() de un solo bucle por un pool concurrente.
    Cada worker es una corutina autónoma que opera sin coordinación
    explícita entre sí, más allá de la PriorityQueue y el Semaphore.

    El pool se inicia una vez en el evento startup de FastAPI
    y permanece activo durante toda la vida del proceso.
    """
    for worker_id in range(1, NUM_WORKERS + 1):
        asyncio.create_task(
            _worker(worker_id),
            name=f"str-worker-{worker_id}",
        )


# ──────────────────────────────────────────────────────────────
# UTILIDADES EXPORTADAS
# ──────────────────────────────────────────────────────────────

async def reset_metrics() -> None:
    """
    Reinicia todas las métricas acumuladas a sus valores iniciales.
    Llamado desde el endpoint /api/reset. Thread-safe con asyncio.Lock.
    """
    async with _metrics_lock:
        for key, value in METRICS.items():
            METRICS[key] = 0 if isinstance(value, int) else 0.0
        METRICS["queue_size"] = QUEUE.qsize()


def get_semaphore_status() -> dict:
    """
    Retorna el estado actual del semáforo de concurrencia crítica.

    Nota sobre CRITICAL_SEMAPHORE._value:
    asyncio.Semaphore expone _value como atributo interno (no público).
    Se usa aquí exclusivamente con fines de observabilidad del STR,
    ya que asyncio no provee una API pública para leer el contador.
    No se modifica en ningún momento; solo se lee.

    Returns:
        dict con:
          - max:       capacidad total del semáforo.
          - available: slots libres en este instante (puede cambiar inmediatamente).
          - in_use:    slots actualmente ocupados por incidencias críticas.
    """
    available = CRITICAL_SEMAPHORE._value  # noqa: SLF001
    return {
        "max":       MAX_CRITICAL_CONCURRENT,
        "available": available,
        "in_use":    MAX_CRITICAL_CONCURRENT - available,
    }


def get_queue_status() -> dict:
    """
    Retorna el estado actual de la cola de prioridad.

    Returns:
        dict con tamaño actual, capacidad máxima y porcentaje de ocupación.
    """
    size = QUEUE.qsize()
    return {
        "current_size": size,
        "max_size": QUEUE_MAXSIZE,
        "usage_pct": round(size / QUEUE_MAXSIZE * 100, 1),
        "rate_rejected": METRICS["rate_rejected"],
        "backlog_rejected": METRICS["backlog_rejected"],
        "total_rejected": METRICS["rate_rejected"] + METRICS["backlog_rejected"]
    }
