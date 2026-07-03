# web.py - Embedded async web server
# Serves a dashboard with live readings + historical chart
# Uses uasyncio for non-blocking operation

import ujson
import uasyncio as asyncio
import config

# ------------------------------------------------------------------ #
#  HTML template (served once, then JS polls /data)                  #
# ------------------------------------------------------------------ #

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AirCube</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3a;
    --text: #e8eaf0;
    --sub: #8b8fa8;
    --good: #00ff41;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    padding: 20px;
    min-height: 100vh;
  }
  h1 {
    font-size: 1.4rem;
    font-weight: 600;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  #status-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #444;
    display: inline-block;
    transition: background 0.5s;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }
  .card .label {
    font-size: 0.75rem;
    color: var(--sub);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 8px;
  }
  .card .value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
  }
  .card .unit {
    font-size: 0.8rem;
    color: var(--sub);
    margin-top: 4px;
  }
  #co2-value { color: var(--good); }
  .chart-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 16px;
  }
  .chart-card h2 {
    font-size: 0.8rem;
    color: var(--sub);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 12px;
  }
  canvas { width: 100% !important; }
  #last-update {
    font-size: 0.75rem;
    color: var(--sub);
    text-align: right;
    margin-top: 8px;
  }
</style>
</head>
<body>

<h1>
  <span id="status-dot"></span>
  AirCube
</h1>

<div class="cards">
  <div class="card">
    <div class="label">CO&#8322;</div>
    <div class="value" id="co2-value">--</div>
    <div class="unit">ppm</div>
  </div>
  <div class="card">
    <div class="label">Temperature</div>
    <div class="value" id="temp-value">--</div>
    <div class="unit" id="temp-unit">°F</div>
  </div>
  <div class="card">
    <div class="label">Humidity</div>
    <div class="value" id="hum-value">--</div>
    <div class="unit">% RH</div>
  </div>
  <div class="card">
    <div class="label">Status</div>
    <div class="value" style="font-size:1rem;padding-top:6px;" id="status-value">--</div>
    <div class="unit" id="uptime-value"></div>
  </div>
</div>

<div class="chart-card">
  <h2>CO&#8322; History</h2>
  <canvas id="co2Chart" height="120"></canvas>
</div>

<div class="chart-card">
  <h2>Temperature &amp; Humidity History</h2>
  <canvas id="thChart" height="120"></canvas>
</div>

<div id="last-update">Never updated</div>

<script>
const chartDefaults = {
  responsive: true,
  animation: false,
  plugins: { legend: { labels: { color: '#8b8fa8', boxWidth: 12, font: { size: 11 } } } },
  scales: {
    x: { ticks: { color: '#8b8fa8', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: '#2a2d3a' } },
    y: { ticks: { color: '#8b8fa8', font: { size: 10 } }, grid: { color: '#2a2d3a' } }
  }
};

const co2Chart = new Chart(document.getElementById('co2Chart'), {
  type: 'line',
  data: { labels: [], datasets: [{
    label: 'CO2 (ppm)',
    data: [], borderColor: '#00ff41', backgroundColor: 'rgba(0,255,65,0.08)',
    borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3
  }]},
  options: {
    ...chartDefaults,
    scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 400 } }
  }
});

const thChart = new Chart(document.getElementById('thChart'), {
  type: 'line',
  data: { labels: [], datasets: [
    {
      label: 'Temp (°F)', data: [],
      borderColor: '#ff6b35', backgroundColor: 'transparent',
      borderWidth: 1.5, pointRadius: 0, tension: 0.3, yAxisID: 'yTemp'
    },
    {
      label: 'Humidity (%)', data: [],
      borderColor: '#4db8ff', backgroundColor: 'transparent',
      borderWidth: 1.5, pointRadius: 0, tension: 0.3, yAxisID: 'yHum'
    }
  ]},
  options: {
    ...chartDefaults,
    scales: {
      x: chartDefaults.scales.x,
      yTemp: { position: 'left',  ticks: { color: '#ff6b35', font: { size: 10 } }, grid: { color: '#2a2d3a' } },
      yHum:  { position: 'right', ticks: { color: '#4db8ff', font: { size: 10 } }, grid: { drawOnChartArea: false } }
    }
  }
});

function co2ToColor(ppm) {
  if (ppm <= 600)  return '#00ff41';
  if (ppm <= 800)  return '#b4ff00';
  if (ppm <= 1000) return '#ffb400';
  if (ppm <= 1500) return '#ff3c00';
  return '#ff0000';
}

function co2ToLabel(ppm) {
  if (ppm <= 600)  return 'Excellent';
  if (ppm <= 800)  return 'Good';
  if (ppm <= 1000) return 'Fair';
  if (ppm <= 1500) return 'Poor';
  return 'Bad — ventilate!';
}

async function poll() {
  try {
    const res = await fetch('/data');
    const d = await res.json();

    // Update cards
    const co2 = d.co2.toFixed(0);
    document.getElementById('co2-value').textContent = co2;
    document.getElementById('co2-value').style.color = co2ToColor(d.co2);
    document.getElementById('temp-value').textContent = d.temperature.toFixed(1);
    document.getElementById('hum-value').textContent = d.humidity.toFixed(1);
    document.getElementById('status-value').textContent = co2ToLabel(d.co2);

    const h = Math.floor(d.uptime / 3600);
    const m = Math.floor((d.uptime % 3600) / 60);
    document.getElementById('uptime-value').textContent = `up ${h}h ${m}m`;

    // Status dot
    const dot = document.getElementById('status-dot');
    dot.style.background = co2ToColor(d.co2);

    // Update charts
    const labels = d.history.map(p => p.t);
    co2Chart.data.labels = labels;
    co2Chart.data.datasets[0].data = d.history.map(p => p.c);
    co2Chart.data.datasets[0].borderColor = co2ToColor(d.co2);
    co2Chart.update();

    thChart.data.labels = labels;
    thChart.data.datasets[0].data = d.history.map(p => p.temp);
    thChart.data.datasets[1].data = d.history.map(p => p.hum);
    thChart.update();

    document.getElementById('last-update').textContent =
      'Updated: ' + new Date().toLocaleTimeString();

  } catch(e) {
    document.getElementById('status-dot').style.background = '#ff4444';
    console.error('Poll error:', e);
  }
}

poll();
setInterval(poll, 5000);
</script>
</body>
</html>
"""


# ------------------------------------------------------------------ #
#  Web server                                                         #
# ------------------------------------------------------------------ #

class WebServer:
    def __init__(self, data_store):
        """
        data_store: reference to the shared DataStore object in main.py
        """
        self._data = data_store
        self._port = config.WEB_PORT

    async def _handle_client(self, reader, writer):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            request = request_line.decode().strip()

            # Drain remaining headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=2)
                if line in (b'\r\n', b'', b'\n'):
                    break

            path = request.split(' ')[1] if ' ' in request else '/'

            if path == '/':
                body = HTML.encode()
                header = (
                    b'HTTP/1.1 200 OK\r\n'
                    b'Content-Type: text/html\r\n'
                    b'Connection: close\r\n'
                    b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n'
                )
                writer.write(header + body)

            elif path == '/data':
                payload = self._data.to_json()
                body = payload.encode()
                header = (
                    b'HTTP/1.1 200 OK\r\n'
                    b'Content-Type: application/json\r\n'
                    b'Connection: close\r\n'
                    b'Access-Control-Allow-Origin: *\r\n'
                    b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n'
                )
                writer.write(header + body)

            else:
                writer.write(b'HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n')

            await writer.drain()

        except Exception as e:
            print(f"[web] client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self):
        server = await asyncio.start_server(
            self._handle_client, '0.0.0.0', self._port
        )
        print(f"[web] listening on port {self._port}")
        async with server:
            await server.wait_closed()
