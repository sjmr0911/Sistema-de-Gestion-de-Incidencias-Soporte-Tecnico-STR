async function sendIncident() {
    const data = {
        user: document.getElementById("user").value,
        description: document.getElementById("desc").value,
        type: document.getElementById("type").value,
        severity: parseInt(document.getElementById("sev").value)
    };

    const res = await fetch("/incidents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    });

    const out = await res.json();
    document.getElementById("result").innerText =
        "Resultado: " + out.status;
}

// 🔹 DASHBOARD

async function loadIncidents(){
    const res = await fetch("/api/incidents?limit=20");
    const data = await res.json();
    const tb = document.getElementById("incidents");
    tb.innerHTML = "";

    data.forEach(i=>{
        let color = "#e5e7eb"; // gris (default)

        if (i.severity === 4) color = "#fecaca";      // rojo (crítica)
        else if (i.severity === 3) color = "#fde68a"; // amarillo (alta)
        else if (i.severity === 2) color = "#bfdbfe"; // azul (media)
        else if (i.severity === 1) color = "#bbf7d0"; // verde (baja)

        tb.innerHTML += `<tr style="background:${color}">
          <td>${i.id}</td>
          <td>${i.user}</td>
          <td>${i.type}</td>
          <td>${i.severity}</td>
          <td>${i.status}</td>
        </tr>`;
    });
}


async function loadErrors(){
    const res = await fetch("/api/errors?limit=10");
    const data = await res.json();
    const ul = document.getElementById("errors");
    ul.innerHTML = "";
    data.forEach(e=>{
        ul.innerHTML += `<li>[${e.module}] ${e.message}</li>`;
    });
}

async function loadMetrics(){
    const r = await fetch("/api/metrics");
    const m = await r.json();
    document.getElementById("metrics").innerText =
        `Eventos: ${m.count} | Avg(ms): ${m.avg_ms.toFixed(2)} | Max(ms): ${m.max_ms.toFixed(2)} | Violaciones: ${m.violations}`;
}

async function stressTest(){
    for(let i = 0; i < 30; i++){
        fetch("/incidents", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user: "stress",
                description: "Carga alta simulada",
                type: "red",
                severity: 3
            })
        });
    }
}

async function resetSystem(){
    await fetch("/api/reset", { method: "POST" });
    alert("Sistema limpiado");
}

async function resetSystem(){
    const res = await fetch("/api/reset", { method: "POST" });
    const out = await res.json();

    if(out.status === "system reset"){
        alert("Sistema limpiado correctamente");
    }
}



// 🔁 AUTO-REFRESH
setInterval(loadIncidents, 2000);
setInterval(loadErrors, 3000);
setInterval(loadMetrics, 2000);
