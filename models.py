from pydantic import BaseModel
from enum import Enum
from datetime import datetime

class Severity(int, Enum):
    baja = 1
    media = 2
    alta = 3
    critica = 4

class IncidentType(str, Enum):
    red = "red"
    sistema = "sistema"
    seguridad = "seguridad"
    servicio = "servicio"
    otro = "otro"

class IncidentIn(BaseModel):
    user: str
    description: str
    type: IncidentType = IncidentType.otro
    severity: Severity = Severity.media

class IncidentDB(IncidentIn):
    id: int
    created_at: datetime
    status: str
