import aiosqlite
import datetime

DB = "incidents.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS incidents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            type TEXT,
            severity INTEGER,
            description TEXT,
            created_at TEXT,
            status TEXT
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS errors(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT,
            message TEXT,
            created_at TEXT
        )""")
        await db.commit()

async def save_incident(i):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO incidents(user,type,severity,description,created_at,status)
        VALUES(?,?,?,?,?,?)
        """, (i["user"],i["type"],i["severity"],i["description"],i["created_at"],i["status"]))
        await db.commit()

async def log_error(module, msg):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO errors VALUES(null,?,?,?)",
                         (module,msg,str(datetime.datetime.utcnow())))
        await db.commit()
