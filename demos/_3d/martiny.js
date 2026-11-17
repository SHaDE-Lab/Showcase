/* MaRTiny: procedural 3D model of the field installation.
   Built from the lab's photographs of MaRTiny mounted on a lamp post in a Tempe park, the lab's description of the
   current electronics, and the parts list in Kulkarni et al. (2022), Front. Environ. Sci. 10:866240.
   Units are metres; proportions are approximate. North = -Z, south = +Z.
   North side of the post: the sensor box (yellow board with an ESP32-CAM and an Arduino Uno inside) on a plywood board,
   and, lower down, a second box with the battery and a Wi-Fi dongle. South side: the tilted solar panel carrying the
   globe thermometer and the UV sensor on its uppermost edge. */
import { THREE, mat, cyl, box, rbox, sph, at, between, cable, textTexture } from "./scene.js";

const TILT = 35 * Math.PI / 180;                                         // panel tilt from horizontal, facing south (illustrative)

export function buildMartiny(view = null) {
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
    pcbGreen: mat(0x0f6f7e, { rough: 0.5 }), grey: mat(0x9aa0a8, { rough: 0.5, metal: 0.5 }), silver: mat(0xb9bdc2, { rough: 0.35, metal: 0.75 }),
    cable: mat(0x0b0b0d, { rough: 0.6 }), blue: mat(0x2d56b8, { rough: 0.5 }), yellow: mat(0xe9c63a, { rough: 0.5 }), ylw: mat(0xeab81c, { rough: 0.5 }),
    wireRed: mat(0xd33a2c, { rough: 0.6 }), wireGreen: mat(0x2e9b4e, { rough: 0.6 }), stick: mat(0xcfa56a, { rough: 0.75 }), frame: mat(0x15171b, { rough: 0.45, metal: 0.4 }),
    esp: mat(0x14171c, { rough: 0.5 }), ribbon: mat(0xc9c7bd, { rough: 0.6 }), battery: mat(0x2c3138, { rough: 0.55 }), term: mat(0x3d8f55, { rough: 0.5 }),
  };
  Object.assign(M, { navy: mat(0x1c2548, { rough: 0.9 }), blue2: mat(0x3b6fd6, { rough: 0.5 }), resist: mat(0xb9d7e8, { rough: 0.6 }), brown: mat(0x6b4426, { rough: 0.7 }), purple: mat(0x7a4fa8, { rough: 0.6 }), orange: mat(0xe9812a, { rough: 0.6 }) });
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
  upper.add(at(rbox(0.58, 0.02, 0.5, 0.004, woodMat()), 0, 2.56, BZ));                                           // same size and position as the lower board, exactly above it
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

  /* ---------- inside: laid out as in the photo of the real box (photo up = +x, photo right = +z; parts are drawn at real size, scaled up with the box) ---------- */
  const fy = T, bt = fy + 0.004, K = 1.85;
  const yboard = new THREE.Group();                                                                              // the small yellow carrier board
  yboard.add(at(rbox(0.2, 0.004, 0.107, 0.002, M.ylw), 0.01, fy + 0.002, -0.0025));
  [[0.1, -0.048], [0.1, 0.043], [-0.08, -0.048], [-0.08, 0.043]].forEach(([x, z]) => yboard.add(at(cyl(0.003, 0.006, M.steel, 12), x, bt + 0.003, z)));
  [-0.031, -0.0375, -0.046].forEach((x) => { const r = cyl(0.0024, 0.012, M.resist, 10); r.rotation.x = Math.PI / 2; yboard.add(at(r, x, bt + 0.003, -0.046)); });   // three resistors

  const espCam = new THREE.Group();                                                                              // ESP32-CAM: ESP32 module, SD slot, camera connector, antenna
  espCam.add(at(rbox(0.027, 0.0016, 0.0405, 0.001, M.esp), 0, 0.0008, 0));
  espCam.add(at(rbox(0.016, 0.0032, 0.018, 0.0008, M.steel), 0, 0.0032, 0.003));
  espCam.add(at(rbox(0.015, 0.003, 0.014, 0.0008, M.grey), 0, 0.0031, 0.0145));
  espCam.add(at(rbox(0.007, 0.002, 0.0045, 0.0006, M.white), 0.008, 0.0026, 0.0185));
  espCam.add(at(rbox(0.0085, 0.0075, 0.0085, 0.001, M.black), 0, 0.0052, -0.0148));
  espCam.add(at(cyl(0.0032, 0.0035, M.lens, 16), 0, 0.0108, -0.0148));
  [-0.0115, 0.0115].forEach((x) => espCam.add(at(rbox(0.0025, 0.0025, 0.036, 0.0004, M.black), x, -0.0012, 0)));
  espCam.rotation.y = Math.PI / 2; espCam.scale.setScalar(K); espCam.position.set(-0.054, bt + 0.0046, 0.029);

  const unoTex = textTexture(256, 200, (c, w, h) => {                                                           // Elegoo Uno R3, seen from its underside as in the photo
    c.fillStyle = "#0e0f12"; c.fillRect(0, 0, w, h); c.fillStyle = "#d9dadd"; c.textAlign = "center";
    c.font = "bold 34px sans-serif"; c.fillText("ELEGOO", w * 0.5, h * 0.46); c.font = "600 24px sans-serif"; c.fillText("UNO R3", w * 0.5, h * 0.63);
    c.font = "9px sans-serif"; c.fillText("OPEN-SOURCE ELECTRONICS PROTOTYPING PLATFORM", w * 0.5, h * 0.78);
    c.fillStyle = "#c9a64a"; for (let x = 16; x < w - 16; x += 10) { c.fillRect(x, 7, 5, 5); c.fillRect(x, h - 12, 5, 5); }
  });
  const arduino = new THREE.Group();
  arduino.add(at(box(0.0686, 0.0016, 0.0534, M.dark), 0, 0, 0));
  const unoFace = new THREE.Mesh(new THREE.PlaneGeometry(0.0686, 0.0534), new THREE.MeshStandardMaterial({ map: unoTex, roughness: 0.6 }));
  unoFace.rotation.x = -Math.PI / 2; unoFace.position.y = 0.0009; arduino.add(unoFace);
  arduino.add(at(box(0.0165, 0.0115, 0.0125, M.steel), 0.0288, -0.006, -0.012), at(box(0.0145, 0.011, 0.009, M.black), 0.0288, -0.0058, 0.0134));   // USB-B and power jack
  arduino.add(at(box(0.052, 0.0085, 0.0025, M.black), 0.004, -0.0055, -0.0235), at(box(0.052, 0.0085, 0.0025, M.black), 0.004, -0.0055, 0.0235));    // pin headers
  arduino.scale.setScalar(K); arduino.position.set(0.049, bt + 0.0125 * K, -0.017);

  const booster = new THREE.Group();                                                                             // MT3608 boost converter: 5 V in, 12 V out for the wind sensor
  booster.add(at(box(0.037, 0.0016, 0.017, M.blue), 0, 0.0008, 0));
  booster.add(at(rbox(0.0095, 0.0065, 0.0095, 0.001, M.blue2), 0.0068, 0.0049, 0), at(cyl(0.0022, 0.0012, M.yellow, 12), 0.0068, 0.0087, 0));          // trimmer
  booster.add(at(cyl(0.0048, 0.0045, M.dark, 18), -0.0065, 0.0039, 0.0024), at(box(0.006, 0.0012, 0.004, M.black), 0.0, 0.0022, 0.0045));          // inductor, chip
  [[0.0165, 0.0065], [0.0165, -0.0065], [-0.0165, 0.0065], [-0.0165, -0.0065]].forEach(([x, z]) => booster.add(at(cyl(0.0023, 0.0012, M.steel, 10), x, 0.0022, z)));
  [[-0.0068, "#2bd45a"], [-0.0135, "#e3402f"]].forEach(([x, col]) => { const led = box(0.003, 0.0014, 0.0018, new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 1.3 })); led.userData.keepGlow = true; booster.add(at(led, x, 0.0023, -0.0084)); });
  booster.scale.setScalar(K); booster.position.set(-0.05, bt + 0.0001, -0.016);

  const usbc = new THREE.Group();                                                                                // USB-C breakout with the plug of the power cable from the post
  usbc.add(at(box(0.016, 0.0014, 0.012, M.blue), 0, 0.0007, 0), at(rbox(0.009, 0.0033, 0.0089, 0.001, M.steel), -0.0045, 0.0031, 0));
  usbc.scale.setScalar(K); usbc.position.set(-0.06, bt + 0.0001, -0.046);
  const usbIn = group(
    at(rbox(0.012, 0.006, 0.011, 0.001, M.steel), -0.081, bt + 0.006, -0.046), at(rbox(0.016, 0.012, 0.013, 0.003, M.dark), -0.0955, bt + 0.007, -0.046),
    cable([[-0.1035, bt + 0.007, -0.046], [-0.125, bt + 0.012, -0.048], [-0.152, 0.062, -0.05]], 0.0058, M.cable));  // the power cable goes out through the left gland

  const terminal = new THREE.Group();                                                                            // blue 3-way screw terminal: the wind sensor port
  terminal.add(at(rbox(0.0155, 0.0105, 0.0105, 0.001, M.blue), 0, 0.00525, 0));
  [-0.0052, 0, 0.0052].forEach((x) => terminal.add(at(cyl(0.0022, 0.0012, M.steel, 14), x, 0.0111, 0)));
  terminal.scale.setScalar(K); terminal.position.set(0.01, bt, 0.04);

  const wires = new THREE.Group();
  const th = 0.0014, ty = bt + 0.0097;
  wires.add(cable([[-0.047, bt + 0.004, -0.04], [-0.065, bt + 0.012, -0.022], [-0.0805, bt + 0.006, -0.004]], th, M.wireRed));            // USB 5 V to the booster input
  wires.add(cable([[-0.047, bt + 0.004, -0.052], [-0.07, bt + 0.014, -0.04], [-0.0805, bt + 0.006, -0.028]], th, M.black));
  wires.add(cable([[-0.0195, bt + 0.006, -0.004], [-0.005, bt + 0.03, 0.03], [0.0004, ty, 0.049]], th, M.brown));                          // 12 V out to the wind sensor port
  wires.add(cable([[-0.0195, bt + 0.006, -0.028], [0.0, bt + 0.036, 0.02], [0.01, ty, 0.049]], th, M.blue));
  wires.add(cable([[0.03, bt + 0.03, 0.028], [0.025, bt + 0.025, 0.04], [0.0196, ty, 0.049]], th, M.black));                               // wind pulse from the Arduino
  wires.add(cable([[0.01, ty, 0.056], [0.02, bt + 0.01, 0.085], [0.03, 0.05, D / 2 + 0.002]], 0.0046, M.navy));   // braided wind sensor cable: out through its own gland in the back wall
  const tie = [-0.012, bt + 0.02, 0.07];
  [M.orange, M.wireRed, M.yellow, M.wireGreen, M.white, M.purple].forEach((c, i) => {                                                     // one thin wire per sensor port
    const x = 0.085 - i * 0.01;
    wires.add(cable([[x, bt + 0.02, 0.0285], [(x + tie[0]) / 2, bt + 0.04, 0.05 + i * 0.002], tie], th, c));
  });
  wires.add(at(rbox(0.004, 0.004, 0.014, 0.001, M.wireGreen), tie[0], tie[1], tie[2]));                                                    // cable tie
  wires.add(cable([tie, [-0.08, bt + 0.018, 0.072], [-0.13, 0.04, 0.06], [-0.152, 0.062, 0.05]], 0.0042, M.cable));                        // all of them leave as one black cable
  enclosure.add(gland(0.03, 0.05, D / 2 + 0.006, "z"));
  const windCable = cable([[0.03, 0.05, D / 2 + 0.004], [0.036, 0.085, D / 2 + 0.022], [0.026, H + 0.004, D / 2 + 0.016], [0.02, H + 0.006, D / 2 + 0.012]], 0.0046, M.navy);   // up the back of the box to the hinge
  const camera = group(                                                                                          // lens at the front window, connected by a flat cable to the ESP32-CAM
    at((() => { const r = cyl(0.027, 0.02, M.black, 28); r.rotation.x = Math.PI / 2; return r; })(), -0.095, yMid, fz + F * 0.004),
    at((() => { const r = cyl(0.016, 0.008, M.lens, 24); r.rotation.x = Math.PI / 2; return r; })(), -0.095, yMid, fz + F * 0.016),
    cable([[-0.081, bt + 0.02, 0.029], [-0.09, bt + 0.045, -0.03], [-0.095, yMid - 0.004, -D / 2 + 0.014]], 0.0036, M.dark));
  lidPivot.add(cable([[0.02, 0.006, 0.012], [0.02, 0.014, -0.02], [0.012, 0.014, -0.06], [0.0, 0.012, -0.092]], 0.0046, M.navy));         // over the hinge and along the lid to the anemometer base
  dev.add(enclosure, lidPivot, windCable, yboard, espCam, arduino, booster, usbc, usbIn, terminal, wires, camera);
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
  // Voltaic battery pack: a silver aluminium slab, ports on the black end cap facing +x
  const VY = T + 0.012, VX = 0.031;                                                                                // VY: port height, VX: end-cap face
  const voltaicTex = textTexture(256, 160, (c, w, h) => {
    c.fillStyle = "#b9bdc2"; c.fillRect(0, 0, w, h); c.strokeStyle = "#8f949a"; c.lineWidth = 6;
    c.beginPath(); c.arc(w * 0.5, h * 0.36, 20, 0, 7); c.stroke();
    c.fillStyle = "#8f949a"; c.font = "bold 34px sans-serif"; c.textAlign = "center"; c.fillText("+", w * 0.5, h * 0.36 + 12);
    c.font = "600 26px sans-serif"; c.fillText("Voltaic", w * 0.5, h * 0.8);
  });
  const battery = new THREE.Group();
  battery.add(at(rbox(0.12, 0.024, 0.08, 0.002, M.silver), -0.035, VY, 0));
  const vlabel = new THREE.Mesh(new THREE.PlaneGeometry(0.08, 0.05), new THREE.MeshStandardMaterial({ map: voltaicTex, roughness: 0.4, metalness: 0.5 }));
  vlabel.rotation.x = -Math.PI / 2; vlabel.rotation.z = Math.PI; vlabel.position.set(-0.04, VY + 0.0122, 0); battery.add(vlabel);
  battery.add(at(box(0.004, 0.0245, 0.0805, M.black), VX - 0.002, VY, 0));                                         // black end cap
  const port = (z, w, h, m = M.steel) => battery.add(at(box(0.002, h, w, m), VX + 0.0002, VY - 0.003, z));
  port(-0.016, 0.0135, 0.0058); port(0.022, 0.0135, 0.0058); port(0.004, 0.0085, 0.0028);                       // two USB-A, one USB-C
  battery.add(at(cyl(0.0033, 0.002, M.dark, 14), VX - 0.001, VY - 0.003, -0.033).rotateZ(Math.PI / 2));          // solar DC input
  battery.add(at(cyl(0.0032, 0.002, M.red, 14), VX + 0.0005, VY + 0.006, 0.036).rotateZ(Math.PI / 2));           // power button
  const dongle = new THREE.Group();                                                                                // Wi-Fi dongle plugged into the first USB-A port
  dongle.add(at(box(0.016, 0.0052, 0.0115, M.steel), 0.002, 0, 0));
  dongle.add(at(rbox(0.032, 0.0095, 0.0165, 0.002, M.black), 0.026, 0, 0));
  dongle.add(at(box(0.004, 0.0015, 0.008, M.pcbGreen), 0.042, 0.0, 0));
  dongle.position.set(VX, VY - 0.003, -0.016);
  const pwires = new THREE.Group();
  pwires.add(cable([[VX, VY - 0.003, 0.022], [0.06, 0.02, 0.04], [0.0, 0.05, 0.05], [-0.05, 0.06, 0.06], [-0.05, 0.06, PD / 2 + 0.002]], 0.0058, M.cable));   // second USB port: out to the sensor box
  pwires.add(cable([[PW / 2 + 0.002, 0.06, 0], [PW / 2 - 0.02, 0.06, 0], [0.09, 0.04, -0.04], [0.05, 0.02, -0.045], [VX, VY - 0.003, -0.033]], 0.0062, M.cable));  // solar feed into the DC jack
  pbox.add(pc.walls, pc.lidPivot, battery, dongle, pwires, gland(-0.05, PHt / 2, PD / 2 + 0.006, "z"), gland(PW / 2 + 0.006, PHt / 2, 0, "x"));
  root.add(pbox);

  /* ---------- two white cups hanging under the board: a DHT22 humidity sensor in one, a Dallas DS18B20 temperature sensor in the other ---------- */
  const makeCup = (x, z, inside) => {
    const g = new THREE.Group();
    g.add(between([x, BY - 0.01, z], [x, BY - 0.10, z], 0.006, M.black, 10));
    g.add(at(cyl(0.016, 0.014, M.black, 16), x, BY - 0.107, z));
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.027, 0.036, 0.09, 40, 1, true), mat(0xf4f5f6, { rough: 0.45, side: THREE.DoubleSide }));
    body.material.transparent = true; body.userData.cupBody = true;
    body.position.set(x, BY - 0.165, z); g.add(body);
    g.add(at(cyl(0.027, 0.004, M.white, 40), x, BY - 0.12, z));
    g.add(inside(x, z));
    return g;
  };
  // while a cup is hovered its wall turns see-through, so the sensor inside shows
  const seeThrough = (g, on) => g.traverse((o) => { if (o.userData.cupBody) { o.material.opacity = on ? 0.18 : 1; o.material.depthWrite = !on; } });
  const humidityCup = makeCup(-0.14, BZ - 0.12, (x, z) => {                              // DHT22: a white block with a grid of small holes, on three pins
    const sensor = new THREE.Group();
    sensor.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.015, 0.02, 0.008), M.white), 0, 0, 0));
    const face = new THREE.Mesh(new THREE.PlaneGeometry(0.015, 0.02), new THREE.MeshStandardMaterial({ map: dhtTex, roughness: 0.6 })); face.position.z = 0.0042; sensor.add(face);
    [-0.004, 0, 0.004].forEach((dx) => sensor.add(at(cyl(0.0007, 0.014, M.steel, 6), dx, 0.016, -0.002)));
    sensor.add(between([0, 0.02, -0.002], [0, 0.045, -0.002], 0.0018, M.cable, 6));
    sensor.position.set(x, BY - 0.16, z);
    return sensor;
  });
  const dallasCup = makeCup(0.12, BZ - 0.13, (x, z) => {                                 // DS18B20: a slim stainless-steel probe on a cable
    const probe = new THREE.Group();
    probe.add(at(cyl(0.003, 0.05, M.steel, 12), 0, 0, 0));
    probe.add(at(cyl(0.0032, 0.004, M.black, 12), 0, 0.027, 0));
    probe.add(between([0, 0.028, 0], [0, 0.06, 0], 0.0018, M.cable, 6));
    probe.position.set(x, BY - 0.155, z);
    return probe;
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
  cables.add(cable([wg1, [-0.27, 1.95, -0.32], [-0.26, 1.98, -0.1], [-0.2, 2.02, 0.16], [uBase.x - 0.02, uBase.y + 0.03, uBase.z + 0.02]], 0.0042, M.cable)); // UV
  cables.add(cable([[-0.05, 1.494, -0.232], [-0.05, 1.54, -0.232], [-0.08, 1.62, -0.22], [-0.2, 1.68, -0.3], [-0.33, 1.8, -0.4], [-0.34, 1.95, -0.45], [-0.3, 1.97, -0.45], [-0.236, 1.97, -0.45]], 0.0058, M.cable));        // battery power up to the sensor box
  const jx = C.clone().add(new THREE.Vector3(0.1, 0, 0)).addScaledVector(nrm, -0.021).addScaledVector(uS, -0.06);                                           // the panel's junction box
  cables.add(cable([jx.toArray(), [0.22, jx.y - 0.04, 0.2], [0.22, 1.6, 0.0], [0.2, 1.43, -0.2], [0.19, 1.40, -0.232], [PW / 2 + 0.002, 1.40, -0.232]], 0.0062, M.cable));          // solar feed to the power box
  root.add(solar, globe, uv, humidityCup, dallasCup, cables);

  /* ---------- where the camera goes to look inside ---------- */
  const LOOK = {
    main: { pos: [-0.08, 2.46, -0.43], target: [-0.08, 1.935, -0.40] },           // straight down, turned 180° about the vertical so the front of the box is at the bottom of the view onto the sensor box (below the upper board)
    rise: { pos: [-0.08, 2.4, -1.0] },                                           // the camera first drops to here, in front of the box and below the upper board, then tilts up and over the box
    power: { pos: [0, 1.40, -0.85], target: [0, 1.40, -0.20] },                   // the power box on the post, straight on
    both: { pos: [0.75, 2.15, -1.70], target: [-0.04, 1.68, -0.30] },             // both boxes in one view
  };
  let flown = false, seen = null;                                                                  // seen: which view the camera was sent to
  const focus = () => {
    if (!view) return;
    const m = !!open.main, p = !!open.power;
    const seen0 = seen;                                                                           // where the camera is now, to back out the way it came in
    const to = m && p ? LOOK.both : m ? LOOK.main : p ? LOOK.power : null;
    flown = !!to; seen = to === LOOK.main ? "main" : to === LOOK.power ? "power" : to ? "both" : null;
    if (to) view.flyTo(to.pos, to.target, to === LOOK.main ? 1900 : 1000, to === LOOK.main ? LOOK.rise : null); else view.flyBack(seen0 === "main" ? 1900 : 1000, seen0 === "main" ? LOOK.rise : null);
  };

  /* ---------- lids: click a box, or use the button, to open and close ---------- */
  const open = { main: 0, power: 0 }, ang = { main: 0, power: 0 };
  const extras = [{
    label: "Open the cases", labelOn: "Close the cases", on: false, focus: true,
    toggle: (on) => { open.main = open.power = on ? 2.0 : 0; if (!on && flown) focus(); },   // the button never zooms in; closing only returns a camera that a click sent in
  }];
  const sync = () => { const x = extras[0]; x.on = !!(open.main || open.power); x.refresh && x.refresh(); };
  const toggleMain = () => {
    if (open.main && view && seen !== "main" && seen !== "both") { seen = "main"; flown = true; view.flyTo(LOOK.main.pos, LOOK.main.target, 1900, LOOK.rise); return; }   // already open (by the button): a click goes to it
    open.main = open.main ? 0 : 2.0; sync(); focus();
  };
  const togglePower = () => {
    if (open.power && view && seen !== "power" && seen !== "both") { seen = "power"; flown = true; view.flyTo(LOOK.power.pos, LOOK.power.target, 1000); return; }
    open.power = open.power ? 0 : 2.0; sync(); focus();
  };
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
    { label: "ESP32-CAM", detail: "A small Wi-Fi camera board next to the boost converter. It captures the images; a server runs YOLO pedestrian detection and shadow segmentation on them.", object: espCam },
    { label: "Arduino Uno", detail: "An Elegoo Arduino Uno R3 on a small yellow carrier board. It reads the sensors: each has its own port and thin wire, and the wires are tied together and leave the box as one black cable.", object: arduino },
    { label: "Boost converter (12 V)", detail: "A boost converter that turns the 5 V from the USB power cable into the 12 V that the wind sensor needs.", object: booster },
    { label: "USB-C power input", detail: "A USB-C breakout where the cable from the Voltaic battery arrives. It feeds the boost converter and the electronics.", objects: [usbc, usbIn] },
    { label: "Wind sensor port", detail: "A blue three-way screw terminal for the wind sensor: 12 V from the booster, ground and the pulse signal. A braided cable runs from it up to the anemometer on the lid.", object: terminal },
    { label: "Globe thermometer", detail: "A grey ping-pong ball on a DS18B20 probe (±0.5 °C), on a stick at the uppermost edge of the solar panel. Its temperature, with air temperature and wind, gives MRT.", object: globe },
    { label: "UV sensor", detail: "An ML8511 breakout (about 1% accuracy) on the uppermost edge of the solar panel next to the globe, facing the sky to measure ultraviolet radiation.", object: uv },
    { label: "Humidity sensor (DHT22)", detail: "A DHT22 hangs in one of the two white cups under the board and measures relative humidity (about 2 to 5% accuracy).", object: humidityCup, onHover: (on) => seeThrough(humidityCup, on) },
    { label: "Temperature sensor (DS18B20)", detail: "A Dallas DS18B20 (±0.5 °C) hangs in the other white cup under the board and measures air temperature.", object: dallasCup, onHover: (on) => seeThrough(dallasCup, on) },
    { label: "Solar panel", detail: "Faces south and leans toward the sun to collect as much light as possible (the model uses a 35° tilt for illustration). Its cable runs to the power box on the post.", object: solar },
    { label: "Power box", detail: "A second box on the post. Click it to open. It holds the Voltaic battery and a Wi-Fi dongle, takes the feed from the solar panel and powers the sensor box.", objects: [pc.walls, pc.lid], onClick: togglePower },
    { label: "Voltaic battery", detail: "A Voltaic battery pack. It stores the power from the solar panel and feeds the sensor box through a USB cable that runs up the post; its other USB port powers the Wi-Fi dongle.", object: battery },
    { label: "Wi-Fi dongle", detail: "Connects the installation to the network so the data and images can be sent to the server.", object: dongle },
    { label: "Lamp post and boards", detail: "A concrete lamp post in a park. The sensor board and the power box are on the north side and the solar panel on the south side, held on with steel straps; a second board sits above.", object: mount },
  ];
  return { root, parts, extras, update };
}
