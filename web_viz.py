"""
WebViz — real-time web visualiser for the Fire AI explorer.

Serves a single-page canvas app at http://localhost:<PORT>.
State is pushed to the browser via Server-Sent Events (SSE) every ~150 ms.

Usage:
    viz = WebViz(get_state=my_callable)
    viz.start(port=5000)   # launches Flask in a daemon thread

get_state() must return a dict with:
    {
      "bounds":       {"min_x", "max_x", "min_y", "max_y"},
      "cells":        [[x, y, type], ...],
      "my_units":     [{id, x, y, type, water, hp}, ...],
      "enemy_units":  [{id, x, y, type, owner}, ...],
    }

Cell types: 0=unknown  1=empty  2=fire  3=water  4=obstacle
"""

import json
import threading
import time
from typing import Callable

from flask import Flask, Response


_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Fire AI – Map</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0e0e0e; color: #ddd; font-family: monospace;
       display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

#bar { padding: 6px 14px; background: #161616; border-bottom: 1px solid #2a2a2a;
       display: flex; gap: 20px; align-items: center; font-size: 13px; flex-shrink: 0; }
#bar b { color: #fff; }
.lbl { opacity: .55; font-size: 11px; margin-right: 2px; }
.v-fire  { color: #f74; }
.v-water { color: #59f; }
.v-obs   { color: #999; }
.v-enemy { color: #f55; }
.v-coord { color: #aaa; }
#status  { margin-left: auto; font-size: 12px; }

canvas { flex: 1; display: block; cursor: crosshair; }

#legend { padding: 5px 14px; background: #111; border-top: 1px solid #222;
          display: flex; gap: 14px; font-size: 11px; flex-shrink: 0;
          align-items: center; flex-wrap: wrap; }
.sw { width: 11px; height: 11px; display: inline-block;
      margin-right: 3px; vertical-align: middle; border-radius: 2px; }
.sw-circle { border-radius: 50%; }
#tip { margin-left: auto; opacity: .35; }
</style>
</head>
<body>

<div id="bar">
  <b>🔥 Fire AI</b>
  <span><span class="lbl">known</span><b id="s-known">0</b></span>
  <span><span class="lbl">fire</span><b id="s-fire" class="v-fire">0</b></span>
  <span><span class="lbl">water</span><b id="s-water" class="v-water">0</b></span>
  <span><span class="lbl">obstacles</span><b id="s-obs" class="v-obs">0</b></span>
  <span><span class="lbl">my units</span><b id="s-my">0</b></span>
  <span><span class="lbl">enemies</span><b id="s-enemy" class="v-enemy">0</b></span>
  <span><span class="lbl">coverage</span><b id="s-cov">—</b></span>
  <span><span class="lbl">cursor</span><b id="s-coord" class="v-coord">—</b></span>
  <span id="status">⏳ connecting…</span>
</div>

<canvas id="c"></canvas>

<div id="legend">
  <span><span class="sw" style="background:#181818;border:1px solid #333"></span>Unknown</span>
  <span><span class="sw" style="background:#8a8a8a"></span>Empty</span>
  <span><span class="sw" style="background:#e05020"></span>Fire</span>
  <span><span class="sw" style="background:#2060d0"></span>Water</span>
  <span><span class="sw" style="background:#303030;border:1px solid #555"></span>Obstacle</span>
  <span><span class="sw sw-circle" style="background:#ffee00"></span>Firefighter</span>
  <span><span class="sw sw-circle" style="background:#dd44ff"></span>Firetruck</span>
  <span><span class="sw sw-circle" style="background:#00ff88"></span>Firecopter</span>
  <span><span class="sw sw-circle" style="background:#ff3333"></span>Enemy</span>
  <span id="tip">scroll = zoom &nbsp;·&nbsp; drag = pan</span>
</div>

<script>
// ── constants ──────────────────────────────────────────────────────────────
const CELL_COLOR = ['#181818','#8a8a8a','#e05020','#2060d0','#303030'];

function myUnitColor(t) {
  t = (t||'').toLowerCase();
  if (t.includes('cop'))   return '#00ff88';
  if (t.includes('truck')) return '#dd44ff';
  return '#ffee00';
}

// ── viewport ───────────────────────────────────────────────────────────────
const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
let vx = 0, vy = 0, scale = 8;
let dragging = false, dragX = 0, dragY = 0;
let mouseX = 0, mouseY = 0, mouseIn = false;
let centred  = false;
let state    = null;

function toCanvas(cx, cy, b) {
  return [vx + (cx - b.min_x) * scale, vy + (cy - b.min_y) * scale];
}

// Inverse coordinate calculation
function toMap(px, py, b) {
  return [
    Math.floor((px - vx) / scale) + b.min_x,
    Math.floor((py - vy) / scale) + b.min_y
  ];
}

function autoCenter(b) {
  if (centred) return;
  centred = true;
  const W = canvas.offsetWidth, H = canvas.offsetHeight;
  const mW = b.max_x - b.min_x + 1, mH = b.max_y - b.min_y + 1;
  scale = Math.max(2, Math.min(Math.floor(W / mW), Math.floor(H / mH), 20));
  vx = Math.floor((W - mW * scale) / 2);
  vy = Math.floor((H - mH * scale) / 2);
}

function updateCursor() {
  const el = document.getElementById('s-coord');
  if (!state || !mouseIn) {
    el.textContent = '—';
    return;
  }
  const [cx, cy] = toMap(mouseX, mouseY, state.bounds);
  el.textContent = `${cx}, ${cy}`;
}

// ── render ─────────────────────────────────────────────────────────────────
function render() {
  if (!state) return;
  const { bounds: b, cells, my_units, enemy_units } = state;
  canvas.width  = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
  const W = canvas.width, H = canvas.height;

  ctx.fillStyle = '#0e0e0e';
  ctx.fillRect(0, 0, W, H);

  // cells (skip fully off-screen for big maps)
  for (const [x, y, t] of cells) {
    const [px, py] = toCanvas(x, y, b);
    if (px + scale < 0 || py + scale < 0 || px > W || py > H) continue;
    ctx.fillStyle = CELL_COLOR[t] ?? '#555';
    ctx.fillRect(px, py, scale, scale);
  }

  // grid lines when zoomed in
  if (scale >= 12) {
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth   = 0.5;
    const [,y0] = toCanvas(b.min_x, b.min_y, b);
    const [,y1] = toCanvas(b.min_x, b.max_y + 1, b);
    const [x0]  = toCanvas(b.min_x, b.min_y, b);
    const [x1]  = toCanvas(b.max_x + 1, b.min_y, b);
    for (let x = b.min_x; x <= b.max_x + 1; x++) {
      const [px] = toCanvas(x, 0, b);
      ctx.beginPath(); ctx.moveTo(px, y0); ctx.lineTo(px, y1); ctx.stroke();
    }
    for (let y = b.min_y; y <= b.max_y + 1; y++) {
      const [, py] = toCanvas(0, y, b);
      ctx.beginPath(); ctx.moveTo(x0, py); ctx.lineTo(x1, py); ctx.stroke();
    }
  }

  // enemy units
  for (const u of (enemy_units || [])) {
    const [px, py] = toCanvas(u.x, u.y, b);
    const r = Math.max(2, scale * 0.85);
    ctx.beginPath();
    ctx.arc(px + scale/2, py + scale/2, r, 0, Math.PI*2);
    ctx.fillStyle   = '#ff3333';
    ctx.fill();
    ctx.strokeStyle = '#ff0000';
    ctx.lineWidth   = 1;
    ctx.stroke();
    if (scale >= 8) {  // ×  marker
      const cx = px + scale/2, cy = py + scale/2;
      ctx.strokeStyle = 'rgba(255,255,255,0.8)';
      ctx.lineWidth   = 1;
      ctx.beginPath(); ctx.moveTo(cx-2, cy-2); ctx.lineTo(cx+2, cy+2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx+2, cy-2); ctx.lineTo(cx-2, cy+2); ctx.stroke();
    }
    if (scale >= 14) {  // owner label
      ctx.fillStyle = 'rgba(255,100,100,0.9)';
      ctx.font      = `${Math.max(7, scale * 0.5)}px monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(u.owner || '?', px + scale/2, py - 2);
    }
  }

  // my units
  for (const u of (my_units || [])) {
    const [px, py] = toCanvas(u.x, u.y, b);
    const r = Math.max(2, scale * 1.0);
    ctx.beginPath();
    ctx.arc(px + scale/2, py + scale/2, r, 0, Math.PI*2);
    ctx.fillStyle   = myUnitColor(u.type);
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.55)';
    ctx.lineWidth   = 1;
    ctx.stroke();
    if (scale >= 10) {  // unit id label
      ctx.fillStyle  = 'rgba(0,0,0,0.8)';
      ctx.font       = `${Math.max(7, scale * 0.55)}px monospace`;
      ctx.textAlign  = 'center';
      ctx.fillText(String(u.id), px + scale/2, py + scale * 1.3);
    }
  }

  // my targets
  for (const t of (state.my_targets || [])) {
    const [px, py] = toCanvas(t.x, t.y, b);
    const u = (state.my_units || []).find(u => u.id === t.uid);
    const uColor = u ? myUnitColor(u.type) : '#fff';
    ctx.strokeStyle = uColor;
    ctx.lineWidth = 2;
    ctx.strokeRect(px, py, scale, scale);
    if (scale >= 10) {
      ctx.fillStyle = uColor;
      ctx.font = `${Math.max(7, scale * 0.5)}px monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(String(t.uid), px + scale/2, py + scale/2 + 2);
    }
  }

  // stats
  let nfire=0, nwater=0, nobs=0, nknown=0;
  for (const [,,t] of cells) {
    if (t===2) nfire++; else if (t===3) nwater++; else if (t===4) nobs++;
    if (t>0) nknown++;
  }
  const mW = b.max_x - b.min_x + 1, mH = b.max_y - b.min_y + 1;
  document.getElementById('s-known').textContent = nknown;
  document.getElementById('s-fire').textContent  = nfire;
  document.getElementById('s-water').textContent = nwater;
  document.getElementById('s-obs').textContent   = nobs;
  document.getElementById('s-my').textContent    = (my_units||[]).length;
  document.getElementById('s-enemy').textContent = (enemy_units||[]).length;
  document.getElementById('s-cov').textContent   = (nknown/(mW*mH)*100).toFixed(1) + '%';
  
  updateCursor();
}

// ── SSE ────────────────────────────────────────────────────────────────────
const es = new EventSource('/events');
es.onmessage = e => {
  state = JSON.parse(e.data);
  autoCenter(state.bounds);
  const el = document.getElementById('status');
  el.textContent = '🟢 live';
  el.style.color = '#4f4';
  render();
};
es.onerror = () => {
  const el = document.getElementById('status');
  el.textContent = '🔴 disconnected';
  el.style.color = '#f44';
};

// ── zoom ───────────────────────────────────────────────────────────────────
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const f = e.deltaY < 0 ? 1.25 : 0.8;
  vx = e.offsetX - (e.offsetX - vx) * f;
  vy = e.offsetY - (e.offsetY - vy) * f;
  scale = Math.max(1, Math.min(64, scale * f));
  render();
}, { passive: false });

// ── pan & mouse ────────────────────────────────────────────────────────────
canvas.addEventListener('mousedown',  e => { dragging=true; dragX=e.clientX; dragY=e.clientY; });
canvas.addEventListener('mousemove',  e => {
  mouseX = e.offsetX; mouseY = e.offsetY; mouseIn = true;
  if (!dragging) { updateCursor(); return; }
  vx += e.clientX - dragX; vy += e.clientY - dragY;
  dragX = e.clientX; dragY = e.clientY;
  render();
});
canvas.addEventListener('mouseup',    () => dragging = false);
canvas.addEventListener('mouseleave', () => { dragging = false; mouseIn = false; updateCursor(); });
window.addEventListener('resize',     render);
</script>
</body>
</html>"""


# web_viz.py (Keep your imports and _HTML string at the top!)

class WebViz:
    """
    Serves the map visualiser at http://localhost:<port>.
    Call start() once; it launches Flask in a background daemon thread.
    """

    def __init__(self, map_info_obj):
        """
        Accepts the main map_info object and translates it automatically.
        """
        self.map = map_info_obj  # Store a reference to your map object
        self._app = Flask(__name__)
        self._app.add_url_rule('/', 'index', self._index)
        self._app.add_url_rule('/events', 'sse_stream', self._sse_stream)

    def _get_state(self):
        """Translates map_info data to WebViz JSON format automatically."""
        # Wrap in list() to prevent crashes if background thread updates map while reading
        fires = list(self.map.fires.keys())
        waters = list(self.map.water_sources.keys())
        obsticles = list(self.map.obsticles.keys())
        units = list(self.map.units.items())

        # 1. Calculate map bounds dynamically
        all_coords = fires + waters + obsticles + [(x, y) for _, (x, y) in units]
        
        if all_coords:
            all_x = [x for x, y in all_coords]
            all_y = [y for x, y in all_coords]
            bounds = {"min_x": min(all_x), "max_x": max(all_x), "min_y": min(all_y), "max_y": max(all_y)}
        else:
            bounds = {"min_x": 0, "max_x": 10, "min_y": 0, "max_y": 10} # Default before data arrives

        # 2. Build the cells array (2=fire, 3=water, 4=obstacle)
        cells = []
        for x, y in fires: cells.append([x, y, 2])
        for x, y in waters: cells.append([x, y, 3])
        for x, y in obsticles: cells.append([x, y, 4])

        # 3. Build units array
        my_units = [{"id": uid, "x": x, "y": y, "type": "firefighter", "water": 100, "hp": 100} for uid, (x, y) in units]

        return {
            "bounds": bounds,
            "cells": cells,
            "my_units": my_units,
            "enemy_units": []
        }

    def start(self, port: int = 5000) -> None:
        t = threading.Thread(
            target=lambda: self._app.run(
                host='0.0.0.0', port=port, debug=False, threaded=True,
                use_reloader=False,
            ),
            daemon=True,
        )
        t.start()
        print(f"[WebViz] Map visualizer running at http://localhost:{port}")

    # ── Flask routes ──────────────────────────────────────────────────────────

    def _index(self):
        return _HTML

    def _sse_stream(self):
        def generate():
            last = None
            while True:
                try:
                    s = json.dumps(self._get_state())
                except Exception as e:
                    time.sleep(0.3)
                    continue
                if s != last:
                    yield f"data: {s}\n\n"
                    last = s
                time.sleep(0.15)

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )