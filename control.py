import asyncio

# ══════════════════════════════════════════════════════════════
# MAPA DE ACCIONES POR SEVERIDAD
#
# Define la acción de respuesta para cada nivel de severidad.
# En un sistema STR real, estas acciones dispararían llamadas
# a sistemas externos (alertas, tickets, notificaciones).
# Aquí se modelan como strings que el scheduler persiste en BD.
# ══════════════════════════════════════════════════════════════

_ACTION_MAP: dict[int, str] = {
    4: "ESCALATE_IMMEDIATELY",
    3: "ESCALATE",
    2: "AUTO_RESPONSE",
    1: "LOG_ONLY",
}

# Latencia simulada de procesamiento por nivel de severidad (segundos).
# Modela el costo diferencial de ejecutar cada tipo de acción:
# - Crítica (4): 20 ms — escalamiento inmediato con carga alta.
# - Alta (3):    10 ms — escalamiento normal.
# - Media (2):    5 ms — respuesta automática ligera.
# - Baja (1):     1 ms — solo registro, sin acción externa.
_PROCESSING_DELAY: dict[int, float] = {
    4: 0.020,
    3: 0.010,
    2: 0.005,
    1: 0.001,
}


def control_action(severity: int) -> str:
    """
    Determina la acción de respuesta según el nivel de severidad.

    Este es un módulo de decisión puro y síncrono. La latencia
    de procesamiento se simula en control_action_async().

    Args:
        severity: entero entre 1 y 4.
            1 (Baja)    → LOG_ONLY
            2 (Media)   → AUTO_RESPONSE
            3 (Alta)    → ESCALATE
            4 (Crítica) → ESCALATE_IMMEDIATELY

    Returns:
        Nombre de la acción a ejecutar como string.
    """
    return _ACTION_MAP.get(severity, "LOG_ONLY")


async def control_action_async(severity: int) -> str:
    """
    Versión asíncrona de control_action con latencia de procesamiento simulada.

    Introduce un await asyncio.sleep() proporcional a la severidad para modelar
    el costo real de ejecutar la acción correspondiente. Esto permite que el
    event loop de asyncio atienda otras corutinas durante el procesamiento,
    en lugar de bloquear con time.sleep().

    Úsese esta función desde el scheduler en lugar de control_action()
    cuando se quiera modelar latencia realista de procesamiento.

    Args:
        severity: nivel de severidad de la incidencia (1–4).

    Returns:
        Nombre de la acción ejecutada.
    """
    if severity not in _ACTION_MAP:
        raise ValueError("Invalid severity level")
    delay = _PROCESSING_DELAY.get(severity, 0.001)
    await asyncio.sleep(delay)
    return _ACTION_MAP.get(severity, "LOG_ONLY")
