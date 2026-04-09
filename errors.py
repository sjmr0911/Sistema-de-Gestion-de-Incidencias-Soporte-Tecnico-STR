import datetime
from database import log_error


class RTErrorLogger:
    """
    Módulo centralizado de registro de errores del STR.

    Cada método estático corresponde a una categoría de error del sistema
    de tiempo real. Todos los métodos aceptan trace_id y worker_id para
    trazabilidad completa en un entorno de múltiples workers concurrentes.

    El registro es persistente (base de datos SQLite) y no interrumpe
    el flujo de procesamiento del worker que lo invoca.

    Categorías de error:
        DEADLINE   — procesamiento superó el deadline total (50 ms).
        SCHEDULER  — retardo de inicio en cola superó MAX_START_DELAY (20 ms).
        CAPTURE    — violación del intervalo mínimo entre eventos (10 ms).
        PROCESSING — error inesperado durante el procesamiento de una incidencia.
        BACKLOG    — cola saturada, incidencia rechazada por backlog lleno.
    """

    @staticmethod
    async def deadline_missed(
        trace_id: str,
        elapsed_ms: float,
        worker_id: int = 0,
    ) -> None:
        """
        Registra una violación de deadline total de procesamiento.

        Se activa cuando el tiempo total (enqueue → fin de procesamiento)
        supera DEADLINE_MS (50 ms por defecto).

        Args:
            trace_id:   identificador temporal de la incidencia (UUID corto asignado
                        en submit_incident antes de persistir en BD).
            elapsed_ms: tiempo total medido en milisegundos.
            worker_id:  ID del worker que detectó la violación.
        """
        await log_error(
            module="DEADLINE",
            msg=(
                f"[W{worker_id}] Deadline excedido | "
                f"trace={trace_id} | "
                f"total={elapsed_ms:.2f} ms (límite: 50 ms)"
            ),
        )

    @staticmethod
    async def queue_delay_violation(
        delay_ms: float,
        trace_id: str = "?",
        worker_id: int = 0,
    ) -> None:
        """
        Registra una violación del retardo máximo de inicio en cola.

        Se activa cuando una incidencia espera más de MAX_START_DELAY (20 ms)
        en la cola antes de comenzar a procesarse.

        Args:
            delay_ms:   tiempo de espera en cola en milisegundos.
            trace_id:   identificador temporal de la incidencia.
            worker_id:  ID del worker que extrajo la incidencia.
        """
        await log_error(
            module="SCHEDULER",
            msg=(
                f"[W{worker_id}] Retardo de inicio excedido | "
                f"trace={trace_id} | "
                f"delay={delay_ms:.2f} ms (límite: 20 ms)"
            ),
        )

    @staticmethod
    async def rate_violation(trace_id: str = "?") -> None:
        """
        Registra una violación de la tasa mínima de llegada de eventos.

        Se activa cuando dos eventos consecutivos llegan con menos de
        MIN_INTERVAL (10 ms) de separación. La incidencia es rechazada
        y no llega a encolarse.

        Args:
            trace_id: identificador del intento rechazado (si disponible).
        """
        await log_error(
            module="CAPTURE",
            msg=(
                f"Violación de intervalo mínimo entre eventos (< 10 ms) | "
                f"trace={trace_id} | "
                f"ts={datetime.datetime.utcnow().isoformat()}"
            ),
        )

    @staticmethod
    async def backlog_full(trace_id: str = "?") -> None:
        """
        Registra el rechazo de una incidencia por saturación del backlog.

        Se activa cuando la cola alcanza QUEUE_MAXSIZE (100 items) y no
        puede aceptar más incidencias. La incidencia es descartada.

        Args:
            trace_id: identificador del intento rechazado.
        """
        await log_error(
            module="BACKLOG",
            msg=(
                f"Cola saturada — incidencia rechazada | "
                f"trace={trace_id} | "
                f"ts={datetime.datetime.utcnow().isoformat()}"
            ),
        )

    @staticmethod
    async def processing_error(
        error: Exception,
        trace_id: str = "?",
        worker_id: int = 0,
    ) -> None:
        """
        Registra un error inesperado durante el procesamiento de una incidencia.

        El worker continúa operando tras registrar el error; el sistema
        no se detiene por fallos individuales.

        Args:
            error:      excepción capturada durante el procesamiento.
            trace_id:   identificador de la incidencia afectada.
            worker_id:  ID del worker donde ocurrió el error.
        """
        await log_error(
            module="PROCESSING",
            msg=(
                f"[W{worker_id}] Error de procesamiento | "
                f"trace={trace_id} | "
                f"{type(error).__name__}: {error}"
            ),
        )
