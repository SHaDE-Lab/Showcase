/* MaRTy: procedural 3D model.
   Built from photographs of the cart, the sensor table in Middel & Krayenhoff (2019, Sci. Total Environ. 687:137-151)
   and the lab's MaRTy cheat sheet (arm and radiometer layout). Units are metres; proportions are approximate.
   Cart long axis = X (handle at -X), plates on the +Z side, mast slightly right of centre. */
import { THREE, mat, cyl, box, rbox, sph, at, between, cable, textTexture } from "./scene.js";

const MX = 0.14;                                                        // mast position along the cart

export function buildMarty() {
  const M = {
    red: mat(0xc9261c, { rough: 0.38, metal: 0.15 }), galv: mat(0xb7bcc4, { rough: 0.38, metal: 0.9 }), alu: mat(0xc9ced5, { rough: 0.22, metal: 0.9 }),
    brass: mat(0xb8892e, { rough: 0.35, metal: 0.85 }), black: mat(0x141518, { rough: 0.62 }), tire: mat(0x0f1012, { rough: 0.95 }),
    rim: mat(0x9aa1ab, { rough: 0.4, metal: 0.6 }), white: mat(0xf3f4f6, { rough: 0.48 }), pipe: mat(0xeceff1, { rough: 0.45 }),
    glass: mat(0xdbe6ee, { rough: 0.06, opacity: 0.8 }), gps: mat(0x13274a, { rough: 0.22, metal: 0.3 }), yellow: mat(0xf2d21c, { rough: 0.5 }),
    floor: mat(0x2a2d32, { rough: 0.85 }), dark: mat(0x24272d, { rough: 0.6 }), steel: mat(0x6d737c, { rough: 0.45, metal: 0.7 }),
    cable: mat(0x0a0a0c, { rough: 0.55 }), zip: mat(0xc6f23a, { rough: 0.5 }), bracket: mat(0xe9eaec, { rough: 0.4, metal: 0.45 }),
  };
  const root = new THREE.Group();
  const group = (...kids) => { const g = new THREE.Group(); kids.forEach((k) => g.add(k)); return g; };
  const rr = (c, x, y, w, h, r) => { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };

  /* ---------- plates and logos (canvas textures) ---------- */
  const flagTex = textTexture(1536, 900, (c, w, h) => {                          // "MaRTy" plate in the Arizona flag design
    rr(c, 0, 0, w, h, 90); c.clip();
    const cx = w / 2, cy = h * 0.5;
    const g = c.createLinearGradient(0, cy, 0, h); g.addColorStop(0, "#2d62a8"); g.addColorStop(1, "#1d4784"); c.fillStyle = g; c.fillRect(0, cy, w, h - cy);
    const n = 13;
    for (let i = 0; i < n; i++) {
      c.beginPath(); c.moveTo(cx, cy); c.arc(cx, cy, w, Math.PI + (i * Math.PI) / n, Math.PI + ((i + 1) * Math.PI) / n); c.closePath();
      c.fillStyle = i % 2 ? "#b02a30" : "#f1c22b"; c.fill();
    }
    c.fillStyle = "#b02a30"; c.fillRect(0, cy - 6, w, h * 0.08);
    const star = (R, r, col, stroke) => { c.beginPath(); for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + (i * Math.PI) / 5, rad = i % 2 ? r : R; c.lineTo(cx + Math.cos(a) * rad, cy + Math.sin(a) * rad); } c.closePath(); c.fillStyle = col; c.fill(); if (stroke) { c.strokeStyle = stroke; c.lineWidth = 9; c.stroke(); } };
    star(h * 0.215, h * 0.09, "#dba432", "#8a6120");
    c.textAlign = "center"; c.textBaseline = "middle";
    c.font = `800 ${h * 0.24}px Inter, Arial, sans-serif`;
    c.lineWidth = h * 0.02; c.strokeStyle = "rgba(255,255,255,.85)"; c.strokeText("MaRTy 2", cx, cy + h * 0.07);             // light outline keeps the name readable over the rays
    c.fillStyle = "#13203a"; c.fillText("MaRTy 2", cx, cy + h * 0.07);
    c.fillStyle = "#ff6a4a"; c.font = `700 ${h * 0.082}px Inter, Arial, sans-serif`; c.fillText("@ASUMaRTy", cx, h * 0.9);
    c.fillStyle = "#cfd3da"; [[0.07, 0.92], [0.93, 0.92]].forEach(([x, y]) => { c.beginPath(); c.arc(w * x, h * y, h * 0.03, 0, 7); c.fill(); });
  });
  const shadeTex = textTexture(512, 290, (c, w, h) => {                          // Arizona "SHaDE Lab" plate
    rr(c, 0, 0, w, h, 28); c.clip();
    const g = c.createLinearGradient(0, 0, 0, h);
    [[0, "#3a8cc6"], [0.16, "#58a8d8"], [0.18, "#eaf4fb"], [0.46, "#f3f8fc"], [0.64, "#f6e6a6"], [1, "#f0a92c"]].forEach(([o, col]) => g.addColorStop(o, col));
    c.fillStyle = g; c.fillRect(0, 0, w, h);
    c.textAlign = "center"; c.textBaseline = "middle";
    c.fillStyle = "#ffffff"; c.font = `800 ${h * 0.115}px Inter, Arial, sans-serif`; c.fillText("ARIZONA", w / 2, h * 0.085);
    c.fillStyle = "#14233c"; c.font = `800 ${h * 0.2}px Inter, Arial, sans-serif`; c.fillText("SHaDE Lab", w / 2, h * 0.37);
    c.fillStyle = "#1b3a66"; c.font = `600 ${h * 0.07}px Inter, Arial, sans-serif`; c.fillText("@ArianeMiddel", w / 2, h * 0.53);
    c.fillStyle = "#2b2016";                                                       // desert hills and a saguaro
    c.beginPath(); c.moveTo(0, h * 0.86); c.quadraticCurveTo(w * 0.2, h * 0.7, w * 0.38, h * 0.8); c.quadraticCurveTo(w * 0.6, h * 0.7, w * 0.8, h * 0.79); c.quadraticCurveTo(w * 0.92, h * 0.74, w, h * 0.8); c.lineTo(w, h); c.lineTo(0, h); c.closePath(); c.fill();
    c.fillRect(w * 0.1, h * 0.58, 12, h * 0.3); c.fillRect(w * 0.1 - 22, h * 0.66, 12, h * 0.1); c.fillRect(w * 0.1 - 22, h * 0.74, 34, 10); c.fillRect(w * 0.1 + 22, h * 0.62, 12, h * 0.1); c.fillRect(w * 0.1, h * 0.7, 34, 10);
    c.fillStyle = "#3b2c1c"; c.font = `600 ${h * 0.05}px Inter, Arial, sans-serif`; c.textAlign = "right"; c.fillText("GRAND CANYON STATE", w * 0.95, h * 0.9);
    c.fillStyle = "#e5e7ec"; [[0.06, 0.06], [0.94, 0.06]].forEach(([x, y]) => { c.beginPath(); c.arc(w * x, h * y, 8, 0, 7); c.fill(); });
  });
  const logoTex = textTexture(256, 70, (c, w, h) => {
    rr(c, 0, 0, w, h, 14); c.fillStyle = "#16171a"; c.fill();
    c.fillStyle = "#f2f2f2"; c.beginPath(); c.arc(38, h / 2, 20, 0, 7); c.fill(); c.fillStyle = "#16171a"; c.beginPath(); c.arc(32, h / 2 - 3, 4, 0, 7); c.arc(44, h / 2 - 3, 4, 0, 7); c.fill();
    c.textBaseline = "middle"; c.font = "800 26px Inter, Arial, sans-serif"; c.fillStyle = "#f2f2f2"; c.fillText("ORILLA", 64, h / 2 + 1);
    c.fillStyle = "#f2d21c"; c.fillText("CARTS", 154, h / 2 + 1);
  });
  const flat = (tex, w, h) => new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.45, metalness: 0.05, transparent: true }));

  /* ---------- wagon: red steel frame, wire mesh, tray, wheels ---------- */
  const cart = new THREE.Group();
  cart.add(at(rbox(0.95, 0.02, 0.58, 0.004, M.floor), 0, 0.285, 0));
  cart.add(at(rbox(0.82, 0.04, 0.5, 0.01, M.dark), 0, 0.235, 0));
  const R = (w, h, d, x, y, z, r = 0.006) => cart.add(at(rbox(w, h, d, r, M.red), x, y, z));
  for (const z of [-0.29, 0.29]) { R(0.99, 0.07, 0.032, 0, 0.27, z, 0.008); R(0.99, 0.028, 0.028, 0, 0.55, z); }      // lower tray lip, top rail
  for (const x of [-0.475, 0.475]) { R(0.032, 0.07, 0.6, x, 0.27, 0, 0.008); R(0.028, 0.028, 0.6, x, 0.55, 0); }
  for (const x of [-0.475, 0.475]) for (const z of [-0.29, 0.29]) R(0.028, 0.29, 0.028, x, 0.415, z);
  for (const z of [-0.29, 0.29]) for (const x of [-0.16, 0.2]) R(0.022, 0.26, 0.022, x, 0.415, z);                  // mid posts
  for (const z of [-0.305, 0.305]) for (const x of [-0.43, -0.08, 0.27, 0.43]) cart.add(at(rbox(0.045, 0.045, 0.014, 0.004, M.red), x, 0.29, z));   // hinge tabs
  const meshTex = textTexture(128, 128, (c, w, h) => {
    c.clearRect(0, 0, w, h); c.strokeStyle = "#d83428"; c.lineWidth = 9; c.lineCap = "round";
    c.beginPath(); c.moveTo(0, h / 2); c.lineTo(w / 2, 0); c.lineTo(w, h / 2); c.lineTo(w / 2, h); c.closePath(); c.stroke();
  });
  meshTex.wrapS = meshTex.wrapT = THREE.RepeatWrapping;
  const side = (len, rotY, x, z) => {
    const t = meshTex.clone(); t.needsUpdate = true; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(len / 0.065, 0.26 / 0.065);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(len, 0.26), new THREE.MeshStandardMaterial({ map: t, transparent: true, alphaTest: 0.35, side: THREE.DoubleSide, roughness: 0.5 }));
    m.position.set(x, 0.415, z); m.rotation.y = rotY; cart.add(m);
  };
  side(0.95, 0, 0, 0.29); side(0.95, 0, 0, -0.29); side(0.58, Math.PI / 2, 0.475, 0); side(0.58, Math.PI / 2, -0.475, 0);
  // brand logos on the tray lip
  [[-0.3, 0.3075, 0], [0.2, 0.3075, 0], [-0.3, -0.3075, Math.PI], [0.2, -0.3075, Math.PI]].forEach(([x, z, ry]) => { const l = flat(logoTex, 0.13, 0.036); l.position.set(x, 0.268, z); l.rotation.y = ry; cart.add(l); });
  // plates, held on with yellow zip ties
  // SHaDE Lab plate: centred on the long side that faces the up/down arm (+Z)
  const shade = flat(shadeTex, 0.34, 0.193); shade.position.set(0.0, 0.425, 0.299); cart.add(shade);
  // MaRTy 2 plate: centred on the short end that faces the left/right radiometer (+X)
  const flag = flat(flagTex, 0.30, 0.176); flag.position.set(0.488, 0.425, 0); flag.rotation.y = Math.PI / 2; cart.add(flag);
  [[-0.15, 0.51], [0.15, 0.51], [-0.15, 0.34], [0.15, 0.34]].forEach(([x, y]) => cart.add(at(rbox(0.012, 0.03, 0.006, 0.002, M.zip), x, y, 0.3)));
  [[-0.12, 0.51], [0.12, 0.51], [-0.12, 0.34], [0.12, 0.34]].forEach(([z, y]) => cart.add(at(rbox(0.006, 0.03, 0.012, 0.002, M.zip), 0.489, y, z)));
  // wheels: knobby tyres, grey rims, axles and brackets
  const tyreProfile = [[0.062, -0.046], [0.095, -0.048], [0.116, -0.04], [0.126, -0.02], [0.1275, 0], [0.126, 0.02], [0.116, 0.04], [0.095, 0.048], [0.062, 0.046]].map(([r, y]) => new THREE.Vector2(r, y));
  const tyreGeo = new THREE.LatheGeometry(tyreProfile, 64);
  const lugGeo = new THREE.BoxGeometry(0.02, 0.014, 0.03);
  const wheel = (x, z, flip) => {
    const w = new THREE.Group();
    w.add(new THREE.Mesh(tyreGeo, M.tire));
    const lugs = new THREE.InstancedMesh(lugGeo, M.tire, 80), d = new THREE.Object3D();
    for (let i = 0; i < 40; i++) for (let k = 0; k < 2; k++) {
      const a = (i + k * 0.5) * (Math.PI * 2 / 40);
      d.position.set(Math.cos(a) * 0.1285, k ? -0.024 : 0.024, Math.sin(a) * 0.1285); d.rotation.set(0, -a, 0); d.updateMatrix(); lugs.setMatrixAt(i * 2 + k, d.matrix);
    }
    w.add(lugs);
    w.add(cyl(0.068, 0.092, M.rim, 40)); w.add(cyl(0.024, 0.104, M.alu, 24));
    for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3, b = cyl(0.006, 0.098, M.steel, 8); b.position.set(Math.cos(a) * 0.045, 0, Math.sin(a) * 0.045); w.add(b); }
    w.rotation.x = Math.PI / 2; const g = new THREE.Group(); g.add(w); g.position.set(x, 0.1275, z); return g;
  };
  [[-0.36, 0.335], [0.36, 0.335], [-0.36, -0.335], [0.36, -0.335]].forEach(([x, z]) => cart.add(wheel(x, z)));
  for (const x of [-0.36, 0.36]) {
    const ax = cyl(0.011, 0.7, M.steel, 14); ax.rotation.x = Math.PI / 2; cart.add(at(ax, x, 0.1275, 0));
    for (const z of [-0.292, 0.292]) cart.add(at(rbox(0.016, 0.14, 0.1, 0.004, M.steel), x, 0.205, z));
  }
  // drag handle with a D-shaped grip lying on the ground
  cart.add(cable([[-0.475, 0.305, 0.14], [-0.57, 0.27, 0.19], [-0.74, 0.11, 0.27], [-0.86, 0.025, 0.33]], 0.011, M.galv));
  const grip = new THREE.CatmullRomCurve3([[-0.86, 0.025, 0.33], [-1.0, 0.025, 0.31], [-0.93, 0.025, 0.47]].map((p) => new THREE.Vector3(...p)), true);
  cart.add(new THREE.Mesh(new THREE.TubeGeometry(grip, 40, 0.014, 10, true), M.black));

  /* ---------- tripod, mast, cross poles ---------- */
  const apex = [MX, 1.04, 0], bases = [[MX - 0.17, 0.295, 0.16], [MX + 0.17, 0.295, 0.16], [MX, 0.295, -0.22]];
  bases.forEach((b) => cart.add(between(b, apex, 0.0125, M.galv)));
  const lerp3 = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
  [[0, 1], [1, 2], [2, 0]].forEach(([i, j]) => cart.add(between(lerp3(bases[i], apex, 0.42), lerp3(bases[j], apex, 0.42), 0.0045, M.brass, 8)));   // brass V-braces
  cart.add(between([MX, 0.295, 0], [MX, 1.50, 0], 0.016, M.galv));
  cart.add(at(cyl(0.028, 0.024, M.brass, 24), MX, 1.0, 0)); cart.add(at(cyl(0.028, 0.024, M.brass, 24), MX, 1.075, 0));   // pipe clamps at the apex
  for (const y of [1.0, 1.075]) cart.add(at(rbox(0.05, 0.016, 0.016, 0.003, M.steel), MX, y, 0.03));
  // white pipe that carries the wind sensor, with a MaRTy label
  cart.add(between([MX, 1.50, 0], [MX, 1.665, 0], 0.02, M.pipe, 24));
  cart.add(between([MX, 1.665, 0], [MX, 1.705, 0], 0.0235, M.black, 24));
  cart.add(at(cyl(0.0205, 0.022, M.yellow, 24), MX, 1.60, 0));
  // long pole: across the cart through the mast; up/down radiometer at the +Z end, back/front at the -Z end
  const LY = 1.16, SY = 1.06, LEND = 0.64, SEND = 0.60;
  cart.add(between([MX, LY, -LEND], [MX, LY, LEND], 0.0165, M.galv));
  // short pole: in line with the cart, away from the handle; left/right radiometer at its end
  cart.add(between([MX, SY, 0], [MX + SEND, SY, 0], 0.0165, M.galv));
  [[MX, LY], [MX, SY]].forEach(([x, y]) => cart.add(at(rbox(0.055, 0.05, 0.055, 0.008, M.steel), x, y, 0)));
  cart.add(at(cyl(0.0172, 0.04, M.yellow, 20), MX, LY, LEND - 0.075).rotateX(Math.PI / 2));
  cart.add(at(cyl(0.0172, 0.04, M.yellow, 20), MX, LY, -LEND + 0.075).rotateX(Math.PI / 2));
  cart.add(at(cyl(0.0172, 0.04, M.yellow, 20), MX + SEND - 0.075, SY, 0).rotateZ(Math.PI / 2));
  root.add(cart);

  /* ---------- data logger case ---------- */
  const logger = group(
    at(rbox(0.34, 0.17, 0.26, 0.014, M.white), -0.22, 0.38, -0.02),
    at(rbox(0.345, 0.006, 0.265, 0.003, M.bracket), -0.22, 0.4, -0.02),
    at(rbox(0.032, 0.05, 0.014, 0.004, M.steel), -0.3, 0.375, 0.118), at(rbox(0.032, 0.05, 0.014, 0.004, M.steel), -0.14, 0.375, 0.118),
    at(cyl(0.012, 0.03, M.black, 16), -0.05, 0.4, -0.02), at(cyl(0.012, 0.03, M.black, 16), -0.05, 0.35, 0.03),
  );
  logger.children[4].rotation.z = Math.PI / 2; logger.children[5].rotation.z = Math.PI / 2;
  root.add(logger);

  /* ---------- net radiometer modules (Hukseflux NR01 style) ----------
     A module is two white saucer hoods back to back around an aluminium body. A shortwave module carries glass
     domes; a longwave module carries flat silicon windows. Local Y is the sensing axis. */
  const hoodGeo = new THREE.LatheGeometry([[0, 0.022], [0.017, 0.022], [0.021, 0.0212], [0.03, 0.0195], [0.045, 0.016], [0.055, 0.0105], [0.0612, 0.004], [0.0625, 0.0], [0.058, -0.0014], [0.04, -0.0014], [0, -0.0014]].map(([r, y]) => new THREE.Vector2(r, y)), 56);
  const hoodMat = mat(0xf6f7f8, { rough: 0.35, side: THREE.DoubleSide });
  // rear face: a concave dish (recessed centre, raised rim), no sensor window
  const dishGeo = new THREE.LatheGeometry([[0, 0.0], [0.022, 0.0016], [0.036, 0.0075], [0.049, 0.0135], [0.0585, 0.019], [0.0625, 0.0215], [0.0615, 0.0172], [0.05, 0.0098], [0.034, 0.0038], [0.018, 0.0008], [0, 0.0]].map(([r, y]) => new THREE.Vector2(r, y)), 56);
  const hood = (sign, kind) => {
    const g = new THREE.Group();
    if (sign > 0) {                                                            // front face: convex saucer with the sensor window
      g.add(new THREE.Mesh(hoodGeo, hoodMat));
      g.add(at(cyl(0.0172, 0.007, M.alu, 28), 0, 0.0245, 0));
      if (kind === "sw") { const dome = sph(0.0125, M.glass, 28); dome.scale.y = 0.8; g.add(at(dome, 0, 0.028, 0)); }
      else { g.add(at(cyl(0.0148, 0.004, M.alu, 28), 0, 0.0285, 0)); g.add(at(cyl(0.0085, 0.0045, M.dark, 20), 0, 0.0288, 0)); }
    } else {                                                                   // back face: concave dish
      g.add(new THREE.Mesh(dishGeo, hoodMat));
      g.add(at(cyl(0.012, 0.004, M.alu, 24), 0, 0.001, 0));
    }
    g.position.y = sign * 0.03; if (sign < 0) g.rotation.x = Math.PI;
    return g;
  };
  const nrModule = (kind, axis, x, y, z) => {
    const g = new THREE.Group(); g.add(hood(1, kind)); g.add(hood(-1, kind)); g.add(cyl(0.0205, 0.062, M.alu, 28));
    if (axis === "z") g.rotation.x = Math.PI / 2; else if (axis === "x") g.rotation.z = Math.PI / 2;
    g.position.set(x, y, z); return g;
  };
  // each net radiometer has a shortwave and a longwave module on a bar at the pole end: side by side for up/down, stacked vertically for the horizontal-looking units
  const unit = (axis, along, x, y, z) => {                                   // along: the horizontal direction the two modules are spread over
    const g = new THREE.Group(), s = 0.085;
    const dx = along === "x" ? s : 0, dy = along === "y" ? s : 0, dz = along === "z" ? s : 0;
    g.add(nrModule("sw", axis, x - dx, y - dy, z - dz)); g.add(nrModule("lw", axis, x + dx, y + dy, z + dz));
    const bar = cyl(0.0095, 0.17, M.alu, 14); if (along === "x") bar.rotation.z = Math.PI / 2; else if (along === "z") bar.rotation.x = Math.PI / 2; g.add(at(bar, x, y, z));
    g.add(at(cyl(0.021, 0.01, M.alu, 20), x, y, z));
    return g;
  };
  const rUD = unit("y", "x", MX, LY, LEND + 0.045);                           // looks up and down
  const rBF = unit("x", "y", MX, LY, -LEND - 0.045);                          // looks back and front (along the cart); modules stacked vertically
  const rLR = unit("z", "y", MX + SEND + 0.045, SY, 0);                       // looks left and right (across the cart); modules stacked vertically
  [rUD, rBF, rLR].forEach((r) => root.add(r));
  // short connectors from each pole end to its T-bar
  root.add(between([MX, LY, LEND - 0.02], [MX, LY, LEND + 0.045], 0.014, M.alu));
  root.add(between([MX, LY, -LEND + 0.02], [MX, LY, -LEND - 0.045], 0.014, M.alu));
  root.add(between([MX + SEND - 0.02, SY, 0], [MX + SEND + 0.045, SY, 0], 0.014, M.alu));

  /* ---------- weather stack ---------- */
  const wind = new THREE.Group();                                             // Gill 2D WindSonic
  wind.add(at(cyl(0.0475, 0.012, M.black, 36), MX, 1.711, 0));
  [-0.026, 0.026].forEach((dx) => wind.add(at(cyl(0.0065, 0.022, M.black, 12), MX + dx, 1.728, 0)));
  for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 + Math.PI / 4; wind.add(at(cyl(0.0035, 0.062, M.black, 8), MX + Math.cos(a) * 0.04, 1.75, Math.sin(a) * 0.04)); }
  wind.add(at(cyl(0.0485, 0.009, M.black, 36), MX, 1.783, 0));
  wind.add(at(cyl(0.03, 0.003, M.dark, 30), MX, 1.789, 0));
  root.add(wind);

  const shield = new THREE.Group();                                           // temperature and humidity probe in a louvred radiation shield
  shield.add(at(rbox(0.1, 0.004, 0.05, 0.002, M.bracket), MX + 0.075, 1.478, 0).rotateZ(0.32));
  for (let i = 0; i < 10; i++) shield.add(at(cyl(0.052, 0.0085, M.white, 36, 0.056), MX + 0.115, 1.5 + i * 0.0175, 0));   // louvre slats, same radius all the way up (straight outline)
  shield.add(at(rbox(0.03, 0.03, 0.03, 0.004, M.black), MX + 0.115, 1.475, 0));
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.058, 40, 18, 0, Math.PI * 2, 0, Math.PI / 2), M.white);   // smooth closed dome on top
  cap.scale.y = 0.5; cap.position.set(MX + 0.115, 1.5 + 9 * 0.0175 + 0.002, 0); shield.add(cap);
  shield.add(at(cyl(0.0585, 0.004, M.white, 40), MX + 0.115, 1.5 + 9 * 0.0175 - 0.002, 0));
  root.add(shield);

  const gps = new THREE.Group();                                              // GPS puck on a white bracket
  gps.add(at(rbox(0.11, 0.004, 0.075, 0.002, M.bracket), MX - 0.07, 1.482, 0));
  [-0.025, 0.025].forEach((dz) => gps.add(at(cyl(0.005, 0.014, M.steel, 10), MX - 0.07, 1.476, dz)));
  gps.add(at(cyl(0.041, 0.012, M.dark, 30), MX - 0.085, 1.49, 0));
  const puck = sph(0.04, M.gps, 28); puck.scale.y = 0.55; puck.position.set(MX - 0.085, 1.494, 0); gps.add(puck);
  root.add(gps);

  /* ---------- cables: down the poles and the mast into the logger ---------- */
  const wires = [
    [[MX + 0.08, 1.12, LEND + 0.04], [MX + 0.05, 1.14, 0.35], [MX + 0.03, 1.1, 0.07], [MX + 0.03, 0.8, 0.05], [0.0, 0.55, 0.07], [-0.12, 0.44, 0.05], [-0.2, 0.43, 0.05]],
    [[MX - 0.08, 1.12, -LEND - 0.04], [MX - 0.05, 1.14, -0.35], [MX - 0.03, 1.1, -0.07], [MX - 0.03, 0.8, -0.05], [-0.02, 0.55, -0.04], [-0.12, 0.44, -0.06], [-0.2, 0.43, -0.08]],
    [[MX + SEND + 0.06, 1.03, 0.0], [MX + 0.35, 1.045, 0.03], [MX + 0.05, 1.05, 0.04], [MX + 0.04, 0.75, 0.07], [0.0, 0.52, 0.09], [-0.12, 0.43, 0.1], [-0.2, 0.42, 0.1]],
    [[MX + 0.115, 1.47, 0.0], [MX + 0.05, 1.3, 0.04], [MX + 0.035, 0.9, 0.0], [MX + 0.01, 0.55, 0.03], [-0.1, 0.44, 0.0]],
    [[MX - 0.085, 1.485, 0.0], [MX - 0.03, 1.3, -0.03], [MX - 0.02, 0.9, -0.03], [MX - 0.03, 0.55, -0.04], [-0.12, 0.45, -0.05]],
    [[MX, 1.68, 0.02], [MX + 0.03, 1.3, 0.03], [MX + 0.02, 0.85, 0.02], [MX - 0.01, 0.5, 0.0], [-0.1, 0.44, -0.02]],
  ];
  const cables = new THREE.Group(); wires.forEach((w) => cables.add(cable(w, 0.0044, M.cable)));
  cables.add(cable([[MX, 0.3, 0.02], [MX - 0.1, 0.31, 0.12], [MX - 0.2, 0.3, 0.05], [MX - 0.3, 0.32, 0.14], [-0.15, 0.31, 0.2]], 0.011, M.cable));       // coiled slack in the tray
  cables.add(cable([[MX, 0.3, -0.02], [MX - 0.05, 0.31, -0.16], [MX - 0.2, 0.3, -0.2], [-0.3, 0.31, -0.12]], 0.01, M.cable));
  cables.add(cable([[-0.4, 0.3, 0.2], [-0.3, 0.33, 0.12], [-0.38, 0.3, 0.05], [-0.42, 0.31, -0.1]], 0.01, M.cable));
  root.add(cables);

  /* ---------- parts shown in the list ---------- */
  const parts = [
    { label: "Gill 2D WindSonic", detail: "Wind speed and direction, 0 to 60 m/s, ±2% at 12 m/s, at 1.7 m. It has no moving parts.", object: wind },
    { label: "Temperature and humidity probe", detail: "Air temperature and relative humidity in a louvred radiation shield at about 1.5 m (a Rotronic HygroClip2 in the 2019 paper; an EE181 probe in the current setup).", object: shield },
    { label: "Garmin GPS16X", detail: "Position, direction and speed to within 3 m, so every reading lands on the map.", object: gps },
    { label: "Net radiometer: up and down", detail: "A Hukseflux NR01 pair of modules, shortwave (glass domes) and longwave (flat windows), each with an upward and a downward sensor. It sits at one end of the long pole.", object: rUD },
    { label: "Net radiometer: back and front", detail: "At the other end of the long pole, looking out along the pole in two opposite horizontal directions.", object: rBF },
    { label: "Net radiometer: left and right", detail: "At the end of the short pole, which runs in line with the cart, looking left and right. Together the three units give six directions and twelve sensors.", object: rLR },
    { label: "Data logger case", detail: "Records every sensor every 2 seconds. Its switch is inside the box; a screen shows when it is running.", object: logger },
    { label: "Cart, tripod and poles", detail: "A wheeled wagon with plates, a tripod and mast. The short pole is fitted in line with the handle and the long pole across it, centred.", object: cart },
  ];
  return { root, parts };
}
