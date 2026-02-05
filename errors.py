# errors.py
import datetime
from database import log_error

class RTErrorLogger:
    """
    Módulo de detección y registro de errores del STR.
    No detiene la ejecución del sistema.
    """

    @staticmethod
    async def deadline_missed(incident_id: int, elapsed_ms: float):
        """
        Se ejecuta cuando una incidencia supera el deadline de 50 ms.
        """
        await log_error(
            module="DEADLINE",
            msg=f"Deadline excedido: {elapsed_ms:.2f} ms",
        )

    @staticmethod
    async def queue_delay_violation(delay_ms: float):
        """
        Se ejecuta cuando el retardo en cola supera los 20 ms.
        """
        await log_error(
            module="SCHEDULER",
            msg=f"Retardo de inicio excedido: {delay_ms:.2f} ms"
        )

    @staticmethod
    async def rate_violation():
        """
        Se ejecuta cuando se viola la separación mínima entre eventos (10 ms).
        """
        await log_error(
            module="CAPTURE",
            msg="Violación de intervalo mínimo entre eventos (<10 ms)"
        )

    @staticmethod
    async def processing_error(error: Exception):
        """
        Error inesperado durante el procesamiento.
        """
        await log_error(
            module="PROCESSING",
            msg=str(error)
        )
