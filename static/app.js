// ══════════════════════════════════════════════
// app.js — Frontend del Sistema STR
// Auto-refresh: incidencias cada 2s, errores cada 3s, métricas cada 2s
// ══════════════════════════════════════════════


// ──────────────────────────────────────────────
// REGISTRO DE INCIDENCIA
// ──────────────────────────────────────────────

async function sendIncident() {
    const user = document.getElementById("user").value.trim();
    const desc = document.getElementById("desc").value.trim();

    if (!user || !desc) {
        document.getElementById("result").innerText = "⚠️ Usuario y descripción son obligatorios.";
        return;
    }

    const data = {
        user: user,
        description: desc,
        type: document.getElementById("type").value,
        severity: parseInt(document.getElementById("sev").value),
    };

    try {
        const res = await fetch("/incidents", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });

        const out = await res.json();

        if (res.status === 429) {
            document.getElementById("result").innerText = "⚠️ Solicitud rechazada: intervalo mínimo STR violado (< 10 ms).";
        } else {
            document.getElementById("result").innerText = "✅ Incidencia registrada: " + out.status;
        }
    } catch (err) {
        document.getElementById("result").innerText = "❌ Error de conexión: " + err.message;
    }
}


// ──────────────────────────────────────────────
// CARGA DE INCIDENCIAS (DASHBOARD)
// ──────────────────────────────────────────────

async function loadIncidents() {
    try {
        const res = await fetch("/api/incidents?limit=20");
        const data = await res.json();
        const tbody = document.getElementById("incidents");
        tbody.innerHTML = "";

        data.forEach(i => {
            const sevClass = `sev-${i.severity}`;
            tbody.innerHTML += `
                <tr class="${sevClass}">
                    <td>${i.id}</td>
                    <td>${i.user}</td>
                    <td>${i.type}</td>
                    <td>${i.severity}</td>
                    <td class="status">${i.status}</td>
                </tr>`;
        });
    } catch (err) {
        console.error("Error cargando incidencias:", err);
    }
}


// ──────────────────────────────────────────────
// CARGA DE ERRORES STR
// ──────────────────────────────────────────────

async function loadErrors() {
    try {
        const res = await fetch("/api/errors?limit=10");
        const data = await res.json();
        const ul = document.getElementById("errors");
        ul.innerHTML = "";

        if (data.length === 0) {
            ul.innerHTML = "<li style='color:#6b7280'>Sin errores registrados.</li>";
            return;
        }

        data.forEach(e => {
            ul.innerHTML += `<li><strong>[${e.module}]</strong> ${e.message}</li>`;
        });
    } catch (err) {
        console.error("Error cargando errores:", err);
    }
}


// ──────────────────────────────────────────────
// CARGA DE MÉTRICAS Y SEMÁFORO
// ──────────────────────────────────────────────

async function loadMetrics() {
    try {
        const res = await fetch("/metrics");
        const data = await res.json();
        const m = data.metrics;
        const sem = data.semaphore;

        document.getElementById("metrics").innerText =
            `Eventos: ${m.count} | Avg: ${m.avg_ms.toFixed(2)} ms | ` +
            `Max: ${m.max_ms.toFixed(2)} ms | Violaciones: ${m.violations} | ` +
            `Semáforo crítico: ${sem.available}/${sem.max} disponibles`;
    } catch (err) {
        console.error("Error cargando métricas:", err);
    }
}


// ──────────────────────────────────────────────
// PRUEBA DE ESTRÉS (desde el navegador)
// ──────────────────────────────────────────────

async function stressTest() {
    document.getElementById("result").innerText = "⚡ Ejecutando prueba de estrés...";

    for (let i = 0; i < 30; i++) {
        fetch("/incidents", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user: "stress_test",
                description: "Carga alta simulada desde el dashboard",
                type: "red",
                severity: 3,
            }),
        });
    }

    setTimeout(() => {
        document.getElementById("result").innerText = "✅ Prueba de estrés completada. Revisa métricas y errores.";
    }, 1500);
}


// ──────────────────────────────────────────────
// RESET DEL SISTEMA
// ──────────────────────────────────────────────

async function resetSystem() {
    if (!confirm("¿Confirmas que deseas limpiar todas las incidencias, errores y métricas?")) {
        return;
    }

    try {
        const res = await fetch("/api/reset", { method: "POST" });
        const out = await res.json();

        if (out.status === "system reset") {
            document.getElementById("result").innerText = "🧹 Sistema limpiado correctamente.";
            loadIncidents();
            loadErrors();
            loadMetrics();
        }
    } catch (err) {
        document.getElementById("result").innerText = "❌ Error al limpiar el sistema: " + err.message;
    }
}


// ──────────────────────────────────────────────
// AUTO-REFRESH
// ──────────────────────────────────────────────

loadIncidents();
loadErrors();
loadMetrics();

setInterval(loadIncidents, 2000);
setInterval(loadErrors,    3000);
setInterval(loadMetrics,   2000);
