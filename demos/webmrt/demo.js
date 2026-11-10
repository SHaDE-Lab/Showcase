/* WebMRT demo widget  ·  window.UHDemos.webmrt.mount(containerEl)

   Runs the *released example model* (LightGBM trained on data/sample_RF_Data.csv, exported by
   codebases/webmrt/run_demo.py) entirely in the browser:
     - core.evaluate()  : tree-ensemble evaluator (parity-tested against Python to 1e-6, see parity.test.mjs)
     - core.solarPosition(): NOAA/Meeus solar position for Phoenix (parity-tested against pvlib)
   Features are built exactly like the deployed tool: solar altitude + minutes from its fixed reference sunrise. */
(function () {
  "use strict";
  const g = typeof window !== "undefined" ? window : globalThis;
  g.UHDemos = g.UHDemos || {};
  const SCRIPT_URL = typeof document !== "undefined" && document.currentScript ? document.currentScript.src : "";

  /* =========================== CORE (no DOM) =========================== */
  const RAD = Math.PI / 180;

  /** Sum of leaf values over all trees; LightGBM numerical splits go left when x <= threshold. */
  function evaluate(model, row) {
    let s = 0;
    for (const t of model.trees) {
      let n = t.root;
      while (n >= 0) n = row[t.f[n]] <= t.t[n] ? t.l[n] : t.r[n];
      s += t.v[~n];
    }
    return s;
  }

  function julianDay(y, mo, d, hUTC) {          // Gregorian calendar, hUTC may exceed 24 or be negative
    if (mo <= 2) { y -= 1; mo += 12; }
    const A = Math.floor(y / 100), B = 2 - A + Math.floor(A / 4);
    return Math.floor(365.25 * (y + 4716)) + Math.floor(30.6001 * (mo + 1)) + d + B - 1524.5 + hUTC / 24;
  }

  /** NOAA solar position (geometric elevation, azimuth clockwise from north). Local clock = UTC + utcOffsetHours. */
  function solarPosition(y, mo, d, hour, minute, lat, lon, utcOffsetHours) {
    const hUTC = hour + minute / 60 - utcOffsetHours;
    const T = (julianDay(y, mo, d, hUTC) - 2451545) / 36525;
    const L0 = (((280.46646 + T * (36000.76983 + T * 0.0003032)) % 360) + 360) % 360;
    const M = 357.52911 + T * (35999.05029 - 0.0001537 * T);
    const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
    const C = Math.sin(M * RAD) * (1.914602 - T * (0.004817 + 0.000014 * T)) +
      Math.sin(2 * M * RAD) * (0.019993 - 0.000101 * T) + Math.sin(3 * M * RAD) * 0.000289;
    const omega = 125.04 - 1934.136 * T;
    const lam = L0 + C - 0.00569 - 0.00478 * Math.sin(omega * RAD);
    const eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60;
    const eps = eps0 + 0.00256 * Math.cos(omega * RAD);
    const decl = Math.asin(Math.sin(eps * RAD) * Math.sin(lam * RAD));
    const yy = Math.tan(eps * RAD / 2) ** 2;
    const eot = 4 / RAD * (yy * Math.sin(2 * L0 * RAD) - 2 * e * Math.sin(M * RAD) +
      4 * e * yy * Math.sin(M * RAD) * Math.cos(2 * L0 * RAD) - 0.5 * yy * yy * Math.sin(4 * L0 * RAD) -
      1.25 * e * e * Math.sin(2 * M * RAD));
    const tst = (((hUTC * 60 + eot + 4 * lon) % 1440) + 1440) % 1440;
    const H = tst / 4 - 180, phi = lat * RAD;
    const cosZ = Math.sin(phi) * Math.sin(decl) + Math.cos(phi) * Math.cos(decl) * Math.cos(H * RAD);
    const Z = Math.acos(Math.min(1, Math.max(-1, cosZ)));
    let az = Math.acos(Math.min(1, Math.max(-1, (Math.sin(phi) * Math.cos(Z) - Math.sin(decl)) / (Math.cos(phi) * Math.sin(Z)))));
    az = (H > 0 ? az / RAD + 180 : 540 - az / RAD) % 360;
    return { elevation: 90 - Z / RAD, azimuth: az };
  }

  function parseDate(date) { const p = date.split("-").map(Number); return { y: p[0], mo: p[1], d: p[2] }; }
  function parseTime(time) { const p = time.split(":").map(Number); return { h: p[0], mi: p[1] }; }

  /** Minutes between the chosen local date-time and the deployed tool's fixed reference sunrise (int(), toward zero). */
  function minFromSunrise(model, date, time) {
    const a = parseDate(date), t = parseTime(time);
    const [sd, st] = model.sunrise_as_deployed.split(" "), s = parseDate(sd), s2 = st.split(":").map(Number);
    const ms = Date.UTC(a.y, a.mo - 1, a.d, t.h, t.mi, 0) - Date.UTC(s.y, s.mo - 1, s.d, s2[0], s2[1], s2[2]);
    return Math.trunc(ms / 60000);
  }

  function buildRow(model, inp) {
    const d = parseDate(inp.date), t = parseTime(inp.time), site = model.site;
    const sp = solarPosition(d.y, d.mo, d.d, t.h, t.mi, site.latitude, site.longitude, site.utc_offset_hours);
    return {
      row: [inp.svf, inp.trees, inp.buildings, inp.pervious, inp.shaded, inp.airC, sp.elevation,
        minFromSunrise(model, inp.date, inp.time)],
      sun: sp,
    };
  }

  function predict(model, inp) { const r = buildRow(model, inp); return { tmrt: evaluate(model, r.row), sun: r.sun, row: r.row }; }

  g.UHDemos.webmrt = g.UHDemos.webmrt || {};
  g.UHDemos.webmrt.core = { evaluate, solarPosition, minFromSunrise, buildRow, predict };

  if (typeof document === "undefined") return;     // loaded by node for the parity test

  /* =========================== WIDGET =========================== */
  const BASE = SCRIPT_URL.replace(/[^/]*$/, "");
  const $ = (el, s) => el.querySelector(s);
  const cvar = (el, v) => getComputedStyle(el).getPropertyValue(v).trim();
  const fmtT = (m) => { const h = Math.floor(m / 60), mm = m % 60; return String(h).padStart(2, "0") + ":" + String(mm).padStart(2, "0"); };
  const cToF = (c) => c * 9 / 5 + 32, fToC = (f) => (f - 32) * 5 / 9;
  const TRAIN = { svf: [0.001, 0.934], trees: [0, 0.539], buildings: [0, 0.856] };   // ranges of the training table

  const HTML = `
  <div class="uhwm">
    <p class="uhwm-banner">This is the released example model (LightGBM, same code and
      parameters as WebMRT) running in your browser. It is trained on a 451-row sample of the field data, so it is a
      demonstration; the live WebMRT tool uses the full dataset.</p>
    <div class="uhwm-grid">
      <div class="uhwm-col uhwm-left">
        <div class="uhwm-grp">
        <h4>Surroundings</h4>
        <canvas class="uhwm-pad" tabindex="0" role="application"
          aria-label="Ternary pad: drag to set the share of sky, trees and buildings. Arrow keys also work."></canvas>
        <div class="uhwm-fr"><span><i class="s"></i>Sky <b data-o="sky"></b></span><span><i class="t"></i>Trees <b data-o="trees"></b></span><span><i class="b"></i>Buildings <b data-o="bld"></b></span></div>
        <p class="uhwm-warn" hidden>Outside the range of the training data, so the model is extrapolating.</p>
        </div>
        <div class="uhwm-grp">
        <h4>Conditions</h4>
        <label class="uhwm-row">Air temperature
          <input type="range" data-i="air" min="26" max="44" step="0.5" value="38"><output data-o="air"></output></label>
        <div class="uhwm-seg" role="group" aria-label="Temperature unit"><button type="button" data-u="C" aria-pressed="true">°C</button><button type="button" data-u="F" aria-pressed="false">°F</button></div>
        <label class="uhwm-row">Date <input type="date" data-i="date" min="2023-06-01" max="2023-08-31" value="2023-07-15"></label>
        <label class="uhwm-row">Time <input type="range" data-i="time" min="300" max="1200" step="5" value="780"><output data-o="time"></output></label>
        </div>
        <div class="uhwm-grp">
        <h4>Ground and shade</h4>
        <label class="uhwm-row">Pervious ground <input type="range" data-i="perv" min="0" max="1" step="0.01" value="0.5"><output data-o="perv"></output></label>
        <label class="uhwm-row chk"><input type="checkbox" data-i="shaded"> Shaded at the spot</label>
        </div>
      </div>
      <div class="uhwm-col">
        <div class="uhwm-big"><span class="num" data-o="tmrt">–</span><span class="unit">°C Tmrt</span><span class="f" data-o="tmrtF"></span></div>
        <div class="uhwm-sub" data-o="sunline"></div>
        <canvas class="uhwm-curve" aria-label="Predicted Tmrt through the day for shaded and unshaded conditions"></canvas>
        <p class="uhwm-cap uhwm-curve-cap">Predicted Tmrt through the day for the current surroundings: solid is your setting, dashed is the opposite shade state. Faint stretches: sun below the horizon, where the model has almost no field data and is extrapolating.</p>
        <div class="uhwm-metrics"></div>
      </div>
    </div>
    <details class="uhwm-about"><summary>Held-out check of the sample model</summary>
      <div class="uhwm-pair">
        <figure>
          <h4 class="uhwm-h">Observed vs. predicted (held-out rows)</h4>
          <canvas class="uhwm-scatter" aria-label="Held-out observed versus predicted Tmrt"></canvas>
          <figcaption class="uhwm-cap">Each dot is a held-out field measurement that the sample model never saw (30% split). The paper's numbers are for the full model and full dataset; the sample model is expected to be a little weaker.</figcaption>
        </figure>
        <figure>
          <h4 class="uhwm-h">Feature importance (gain)</h4>
          <canvas class="uhwm-imp" aria-label="How often each input is used by the model's trees"></canvas>
          <figcaption class="uhwm-cap">LightGBM gain importance: how much of the model's total error reduction comes from splits on each input, summed over the 200 trees of the sample model. It describes the trained model, not a causal effect. Minutes-from-sunrise is computed exactly as the live tool does (a fixed reference sunrise), so it carries no day-length information here.</figcaption>
        </figure>
      </div>
    </details>
  </div>`;

  function mount(container) {
    container.innerHTML = HTML;
    const root = $(container, ".uhwm");
    const st = { s: 0.5, t: 0.25, b: 0.25, unit: "C", model: null, golden: null };
    const inp = (n) => $(root, `[data-i="${n}"]`), out = (n) => $(root, `[data-o="${n}"]`);

    Promise.all([fetch(BASE + "data/model.json").then((r) => r.json()), fetch(BASE + "data/golden.json").then((r) => r.json())])
      .then(([m, gd]) => { st.model = m; st.golden = gd; fillMetrics(); update(); })
      .catch(() => { $(root, ".uhwm-banner").textContent = "Could not load the model files. Serve this page over http(s) (not file://)."; });

    function current(shadedOverride) {
      const airUI = parseFloat(inp("air").value), airC = st.unit === "F" ? fToC(airUI) : airUI;
      const mins = +inp("time").value;
      return { date: inp("date").value, time: fmtT(mins), svf: st.s, trees: st.t, buildings: st.b,
        pervious: +inp("perv").value, shaded: shadedOverride === undefined ? (inp("shaded").checked ? 1 : 0) : shadedOverride, airC };
    }

    /* ---- ternary pad ---- */
    const pad = $(root, ".uhwm-pad"), pctx = pad.getContext("2d");
    let dragging = false;
    function padGeom() {
      const w = pad.clientWidth, h = Math.round(w * 0.88), dpr = Math.min(devicePixelRatio || 1, 2);
      if (pad.width !== Math.round(w * dpr)) { pad.width = Math.round(w * dpr); pad.height = Math.round(h * dpr); pad.style.height = h + "px"; }
      const m = 26, top = [w / 2, m], bl = [m, h - m], br = [w - m, h - m];
      return { w, h, dpr, top, bl, br };
    }
    /* ---- knob trail: a glowing tail that tapers and dissolves fast ---- */
    const TAIL_MS = 380, path = [];
    let lastBary = null, trailRaf = 0;
    const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
    function spawnTrail(G) {
      const cur = [st.s, st.t, st.b], at = (b) => [b[0] * G.top[0] + b[1] * G.bl[0] + b[2] * G.br[0], b[0] * G.top[1] + b[1] * G.bl[1] + b[2] * G.br[1]];
      if (lastBary && !calm) {
        const d = Math.hypot(cur[0] - lastBary[0], cur[1] - lastBary[1], cur[2] - lastBary[2]);   // moved in share space, so a resize adds nothing
        if (d > 1e-4) {
          const n = Math.min(20, Math.max(1, Math.ceil(d * G.w / 4))), now = performance.now();
          for (let k = 1; k <= n; k++) {
            const f = k / n, t = now - (n - k) * 4;
            const [x, y] = at([lastBary[0] + (cur[0] - lastBary[0]) * f, lastBary[1] + (cur[1] - lastBary[1]) * f, lastBary[2] + (cur[2] - lastBary[2]) * f]);
            path.push({ x, y, t });
          }
        }
      }
      lastBary = cur;
    }
    function drawTrail(c, kx, ky) {
      const now = performance.now(), a1 = cvar(root, "--accent") || "#8a63ff", a2 = cvar(root, "--accent-2") || "#ffd23f";
      for (let i = path.length - 1; i >= 0; i--) if (now - path[i].t > TAIL_MS) path.splice(i, 1);
      const dark = document.documentElement.dataset.theme === "dark", core = dark ? "#ffffff" : a2;
      c.save(); c.globalCompositeOperation = dark ? "lighter" : "source-over"; c.lineCap = "round"; c.lineJoin = "round";
      // halo that pulses around the knob while it is moving
      if (path.length) {
        const k = 1 - Math.min(1, (now - path[path.length - 1].t) / TAIL_MS), g = c.createRadialGradient(kx, ky, 0, kx, ky, 34);
        g.addColorStop(0, a1); g.addColorStop(1, dark ? "rgba(0,0,0,0)" : "rgba(255,255,255,0)"); c.globalAlpha = 0.38 * k; c.fillStyle = g; c.beginPath(); c.arc(kx, ky, 34, 0, 7); c.fill();
      }
      // tapered ribbon: soft wide glow + bright thin core, older points thinner and fainter
      for (let pass = 0; pass < 2; pass++) {
        for (let i = 1; i < path.length; i++) {
          const f = Math.max(0, now - path[i].t) / TAIL_MS, w = 10 * Math.pow(1 - f, 1.3) + 0.4, al = Math.pow(1 - f, 1.5);
          c.globalAlpha = pass ? al * 0.95 : al * 0.28; c.strokeStyle = pass ? (f < 0.35 ? core : a2) : (f < 0.5 ? a1 : a2);
          c.lineWidth = pass ? w * 0.38 : w * 2.1;
          c.beginPath(); c.moveTo(path[i - 1].x, path[i - 1].y); c.lineTo(path[i].x, path[i].y); c.stroke();
        }
      }
      c.restore();
    }
    function drawPad() {
      const G = padGeom(), c = pctx; c.setTransform(G.dpr, 0, 0, G.dpr, 0, 0); c.clearRect(0, 0, G.w, G.h);
      const line = cvar(root, "--line") || "#ccc", ink = cvar(root, "--ink") || "#222", muted = cvar(root, "--muted") || "#777";
      const grad = c.createLinearGradient(0, G.top[1], 0, G.bl[1]);
      grad.addColorStop(0, "rgba(63,134,230,.30)"); grad.addColorStop(1, "rgba(120,120,130,.22)");
      c.beginPath(); c.moveTo(...G.top); c.lineTo(...G.bl); c.lineTo(...G.br); c.closePath(); c.fillStyle = grad; c.fill();
      c.strokeStyle = muted; c.lineWidth = 2; c.globalAlpha = 0.4;      // inner 20% grid: thicker, softer than the outline
      const B = (s, t, b) => [s * G.top[0] + t * G.bl[0] + b * G.br[0], s * G.top[1] + t * G.bl[1] + b * G.br[1]];
      for (let k = 1; k < 5; k++) {           // 20% grid: lines of constant sky, trees and buildings
        const f = k / 5;
        [[B(f, 1 - f, 0), B(f, 0, 1 - f)], [B(1 - f, f, 0), B(0, f, 1 - f)], [B(1 - f, 0, f), B(0, 1 - f, f)]].forEach(([p1, p2]) => {
          c.beginPath(); c.moveTo(...p1); c.lineTo(...p2); c.stroke();
        });
      }
      c.globalAlpha = 1;
      c.beginPath(); c.moveTo(...G.top); c.lineTo(...G.bl); c.lineTo(...G.br); c.closePath(); c.strokeStyle = muted; c.lineWidth = 1.5; c.stroke();
      c.font = "600 12px Inter,system-ui,sans-serif"; c.fillStyle = ink; c.textAlign = "center";
      c.fillText("Sky", G.top[0], G.top[1] - 9); c.fillText("Trees", G.bl[0] + 6, G.bl[1] + 18); c.fillText("Buildings", G.br[0] - 14, G.br[1] + 18);
      const x = st.s * G.top[0] + st.t * G.bl[0] + st.b * G.br[0], y = st.s * G.top[1] + st.t * G.bl[1] + st.b * G.br[1];
      spawnTrail(G); drawTrail(c, x, y);
      c.beginPath(); c.arc(x, y, 9, 0, 7); c.fillStyle = cvar(root, "--accent") || "#c8321f"; c.fill(); c.lineWidth = 3; c.strokeStyle = "#fff"; c.stroke();
      if (path.length && !trailRaf) trailRaf = requestAnimationFrame(() => { trailRaf = 0; drawPad(); });
    }
    function setFromPointer(e) {
      const G = padGeom(), r = pad.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
      const [x1, y1] = G.top, [x2, y2] = G.bl, [x3, y3] = G.br, den = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3);
      let s = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / den;
      let t = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / den;
      let b = 1 - s - t; s = Math.max(0, s); t = Math.max(0, t); b = Math.max(0, b);
      const sum = s + t + b || 1; st.s = s / sum; st.t = t / sum; st.b = b / sum; update();
    }
    pad.addEventListener("pointerdown", (e) => { dragging = true; pad.setPointerCapture(e.pointerId); setFromPointer(e); });
    pad.addEventListener("pointermove", (e) => { if (dragging) setFromPointer(e); });
    pad.addEventListener("pointerup", () => (dragging = false));
    pad.addEventListener("keydown", (e) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
      e.preventDefault(); const step = 0.02;
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {        // more / less sky, the rest shrinks proportionally
        const ns = Math.min(1, Math.max(0, st.s + (e.key === "ArrowUp" ? step : -step))), rest = st.t + st.b, left = 1 - ns;
        if (rest > 0) { st.t = st.t / rest * left; st.b = st.b / rest * left; } else { st.t = st.b = left / 2; }
        st.s = ns;
      } else {                                                    // move share between trees and buildings
        const d = e.key === "ArrowLeft" ? step : -step, pair = st.t + st.b, nt = Math.min(pair, Math.max(0, st.t + d));
        st.t = nt; st.b = pair - nt;
      }
      update();
    });

    /* ---- curve ---- */
    const curve = $(root, ".uhwm-curve"), kctx = curve.getContext("2d");
    function drawCurve(inpv, tmrtNow, mins) {
      const w = curve.clientWidth, h = Math.round(w * 0.56), dpr = Math.min(devicePixelRatio || 1, 2);
      if (curve.width !== Math.round(w * dpr)) { curve.width = Math.round(w * dpr); curve.height = Math.round(h * dpr); curve.style.height = h + "px"; }
      const c = kctx; c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
      const pl = 40, pr = 20, pt = 10, pb = 26, X = (m) => pl + (m - 300) / 900 * (w - pl - pr);
      const series = (sh) => { const a = []; for (let m = 300; m <= 1200; m += 15) { const r = predict(st.model, { ...inpv, time: fmtT(m), shaded: sh }); a.push([m, r.tmrt, r.sun.elevation > 0]); } return a; };
      const mine = series(inpv.shaded), other = series(inpv.shaded ? 0 : 1);
      const all = mine.concat(other).map((p) => p[1]), lo = Math.floor(Math.min(...all) / 10) * 10, hi = Math.ceil(Math.max(...all) / 10) * 10;
      const Y = (v) => pt + (1 - (v - lo) / (hi - lo)) * (h - pt - pb);
      const line = cvar(root, "--line") || "#ccc", muted = cvar(root, "--muted") || "#777";
      c.font = "11px Inter,system-ui,sans-serif"; c.fillStyle = muted; c.strokeStyle = line; c.lineWidth = 1; c.textAlign = "right";
      for (let v = lo; v <= hi; v += 10) { c.beginPath(); c.moveTo(pl, Y(v)); c.lineTo(w - pr, Y(v)); c.stroke(); c.fillText(v + "°", pl - 6, Y(v) + 4); }
      c.textAlign = "center"; for (let hr = 6; hr <= 20; hr += 2) c.fillText(hr + ":00", X(hr * 60), h - 8);
      // sun below the horizon: the field data has almost no such conditions, so those stretches are drawn faint
      const path = (pts, col, wd, dash) => {
        c.strokeStyle = col; c.lineWidth = wd; c.setLineDash(dash || []);
        for (let i = 1; i < pts.length; i++) {
          c.globalAlpha = pts[i][2] && pts[i - 1][2] ? 1 : 0.25;
          c.beginPath(); c.moveTo(X(pts[i - 1][0]), Y(pts[i - 1][1])); c.lineTo(X(pts[i][0]), Y(pts[i][1])); c.stroke();
        }
        c.globalAlpha = 1; c.setLineDash([]);
      };
      path(other, muted, 1.6, [5, 4]); path(mine, cvar(root, "--accent") || "#c8321f", 2.6);
      c.strokeStyle = cvar(root, "--ink") || "#222"; c.lineWidth = 1; c.setLineDash([2, 3]); c.beginPath(); c.moveTo(X(mins), pt); c.lineTo(X(mins), h - pb); c.stroke(); c.setLineDash([]);
      c.fillStyle = cvar(root, "--accent") || "#c8321f"; c.beginPath(); c.arc(X(mins), Y(tmrtNow), 5, 0, 7); c.fill();
    }

    /* ---- held-out metrics + scatter ---- */
    function fillMetrics() {
      const m = st.golden.metrics, p = st.golden.paper_metrics, tr = st.golden.training;
      // Other SHaDE Lab models, as published ("–" = not reported).
      // VisionMRT: accepted, Sustainable Cities and Society; 1,174 records at 132 Phoenix-area sites.
      // PINN-MRT: Shaeri et al. ICCV Workshops 2025 / arXiv:2503.08482, best configurations (abstract).
      const rows = [
        ["This sample model", `${tr.n_train} train / ${tr.n_test} held-out rows`, m.r2, m.rmse],
        ["WebMRT, published full model", "AlKhaled et al. 2024", p.r2, p.rmse],
        ["VisionMRT", "accepted, Sustainable Cities and Society", 0.94, 3.12],
        ["PINN-MRT", "Shaeri et al. 2025, best configurations", 0.88, 3.50],
      ];
      $(root, ".uhwm-metrics").innerHTML = `<table><thead><tr><th>Model</th><th>R²</th><th>RMSE (°C)</th></tr></thead><tbody>` +
        rows.map(([n, sub, r2, rmse]) => `<tr><td>${n}<br><small>${sub}</small></td><td>${r2.toFixed(2)}</td><td>${rmse.toFixed(2)}</td></tr>`).join("") +
        `</tbody></table><p class="uhwm-cap">Each model was evaluated on different data, splits and inputs, so rows are not directly comparable.</p>`;
    }
    const sc = $(root, ".uhwm-scatter"), sctx = sc.getContext("2d");
    function drawScatter() {
      if (!st.golden) return;
      drawImportance();
      const w = sc.clientWidth, h = CHART_H, dpr = Math.min(devicePixelRatio || 1, 2);
      sc.width = Math.round(w * dpr); sc.height = Math.round(h * dpr); sc.style.height = h + "px";
      const c = sctx; c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
      const { observed: o, predicted: p } = st.golden.heldout, lo = 10, hi = 80, pl = 36, pb = 28, pt = 8, pr = 8;
      const X = (v) => pl + (v - lo) / (hi - lo) * (w - pl - pr), Y = (v) => h - pb - (v - lo) / (hi - lo) * (h - pb - pt);
      const line = cvar(root, "--line") || "#ccc", muted = cvar(root, "--muted") || "#777";
      c.strokeStyle = line; c.fillStyle = muted; c.font = "11px Inter,system-ui,sans-serif"; c.textAlign = "right";
      for (let v = 20; v <= 80; v += 20) { c.beginPath(); c.moveTo(pl, Y(v)); c.lineTo(w - pr, Y(v)); c.stroke(); c.fillText(v + "", pl - 5, Y(v) + 4); }
      c.textAlign = "center"; for (let v = 20; v <= 80; v += 20) c.fillText(v + "", X(v), h - 12);
      c.fillText("Observed Tmrt (°C)", (w + pl) / 2, h - 0); c.setLineDash([4, 4]); c.beginPath(); c.moveTo(X(lo), Y(lo)); c.lineTo(X(hi), Y(hi)); c.stroke(); c.setLineDash([]);
      c.fillStyle = cvar(root, "--accent") || "#c8321f"; c.globalAlpha = 0.65; o.forEach((v, i) => { c.beginPath(); c.arc(X(v), Y(p[i]), 3, 0, 7); c.fill(); }); c.globalAlpha = 1;
      c.save(); c.translate(10, h / 2); c.rotate(-Math.PI / 2); c.fillStyle = muted; c.textAlign = "center"; c.fillText("Predicted (°C)", 0, 0); c.restore();
    }

    /* ---- shared horizontal bar chart ---- */
    const FEAT_LABEL = { SVF_Up: "Sky view factor", surr_trees: "Trees", surr_buildings: "Buildings", surr_pervious: "Pervious ground",
      Shade_AtMeasurement: "Shaded at the spot", AirT_C_detrended: "Air temperature", Solar_Altitude: "Solar altitude", min_from_sunrise: "Minutes from sunrise" };
    const CHART_H = 320;                                   // both held-out diagrams use this height
    function barChart(canvas, items, color, axisLabel, fmt) {
      // items: [[label, value]] already sorted, largest first (so the biggest effect is at the top)
      const w = canvas.clientWidth, pt = 8, pb = 22, h = CHART_H, rowH = (h - pt - pb) / items.length, dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); canvas.style.height = h + "px";
      const c = canvas.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
      const ink = cvar(root, "--ink") || "#222", muted = cvar(root, "--muted") || "#777", line = cvar(root, "--line") || "#ccc";
      const pl = 136, pr = 64, max = Math.max(1e-9, ...items.map((i) => i[1])), X = (v) => pl + v / max * (w - pl - pr);
      c.font = "12px Inter,system-ui,sans-serif"; c.textBaseline = "middle";
      items.forEach(([name, v], i) => {
        const y = pt + i * rowH + rowH / 2;
        c.fillStyle = ink; c.textAlign = "right"; c.fillText(name, pl - 8, y);
        c.fillStyle = color; c.globalAlpha = 0.9; c.fillRect(pl, y - 8, Math.max(1, X(v) - pl), 16); c.globalAlpha = 1;
        c.fillStyle = muted; c.textAlign = "left"; c.fillText(fmt(v), X(v) + 6, y);
      });
      c.strokeStyle = line; c.beginPath(); c.moveTo(pl + 0.5, pt); c.lineTo(pl + 0.5, h - pb); c.stroke();
      c.fillStyle = muted; c.textAlign = "center"; c.textBaseline = "alphabetic"; c.fillText(axisLabel, (pl + w - pr) / 2, h - 4);
    }

    /* ---- feature importance: LightGBM gain, exported with the model (accent colour) ---- */
    const imc = $(root, ".uhwm-imp");
    function drawImportance() {
      if (!st.model || !st.model.importance_gain) return;
      const items = st.model.features.map((f, i) => [FEAT_LABEL[f] || f, st.model.importance_gain[i]]).sort((x, y) => y[1] - x[1]);
      barChart(imc, items, cvar(root, "--accent") || "#c8321f", "Share of total gain", (v) => (v * 100).toFixed(0) + "%");
    }

    $(root, ".uhwm-about").addEventListener("toggle", drawScatter);

    /* ---- controls ---- */
    function update() {
      const air = inp("air"), uF = st.unit === "F";
      out("sky").textContent = Math.round(st.s * 100) + "%"; out("trees").textContent = Math.round(st.t * 100) + "%"; out("bld").textContent = Math.round(st.b * 100) + "%";
      out("perv").textContent = (+inp("perv").value).toFixed(2);
      out("air").textContent = (+air.value).toFixed(uF ? 0 : 1) + (uF ? " °F" : " °C");
      const mins = +inp("time").value; out("time").textContent = fmtT(mins);
      $(root, ".uhwm-warn").hidden = !(st.t > TRAIN.trees[1] || st.b > TRAIN.buildings[1] || st.s > TRAIN.svf[1]);
      drawPad();
      if (!st.model) return;
      const inpv = current(), r = predict(st.model, inpv);
      out("tmrt").textContent = r.tmrt.toFixed(1); out("tmrtF").textContent = "(" + cToF(r.tmrt).toFixed(0) + " °F)";
      out("sunline").textContent = r.sun.elevation > 0
        ? `Sun ${r.sun.elevation.toFixed(1)}° above the horizon, azimuth ${r.sun.azimuth.toFixed(0)}° (Phoenix, MST)`
        : `Sun is below the horizon (${r.sun.elevation.toFixed(1)}°)`;
      drawCurve(inpv, r.tmrt, mins);
    }
    root.addEventListener("input", (e) => { if (e.target.matches("[data-i]")) update(); });
    $$u(root, "[data-u]").forEach((b) => b.addEventListener("click", () => {
      const ui = inp("air"), cNow = st.unit === "F" ? fToC(+ui.value) : +ui.value; st.unit = b.dataset.u;
      $$u(root, "[data-u]").forEach((x) => x.setAttribute("aria-pressed", x === b));
      if (st.unit === "F") { ui.min = 79; ui.max = 111; ui.step = 1; ui.value = Math.round(cToF(cNow)); }
      else { ui.min = 26; ui.max = 44; ui.step = 0.5; ui.value = Math.round(fToC(+ui.value) * 2) / 2; }
      update();
    }));
    function $$u(el, s) { return [...el.querySelectorAll(s)]; }
    let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { update(); drawScatter(); }, 120); });
    const redraw = () => { update(); drawScatter(); };
    new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
    update();
  }

  g.UHDemos.webmrt.mount = mount;
})();
