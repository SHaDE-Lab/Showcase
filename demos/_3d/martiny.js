/* MaRTiny: procedural 3D model of the field installation.
   Built from the lab's photographs of MaRTiny mounted on a lamp post in a Tempe park, the lab's description of the
   current electronics, and the parts list in Kulkarni et al. (2022), Front. Environ. Sci. 10:866240.
   Units are metres; proportions are approximate. North = -Z, south = +Z.
   North side of the post: the sensor box (yellow board with an ESP32-CAM and an Arduino Uno inside) on a plywood board,
   and, lower down, a second box with the battery and a Wi-Fi dongle. South side: the tilted solar panel carrying the
   globe thermometer and the UV sensor on its uppermost edge. */
import { THREE, mat, cyl, box, rbox, sph, at, between, cable, textTexture } from "./scene.js";

const TILT = 35 * Math.PI / 180;                                         // panel tilt from horizontal, facing south (illustrative)

export function buildMartiny() {
  const wood = textTexture(256, 256, (c, w, h) => {
    c.fillStyle = "#d9b17a"; c.fillRect(0, 0, w, h);
    for (let i = 0; i < 90; i++) { c.strokeStyle = `rgba(${110 + Math.random() * 40},${70 + Math.random() * 30},30,${0.08 + Math.random() * 0.12})`; c.lineWidth = 1 + Math.random() * 1.6; c.beginPath(); const y = Math.random() * h; c.moveTo(0, y); c.bezierCurveTo(w * 0.3, y + Math.random() * 10 - 5, w * 0.7, y + Math.random() * 10 - 5, w, y + Math.random() * 8 - 4); c.stroke(); }
  });
  const concrete = textTexture(256, 512, (c, w, h) => {
    c.fillStyle = "#a9a6a0"; c.fillRect(0, 0, w, h);
    for (let i = 0; i < 9000; i++) { const g = Math.random() < 0.5 ? 40 : 235; c.fillStyle = `rgba(${g},${g},${g},${Math.random() * 0.22})`; c.fillRect(Math.random() * w, Math.random() * h, 1 + Math.random() * 2.5, 1 + Math.random() * 2.5); }
  });
  concrete.wrapS = concrete.wrapT = THREE.RepeatWrapping; concrete.repeat.set(2, 4);
  const cellTex = textTexture(256, 340, (c, w, h) => {
    c.fillStyle = "#0e1f42"; c.fillRect(0, 0, w, h);
    const cols = 6, rows = 9, mx = 12, my = 12, cw = (w - 2 * mx) / cols, ch = (h - 2 * my) / rows;
    for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
      const x = mx + i * cw + 2, y = my + j * ch + 2, g = c.createLinearGradient(x, y, x + cw, y + ch);
      g.addColorStop(0, "#1b3f86"); g.addColorStop(1, "#102a63"); c.fillStyle = g; c.fillRect(x, y, cw - 4, ch - 4);
      c.strokeStyle = "rgba(190,210,240,.55)"; c.lineWidth = 1.2; for (let k = 1; k < 4; k++) { c.beginPath(); c.moveTo(x + (cw - 4) * k / 4, y); c.lineTo(x + (cw - 4) * k / 4, y + ch - 4); c.stroke(); }
    }
    c.strokeStyle = "rgba(235,240,250,.9)"; c.lineWidth = 3; c.strokeRect(5, 5, w - 10, h - 10);
  });
  const pcbTex = textTexture(64, 80, (c, w, h) => { c.fillStyle = "#4b2a7a"; c.fillRect(0, 0, w, h); c.fillStyle = "#c9ccd4"; c.fillRect(w * 0.28, h * 0.3, w * 0.44, h * 0.34); c.fillStyle = "#222"; c.fillRect(w * 0.36, h * 0.38, w * 0.28, h * 0.18); c.fillStyle = "#d8b94a"; [0.2, 0.4, 0.6, 0.8].forEach((x) => c.fillRect(w * x - 3, h * 0.86, 6, 6)); });
  const dhtTex = textTexture(64, 96, (c, w, h) => { c.fillStyle = "#f2f2ef"; c.fillRect(0, 0, w, h); c.fillStyle = "#8d9096"; for (let y = 8; y < h * 0.7; y += 6) for (let x = 8; x < w - 6; x += 6) c.fillRect(x, y, 3, 3); c.fillStyle = "#2b2d31"; c.font = "bold 11px sans-serif"; c.fillText("DHT22", 10, h - 12); });
  const woodMat = () => { const m = mat(0xffffff, { rough: 0.8 }); m.map = wood; return m; };

  const M = {
    white: mat(0xeceef0, { rough: 0.5 }), whiteSoft: mat(0xdfe3e6, { rough: 0.55 }), steel: mat(0xc2c8d0, { rough: 0.3, metal: 0.85 }),
    black: mat(0x16181c, { rough: 0.6 }), dark: mat(0x23262c, { rough: 0.6 }), globe: mat(0x7a8087, { rough: 0.5 }),
    glass: mat(0xe9eef2, { rough: 0.1, opacity: 0.85 }), lens: mat(0x0a0b0e, { rough: 0.15, metal: 0.2 }), red: mat(0xd4232a, { rough: 0.5 }),
    pcbGreen: mat(0x0f6f7e, { rough: 0.5 }), grey: mat(0x9aa0a8, { rough: 0.5, metal: 0.5 }),
    cable: mat(0x0b0b0d, { rough: 0.6 }), blue: mat(0x2d56b8, { rough: 0.5 }), yellow: mat(0xe9c63a, { rough: 0.5 }), ylw: mat(0xeab81c, { rough: 0.5 }),
    wireRed: mat(0xd33a2c, { rough: 0.6 }), wireGreen: mat(0x2e9b4e, { rough: 0.6 }), stick: mat(0xcfa56a, { rough: 0.75 }), frame: mat(0x15171b, { rough: 0.45, metal: 0.4 }),
    esp: mat(0x14171c, { rough: 0.5 }), ribbon: mat(0xc9c7bd, { rough: 0.6 }), battery: mat(0x2c3138, { rough: 0.55 }), term: mat(0x3d8f55, { rough: 0.5 }),
  };
  M.pole = mat(0xffffff, { rough: 0.95 }); M.pole.map = concrete;
  const group = (...kids) => { const g = new THREE.Group(); kids.forEach((k) => g.add(k)); return g; };
  const root = new THREE.Group();

  /* ---------- a white junction box with a hinged lid (used twice) ---------- */
  const mkCase = (W, H, D, T = 0.005) => {
    const walls = new THREE.Group();
    walls.add(at(box(W, T, D, M.white), 0, T / 2, 0));
    walls.add(at(box(W, H, T, M.white), 0, H / 2, D / 2 - T / 2));
    walls.add(at(box(W, H, T, M.white), 0, H / 2, -D / 2 + T / 2));
    walls.add(at(box(T, H, D, M.white), W / 2 - T / 2, H / 2, 0));
    walls.add(at(box(T, H, D, M.white), -W / 2 + T / 2, H / 2, 0));
    for (const x of [-W / 2 + 0.009, W / 2 - 0.009]) for (const z of [-D / 2 + 0.009, D / 2 - 0.009]) walls.add(at(cyl(0.0045, H - 0.01, M.whiteSoft, 10), x, H / 2, z));
    const lidPivot = new THREE.Group(); lidPivot.position.set(0, H, D / 2);                                       // hinge on the back edge
    const lid = new THREE.Group();
    lid.add(at(box(W + 0.004, 0.006, D + 0.004, M.white), 0, 0.003, -D / 2));
    lid.add(at(box(W - 0.02, 0.003, D - 0.02, M.whiteSoft), 0, -0.002, -D / 2));
    lidPivot.add(lid);
    return { walls, lidPivot, lid };
  };
  const gland = (x, y, z, axis) => { const g = cyl(0.011, 0.014, M.whiteSoft, 18); if (axis === "x") g.rotation.z = Math.PI / 2; else if (axis === "z") g.rotation.x = Math.PI / 2; return at(g, x, y, z); };

  /* ---------- lamp post, straps, plywood boards ---------- */
  const PR = 0.15, PH = 3.4, BY = 1.90, BZ = -0.40;
  const pole = new THREE.Group();
  pole.add(at(cyl(PR * 0.97, PH, M.pole, 48, PR), 0, PH / 2, 0));
  for (const y of [BY + 0.06, BY - 0.12, 2.5, 2.62, 1.30, 1.50]) { const t = new THREE.Mesh(new THREE.TorusGeometry(PR + 0.004, 0.006, 8, 48), M.steel); t.rotation.x = Math.PI / 2; t.position.y = y; pole.add(t); }
  pole.add(at(rbox(0.04, 0.6, 0.012, 0.003, M.steel), 0.0, BY + 0.02, -PR - 0.004));
  const board = new THREE.Group();
  board.add(at(rbox(0.58, 0.02, 0.5, 0.004, woodMat()), 0, BY, BZ));
  board.add(at(rbox(0.1, 0.045, 0.14, 0.006, M.dark), 0, BY - 0.032, -0.23));
  board.add(at(rbox(0.32, 0.24, 0.02, 0.004, woodMat()), 0, 1.40, -PR - 0.01));                                   // backplate for the lower box
  const upper = new THREE.Group();
  upper.add(at(rbox(0.54, 0.02, 0.46, 0.004, woodMat()), 0.04, 2.56, -0.36).rotateY(0.06));
  upper.add(at(rbox(0.09, 0.04, 0.12, 0.006, M.steel), 0.0, 2.535, -0.2));
  const mount = group(pole, board, upper);
  root.add(mount);

  /* ---------- sensor box (MaRTiny) on the board ---------- */
  const W = 0.30, H = 0.11, D = 0.22, T = 0.005, F = -1;                                                         // F = -1: front faces north
  const dev = new THREE.Group(); dev.position.set(-0.08, BY + 0.01, BZ);
  const mc = mkCase(W, H, D), enclosure = mc.walls, lidPivot = mc.lidPivot;
  const yMid = H / 2, fz = F * (D / 2 + 0.002);
  const lensRing = cyl(0.023, 0.012, M.black, 28); lensRing.rotation.x = Math.PI / 2; enclosure.add(at(lensRing, -0.095, yMid, fz));
  const lensGlass = cyl(0.015, 0.006, M.lens, 24); lensGlass.rotation.x = Math.PI / 2; enclosure.add(at(lensGlass, -0.095, yMid, fz + F * 0.008));
  const dome = sph(0.029, M.glass, 28); dome.scale.z = 0.45; enclosure.add(at(dome, 0, yMid, fz));
  enclosure.add(at(new THREE.Mesh(new THREE.PlaneGeometry(0.052, 0.038), M.red), 0.098, yMid, fz + F * 0.001).rotateY(Math.PI));
  [[0.04, "#2bd45a"], [-0.04, "#e3402f"]].forEach(([z, col]) => {
    const ring = cyl(0.018, 0.012, M.black, 24); ring.rotation.z = Math.PI / 2; enclosure.add(at(ring, W / 2 + 0.003, 0.04, z));
    const led = sph(0.006, new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 1.4 }), 12); led.userData.keepGlow = true; enclosure.add(at(led, W / 2 + 0.01, 0.04, z));
  });
  enclosure.add(gland(-W / 2 - 0.006, 0.06, -0.05, "x"), gland(-W / 2 - 0.006, 0.06, 0.05, "x"));

  /* ---------- inside: a yellow board with an ESP32-CAM, an Arduino Uno and the sensor connections ---------- */
  const fy = T;
  const yboard = new THREE.Group();
  yboard.add(at(rbox(0.27, 0.006, 0.17, 0.002, M.ylw), 0, fy + 0.003, 0));
  [[-0.12, -0.07], [0.12, -0.07], [-0.12, 0.07], [0.12, 0.07]].forEach(([x, z]) => yboard.add(at(cyl(0.004, 0.007, M.steel, 12), x, fy + 0.0065, z)));

  const espCam = new THREE.Group();                                                                              // ESP32-CAM: ESP32 module, SD slot, camera, antenna
  espCam.add(at(rbox(0.027, 0.0016, 0.0405, 0.001, M.esp), 0, 0.0008, 0));
  espCam.add(at(rbox(0.016, 0.0032, 0.018, 0.0008, M.steel), 0, 0.0032, 0.003));
  espCam.add(at(rbox(0.015, 0.003, 0.014, 0.0008, M.grey), 0, 0.0031, 0.0145));
  espCam.add(at(rbox(0.007, 0.002, 0.0045, 0.0006, M.white), 0.008, 0.0026, 0.0185));
  espCam.add(at(rbox(0.0085, 0.0075, 0.0085, 0.001, M.black), 0, 0.0052, -0.0148));
  espCam.add(at(cyl(0.0032, 0.0035, M.lens, 16), 0, 0.0108, -0.0148));
  [-0.0115, 0.0115].forEach((x) => espCam.add(at(rbox(0.0025, 0.0025, 0.036, 0.0004, M.black), x, -0.0012, 0)));
  espCam.position.set(-0.095, fy + 0.0075, -0.035);

  const arduino = new THREE.Group();
  arduino.add(at(box(0.069, 0.002, 0.053, M.pcbGreen), 0, 0.012, 0)); arduino.add(at(box(0.013, 0.011, 0.016, M.grey), -0.029, 0.018, -0.012));
  arduino.add(at(box(0.009, 0.011, 0.014, M.black), -0.03, 0.018, 0.014));
  arduino.add(at(box(0.052, 0.0085, 0.0025, M.black), 0.004, 0.0165, -0.0235), at(box(0.052, 0.0085, 0.0025, M.black), 0.004, 0.0165, 0.0235));
  arduino.add(at(box(0.034, 0.003, 0.009, M.dark), 0.012, 0.0145, 0));
  [[-0.026, -0.022], [0.028, -0.022], [-0.026, 0.022], [0.028, 0.022]].forEach(([x, z]) => arduino.add(at(cyl(0.0025, 0.01, M.steel, 8), x, 0.006, z)));
  arduino.position.set(0.075, fy + 0.006, 0.02);

  const dht = new THREE.Group();                                                                                 // DHT22 humidity sensor
  dht.add(new THREE.Mesh(new THREE.BoxGeometry(0.015, 0.007, 0.024), M.white));
  const dhtFace = new THREE.Mesh(new THREE.PlaneGeometry(0.015, 0.024), new THREE.MeshStandardMaterial({ map: dhtTex, roughness: 0.6 })); dhtFace.rotation.x = -Math.PI / 2; dhtFace.position.y = 0.0036; dht.add(dhtFace);
  [-0.005, 0, 0.005].forEach((x) => dht.add(at(cyl(0.0008, 0.01, M.steel, 6), x, -0.004, 0.013)));
  dht.position.set(-0.035, fy + 0.0095, 0.06);
  const terminal = new THREE.Group();                                                                            // screw terminals where the sensor cables arrive
  terminal.add(at(rbox(0.036, 0.013, 0.014, 0.002, M.term), 0, 0.0065, 0));
  [-0.011, 0, 0.011].forEach((x) => terminal.add(at(cyl(0.0032, 0.003, M.steel, 12), x, 0.0145, 0)));
  terminal.position.set(-0.115, fy + 0.006, 0.06);

  const wires = new THREE.Group();
  const wy = fy + 0.02;
  [[[0.045, wy, 0.0], [0.0, wy + 0.02, -0.02], [-0.075, wy, -0.03]], [[0.05, wy, -0.002], [0.01, wy + 0.03, -0.012], [-0.085, wy - 0.005, -0.045]],
   [[0.045, wy, 0.05], [0.0, wy + 0.022, 0.058], [-0.03, wy - 0.002, 0.06]], [[0.05, wy, 0.052], [0.01, wy + 0.03, 0.045], [-0.04, wy - 0.002, 0.058]],
   [[0.04, wy, 0.044], [-0.04, wy + 0.025, 0.05], [-0.108, wy, 0.06]], [[-0.012, wy, 0.06], [-0.05, wy + 0.02, 0.066], [-0.108, wy, 0.062]]]
    .forEach((pts, i) => wires.add(cable(pts, 0.0017, [M.yellow, M.wireRed, M.wireGreen, M.blue, M.black, M.wireRed][i])));
  wires.add(cable([[-0.123, fy + 0.016, 0.06], [-0.135, fy + 0.03, 0.07], [-W / 2 + 0.01, 0.062, 0.05]], 0.003, M.cable));         // sensor cables to the glands
  wires.add(cable([[-0.123, fy + 0.016, 0.06], [-0.138, fy + 0.025, 0.03], [-W / 2 + 0.01, 0.062, -0.05]], 0.003, M.cable));
  const camera = group(                                                                                          // lens at the front window, connected by a flat cable to the ESP32-CAM
    at((() => { const r = cyl(0.027, 0.02, M.black, 28); r.rotation.x = Math.PI / 2; return r; })(), -0.095, yMid, fz + F * 0.004),
    at((() => { const r = cyl(0.016, 0.008, M.lens, 24); r.rotation.x = Math.PI / 2; return r; })(), -0.095, yMid, fz + F * 0.016),
    cable([[-0.095, fy + 0.016, -0.052], [-0.095, fy + 0.04, -0.075], [-0.095, yMid - 0.004, -D / 2 + 0.014]], 0.0036, M.ribbon));
  dev.add(enclosure, lidPivot, yboard, espCam, arduino, dht, terminal, wires, camera);
  root.add(dev);

  /* ---------- cup anemometer on the lid (it lifts with the lid) ---------- */
  const anemometer = new THREE.Group();
  anemometer.position.set(0, 0.006, -D / 2);
  anemometer.add(at(cyl(0.05, 0.01, M.black, 28), 0, 0.005, 0));                                                 // base plate
  anemometer.add(at(cyl(0.022, 0.11, M.black, 24), 0, 0.065, 0));                                                // body: spans y 0.01 to 0.12
  anemometer.add(at(cyl(0.026, 0.014, M.black, 24), 0, 0.123, 0));                                               // cap on top of the body
  anemometer.add(at(cyl(0.0085, 0.07, M.steel, 14), 0, 0.14, 0));                                                // spindle from the cap (0.105) up into the hub (0.175)
  const cups = new THREE.Group(); cups.position.set(0, 0.17, 0);                                                 // rotating head, sitting on the spindle
  cups.add(cyl(0.013, 0.016, M.black, 16));
  for (let i = 0; i < 3; i++) {
    const arm = new THREE.Group(); arm.rotation.y = i * Math.PI * 2 / 3;
    arm.add(between([0, 0, 0], [0.058, 0, 0], 0.0035, M.black, 8));
    const cup = new THREE.Mesh(new THREE.SphereGeometry(0.023, 20, 12, 0, Math.PI), M.black); cup.material.side = THREE.DoubleSide;
    cup.position.set(0.058, 0, 0); cup.rotation.y = Math.PI / 2; arm.add(cup); cups.add(arm);
  }
  anemometer.add(cups);
  lidPivot.add(anemometer);

  /* ---------- power box on the post: battery and Wi-Fi dongle ---------- */
  const PW = 0.26, PHt = 0.12, PD = 0.18;
  const pc = mkCase(PW, PHt, PD), pbox = new THREE.Group();
  pbox.rotation.x = -Math.PI / 2;                                                                                // floor against the post, lid facing north
  pbox.position.set(0, 1.40, -PR - 0.022);
  const battery = new THREE.Group();
  battery.add(at(rbox(0.13, 0.06, 0.07, 0.005, M.battery), -0.05, T + 0.03, 0.0));
  battery.add(at(rbox(0.128, 0.004, 0.068, 0.002, M.grey), -0.05, T + 0.062, 0.0));
  [-0.025, 0.025].forEach((dz, i) => battery.add(at(cyl(0.0065, 0.008, i ? M.wireRed : M.black, 14), -0.095, T + 0.066, dz)));
  const dongle = new THREE.Group();
  dongle.add(at(rbox(0.018, 0.008, 0.05, 0.002, M.black), 0, 0, 0)); dongle.add(at(box(0.012, 0.004, 0.012, M.steel), 0, 0, 0.03));
  dongle.add(at(cyl(0.0035, 0.03, M.black, 8), 0.0, 0.01, -0.02));
  dongle.position.set(0.075, T + 0.007, 0.01);
  const pwires = new THREE.Group();
  pwires.add(cable([[-0.095, T + 0.07, -0.025], [-0.06, T + 0.085, -0.045], [-0.04, T + 0.03, -0.075], [-0.05, 0.062, PD / 2 - 0.01]], 0.0032, M.black));
  pwires.add(cable([[-0.095, T + 0.07, 0.025], [-0.07, T + 0.09, 0.05], [-0.05, 0.062, PD / 2 - 0.02]], 0.0032, M.wireRed));
  pwires.add(cable([[0.075, T + 0.012, 0.035], [0.05, T + 0.04, 0.06], [0.0, T + 0.05, 0.075], [-0.04, 0.05, 0.075]], 0.002, M.cable));
  pbox.add(pc.walls, pc.lidPivot, battery, dongle, pwires, gland(-0.05, PHt / 2, PD / 2 + 0.006, "z"), gland(PW / 2 + 0.006, PHt / 2, 0, "x"));
  root.add(pbox);

  /* ---------- two radiation cups hanging under the board ---------- */
  const radCups = new THREE.Group();
  [[-0.14, BZ - 0.12], [0.12, BZ - 0.13]].forEach(([x, z]) => {
    radCups.add(between([x, BY - 0.01, z], [x, BY - 0.10, z], 0.006, M.black, 10));
    radCups.add(at(cyl(0.016, 0.014, M.black, 16), x, BY - 0.107, z));
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.027, 0.036, 0.09, 40, 1, true), mat(0xf4f5f6, { rough: 0.45, side: THREE.DoubleSide }));
    body.position.set(x, BY - 0.165, z); radCups.add(body);
    radCups.add(at(cyl(0.027, 0.004, M.white, 40), x, BY - 0.12, z));
    radCups.add(at(cyl(0.0035, 0.06, M.black, 8), x, BY - 0.15, z));
  });

  /* ---------- solar panel on the south side ---------- */
  const C = new THREE.Vector3(0, 1.78, 0.45), nrm = new THREE.Vector3(0, Math.cos(TILT), Math.sin(TILT)), uS = new THREE.Vector3(0, -Math.sin(TILT), Math.cos(TILT));
  const panel = new THREE.Group(); panel.position.copy(C); panel.rotation.x = TILT;
  panel.add(rbox(0.46, 0.022, 0.36, 0.004, M.frame));
  const face = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.32), new THREE.MeshStandardMaterial({ map: cellTex, roughness: 0.18, metalness: 0.25 }));
  face.rotation.x = -Math.PI / 2; face.position.y = 0.0115; panel.add(face);
  panel.add(at(rbox(0.07, 0.02, 0.05, 0.004, M.dark), 0.1, -0.02, -0.06));
  const armsS = new THREE.Group();
  const north = C.clone().addScaledVector(uS, -0.17).addScaledVector(nrm, -0.011);
  [-1, 1].forEach((s) => armsS.add(between([s * 0.07, 1.94, 0.13], [s * 0.15, north.y, north.z + 0.012], 0.009, M.black, 10)));
  armsS.add(between([0, 1.55, 0.145], [0, C.y - 0.012, C.z - 0.006], 0.008, M.black, 10));
  armsS.add(at(rbox(0.12, 0.05, 0.03, 0.005, M.dark), 0, 1.94, 0.14));
  const solar = group(panel, armsS);

  /* ---------- globe thermometer and UV sensor, on the uppermost (pole-side) edge of the panel ---------- */
  const edge = C.clone().addScaledVector(uS, -0.145).addScaledVector(nrm, 0.011);                                // just inside the highest edge, which is the one nearest the post
  const globe = new THREE.Group();
  const gDir = new THREE.Vector3(0, 1, 0), gBase = edge.clone().add(new THREE.Vector3(-0.12, 0, 0)), gTip = gBase.clone().addScaledVector(gDir, 0.17);
  globe.add(between(gBase.toArray(), gTip.toArray(), 0.0065, M.stick, 10));
  globe.add(at(cyl(0.012, 0.03, M.black, 14), gBase.x, gBase.y, gBase.z).rotateX(TILT));
  globe.add(at(sph(0.0205, M.globe, 32), gTip.x + gDir.x * 0.018, gTip.y + gDir.y * 0.018, gTip.z + gDir.z * 0.018));
  const uv = new THREE.Group();
  const uBase = edge.clone().add(new THREE.Vector3(0.10, 0, 0.0)), uTip = uBase.clone().add(new THREE.Vector3(0, 0.15, 0));
  uv.add(between(uBase.toArray(), uTip.toArray(), 0.0058, M.stick, 10));
  uv.add(at(cyl(0.012, 0.03, M.black, 14), uBase.x, uBase.y, uBase.z).rotateX(TILT));
  const pcb = new THREE.Group();
  pcb.add(box(0.03, 0.036, 0.004, M.dark));
  const pcbFace = new THREE.Mesh(new THREE.PlaneGeometry(0.03, 0.036), new THREE.MeshStandardMaterial({ map: pcbTex, roughness: 0.5 })); pcbFace.position.z = 0.0022; pcb.add(pcbFace);
  pcb.position.set(uTip.x, uTip.y + 0.008, uTip.z + 0.003); pcb.rotation.x = -0.9; uv.add(pcb);

  /* ---------- cables: sensors to the box, power box to the box, panel to the power box ---------- */
  const cables = new THREE.Group();
  const wg1 = [-0.236, 1.97, BZ + 0.05], wg2 = [-0.236, 1.97, BZ - 0.05];                                         // the sensor cable glands, in world coordinates
  cables.add(cable([wg1, [-0.25, 1.95, -0.3], [-0.24, 1.97, -0.1], [-0.2, 2.0, 0.15], [gBase.x - 0.02, gBase.y + 0.03, gBase.z + 0.02]], 0.0042, M.cable));  // globe
  cables.add(cable([wg2, [-0.27, 1.95, -0.32], [-0.26, 1.98, -0.1], [-0.2, 2.02, 0.16], [uBase.x - 0.02, uBase.y + 0.03, uBase.z + 0.02]], 0.0042, M.cable)); // UV
  cables.add(cable([[-0.05, 1.50, -0.232], [-0.07, 1.62, -0.2], [-0.14, 1.78, -0.28], [-0.2, 1.9, -0.32], [-0.236, 1.97, -0.35]], 0.0058, M.cable));        // battery power up to the sensor box
  const jx = C.clone().add(new THREE.Vector3(0.1, 0, 0)).addScaledVector(nrm, -0.021).addScaledVector(uS, -0.06);                                           // the panel's junction box
  cables.add(cable([jx.toArray(), [0.22, jx.y - 0.04, 0.2], [0.22, 1.6, 0.0], [0.2, 1.46, -0.15], [PW / 2 + 0.03, 1.40, -0.232]], 0.0062, M.cable));          // solar feed to the power box
  root.add(solar, globe, uv, radCups, cables);

  /* ---------- lids: click a box, or use the button, to open and close ---------- */
  const open = { main: 0, power: 0 }, ang = { main: 0, power: 0 };
  const extras = [{
    label: "Open the cases", labelOn: "Close the cases", on: false, focus: true,
    toggle: (on) => { open.main = open.power = on ? 2.0 : 0; },
  }];
  const sync = () => { const x = extras[0]; x.on = !!(open.main || open.power); x.refresh && x.refresh(); };
  const toggleMain = () => { open.main = open.main ? 0 : 2.0; sync(); };
  const togglePower = () => { open.power = open.power ? 0 : 2.0; sync(); };
  const update = (dt, t) => {
    cups.rotation.y = t * 1.6;
    const k = Math.min(1, dt * 5.5);
    ang.main += (open.main - ang.main) * k; ang.power += (open.power - ang.power) * k;
    lidPivot.rotation.x = ang.main; pc.lidPivot.rotation.x = ang.power;
  };

  const parts = [
    { label: "Weatherproof box", detail: "The white sensor box on the plywood board. Click it, or use the button, to open the lid and see the yellow board inside.", objects: [enclosure, mc.lid], onClick: toggleMain },
    { label: "Cup anemometer", detail: "Wind speed (worst-case error about 1 m/s), needed to turn globe temperature into mean radiant temperature. It is bolted to the lid of the box.", object: anemometer, onClick: toggleMain },
    { label: "Camera", detail: "A camera at the front window, connected by a flat cable to the ESP32-CAM, looks at the people using the space.", object: camera },
    { label: "ESP32-CAM", detail: "A small Wi-Fi camera board on the yellow board. It captures the images; a server runs YOLO pedestrian detection and shadow segmentation on them.", object: espCam },
    { label: "Yellow board, Arduino Uno and sensors", detail: "The Arduino Uno reads the humidity (DHT22) and the other sensors, wired to screw terminals on the yellow board. Cables run out through glands to the sensors and to the power box.", objects: [yboard, arduino, dht, terminal, wires] },
    { label: "Globe thermometer", detail: "A grey ping-pong ball on a DS18B20 probe (±0.5 °C), on a stick at the uppermost edge of the solar panel. Its temperature, with air temperature and wind, gives MRT.", object: globe },
    { label: "UV sensor", detail: "An ML8511 breakout (about 1% accuracy) on the uppermost edge of the solar panel next to the globe, facing the sky to measure ultraviolet radiation.", object: uv },
    { label: "Radiation cups", detail: "White cups hang open end down under the board and shade the air-temperature probe (a DS18B20) from direct sun.", object: radCups },
    { label: "Solar panel", detail: "Faces south and leans toward the sun to collect as much light as possible (the model uses a 35° tilt for illustration). Its cable runs to the power box on the post.", object: solar },
    { label: "Power box", detail: "A second box on the post. Click it to open. It holds the battery and a Wi-Fi dongle, takes the feed from the solar panel and powers the sensor box.", objects: [pc.walls, pc.lid], onClick: togglePower },
    { label: "Battery", detail: "Stores the power from the solar panel and feeds the sensor box through the cable that runs up the post.", object: battery },
    { label: "Wi-Fi dongle", detail: "Connects the installation to the network so the data and images can be sent to the server.", object: dongle },
    { label: "Lamp post and boards", detail: "A concrete lamp post in a park. The sensor board and the power box are on the north side and the solar panel on the south side, held on with steel straps; a second board sits above.", object: mount },
  ];
  return { root, parts, extras, update };
}
