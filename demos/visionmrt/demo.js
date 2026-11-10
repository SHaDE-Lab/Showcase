/* VisionMRT demo widget
   Usage:  UHDemos.visionmrt.mount(document.getElementById("target"))
   Data:   data.json + img/ next to this file, produced by codebases/visionmrt/run_demo.py (real outputs of the
           released code, precomputed for two example sites; nothing here is simulated in the browser). */
(function () {
  "use strict";
  window.UHDemos = window.UHDemos || {};
  const BASE = document.currentScript.src.replace(/[^/]*$/, "");
  const LIVE = "https://shadelab.asu.edu/VisionMRT";
  const METRICS = {
    mrt:  { label: "MRT",  full: "Mean radiant temperature" },
    utci: { label: "UTCI", full: "Universal Thermal Climate Index" },
    pet:  { label: "PET",  full: "Physiological Equivalent Temperature" },
  };
  const FACES = [["Up", 0, 1], ["West", 1, 0], ["North", 1, 1], ["East", 1, 2], ["South", 1, 3], ["Down", 2, 1]];
  const NS = "http://www.w3.org/2000/svg";

  const el = (tag, attrs, kids) => {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => (k === "text" ? (n.textContent = v) : n.setAttribute(k, v)));
    (kids || []).forEach((c) => n.appendChild(c));
    return n;
  };
  const svg = (tag, attrs, text) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    if (text != null) n.textContent = text;
    return n;
  };
  const hr12 = (h) => ((h + 11) % 12 + 1) + (h < 12 ? " AM" : " PM");

  function loadCss() {
    if (document.getElementById("vm-demo-css")) return;
    const l = el("link", { id: "vm-demo-css", rel: "stylesheet", href: BASE + "demo.css" });
    document.head.appendChild(l);
  }

  function mount(root) {
    loadCss();
    root.classList.add("vmd");
    root.innerHTML = '<p class="vmd-note">Loading demo data…</p>';
    fetch(BASE + "data.json")
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => build(root, d))
      .catch((e) => { root.innerHTML = '<p class="vmd-note">Could not load the demo data (' + e.message + "). Open this page through a web server, not from a file.</p>"; });
  }

  function build(root, D) {
    const ids = Object.keys(D.sites);
    const st = { site: ids[0], hour: 12, metric: "mrt", view: "shadow" };
    const idx = () => D.hours.indexOf(st.hour);

    root.innerHTML = "";
    /* ---- header: site toggle ---- */
    const siteBtns = ids.map((id) => {
      const s = D.sites[id];
      const b = el("button", { type: "button", "data-site": id, "aria-pressed": "false" });
      b.innerHTML = "<b>" + s.label + "</b><small>sky view factor " + s.svf.toFixed(2) + "</small>";
      b.addEventListener("click", () => { st.site = id; render(); });
      return b;
    });
    const head = el("div", { class: "vmd-seg", role: "group", "aria-label": "Choose a site" }, siteBtns);

    /* ---- left: image view ---- */
    const tabs = [["shadow", "Shade at this hour"], ["fisheye", "Sky view"], ["seg", "Segmentation"]].map(([k, t]) => {
      const b = el("button", { type: "button", "data-view": k, "aria-pressed": "false", text: t });
      b.addEventListener("click", () => { st.view = k; render(); });
      return b;
    });
    const imgBox = el("div", { class: "vmd-imgbox" });
    const img = el("img", { alt: "" });
    const labels = el("div", { class: "vmd-faces", "aria-hidden": "true" });
    FACES.forEach(([n, r, c]) => labels.appendChild(el("span", { text: n, style: "grid-row:" + (r + 1) + ";grid-column:" + (c + 1) })));
    imgBox.append(img, labels);
    const caption = el("p", { class: "vmd-cap" });
    const legend = el("div", { class: "vmd-legend" });
    D.classes.forEach((c) => legend.appendChild(el("span", {}, [el("i", { style: "background:rgb(" + c.rgb.join(",") + ")" }), document.createTextNode(c.name)])));
    legend.appendChild(el("span", {}, [el("i", { class: "shade" }), document.createTextNode("In shadow (darkened)")]));

    const slider = el("input", { type: "range", id: "vmd-hour", min: D.hours[0], max: D.hours[D.hours.length - 1], step: 1, value: st.hour });
    const hourOut = el("output", { for: "vmd-hour" });
    slider.addEventListener("input", () => { st.hour = +slider.value; render(); });
    const sliderRow = el("div", { class: "vmd-ctrl" }, [el("label", { for: "vmd-hour", text: "Hour of day" }), slider, hourOut]);

    const left = el("div", { class: "vmd-panel" }, [
      el("div", { class: "vmd-tabs", role: "group", "aria-label": "View" }, tabs), imgBox, caption, legend, sliderRow,
    ]);

    /* ---- right: readouts + charts ---- */
    const kpi = (id, name) => el("div", { class: "vmd-kpi", id: "vmd-" + id }, [el("small", { text: name }), el("b", { text: "–" })]);
    const kMrt = kpi("mrt", "MRT"), kUtci = kpi("utci", "UTCI"), kPet = kpi("pet", "PET");
    const kAir = kpi("air", "Air temperature"), kSun = kpi("sun", "Direct sun at the person"), kGround = kpi("gnd", "Sunlit ground");
    const kpis = el("div", { class: "vmd-kpis" }, [kMrt, kUtci, kPet, kAir, kSun, kGround]);

    const mtabs = Object.keys(METRICS).map((k) => {
      const b = el("button", { type: "button", "aria-pressed": "false", text: METRICS[k].label, title: METRICS[k].full });
      b.addEventListener("click", () => { st.metric = k; render(); });
      b.dataset.metric = k;
      return b;
    });
    const chart1 = el("div", { class: "vmd-chart" });
    const chart2 = el("div", { class: "vmd-chart" });
    const right = el("div", { class: "vmd-panel" }, [
      kpis,
      el("div", { class: "vmd-chead" }, [el("span", { text: "Through the day" }), el("div", { class: "vmd-tabs sm", role: "group", "aria-label": "Metric" }, mtabs)]),
      chart1,
      el("p", { class: "vmd-note sm", text: "Hollow marker: direct sun is blocked at the person's position that hour." }),
      el("div", { class: "vmd-chead" }, [el("span", { text: "What drives it: absorbed radiation, selected site (W/m²)" })]),
      chart2,
    ]);

    const foot = el("p", { class: "vmd-note" });
    foot.innerHTML =
      "<b>What you are seeing:</b> real output of the released VisionMRT code (<code>codebases/visionmrt</code>), run once on two example sites in Tempe, " +
      "Arizona for " + D.date + " with hourly weather from Open-Meteo, then stored. Nothing is simulated in your browser. " +
      "Two sites illustrate the method; they do not reproduce the paper&rsquo;s validation. Source photographs are not shown, only the segmentation classes. " +
      'Want a new place? <a href="' + LIVE + '" target="_blank" rel="noopener">Run your own 360° image in the live tool ↗</a>';

    root.append(head, el("div", { class: "vmd-grid" }, [left, right]), foot);

    /* ---- charts (inline SVG, theme via CSS variables) ---- */
    function lineChart(host) {
      const W = 620, H = 230, m = { l: 44, r: 14, t: 12, b: 30 };
      const key = st.metric, hours = D.hours;
      const all = ids.flatMap((i) => D.sites[i][key]);
      const lo = Math.floor(Math.min(...all) / 5) * 5 - 0, hi = Math.ceil(Math.max(...all) / 5) * 5;
      const x = (h) => m.l + ((h - hours[0]) / (hours[hours.length - 1] - hours[0])) * (W - m.l - m.r);
      const y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
      const s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": METRICS[key].full + " by hour for both sites" });
      for (let v = lo; v <= hi; v += 5) {
        s.appendChild(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "grid" }));
        s.appendChild(svg("text", { x: m.l - 6, y: y(v) + 4, class: "tick", "text-anchor": "end" }, v));
      }
      hours.forEach((h) => { if (h % 2 === 1) s.appendChild(svg("text", { x: x(h), y: H - 10, class: "tick", "text-anchor": "middle" }, hr12(h).replace(" ", ""))); });
      s.appendChild(svg("text", { x: 12, y: m.t + 8, class: "unit" }, "°C"));
      s.appendChild(svg("line", { x1: x(st.hour), x2: x(st.hour), y1: m.t, y2: H - m.b, class: "cursor" }));
      ids.slice().sort((a) => (a === st.site ? 1 : -1)).forEach((id) => {
        const S = D.sites[id], sel = id === st.site, cls = "series " + (id === ids[0] ? "a" : "b") + (sel ? " sel" : "");
        s.appendChild(svg("polyline", { points: hours.map((h, i) => x(h) + "," + y(S[key][i])).join(" "), class: cls }));
        hours.forEach((h, i) => s.appendChild(svg("circle", { cx: x(h), cy: y(S[key][i]), r: sel ? 3.6 : 2.6, class: cls + " dot" + (S.sun_visible[i] ? "" : " hollow") })));
      });
      const a = D.sites[ids[0]], b = D.sites[ids[1]];
      const lg = svg("g", { transform: "translate(" + (m.l + 8) + "," + (m.t + 6) + ")", class: "lg" });
      [[a, "a", 0], [b, "b", 150]].forEach(([S, c, dx]) => {
        lg.appendChild(svg("circle", { cx: dx, cy: 0, r: 4, class: "series dot " + c + " sel" }));
        lg.appendChild(svg("text", { x: dx + 9, y: 4, class: "tick" }, S.label));
      });
      s.appendChild(lg);
      host.innerHTML = ""; host.appendChild(s);
    }

    function barChart(host) {
      const S = D.sites[st.site], W = 620, H = 190, m = { l: 44, r: 14, t: 10, b: 28 };
      const tot = S.sw_absorbed.map((v, i) => v + S.lw_absorbed[i]);
      const hi = Math.ceil(Math.max(...tot) / 100) * 100, n = D.hours.length;
      const bw = (W - m.l - m.r) / n, y = (v) => H - m.b - (v / hi) * (H - m.t - m.b);
      const s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Absorbed shortwave and longwave radiation by hour" });
      for (let v = 0; v <= hi; v += 200) {
        s.appendChild(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "grid" }));
        s.appendChild(svg("text", { x: m.l - 6, y: y(v) + 4, class: "tick", "text-anchor": "end" }, v));
      }
      D.hours.forEach((h, i) => {
        const x0 = m.l + i * bw + bw * 0.14, w = bw * 0.72, cur = h === st.hour;
        s.appendChild(svg("rect", { x: x0, y: y(S.lw_absorbed[i]), width: w, height: y(0) - y(S.lw_absorbed[i]), class: "vmd-lw" + (cur ? " cur" : "") }));
        s.appendChild(svg("rect", { x: x0, y: y(tot[i]), width: w, height: y(S.lw_absorbed[i]) - y(tot[i]), class: "vmd-sw" + (cur ? " cur" : "") }));
        if (h % 2 === 1) s.appendChild(svg("text", { x: x0 + w / 2, y: H - 9, class: "tick", "text-anchor": "middle" }, hr12(h).replace(" ", "")));
      });
      const lg = svg("g", { transform: "translate(" + (m.l + 8) + "," + (m.t + 4) + ")" });
      [["vmd-sw", "Shortwave (sun)", 0], ["vmd-lw", "Longwave (surfaces + sky)", 130]].forEach(([c, t, dx]) => {
        lg.appendChild(svg("rect", { x: dx, y: -6, width: 10, height: 10, class: c }));
        lg.appendChild(svg("text", { x: dx + 15, y: 3, class: "tick" }, t));
      });
      s.appendChild(lg);
      host.innerHTML = ""; host.appendChild(s);
    }

    /* ---- render ---- */
    function render() {
      const S = D.sites[st.site], i = idx();
      siteBtns.forEach((b) => b.setAttribute("aria-pressed", b.dataset.site === st.site));
      tabs.forEach((b) => b.setAttribute("aria-pressed", b.dataset.view === st.view));
      mtabs.forEach((b) => b.setAttribute("aria-pressed", b.dataset.metric === st.metric));
      const dir = BASE + "img/" + st.site + "/";
      const net = st.view === "shadow" || st.view === "seg";
      img.src = dir + (st.view === "shadow" ? "shadow_" + String(st.hour).padStart(2, "0") + ".png" : st.view === "seg" ? "seg_net.png" : "fisheye.png");
      img.alt = st.view === "fisheye" ? "Fisheye sky-view segmentation of " + S.label : "Cube-face view of " + S.label;
      imgBox.classList.toggle("net", net); imgBox.classList.toggle("fish", !net);
      labels.style.display = net ? "" : "none";
      legend.querySelector(".shade").parentElement.style.display = st.view === "shadow" ? "" : "none";
      caption.textContent = st.view === "shadow"
        ? "The six faces of the 360° view unfolded (up on top, down below). Shadows are cast through the reconstructed 3D scene at " + hr12(st.hour) + "."
        : st.view === "fisheye" ? "Looking straight up: the fisheye projection the sky view factor is read from (centre = zenith, rim = horizon)."
        : "Per-pixel classes from the segmentation step: the input to shadows and the energy balance.";
      hourOut.textContent = hr12(st.hour); slider.disabled = false;
      slider.style.opacity = st.view === "shadow" ? 1 : 0.55;

      const u = (v, d) => (v == null ? "–" : v.toFixed(d == null ? 1 : d) + " °C");
      kMrt.lastChild.textContent = u(S.mrt[i]); kUtci.lastChild.textContent = u(S.utci[i]); kPet.lastChild.textContent = u(S.pet[i]);
      kAir.lastChild.textContent = u(D.weather.air_temperature[i]);
      kSun.lastChild.textContent = S.sun_visible[i] ? "Visible" : "Blocked";
      kSun.classList.toggle("hot", S.sun_visible[i]); kSun.classList.toggle("cool", !S.sun_visible[i]);
      kGround.lastChild.textContent = Math.round(S.sunlit_share[st.hour].Down * 100) + " %";
      lineChart(chart1); barChart(chart2);
    }
    render();
  }

  window.UHDemos.visionmrt = { mount };
})();
