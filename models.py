from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class Severity(int, Enum):
    """Nivel de severidad de una incidencia. Mayor valor = mayor prioridad de atención."""
    baja = 1
    media = 2
    alta = 3
    critica = 4


class IncidentType(str, Enum):
    """Categoría de la incidencia según el área afectada."""
    red = "red"
    sistema = "sistema"
    seguridad = "seguridad"
    servicio = "servicio"
    otro = "otro"


class IncidentIn(BaseModel):
    """
    Modelo de entrada para el registro de una incidencia.

    Validaciones:
    - `user`: entre 1 y 100 caracteres, no puede estar vacío.
    - `description`: entre 5 y 500 caracteres.
    - `type`: debe ser uno de los valores definidos en IncidentType.
    - `severity`: debe ser uno de los valores definidos en Severity.
    """
    user: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Nombre del usuario o técnico que reporta la incidencia.",
    )
    description: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Descripción detallada del problema reportado.",
    )
    type: IncidentType = Field(
        default=IncidentType.otro,
        description="Categoría de la incidencia.",
    )
    severity: Severity = Field(
        default=Severity.media,
        description="Nivel de severidad. Determina la prioridad en la cola de procesamiento.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user": "jperez",
                "description": "El servidor de producción no responde a peticiones HTTP.",
                "type": "sistema",
                "severity": 4,
            }
        }


class IncidentDB(IncidentIn):
    """
    Modelo extendido que representa una incidencia almacenada en base de datos.
    Incluye los campos generados por el sistema: ID, timestamp y estado.
    """
    id: int
    created_at: datetime
    status: str
