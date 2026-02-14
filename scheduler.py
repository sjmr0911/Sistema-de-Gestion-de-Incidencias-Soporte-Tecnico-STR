import asyncio
import time
from control import control_action
from database import save_incident, log_error

QUEUE = asyncio.PriorityQueue()

# ==============================
# IMPLEMENTACIÓN DE SEMÁFORO
# Controla concurrencia de incidencias críticas
# ==============================

MAX_CRITICAL_ACTIONS = 2  # solo 2 críticas al mismo tiempo
CRITICAL_SEMAPHORE = asyncio.Semaphore(MAX_CRITICAL_ACTIONS)


DEADLINE_MS = 50
MAX_START_DELAY = 20
MIN_INTERVAL = 0.01  # 10 ms

last_event = 0

# 🔹 MÉTRICAS GLOBALES (NO se reinician)
METRICS = {
    "count": 0,
    "avg_ms": 0.0,
    "max_ms": 0.0,
    "violations": 0
}

async def submit_incident(priority, incident):
    global last_event
    now = time.time()

    if now - last_event < MIN_INTERVAL:
        raise Exception("EVENT_RATE_VIOLATION")

    last_event = now
    await QUEUE.put((priority, time.time(), incident))

def update_metrics(elapsed_ms, violated):
    m = METRICS
    m["count"] += 1
    m["avg_ms"] = ((m["avg_ms"] * (m["count"] - 1)) + elapsed_ms) / m["count"]
    m["max_ms"] = max(m["max_ms"], elapsed_ms)
    if violated:
        m["violations"] += 1

async def scheduler():
    while True:
        priority, ts, incident = await QUEUE.get()

        start = time.time()
        queue_delay = (start - ts) * 1000

        if queue_delay > MAX_START_DELAY:
            await log_error("SCHEDULER", "Queue delay violation")

        try:
            # 🔹 Si es crítica, usar semáforo
            if incident["severity"] == 4:
                async with CRITICAL_SEMAPHORE:
                    action = control_action(incident["severity"])
                    await asyncio.sleep(0.02)  # simulación carga pesada
                    incident["status"] = action
                    await save_incident(incident)
            else:
                action = control_action(incident["severity"])
                incident["status"] = action
                await save_incident(incident)

        except Exception as e:
            await log_error("PROCESSING", str(e))

        total_ms = (time.time() - ts) * 1000
        violated = total_ms > DEADLINE_MS

        if violated:
            await log_error("DEADLINE", "Deadline missed")

        update_metrics(total_ms, violated)

def reset_metrics():
    METRICS["count"] = 0
    METRICS["avg_ms"] = 0.0
    METRICS["max_ms"] = 0.0
    METRICS["violations"] = 0

def get_semaphore_status():
    return {
        "max": MAX_CRITICAL_ACTIONS,
        "available": CRITICAL_SEMAPHORE._value
    }

