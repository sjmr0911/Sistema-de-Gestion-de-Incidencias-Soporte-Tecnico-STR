from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import sqlite3

from models import IncidentIn
from scheduler import submit_incident, scheduler
from database import init_db
from scheduler import submit_incident, scheduler, METRICS, reset_metrics


import asyncio
import time

app = FastAPI(title="STR Support System")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def start():
    await init_db()
    asyncio.create_task(scheduler())

@app.post("/incidents")
async def create_incident(i: IncidentIn):
    data = i.dict()
    data["created_at"] = time.time()
    data["status"] = "RECEIVED"

    try:
        await submit_incident(-i.severity, data)
    except:
        raise HTTPException(429, "Too many events (STR interval violated)")

    return {"status": "accepted"}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

def get_db():
    return sqlite3.connect("incidents.db")

@app.get("/api/incidents")
async def list_incidents(limit: int = 50):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user, type, severity, description, created_at, status
        FROM incidents
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "user": r[1], "type": r[2], "severity": r[3],
            "description": r[4], "created_at": r[5], "status": r[6]
        } for r in rows
    ]
    
@app.get("/api/errors")
async def list_errors(limit: int = 50):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT module, message, created_at
        FROM errors
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [{"module": r[0], "message": r[1], "created_at": r[2]} for r in rows]


@app.get("/api/metrics")
async def metrics():
    return METRICS

@app.get("/api/history")
async def history(limit: int = 50):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user, type, severity, description, created_at, status
        FROM incidents
        ORDER BY id ASC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

@app.post("/api/reset")
async def reset_system():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM incidents")
    cur.execute("DELETE FROM errors")

    conn.commit()
    conn.close()

    reset_metrics()

    return {"status": "system reset"}

