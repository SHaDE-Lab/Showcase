/* MaRTiny: procedural 3D model, built from photographs of the device and the parts list in
   Kulkarni et al. (2022), Front. Environ. Sci. 10:866240. Units are metres; proportions are approximate. */
import { THREE, mat, cyl, box, sph, at, between, cable, textTexture } from "./scene.js";

export function buildMartiny() {
  const M = {
    white: mat(0xeceef0, { rough: 0.5 }), whiteSoft: mat(0xdfe3e6, { rough: 0.55 }), steel: mat(0xc9ced6, { rough: 0.3, metal: 0.85 }),
    black: mat(0x15171b, { rough: 0.65 }), dark: mat(0x23262c, { rough: 0.6 }), globe: mat(0x7a8087, { rough: 0.55 }),
    glass: mat(0xe9eef2, { rough: 0.1, opacity: 0.85 }), lens: mat(0x0a0b0e, { rough: 0.15, metal: 0.2 }), red: mat(0xd4232a, { rough: 0.5 }),
    pcbGreen: mat(0x0f6f7e, { rough: 0.5 }), pcbBlack: mat(0x1b1d22, { rough: 0.55 }), fan: mat(0x7a4a2a, { rough: 0.6 }),
    board: mat(0xf3f3ee, { rough: 0.6 }), grey: mat(0x9aa0a8, { rough: 0.5, metal: 0.5 }), cable: mat(0x0b0b0d, { rough: 0.6 }),
    blue: mat(0x2d56b8, { rough: 0.5 }), yellow: mat(0xe9c63a, { rough: 0.5 }), wireRed: mat(0xd33a2c, { rough: 0.6 }), wireGreen: mat(0x2e9b4e, { rough: 0.6 }),
  };
  const group = (...kids) => { const g = new THREE.Group(); kids.forEach((k) => g.add(k)); return g; };
  const root = new THREE.Group();

  /* ---------- stand: mast stub, platform and posts ---------- */
  const stand = new THREE.Group();
  stand.add(between([0, 0, 0], [0, 0.236, 0], 0.02, M.steel));
  stand.add(at(box(0.32, 0.014, 0.26, M.black), 0, 0.243, 0));
  [[-0.13, -0.1], [0.13, -0.1], [-0.13, 0.1], [0.13, 0.1]].forEach(([x, z]) => stand.add(between([x, 0.25, z], [x, 0.292, z], 0.007, M.black, 10)));

  /* ---------- enclosure: open tray + hinged lid ---------- */
  const W = 0.24, H = 0.09, D = 0.19, T = 0.005, Y0 = 0.292;       // outer size, wall thickness, floor level
  const enclosure = new THREE.Group();
  enclosure.add(at(box(W, T, D, M.white), 0, Y0 + T / 2, 0));
  enclosure.add(at(box(W, H, T, M.white), 0, Y0 + H / 2, D / 2 - T / 2));
  enclosure.add(at(box(W, H, T, M.white), 0, Y0 + H / 2, -D / 2 + T / 2));
  enclosure.add(at(box(T, H, D, M.white), W / 2 - T / 2, Y0 + H / 2, 0));
  enclosure.add(at(box(T, H, D, M.white), -W / 2 + T / 2, Y0 + H / 2, 0));
  for (const x of [-W / 2 + 0.008, W / 2 - 0.008]) for (const z of [-D / 2 + 0.008, D / 2 - 0.008]) enclosure.add(at(cyl(0.004, H - 0.01, M.whiteSoft, 10), x, Y0 + H / 2, z));
  // cable glands on the sides
  [[-W / 2 - 0.006, 0.06, -0.04], [-W / 2 - 0.006, 0.06, 0.04], [W / 2 + 0.006, 0.06, 0.0]].forEach(([x, y, z]) => {
    const g = cyl(0.011, 0.014, M.whiteSoft, 18); g.rotation.z = Math.PI / 2; enclosure.add(at(g, x, Y0 + y, z));
  });
  // front panel: camera lens, translucent dome window, red label
  const front = D / 2 + 0.002, yMid = Y0 + H / 2;
  const lensRing = cyl(0.021, 0.012, M.black, 28); lensRing.rotation.x = Math.PI / 2; enclosure.add(at(lensRing, -0.075, yMid, front));
  const lensGlass = cyl(0.014, 0.006, M.lens, 24); lensGlass.rotation.x = Math.PI / 2; enclosure.add(at(lensGlass, -0.075, yMid, front + 0.008));
  const dome = sph(0.027, M.glass, 28); dome.scale.z = 0.45; enclosure.add(at(dome, 0.0, yMid, front));
  const label = new THREE.Mesh(new THREE.PlaneGeometry(0.05, 0.036), M.red); enclosure.add(at(label, 0.078, yMid, front + 0.001));
  // lid on a hinge at the back edge
  const lidPivot = new THREE.Group(); lidPivot.position.set(0, Y0 + H, -D / 2);
  lidPivot.add(at(box(W + 0.004, 0.006, D + 0.004, M.white), 0, 0.003, D / 2));
  lidPivot.add(at(box(W - 0.02, 0.003, D - 0.02, M.whiteSoft), 0, -0.002, D / 2));
  enclosure.add(lidPivot);

  /* ---------- electronics inside the enclosure ---------- */
  const fy = Y0 + T;                                                 // floor top
  // NVIDIA Jetson Nano: board, heat sink and fan
  const jetson = new THREE.Group();
  jetson.add(at(box(0.10, 0.002, 0.08, M.pcbBlack), 0, 0.012, 0));
  jetson.add(at(box(0.064, 0.026, 0.05, M.dark), 0, 0.027, -0.004));
  for (let i = -3; i <= 3; i++) jetson.add(at(box(0.064, 0.012, 0.0035, M.black), 0, 0.046, -0.004 + i * 0.0066));
  jetson.add(at(box(0.042, 0.012, 0.042, M.fan), 0, 0.058, -0.004));
  jetson.add(at(cyl(0.015, 0.0125, M.black, 20), 0, 0.0585, -0.004));
  jetson.add(at(box(0.02, 0.014, 0.016, M.grey), -0.047, 0.02, 0.01), at(box(0.02, 0.014, 0.016, M.grey), -0.047, 0.02, -0.014));   // USB ports
  jetson.add(at(box(0.026, 0.008, 0.002, M.whiteSoft), 0.0, 0.016, 0.043));                                                        // camera ribbon
  jetson.position.set(-0.062, fy, -0.028);
  // Arduino Uno
  const arduino = new THREE.Group();
  arduino.add(at(box(0.069, 0.002, 0.053, M.pcbGreen), 0, 0.012, 0));
  arduino.add(at(box(0.013, 0.011, 0.016, M.grey), -0.029, 0.018, -0.012));                                                        // USB-B
  arduino.add(at(box(0.009, 0.011, 0.014, M.black), -0.03, 0.018, 0.014));                                                         // power jack
  arduino.add(at(box(0.052, 0.0085, 0.0025, M.black), 0.004, 0.0165, -0.0235), at(box(0.052, 0.0085, 0.0025, M.black), 0.004, 0.0165, 0.0235));
  arduino.add(at(box(0.034, 0.003, 0.009, M.dark), 0.012, 0.0145, 0.0));                                                           // microcontroller
  arduino.position.set(0.075, fy, -0.03);
  // breadboard with the NodeMCU (ESP8266) and a sensor breakout
  const bread = new THREE.Group();
  bread.add(at(box(0.083, 0.009, 0.055, M.board), 0, 0.0045, 0));
  bread.add(at(box(0.05, 0.0015, 0.026, M.pcbBlack), -0.004, 0.0105, 0.0));
  bread.add(at(box(0.014, 0.003, 0.014, M.grey), 0.014, 0.0125, 0.0));                                                              // Wi-Fi module
  bread.add(at(box(0.012, 0.0015, 0.016, M.blue), -0.03, 0.0105, 0.018));                                                            // sensor breakout
  bread.position.set(0.012, fy, 0.05);
  // jumper wires
  const wireMats = [M.wireRed, M.yellow, M.wireGreen, M.blue, M.black];
  const wires = new THREE.Group();
  [[[0.0, 0.31, 0.04], [0.03, 0.325, 0.0], [0.07, 0.31, -0.02]], [[0.02, 0.31, 0.055], [-0.01, 0.33, 0.02], [-0.04, 0.325, -0.01]],
   [[0.045, 0.31, 0.06], [0.06, 0.322, 0.03], [0.085, 0.31, 0.0]], [[-0.02, 0.31, 0.066], [-0.05, 0.322, 0.06], [-0.085, 0.31, 0.05]],
   [[0.0, 0.31, 0.03], [-0.02, 0.328, 0.0], [-0.03, 0.31, -0.03]]].forEach((pts, i) => wires.add(cable(pts, 0.0017, wireMats[i % wireMats.length])));

  /* ---------- sensors ---------- */
  // cup anemometer on its own post behind the enclosure; the cups turn slowly
  const anemometer = new THREE.Group();
  anemometer.add(between([0, 0.25, -0.125], [0, 0.50, -0.125], 0.009, M.black, 14));
  anemometer.add(at(cyl(0.0095, 0.05, M.steel, 14), 0, 0.30, -0.125));
  const cups = new THREE.Group(); cups.position.set(0, 0.505, -0.125);
  cups.add(cyl(0.012, 0.014, M.black, 16));
  for (let i = 0; i < 3; i++) {
    const a = i * Math.PI * 2 / 3, arm = new THREE.Group(); arm.rotation.y = a;
    const rod = between([0, 0, 0], [0.058, 0, 0], 0.0035, M.black, 8); arm.add(rod);
    const cup = new THREE.Mesh(new THREE.SphereGeometry(0.022, 20, 12, 0, Math.PI), M.black); cup.material.side = THREE.DoubleSide;
    cup.position.set(0.058, 0, 0); cup.rotation.y = Math.PI / 2; arm.add(cup);
    cups.add(arm);
  }
  anemometer.add(cups);

  // globe thermometer: grey ball on a probe, on a stalk at the side of the enclosure
  const globe = new THREE.Group();
  globe.add(between([W / 2, Y0 + 0.07, 0.01], [W / 2 + 0.02, Y0 + 0.105, 0.02], 0.0035, M.black, 8));
  globe.add(at(sph(0.02, M.globe, 32), W / 2 + 0.024, Y0 + 0.128, 0.022));
  // air-temperature probe hanging in a white radiation cup
  const airCup = new THREE.Group();
  airCup.add(between([-W / 2, Y0 + 0.07, 0.06], [-W / 2 - 0.03, Y0 + 0.045, 0.075], 0.0018, M.cable, 6));
  const cupBody = cyl(0.028, 0.058, M.white, 32, 0.02); cupBody.material.side = THREE.DoubleSide; cupBody.position.set(-W / 2 - 0.045, Y0 + 0.005, 0.085);
  airCup.add(cupBody); airCup.add(at(cyl(0.004, 0.036, M.steel, 8), -W / 2 - 0.045, Y0 + 0.002, 0.085));
  // camera (the lens window on the front panel)
  const camera = group(at((() => { const r = cyl(0.026, 0.02, M.black, 28); r.rotation.x = Math.PI / 2; return r; })(), -0.075, yMid, front + 0.004),
                       at((() => { const r = cyl(0.015, 0.008, M.lens, 24); r.rotation.x = Math.PI / 2; return r; })(), -0.075, yMid, front + 0.016));
  // Wi-Fi antenna
  const antenna = new THREE.Group();
  antenna.add(between([-W / 2 - 0.006, Y0 + 0.062, -0.07], [-W / 2 - 0.115, Y0 + 0.075, -0.07], 0.0055, M.black, 12));
  antenna.add(at(sph(0.0065, M.black, 10), -W / 2 - 0.115, Y0 + 0.075, -0.07));
  root.add(anemometer, globe, airCup, camera);

  /* ---------- the case opens: the lid swings up and back ---------- */
  let target = 0, angle = 0;
  const extras = [{
    label: "Open the case", on: false, focus: true,
    toggle: (on) => { target = on ? -2.0 : 0; },
  }];
  const update = (dt, t) => {
    cups.rotation.y = t * 1.6;
    angle += (target - angle) * Math.min(1, dt * 5.5);
    lidPivot.rotation.x = angle;
  };

  const micro = group(arduino, bread, wires), casing = group(enclosure, stand, antenna);
  root.add(casing, jetson, micro);

  const parts = [
    { label: "Cup anemometer", detail: "Wind speed (worst-case error about 1 m/s), needed to turn globe temperature into mean radiant temperature. Powered at 9 V.", object: anemometer },
    { label: "Globe thermometer", detail: "A grey ping-pong ball on a DS18B20 probe (±0.5 °C). Its temperature, with air temperature and wind, gives MRT.", object: globe },
    { label: "Air probe in a radiation cup", detail: "A second DS18B20 hangs inside a white cup that shades it from the sun.", object: airCup },
    { label: "Camera", detail: "An IMX219 camera feeds computer vision that counts pedestrians in sun and in shade. Images are discarded after analysis.", object: camera },
    { label: "NVIDIA Jetson Nano", detail: "Edge computer with a cooling fan. Runs YOLOv3 pedestrian detection (about 4 frames per second) and shadow detection every 15 minutes.", object: jetson },
    { label: "Arduino Uno and NodeMCU", detail: "The Uno reads the DHT22 humidity and ML8511 UV sensors and the probes; the NodeMCU (ESP8266) sends the data over Wi-Fi.", object: micro },
    { label: "Enclosure and mount", detail: "A white weatherproof junction box on a platform and mast stub, powered from one 20 W supply, with a Wi-Fi antenna on the side.", object: casing },
  ];
  return { root, parts, extras, update };
}
