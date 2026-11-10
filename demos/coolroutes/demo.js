/* Cool Routes demo: runs the released routing method on real ASU campus data.
 *
 * Data (demos/coolroutes/data) are produced by codebases/cool-routes/run_demo.py from the sample
 * rasters and walking network.  The router below re-implements, in JavaScript, the exact cost
 * functions of coolroutes/routing.py (cool = edge "cost", shortest = edge "length") and is checked
 * against the Python golden routes by parity.test.mjs.
 */
(function (root) {
  "use strict";
  var SCRIPT_URL = (typeof document !== "undefined" && document.currentScript) ? document.currentScript.src : "";
  var BASE = SCRIPT_URL ? SCRIPT_URL.replace(/[^/]*$/, "") : "";

  /* ============================== router (pure, also used by the node test) ============================== */
  var R_EARTH = 6378137;
  function mercX(lon) { return R_EARTH * lon * Math.PI / 180; }
  function mercY(lat) { return R_EARTH * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); }

  /** graph = parsed graph.json; si = stamp index. Edge row: [u, v, length, geomLonLat, cost0, mrt0, cost1, mrt1, ...] */
  function buildGraph(graph, si) {
    var n = graph.nodes.length, adj = new Array(n), i;
    for (i = 0; i < n; i++) adj[i] = [];
    var nx = new Float64Array(n), ny = new Float64Array(n);
    graph.nodes.forEach(function (nd, k) { nx[k] = mercX(nd[1]); ny[k] = mercY(nd[2]); });
    graph.edges.forEach(function (e, k) { adj[e[0]].push([e[1], k]); adj[e[1]].push([e[0], k]); });
    return { graph: graph, si: si, adj: adj, nx: nx, ny: ny, scale: graph.scale[graph.stamps[si]] };
  }
  function edgeCost(G, e) { return e[4 + 2 * G.si]; }
  function edgeMrt(G, e) { return e[5 + 2 * G.si]; }

  /** weight: {kind:"length"} | {kind:"cost"} | {kind:"blend", w}   (blend = (1-w)*length + w*cost/scale) */
  function weightFn(G, weight) {
    if (weight.kind === "length") return function (e) { return e[2]; };
    if (weight.kind === "cost") return function (e) { return edgeCost(G, e); };
    var w = weight.w, s = G.scale;
    return function (e) { return (1 - w) * e[2] + w * edgeCost(G, e) / s; };
  }

  function nearestNode(G, lon, lat) {
    var x = mercX(lon), y = mercY(lat), best = -1, bd = Infinity;
    for (var i = 0; i < G.nx.length; i++) {
      var d = (G.nx[i] - x) * (G.nx[i] - x) + (G.ny[i] - y) * (G.ny[i] - y);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  function Heap() { this.a = []; this.c = 0; }
  Heap.prototype.push = function (d, v) {
    var a = this.a, i = a.length; a.push([d, this.c++, v]);
    while (i > 0) { var p = (i - 1) >> 1; if (less(a[i], a[p])) { var t = a[i]; a[i] = a[p]; a[p] = t; i = p; } else break; }
  };
  Heap.prototype.pop = function () {
    var a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last; var i = 0;
      for (;;) {
        var l = 2 * i + 1, r = l + 1, m = i;
        if (l < a.length && less(a[l], a[m])) m = l;
        if (r < a.length && less(a[r], a[m])) m = r;
        if (m === i) break; var t = a[i]; a[i] = a[m]; a[m] = t; i = m;
      }
    }
    return top;
  };
  function less(p, q) { return p[0] < q[0] || (p[0] === q[0] && p[1] < q[1]); }

  /** Dijkstra from src to dst; returns {nodes:[idx..], edges:[edgeIdx..]} or null. Parallel edges: cheapest wins. */
  function route(G, src, dst, weight) {
    var wf = weightFn(G, weight), n = G.adj.length, dist = new Float64Array(n).fill(Infinity);
    var prevNode = new Int32Array(n).fill(-1), prevEdge = new Int32Array(n).fill(-1), done = new Uint8Array(n);
    var h = new Heap(); dist[src] = 0; h.push(0, src);
    while (h.a.length) {
      var top = h.pop(), u = top[2];
      if (done[u]) continue; done[u] = 1;
      if (u === dst) break;
      var nb = G.adj[u];
      for (var i = 0; i < nb.length; i++) {
        var v = nb[i][0], ei = nb[i][1], nd = dist[u] + wf(G.graph.edges[ei]);
        if (nd < dist[v]) { dist[v] = nd; prevNode[v] = u; prevEdge[v] = ei; h.push(nd, v); }
      }
    }
    if (!isFinite(dist[dst])) return null;
    var nodes = [dst], edges = [];
    for (var k = dst; k !== src; k = prevNode[k]) { edges.push(prevEdge[k]); nodes.push(prevNode[k]); }
    nodes.reverse(); edges.reverse();
    return { nodes: nodes, edges: edges };
  }

  /** Same fields as coolroutes.routing.calculate_statistics. */
  function stats(G, r) {
    var len = 0, mrt = 0, cost = 0, heatLen = 0;
    r.edges.forEach(function (ei) {
      var e = G.graph.edges[ei];
      len += e[2]; mrt += edgeMrt(G, e); cost += edgeCost(G, e); heatLen += edgeMrt(G, e) * e[2];
    });
    return { length: len, mrt: mrt, average_mrt: len ? cost / len : 0, corrected_mean_mrt: len ? heatLen / len : 0 };
  }

  var router = { buildGraph: buildGraph, nearestNode: nearestNode, route: route, stats: stats, weightFn: weightFn,
                 mercX: mercX, mercY: mercY };
  if (typeof module !== "undefined" && module.exports) module.exports = router;
  if (typeof document === "undefined") return;       // node: stop here (no DOM)

  /* ============================================ widget ============================================ */
  root.UHDemos = root.UHDemos || {};
  root.UHDemos.coolroutes = { router: router, mount: mount };

  var link = document.createElement("link");
  link.rel = "stylesheet"; link.href = BASE + "demo.css"; document.head.appendChild(link);

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function fetchJson(u) { return fetch(BASE + u).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }
  function loadImg(u) {
    return new Promise(function (ok, bad) { var i = new Image(); i.onload = function () { ok(i); }; i.onerror = bad; i.src = BASE + u; });
  }

  function mount(host) {
    host.classList.add("crd");
    host.innerHTML = '<p class="demo-status">Loading campus data…</p>';
    Promise.all([fetchJson("data/graph.json"), fetchJson("data/meta.json")]).then(function (res) {
      var graph = res[0], meta = res[1];
      return Promise.all(graph.stamps.map(function (s) { return loadImg("data/mrt_" + s + ".webp"); })).then(function (imgs) {
        start(host, graph, meta, imgs);
      });
    }).catch(function (e) {
      host.innerHTML = '<p class="demo-status">Could not load the Cool Routes demo data (' + e.message + '). ' +
        'Serve the site over http (e.g. <code>python -m http.server</code>) rather than opening the file.</p>';
    });
  }

  function start(host, graph, meta, imgs) {
    var Gs = graph.stamps.map(function (_, i) { return buildGraph(graph, i); });
    var B = meta.bounds3857, W = B[2] - B[0], H = B[3] - B[1];
    var st = { si: 0, w: 1, a: nearestNode(Gs[0], meta.defaults.start[0], meta.defaults.start[1]),
               b: nearestNode(Gs[0], meta.defaults.end[0], meta.defaults.end[1]), next: "a" };

    host.innerHTML = "";
    var bar = el("div", "crd-bar");
    var stampBtns = meta.stamps.map(function (s, i) {
      var b = el("button", "crd-chip", s.label); b.type = "button";
      b.addEventListener("click", function () { st.si = i; draw(); });
      bar.appendChild(b); return b;
    });
    var rnd = el("button", "crd-chip crd-ghost", "Random trip"), swap = el("button", "crd-chip crd-ghost", "Swap A ⇄ B");
    rnd.type = swap.type = "button";
    bar.appendChild(rnd); bar.appendChild(swap);

    var map = el("div", "crd-map"), cv = el("canvas"); cv.setAttribute("aria-label", "ASU campus MRT map with a shortest and a cool walking route; click to move the start and end points");
    cv.setAttribute("role", "img"); map.appendChild(cv);
    var tip = el("div", "crd-tip", "Click the map to move A, then B"); map.appendChild(tip);

    var legend = el("div", "crd-legend", '<span>25 °C</span><i></i><span>80 °C MRT</span>');
    var ctl = el("div", "crd-ctl");
    var lab = el("label", null, "Walk shorter"); lab.htmlFor = "crd-w-" + Math.random().toString(36).slice(2, 7);
    var rng = el("input"); rng.type = "range"; rng.min = 0; rng.max = 100; rng.step = 5; rng.value = 100; rng.id = lab.htmlFor;
    var lab2 = el("span", "crd-end", "Cooler"), val = el("output", "crd-val");
    ctl.appendChild(lab); ctl.appendChild(rng); ctl.appendChild(lab2); ctl.appendChild(val);
    var read = el("div", "crd-read");
    var note = el("p", "crd-note",
      "<b>Real campus data, real method.</b> The two MRT maps are SOLWEIG output from the Cool Routes system (ASU Tempe core, 1 km window; " +
      "times are local, Arizona). Routing runs here in your browser with the released cost functions: <i>cool</i> minimises summed edge MRT (<code>cost</code>), " +
      "<i>shortest</i> minimises <code>length</code>. Sliding between the ends is a demo extension; 100 % is the published cool route. " +
      "“Mean MRT” is length-weighted along the route. Blue = shaded surfaces, yellow to red = sun-exposed (rooftops included).");
    host.appendChild(bar); host.appendChild(map); host.appendChild(legend); host.appendChild(ctl); host.appendChild(read); host.appendChild(note);

    var ctx = cv.getContext("2d"), S = 600, dpr = 1;
    function px(x) { return (x - B[0]) / W * S; }
    function py(y) { return (B[3] - y) / H * S; }
    // precompute edge polylines in mercator
    var polys = graph.edges.map(function (e) {
      var a = graph.nodes[e[0]], b = graph.nodes[e[1]], pts = [[mercX(a[1]), mercY(a[2])]], g = e[3];
      for (var i = 0; i < g.length; i += 2) pts.push([mercX(g[i]), mercY(g[i + 1])]);
      pts.push([mercX(b[1]), mercY(b[2])]); return pts;
    });
    function line(ei_list, G, col, wd, dash, halo) {
      function path() {
        ctx.beginPath(); var first = true;
        ei_list.nodesOrdered.forEach(function (seg) {
          var pts = seg.slice();
          pts.forEach(function (p, i) { var x = px(p[0]), y = py(p[1]); if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y); });
        });
      }
      ctx.lineJoin = ctx.lineCap = "round";
      if (halo) { ctx.setLineDash([]); ctx.strokeStyle = halo; ctx.lineWidth = (wd + 3) * dpr; path(); ctx.stroke(); }
      ctx.setLineDash(dash || []); ctx.strokeStyle = col; ctx.lineWidth = wd * dpr; path(); ctx.stroke(); ctx.setLineDash([]);
    }
    function ordered(r) {      // polylines of the route oriented along the walking direction
      var segs = [];
      r.edges.forEach(function (ei, k) {
        var pts = polys[ei].slice(), u = r.nodes[k], e = graph.edges[ei];
        if (e[0] !== u) pts.reverse();
        segs.push(pts);
      });
      return { nodesOrdered: segs };
    }
    function marker(n, col, t) {
      var x = px(Gs[0].nx[n]), y = py(Gs[0].ny[n]), r = 11 * dpr;
      ctx.fillStyle = col; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 * dpr;
      ctx.beginPath(); ctx.arc(x * 1, y * 1, r, 0, 7); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = "700 " + 12 * dpr + "px Inter,system-ui,sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(t, x, y + dpr * .5);
    }
    function resize() {
      var w = map.clientWidth || 600; dpr = Math.min(window.devicePixelRatio || 1, 2);
      cv.width = Math.round(w * dpr); cv.height = Math.round(w * dpr); cv.style.height = w + "px"; S = cv.width;
      draw();
    }

    function draw() {
      var G = Gs[st.si], im = imgs[st.si];
      stampBtns.forEach(function (b, i) { b.setAttribute("aria-pressed", i === st.si); });
      ctx.fillStyle = css("--bld") || "#333"; ctx.fillRect(0, 0, S, S);
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high"; ctx.drawImage(im, 0, 0, S, S);
      // faint network
      ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = Math.max(1, .8 * dpr); ctx.setLineDash([]);
      ctx.beginPath(); polys.forEach(function (p) { p.forEach(function (q, i) { var x = px(q[0]), y = py(q[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); }); ctx.stroke();

      var wt = st.w >= 1 ? { kind: "cost" } : st.w <= 0 ? { kind: "length" } : { kind: "blend", w: st.w };
      var rs = route(G, st.a, st.b, { kind: "length" }), rc = st.a === st.b ? null : route(G, st.a, st.b, wt);
      if (st.a === st.b || !rs || !rc) { read.innerHTML = '<p class="crd-msg">No walking route between these points. Click elsewhere.</p>'; marker(st.a, "#2f6df6", "A"); marker(st.b, "#e5384a", "B"); return; }
      line(ordered(rs), G, "#ffffff", 3, [8 * dpr, 6 * dpr], "rgba(10,14,30,.7)");
      line(ordered(rc), G, css("--cool") || "#0e8f87", 4.5, null, "rgba(10,14,30,.85)");
      marker(st.a, "#2f6df6", "A"); marker(st.b, "#e5384a", "B");

      var ss = stats(G, rs), sc = stats(G, rc);
      var dT = ss.corrected_mean_mrt - sc.corrected_mean_mrt, dL = (sc.length / ss.length - 1) * 100;
      val.textContent = st.w >= 1 ? "Cool route (published)" : st.w <= 0 ? "Shortest" : Math.round(st.w * 100) + " % heat weight";
      read.innerHTML =
        '<div class="crd-card"><small><i class="crd-sw"></i>Shortest route</small><b>' + Math.round(ss.length) + ' m</b><span>' + ss.corrected_mean_mrt.toFixed(1) + ' °C mean MRT</span></div>' +
        '<div class="crd-card"><small><i class="crd-sw c"></i>Your route</small><b>' + Math.round(sc.length) + ' m</b><span>' + sc.corrected_mean_mrt.toFixed(1) + ' °C mean MRT</span></div>' +
        '<p class="crd-delta">' + (dT > 0.05 ? '<b>' + dT.toFixed(1) + ' °C cooler</b> on average for ' + Math.max(0, dL).toFixed(1) + ' % more walking.' :
          'Here the shortest route is already the coolest option.') + '</p>';
    }

    // interaction
    cv.addEventListener("click", function (e) {
      var r = cv.getBoundingClientRect(), x = B[0] + (e.clientX - r.left) / r.width * W, y = B[3] - (e.clientY - r.top) / r.height * H;
      var G = Gs[0], best = -1, bd = Infinity;
      for (var i = 0; i < G.nx.length; i++) { var d = (G.nx[i] - x) * (G.nx[i] - x) + (G.ny[i] - y) * (G.ny[i] - y); if (d < bd) { bd = d; best = i; } }
      st[st.next] = best; st.next = st.next === "a" ? "b" : "a";
      tip.textContent = "Next click moves " + st.next.toUpperCase(); draw();
    });
    rng.addEventListener("input", function () { st.w = rng.value / 100; draw(); });
    swap.addEventListener("click", function () { var t = st.a; st.a = st.b; st.b = t; draw(); });
    rnd.addEventListener("click", function () {
      var G = Gs[0], n = G.nx.length, tries = 0, a, b, d;
      do { a = Math.floor(Math.random() * n); b = Math.floor(Math.random() * n); d = Math.hypot(G.nx[a] - G.nx[b], G.ny[a] - G.ny[b]); tries++; }
      while ((d < 350 || d > 900) && tries < 400);
      st.a = a; st.b = b; draw();
    });
    if (window.ResizeObserver) new ResizeObserver(resize).observe(map); else window.addEventListener("resize", resize);
    new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    resize();
  }
})(typeof window !== "undefined" ? window : globalThis);
