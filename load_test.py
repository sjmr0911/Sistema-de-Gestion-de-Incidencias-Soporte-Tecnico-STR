"""
load_test.py — Script de prueba de carga para el STR

Lanza 50 solicitudes concurrentes con intervalos de 5 ms (por debajo del
umbral mínimo de 10 ms) para forzar violaciones de tasa y observar el
comportamiento del sistema bajo carga extrema.

Uso:
    1. Iniciar el servidor: uvicorn main:app --reload --port 8000
    2. En otra terminal: python load_test.py

Resultados esperados:
    - HTTP 200: incidencia aceptada correctamente.
    - HTTP 429: violación de intervalo mínimo entre eventos (STR).
    - HTTP 503: backlog lleno / sistema sobrecargado.
    - ERR:      error de conexión (servidor no disponible).
"""

import requests
import time
import threading

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────

URL = "http://127.0.0.1:8000/incidents"

PAYLOAD = {
    "user": "load_test",
    "description": "Prueba de carga automatizada del sistema STR",
    "type": "red",
    "severity": 3,
}

TOTAL_REQUESTS = 50
INTERVAL_S = 0.005  # 5 ms entre solicitudes (fuerza violaciones STR)

# Contadores compartidos
results = {"ok": 0, "rate_limited": 0, "backlog_full": 0, "error": 0}
lock = threading.Lock()


# ──────────────────────────────────────────────
# FUNCIÓN DE ENVÍO
# ──────────────────────────────────────────────

def send_request(index: int) -> None:
    """Envía una solicitud POST y registra el resultado."""
    try:
        response = requests.post(URL, json=PAYLOAD, timeout=2)
        with lock:
            if response.status_code == 200:
                results["ok"] += 1
                print(f"[{index:02d}] ✅ 200 OK")
            elif response.status_code == 429:
                results["rate_limited"] += 1
                print(f"[{index:02d}] ⚠️  429 Rate Limited")
            elif response.status_code == 503:
                results["backlog_full"] += 1
                print(f"[{index:02d}] ⚠️ 503 Backlog Full")
            else:
                results["error"] += 1
                print(f"[{index:02d}] ❌ {response.status_code}")
    except Exception as exc:
        with lock:
            results["error"] += 1
            print(f"[{index:02d}] ❌ ERR — {exc}")


# ──────────────────────────────────────────────
# EJECUCIÓN
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Iniciando prueba de carga: {TOTAL_REQUESTS} solicitudes a {URL}")
    print(f"Intervalo entre solicitudes: {INTERVAL_S * 1000:.0f} ms\n")

    threads = []
    for i in range(TOTAL_REQUESTS):
        t = threading.Thread(target=send_request, args=(i + 1,))
        threads.append(t)
        t.start()
        time.sleep(INTERVAL_S)

    for t in threads:
        t.join()

    print("\n── Resultados ──────────────────────")
    print(f"  Aceptadas (200):      {results['ok']}")
    print(f"  Rate limited (429):   {results['rate_limited']}")
    print(f"  Backlog full (503):   {results['backlog_full']}")
    print(f"  Errores de conexión:  {results['error']}")
    print("────────────────────────────────────")
