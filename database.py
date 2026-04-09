import aiosqlite
import datetime

# Ruta de la base de datos SQLite. Exportada para uso en otros módulos.
DB = "incidents.db"


async def init_db() -> None:
    """
    Inicializa la base de datos creando las tablas necesarias si no existen.

    Tablas:
    - `incidents`: almacena las incidencias recibidas y procesadas.
    - `errors`:    almacena los errores internos detectados por el STR.
    """
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user        TEXT    NOT NULL,
                type        TEXT    NOT NULL,
                severity    INTEGER NOT NULL,
                description TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                status      TEXT    NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                module     TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def save_incident(incident: dict) -> None:
    """
    Persiste una incidencia procesada en la base de datos.

    Args:
        incident: diccionario con las claves user, type, severity,
                  description, created_at y status.
    """
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            """
            INSERT INTO incidents (user, type, severity, description, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                incident["user"],
                incident["type"],
                incident["severity"],
                incident["description"],
                incident["created_at"],
                incident["status"],
            ),
        )
        await db.commit()


async def log_error(module: str, msg: str) -> None:
    """
    Registra un error interno del STR en la base de datos.

    Args:
        module: identificador del módulo que detectó el error
                (p. ej.: DEADLINE, SCHEDULER, CAPTURE, PROCESSING).
        msg:    descripción del error ocurrido.
    """
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO errors (module, message, created_at) VALUES (?, ?, ?)",
            (module, msg, str(datetime.datetime.utcnow())),
        )
        await db.commit()
