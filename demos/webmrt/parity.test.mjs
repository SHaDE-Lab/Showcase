// Parity test: the JavaScript demo must agree with the Python reference (golden.json).
//   node demos/webmrt/parity.test.mjs        (run from the portal root, or anywhere)
//
// Regenerate the golden file with:  python codebases/webmrt/run_demo.py
//
// Tolerances
//   model evaluator   : |JS - Python| < 1e-6 degC given the *same* feature row (exact algorithm, double precision)
//   solar position    : elevation within 0.03 deg and azimuth within 0.10 deg of pvlib (SPA) for Phoenix
//                       (NOAA/Meeus is documented as agreeing with SPA to a few hundredths of a degree)
//   minutes-from-sunrise feature : exactly equal to Python's int() value
//   end-to-end        : JS builds its own features (own solar position); the prediction may differ from Python only if
//                       the ~0.01 deg altitude difference crosses a tree split, so we require 99% within 0.05 degC
//                       and report the worst case.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
globalThis.window = globalThis;
await import(join(here, "demo.js").replace(/\\/g, "/").replace(/^([A-Za-z]):/, "file:///$1:"));
const { evaluate, solarPosition, minFromSunrise, buildRow } = globalThis.UHDemos.webmrt.core;

const model = JSON.parse(readFileSync(join(here, "data", "model.json"), "utf8"));
const golden = JSON.parse(readFileSync(join(here, "data", "golden.json"), "utf8"));
let failures = 0;
const check = (name, fn) => { try { fn(); console.log("ok   ", name); } catch (e) { failures++; console.log("FAIL ", name, "\n     ", e.message); } };

check(`evaluator matches Python on ${golden.cases.length} cases (< 1e-6)`, () => {
  let worst = 0;
  for (const c of golden.cases) worst = Math.max(worst, Math.abs(evaluate(model, c.row) - c.tmrt));
  console.log("      worst |JS-Python| =", worst.toExponential(2));
  assert.ok(worst < 1e-6, "worst difference " + worst);
});

check(`solar position matches pvlib on ${golden.solar.length} date-times`, () => {
  let we = 0, wa = 0;
  for (const s of golden.solar) {
    const [y, mo, d] = s.date.split("-").map(Number), [h, mi] = s.time.split(":").map(Number);
    const p = solarPosition(y, mo, d, h, mi, model.site.latitude, model.site.longitude, model.site.utc_offset_hours);
    we = Math.max(we, Math.abs(p.elevation - s.elevation));
    if (s.elevation > 0) wa = Math.max(wa, Math.abs(p.azimuth - s.azimuth));
  }
  console.log(`      worst elevation error ${we.toFixed(4)} deg, worst azimuth error ${wa.toFixed(4)} deg`);
  assert.ok(we < 0.03, "elevation " + we); assert.ok(wa < 0.1, "azimuth " + wa);
});

check("minutes-from-sunrise feature equals Python exactly", () => {
  for (const c of golden.cases) assert.equal(minFromSunrise(model, c.in.date, c.in.time), c.row[7]);
});

check("end-to-end: JS builds features and predicts (99% within 0.05 degC of Python)", () => {
  let within = 0, worst = 0;
  for (const c of golden.cases) {
    const { row } = buildRow(model, { ...c.in });
    const d = Math.abs(evaluate(model, row) - c.tmrt); worst = Math.max(worst, d); if (d < 0.05) within++;
  }
  console.log(`      ${within}/${golden.cases.length} within 0.05 degC, worst ${worst.toFixed(3)} degC`);
  assert.ok(within / golden.cases.length >= 0.99);
});

check("model file is the 200-tree, 8-feature LightGBM export", () => {
  assert.equal(model.trees.length, 200); assert.equal(model.features.length, 8);
});

if (failures) { console.log(`\n${failures} check(s) failed`); process.exit(1); }
console.log("\nall parity checks passed");
