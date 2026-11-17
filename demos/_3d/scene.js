/* Shared 3D viewer for the MaRTy and MaRTiny models.
   three.js is loaded through the import map in index.html (pinned CDN version).
   A builder returns { root, parts, extras?, update? }; this module supplies the scene, lights, orbit
   controls, hover highlights, labels and the parts list. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

export { THREE };

/* ---------- small geometry helpers (units are metres) ---------- */
export const mat = (color, o = {}) => new THREE.MeshStandardMaterial({
  color, roughness: o.rough ?? 0.5, metalness: o.metal ?? 0,
  transparent: o.opacity !== undefined, opacity: o.opacity ?? 1, side: o.side ?? THREE.FrontSide, emissive: 0x000000,
});
export const cyl = (r, h, m, seg = 28, rTop) => new THREE.Mesh(new THREE.CylinderGeometry(rTop ?? r, r, h, seg), m);
export const box = (w, h, d, m) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
export const rbox = (w, h, d, r, m, seg = 3) => new THREE.Mesh(new RoundedBoxGeometry(w, h, d, seg, Math.min(r, w / 2 - 1e-4, h / 2 - 1e-4, d / 2 - 1e-4)), m);
export const sph = (r, m, seg = 28) => new THREE.Mesh(new THREE.SphereGeometry(r, seg, Math.max(12, seg / 2)), m);
export const at = (o, x, y, z) => { o.position.set(x, y, z); return o; };
export function between(a, b, r, m, seg = 14) {                       // a cylinder running from point a to point b
  const va = new THREE.Vector3(...a), vb = new THREE.Vector3(...b), len = va.distanceTo(vb), mesh = cyl(r, len, m, seg);
  mesh.position.copy(va).add(vb).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), vb.clone().sub(va).normalize());
  return mesh;
}
export function cable(points, r, m) {
  const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)));
  return new THREE.Mesh(new THREE.TubeGeometry(curve, 56, r, 8, false), m);
}
export function own(obj) { obj.traverse((o) => { if (o.isMesh) o.material = o.material.clone(); }); return obj; }   // per-part materials, so highlights stay local
export function textTexture(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}

/* ---------- the viewer ---------- */
export function createViewer(host, spec) {
  host.innerHTML = `<div class="v3d">
    <div class="v3d-stage">
      <canvas class="v3d-canvas" aria-label="${spec.label || "3D model"}"></canvas>
      <div class="v3d-pin" hidden></div>
      <div class="v3d-bar"><button type="button" data-act="reset">Reset view</button><button type="button" data-act="spin" aria-pressed="true">Auto-rotate</button><span class="v3d-extra"></span></div>
      <div class="v3d-hint">Drag to rotate · scroll or pinch to zoom</div>
    </div>
    <div class="v3d-side"><ol class="v3d-parts"></ol></div>
  </div>`;
  const q = (s) => host.querySelector(s);
  const stage = q(".v3d-stage"), canvas = q(".v3d-canvas"), pin = q(".v3d-pin"), list = q(".v3d-parts");

  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" }); }
  catch (e) { stage.innerHTML = '<p class="demo-status">This 3D view needs WebGL, which is not available in this browser.</p>'; return null; }
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 0.35));
  const sun = new THREE.DirectionalLight(0xfff1dc, 2.8);
  sun.position.set(2.2, 3.6, 2.4); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.01;
  const sc = sun.shadow.camera; sc.left = -1.6; sc.right = 1.6; sc.top = 1.6; sc.bottom = -1.6; sc.near = 0.5; sc.far = 10;
  scene.add(sun);
  const rimLight = new THREE.DirectionalLight(0xbcd2ff, 0.9); rimLight.position.set(-3, 2.2, -3); scene.add(rimLight);

  const built = spec.build();
  scene.add(built.root);
  built.root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });

  // ground: a concrete floor that fades out at the edge and receives the shadows
  const concrete = textTexture(512, 512, (c, w, h) => {
    c.fillStyle = "#a3a29d"; c.fillRect(0, 0, w, h);
    for (let i = 0; i < 14000; i++) { const g = Math.random() < 0.5 ? 0 : 255; c.fillStyle = `rgba(${g},${g},${g},${Math.random() * 0.1})`; c.fillRect(Math.random() * w, Math.random() * h, 1 + Math.random() * 2, 1 + Math.random() * 2); }
    c.strokeStyle = "rgba(0,0,0,.12)"; c.lineWidth = 2; c.beginPath(); c.moveTo(0, h / 2); c.lineTo(w, h / 2); c.moveTo(w / 2, 0); c.lineTo(w / 2, h); c.stroke();   // expansion joints
  });
  concrete.wrapS = concrete.wrapT = THREE.RepeatWrapping; concrete.repeat.set(2, 2);
  const fade = textTexture(256, 256, (c, w, h) => { const g = c.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2); g.addColorStop(0, "#fff"); g.addColorStop(0.62, "#fff"); g.addColorStop(1, "#000"); c.fillStyle = g; c.fillRect(0, 0, w, h); });
  fade.colorSpace = THREE.NoColorSpace;
  const ground = new THREE.Mesh(new THREE.CircleGeometry(spec.ground ?? 1.4, 96), new THREE.MeshStandardMaterial({ map: concrete, alphaMap: fade, transparent: true, roughness: 0.96, metalness: 0 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.002; ground.receiveShadow = true; scene.add(ground);
  const tint = () => {
    const css = getComputedStyle(document.documentElement), dark = document.documentElement.dataset.theme === "dark";
    ground.material.color.set(dark ? "#5b6270" : "#e7e2d8");
    accent.set((css.getPropertyValue("--accent") || "#ff6a4d").trim() || "#ff6a4d");
  };
  const accent = new THREE.Color("#ff6a4d");
  tint(); document.addEventListener("uh:theme", () => { tint(); });

  // camera and controls
  const cam = spec.camera;
  const camera = new THREE.PerspectiveCamera(cam.fov ?? 32, 1, 0.05, 40);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.autoRotate = true; controls.autoRotateSpeed = 1.1;
  controls.minDistance = cam.min ?? 0.6; controls.maxDistance = cam.max ?? 6; controls.maxPolarAngle = Math.PI / 2 - 0.03; controls.enablePan = false;
  const home = () => { camera.position.set(...cam.pos); controls.target.set(...cam.target); controls.update(); };
  home();
  const spinBtn = q('[data-act="spin"]');
  const setSpin = (on) => { controls.autoRotate = on; spinBtn.setAttribute("aria-pressed", String(on)); };
  controls.addEventListener("start", () => setSpin(false));
  q('[data-act="reset"]').addEventListener("click", () => { home(); setSpin(true); });
  spinBtn.addEventListener("click", () => setSpin(!controls.autoRotate));

  // optional extra toggles (e.g. "Open the case")
  (built.extras || []).forEach((x) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = x.label; b.setAttribute("aria-pressed", String(!!x.on));
    b.addEventListener("click", () => { x.on = !x.on; b.setAttribute("aria-pressed", String(x.on)); x.toggle(x.on); if (x.on && x.focus) { setSpin(false); } });
    q(".v3d-extra").appendChild(b);
  });

  // parts list, hover highlight and label
  const meshToPart = new Map(), partMeshes = [];
  built.parts.forEach((p, i) => {
    own(p.object);
    p.object.traverse((o) => { if (o.isMesh) { meshToPart.set(o, i); partMeshes.push(o); } });
    const li = document.createElement("li");
    li.innerHTML = `<button type="button"><span class="n">${i + 1}</span><span><b>${p.label}</b><small>${p.detail}</small></span></button>`;
    li.querySelector("button").addEventListener("pointerenter", () => hover(i));
    li.querySelector("button").addEventListener("focus", () => hover(i));
    li.querySelector("button").addEventListener("pointerleave", () => hover(-1));
    li.querySelector("button").addEventListener("blur", () => hover(-1));
    list.appendChild(li);
  });
  let cur = -1;
  const box3 = new THREE.Box3(), v = new THREE.Vector3();
  function hover(i) {
    if (i === cur) return;
    cur = i;
    built.parts.forEach((p, k) => p.object.traverse((o) => {
      if (!o.isMesh) return;
      o.material.emissive.set(k === i ? accent : 0x000000); o.material.emissiveIntensity = k === i ? 0.55 : 0;
    }));
    [...list.children].forEach((li, k) => li.classList.toggle("on", k === i));
    pin.hidden = i < 0; if (i >= 0) pin.textContent = built.parts[i].label;
    stage.style.cursor = i >= 0 ? "pointer" : "grab";
  }
  function placePin() {
    if (cur < 0) return;
    box3.setFromObject(built.parts[cur].object).getCenter(v).project(camera);
    const w = stage.clientWidth, h = stage.clientHeight;
    pin.style.transform = `translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px) translate(-50%, -135%)`;
  }
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  canvas.addEventListener("pointermove", (e) => {
    if (e.buttons) return;
    const r = canvas.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(partMeshes, false)[0];
    hover(hit ? meshToPart.get(hit.object) : -1);
  });
  canvas.addEventListener("pointerleave", () => hover(-1));

  // sizing and the render loop (runs only while the viewer is on screen)
  const resize = () => {
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(stage); resize();
  const clock = new THREE.Clock(); let running = false, raf = 0;
  const frame = () => {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), 0.05);
    built.update?.(dt, clock.elapsedTime);
    controls.update(); placePin(); renderer.render(scene, camera);
  };
  new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting && !running) { running = true; clock.getDelta(); frame(); }
    else if (!e.isIntersecting && running) { running = false; cancelAnimationFrame(raf); }
  }), { rootMargin: "120px" }).observe(stage);
  frame(); cancelAnimationFrame(raf); running = false; renderer.render(scene, camera);          // first frame right away
  return { scene, camera, controls, renderer, built, render: () => renderer.render(scene, camera) };
}
