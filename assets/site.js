/* ------------------------------------------------------------------
   Single place to edit project facts, links and release status.
   Leave a url as "" and its button is hidden automatically.
------------------------------------------------------------------- */
/* embed: shadelab.asu.edu currently sends X-Frame-Options: DENY, so WebMRT and VisionMRT cannot be framed.
   If the host allows this site (CSP frame-ancestors), flip their embed flag to true. */
window.PORTAL = {
  contact: "https://shadelab.asu.edu/contact/",
  projects: {
    marty: { paper: "https://doi.org/10.1016/j.scitotenv.2019.06.085", code: "https://github.com/SHaDE-Lab/Showcase/tree/main/codebases/MaRTy" },                                  // Middel & Krayenhoff 2019
    martiny: { paper: "https://doi.org/10.3389/fenvs.2022.866240", code: "https://github.com/SHaDE-Lab/Showcase/tree/main/codebases/MaRTiny" },  // Kulkarni et al. 2022
    coolroutes: {
      embed: true,      // true = show the live tool in an iframe; false = launch card
      // pre-selects Coor Hall -> Creativity Commons (building codes). Needs patches/cool-routes-frontend-url-params.patch deployed; ignored otherwise.
      embedQuery: "?start=COOR&end=CRTVC",
      poster: "assets/img/coolroutes-preview.webp",   // cover shown over the live tool until the visitor clicks
      tool: "https://coolroutes.sensableheatscapes.com/",
      paper: "https://doi.org/10.1016/j.buildenv.2026.114622",
      code: "https://github.com/SHaDE-Lab/Showcase/tree/main/codebases/cool-routes",
      data: "",
      codeStatus: "Open-source example code (Apache-2.0)",
      folder: "codebases/cool-routes/",
    },
    webmrt: {
      embed: false,      // true = show the live tool in an iframe; false = launch card
      tool: "https://shadelab.asu.edu/WebMRT",
      paper: "https://doi.org/10.1016/j.scs.2024.105861",
      code: "https://github.com/SHaDE-Lab/Showcase/tree/main/codebases/webmrt",
      data: "",
      codeStatus: "Open-source example code (Apache-2.0)",
      folder: "codebases/webmrt/",
    },
    panomrt: {         // a method and open-source model with no web tool
      paper: "https://doi.org/10.1016/j.scitotenv.2022.160301",   // Science of The Total Environment 859:160301 (2023)
      code: "https://github.com/SHaDE-Lab/Showcase/tree/main/codebases/panomrt",
      codeStatus: "Open-source example code (Apache-2.0)",
      folder: "codebases/panomrt/",
    },
    visionmrt: {
      embed: false,      // true = show the live tool in an iframe; false = launch card
      tool: "https://shadelab.asu.edu/VisionMRT",
      paper: "https://doi.org/10.1016/j.scs.2026.108016",   // Sustainable Cities and Society 151:108016 (2026)
      code: "https://github.com/SHaDE-Lab/Showcase/tree/main/codebases/visionmrt",
      data: "",
      codeStatus: "Open-source example code (Apache-2.0)",
      folder: "codebases/visionmrt/",
    },
  },
};

(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;

  /* ---------- wire links from PORTAL ---------- */
  $$("[data-link]").forEach((a) => {
    const [proj, kind] = a.dataset.link.split(".");
    const url = window.PORTAL.projects[proj][kind];
    if (url) { a.href = url; if (/^https?:/.test(url)) { a.target = "_blank"; a.rel = "noopener"; } }
    else a.remove();
  });
  $$("[data-link$='.code']").forEach((a) => { if (!a.querySelector("svg")) a.insertAdjacentHTML("beforeend", ' <span aria-hidden="true">&lt;/&gt;</span>'); });

  $$("[data-contact]").forEach((a) => (a.href = window.PORTAL.contact));

  /* ---------- theme ---------- */
  if (!root.dataset.theme) root.dataset.theme = "dark";
  $("#theme").addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    const apply = () => {
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (e) {}
      // demos that draw on <canvas> can listen for this and repaint
      document.dispatchEvent(new CustomEvent("uh:theme"));
    };
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { apply(); return; }
    if (document.startViewTransition) document.startViewTransition(apply);          // quick cross-fade of the whole page, canvases included
    else { root.classList.add("theme-anim"); apply(); setTimeout(() => root.classList.remove("theme-anim"), 320); }
  });

  /* ---------- small-screen menu ---------- */
  (function () {
    const btn = $("#menu"), nav = $("#navmenu");
    const set = (open) => {
      nav.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", String(open));
      btn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    };
    btn.addEventListener("click", (e) => { e.stopPropagation(); set(!nav.classList.contains("open")); });
    nav.addEventListener("click", (e) => { if (e.target.closest("a")) set(false); });           // choosing a section closes it
    document.addEventListener("click", (e) => { if (!e.target.closest(".nav")) set(false); });  // click outside closes it
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") set(false); });
    matchMedia("(min-width: 761px)").addEventListener("change", (m) => { if (m.matches) set(false); });
  })();

  /* ---------- reveal + scrollspy ---------- */
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }), { threshold: 0.12 });
  $$(".reveal").forEach((el) => io.observe(el));

  const links = $$(".nav a[href^='#']");
  const spy = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    links.forEach((l) => l.classList.toggle("active", l.getAttribute("href") === "#" + e.target.id));
    $$(".nav .dd").forEach((dd) => dd.classList.toggle("has-active", !!dd.querySelector(".dd-m a.active")));   // parent lights up for its children
  }), { rootMargin: "-45% 0px -50% 0px" });
  $$("main section[id]").forEach((s) => spy.observe(s));

  /* ---------- bibtex panels: closed until asked, then they slide open ---------- */
  $$(".bib-toggle").forEach((btn) => btn.addEventListener("click", () => {
    const panel = document.getElementById(btn.getAttribute("aria-controls")), open = !panel.classList.contains("open");
    panel.classList.toggle("open", open);
    panel.inert = !open;                                   // a closed panel cannot be tabbed into
    btn.setAttribute("aria-expanded", String(open));
  }));

  /* ---------- bibtex copy ---------- */
  $$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const txt = $("#" + b.dataset.copy).textContent.trim();
    try { await navigator.clipboard.writeText(txt); b.textContent = "Copied"; }
    catch (e) { b.textContent = "Select & copy"; }
    setTimeout(() => (b.textContent = "Copy BibTeX"), 1800);
  }));

  /* ---------- hero heat field (decorative) ---------- */
  const hero = $("#heroCanvas"), hctx = hero.getContext("2d");
  let hw, hh;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function heroSize() {
    const r = hero.getBoundingClientRect(), d = Math.min(devicePixelRatio || 1, 2);
    hw = hero.width = r.width * d; hh = hero.height = r.height * d;
  }
  function heat(v) {
    const stops = [[30, 41, 82], [64, 98, 187], [253, 224, 140], [244, 129, 52], [190, 30, 45]];
    const p = Math.min(0.999, Math.max(0, v)) * (stops.length - 1), i = Math.floor(p), f = p - i;
    return stops[i].map((c, k) => Math.round(c + (stops[i + 1][k] - c) * f));
  }
  function heroFrame(ts) {
    const cell = Math.max(10, Math.round(hw / 90)), t = ts / 4000;
    for (let y = 0; y < hh; y += cell) for (let x = 0; x < hw; x += cell) {
      const nx = x / hw, ny = y / hh;
      let v = 0.5 + 0.22 * Math.sin(nx * 7 + t) + 0.18 * Math.sin(ny * 9 - t * 1.3) + 0.12 * Math.sin((nx + ny) * 14 + t * 0.7);
      const bx = Math.floor(nx * 9), by = Math.floor(ny * 5);
      if (((nx * 9) % 1 > 0.28 && (ny * 5) % 1 > 0.3) && ((bx * 7 + by * 3) % 4 !== 0)) v -= 0.35;
      const c = heat(v);
      hctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
      hctx.fillRect(x, y, cell - 1, cell - 1);
    }
    if (!reduce) requestAnimationFrame(heroFrame);
  }
  heroSize(); requestAnimationFrame(heroFrame);
  addEventListener("resize", () => { heroSize(); if (reduce) heroFrame(0); });

  /* ---------- demo tabs (e.g. Cool Routes: released-code demo | live tool) ---------- */
  $$("[data-tabs]").forEach((box) => {
    const tabs = $$("[role=tab]", box), panes = $$("[role=tabpanel]", box);
    function show(id) {
      tabs.forEach((t) => t.setAttribute("aria-selected", t.dataset.pane === id));
      panes.forEach((p) => (p.hidden = p.id !== id));
      const pane = panes.find((p) => p.id === id);
      $$("[data-demo]", pane).forEach(loadDemo);        // start a demo that was hidden until now
    }
    tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.pane)));
  });

  /* ---------- live tools: iframe when embeddable, otherwise a launch card ---------- */
  $$("[data-live]").forEach((host) => {
    const key = host.dataset.live, p = window.PORTAL.projects[key];
    const label = { coolroutes: "Cool Routes", webmrt: "WebMRT", visionmrt: "VisionMRT" }[key];
    if (p.embed) {
      const src = p.tool + (p.embedQuery || "");
      const alt = "Cool Routes map showing the coolest and the shortest walking route between Coor Hall and Creativity Commons, with route statistics";
      host.innerHTML = `<div class="live-stage" data-state="${p.poster ? "poster" : "live"}">
          <iframe data-src="${src}" title="${label} live tool" allow="geolocation; fullscreen"${p.poster ? ' tabindex="-1"' : ""}></iframe>
          ${p.poster ? `<button type="button" class="poster" aria-label="Open the live ${label} tool">
            <span class="poster-art"><img src="${p.poster}" alt="${alt}" draggable="false"></span>
            <span class="poster-chip" aria-hidden="true"><i></i>Click to explore the live tool</span>
          </button>` : ""}
        </div>`;
      const stage = host.querySelector(".live-stage"), f = stage.querySelector("iframe");
      // the live app loads underneath the cover as soon as the section is near the screen
      new IntersectionObserver((es, o) => es.forEach((e) => { if (e.isIntersecting) { f.src = f.dataset.src; o.disconnect(); } }), { rootMargin: "400px" }).observe(stage);

      const poster = stage.querySelector(".poster");
      if (poster) {
        // A lens follows the pointer and cuts a hole in the cover, so the live map shows through.
        // Clicking grows the lens until it fills the stage, then the live tool takes over.
        const IDLE = -24, LENS = 120;
        let x = 0, y = 0, r = IDLE, goal = IDLE, raf = 0, opening = false;
        const paint = () => { poster.style.setProperty("--mx", x + "px"); poster.style.setProperty("--my", y + "px"); poster.style.setProperty("--r", r + "px"); };
        const loop = () => {
          r += (goal - r) * (opening ? 0.11 : 0.2);
          paint();
          if (opening && r > Math.hypot(stage.clientWidth, stage.clientHeight) * 0.98) { done(); return; }
          raf = Math.abs(goal - r) > 0.5 || opening ? requestAnimationFrame(loop) : 0;
        };
        const kick = () => { if (!raf) raf = requestAnimationFrame(loop); };
        const done = () => {
          stage.dataset.state = "live"; poster.remove();
          f.removeAttribute("tabindex"); f.focus({ preventScroll: true });
        };
        const where = (e) => { const b = stage.getBoundingClientRect(); x = e.clientX - b.left; y = e.clientY - b.top; };
        poster.addEventListener("pointermove", (e) => {
          if (opening || e.pointerType === "touch") return;
          where(e); goal = LENS; stage.style.setProperty("--cx", x + "px"); stage.style.setProperty("--cy", y + "px"); kick();
        });
        poster.addEventListener("pointerleave", () => { if (!opening) { goal = IDLE; kick(); } });
        poster.addEventListener("click", (e) => {
          if (opening) return;
          if (e.detail === 0) { const b = stage.getBoundingClientRect(); x = b.width / 2; y = b.height / 2; } else where(e);   // keyboard: open from the centre
          if (reduce) { done(); return; }
          opening = true; r = Math.max(r, LENS); goal = Math.hypot(stage.clientWidth, stage.clientHeight) * 1.1;
          stage.dataset.state = "opening"; kick();
        });
        paint();
      }
    } else {
      host.innerHTML = `<div class="launch"><div><b>${label} live tool</b><p>Run the full tool on the SHaDE Lab site.</p></div>
        <a class="btn primary" href="${p.tool}" target="_blank" rel="noopener">View live tool ↗</a></div>`;
    }
  });

  /* ---------- lazy-load the real demo widgets ---------- */
  function loadDemo(el) {
    if (el.dataset.started) return;                       // each demo loads once
    el.dataset.started = "1";
    const name = el.dataset.demo, status = $(".demo-status", el);
    const css = document.createElement("link");           // each demo may ship its own stylesheet
    css.rel = "stylesheet"; css.href = `demos/${name}/demo.css`;
    document.head.appendChild(css);
    const s = document.createElement("script");
    s.src = `demos/${name}/demo.js`;
    s.onload = () => {
      try { window.UHDemos[name].mount(el); if (status) status.remove(); }
      catch (e) { fail(e); }
    };
    s.onerror = () => fail(new Error("demo script not found"));
    function fail(e) {
      if (status) status.innerHTML = "The interactive demo could not load (" + e.message + "). " +
        "If you opened this page from a file, serve the folder instead: <code>python -m http.server</code>.";
    }
    document.head.appendChild(s);
  }
  window.UHDemos = window.UHDemos || {};
  const dio = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { dio.unobserve(e.target); loadDemo(e.target); }
  }), { rootMargin: "300px" });
  $$("[data-demo]").forEach((el) => dio.observe(el));

  /* ---------- pointer as a light source (section titles only) ----------
     Light mode: a soft cast shadow pushed away from the pointer.
     Dark mode: a shadow is invisible on a dark page, so the title is *lit* instead:
       - the glyphs brighten with a radial falloff centred on the pointer,
       - a warm extruded edge is stacked away from the light (length follows angle/distance),
       - a faint rim glow sits on the side facing the light.
     A soft spotlight follows the pointer. Disabled for reduced-motion users. */
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const glow = document.createElement("div");
    glow.id = "spot"; glow.setAttribute("aria-hidden", "true");
    document.body.appendChild(glow);
    const targets = $$(".hero h1, main section h2").map((el) => ({ el, hero: el.matches(".hero h1"), uv: !!el.closest("#webmrt") }));
    let mx = innerWidth * 0.3, my = innerHeight * 0.25, want = false, idle;
    function paint() {
      want = false;
      const dark = root.dataset.theme === "dark";
      glow.style.setProperty("--lx", mx + "px"); glow.style.setProperty("--ly", my + "px");
      for (const t of targets) {
        const el = t.el, r = el.getBoundingClientRect();
        if (r.bottom < -80 || r.top > innerHeight + 80) continue;            // off-screen: skip
        const cx = r.left + Math.min(r.width, 520) / 2, cy = r.top + r.height / 2;
        const dx = cx - mx, dy = cy - my, d = Math.hypot(dx, dy) || 1;
        const ux = dx / d, uy = dy / d;                                      // unit vector: light -> title
        const near = Math.exp(-d / 460);                                     // 1 at the light, -> 0 far away
        const len = 4 + 14 * (0.3 + 0.7 * near);                             // extrusion / shadow length (px)
        if (dark) {
          // extruded warm edge: 4 chained zero-blur copies stepping away from the light
          const step = len / 4, a = (0.35 + 0.4 * near).toFixed(2);
          const ex = `drop-shadow(${(ux * step).toFixed(1)}px ${(uy * step).toFixed(1)}px 0 ${t.uv ? `rgba(124,82,255,${a})` : `rgba(176,84,40,${a})`})`;
          const rim = `drop-shadow(${(-ux * (1 + 2 * near)).toFixed(1)}px ${(-uy * (1 + 2 * near)).toFixed(1)}px ${(2 + 4 * near).toFixed(1)}px ${t.uv ? `rgba(214,196,255,${(0.2 + 0.5 * near).toFixed(2)})` : t.hero ? `rgba(255,214,150,${(0.15 + 0.5 * near).toFixed(2)})` : `rgba(255,226,102,${(0.2 + 0.55 * near).toFixed(2)})`})`;
          const soft = `drop-shadow(0 0 ${(10 + 26 * near).toFixed(0)}px ${t.uv ? `rgba(138,99,255,${(0.14 + 0.36 * near).toFixed(2)})` : `rgba(255,150,70,${(0.10 + 0.30 * near).toFixed(2)})`})`;
          el.style.filter = `${ex} ${ex} ${ex} ${ex} ${rim} ${soft}`;
          if (!t.hero) {                                                     // pointer-lit glyph fill (hero keeps its gradient)
            el.classList.add("lit");
            el.style.setProperty("--gx", (mx - r.left).toFixed(0) + "px");
            el.style.setProperty("--gy", (my - r.top).toFixed(0) + "px");
          }
        } else {
          el.classList.remove("lit");
          const blur = 4 + d / 90;
          el.style.filter = `drop-shadow(${(ux * len).toFixed(1)}px ${(uy * len).toFixed(1)}px ${blur.toFixed(1)}px rgba(60,30,10,.30)) ` +
                            `drop-shadow(${(-ux * (0.8 + 1.4 * near)).toFixed(1)}px ${(-uy * (0.8 + 1.4 * near)).toFixed(1)}px 0 rgba(255,255,255,${(0.6 * near).toFixed(2)}))`;
        }
      }
    }
    const kick = () => { if (!want) { want = true; requestAnimationFrame(paint); } };
    addEventListener("pointermove", (e) => {
      mx = e.clientX; my = e.clientY; glow.style.opacity = 1; kick();
      clearTimeout(idle); idle = setTimeout(() => (glow.style.opacity = 0.55), 2500);
    }, { passive: true });
    document.addEventListener("pointerleave", () => (glow.style.opacity = 0));
    addEventListener("scroll", kick, { passive: true });
    addEventListener("resize", kick);
    document.addEventListener("uh:theme", kick);
    kick();
  }
})();
