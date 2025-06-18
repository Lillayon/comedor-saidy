"""
Comedero Automático – Backend FastAPI
-------------------------------------
• POST  /api/v1/event       → registra una porción servida
• GET   /api/v1/historial   → últimos eventos (param “limit”)
• POST  /api/v1/schedule    → crea un horario (HH:MM)
• GET   /api/v1/schedule    → lista horarios para un feeder
• DELETE /api/v1/schedule   → elimina un horario (“time” en query)
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, time
from contextlib import closing
import psycopg2

# ─────────────────────────── Configuración ────────────────────────────
DB_CONFIG = dict(
    dbname="comedero_ilmx",
    user="comedero_ilmx_user",
    password="XM6kCJKK0eXYbvzKzeBUJzHwpeshgnMO",          # ← cambia por tu contraseña
    host="dpg-d192bhvdiees73aefn7g-a.oregon-postgres.render.com",
    port=5432,
)

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",            # Live Server local
    "https://comedor-wlrm.vercel.app/" # tu dominio (si lo despliegas)
]

app = FastAPI(title="Comedero Automático API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────── Modelos Pydantic ─────────────────────────
class Event(BaseModel):
    feeder_id: int
    portion_grams: int

class ScheduleRequest(BaseModel):
    feeder_id: int
    time: str            # formato "HH:MM" (24 h)

# ─────────────────────────── Helper conexión ──────────────────────────
def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ─────────────────────────── Helper tabla horarios ────────────────────
def ensure_feed_schedules(cur):
    """Crea la tabla feed_schedules si no existe."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feed_schedules (
          id SERIAL PRIMARY KEY,
          feeder_id INT REFERENCES feeders(id),
          feed_time TIME NOT NULL,
          UNIQUE (feeder_id, feed_time)
        );
    """)

# ─────────────────────────── Endpoint: registrar evento ───────────────
@app.post("/api/v1/event")
def post_event(event: Event):
    now = datetime.now()

    with closing(get_conn()) as conn, conn.cursor() as cur:
        # 1. validar que exista el feeder
        cur.execute("SELECT 1 FROM feeders WHERE id=%s", (event.feeder_id,))
        if cur.fetchone() is None:
            raise HTTPException(404, "feeder_id no existe")

        # 2. insertar el evento
        cur.execute("""
            INSERT INTO feeding_events (feeder_id, served_at, portion_grams)
            VALUES (%s, %s, %s)
        """, (event.feeder_id, now, event.portion_grams))
        conn.commit()

    return {"status": "ok", "timestamp": now.isoformat()}

# ─────────────────────────── Endpoint: historial ──────────────────────
@app.get("/api/v1/historial")
def get_historial(limit: int = 10):
    if limit < 1:
        raise HTTPException(400, "limit debe ser ≥ 1")

    with closing(get_conn()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, feeder_id, served_at, portion_grams
            FROM feeding_events
            ORDER BY served_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "feeder_id": r[1],
            "served_at": r[2],
            "portion_grams": r[3],
        } for r in rows
    ]

# ─────────────────────────── Endpoint: crear horario ──────────────────
@app.post("/api/v1/schedule")
def set_schedule(req: ScheduleRequest):
    # validar hora HH:MM
    try:
        hora_obj: time = datetime.strptime(req.time, "%H:%M").time()
    except ValueError:
        raise HTTPException(400, "Hora inválida. Usa formato HH:MM (24h)")

    with closing(get_conn()) as conn, conn.cursor() as cur:
        ensure_feed_schedules(cur)
        # insertar o ignorar si ya existe
        cur.execute("""
            INSERT INTO feed_schedules (feeder_id, feed_time)
            VALUES (%s, %s)
            ON CONFLICT (feeder_id, feed_time) DO NOTHING
        """, (req.feeder_id, hora_obj))
        conn.commit()

    return {"status": "programado", "time": hora_obj.strftime("%H:%M")}

# ─────────────────────────── Endpoint: listar horarios ────────────────
@app.get("/api/v1/schedule")
def get_schedules(feeder_id: int = 1):
    with closing(get_conn()) as conn, conn.cursor() as cur:
        ensure_feed_schedules(cur)
        cur.execute("""
            SELECT feed_time
            FROM feed_schedules
            WHERE feeder_id=%s
            ORDER BY feed_time
        """, (feeder_id,))
        horas = [r[0].strftime("%H:%M") for r in cur.fetchall()]
    return horas

# ─────────────────────────── Endpoint: eliminar horario ───────────────
@app.delete("/api/v1/schedule")
def delete_schedule(feeder_id: int, time: str):
    try:
        hora_obj: time = datetime.strptime(time, "%H:%M").time()
    except ValueError:
        raise HTTPException(400, "Hora inválida. Usa formato HH:MM (24h)")

    with closing(get_conn()) as conn, conn.cursor() as cur:
        ensure_feed_schedules(cur)
        cur.execute("""
            DELETE FROM feed_schedules
            WHERE feeder_id=%s AND feed_time=%s
        """, (feeder_id, hora_obj))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Horario no encontrado")

    return {"status": "eliminado", "time": time}

# ─────────────────────────── Inicio local ─────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
