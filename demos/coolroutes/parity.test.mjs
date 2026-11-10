// Parity test: the JavaScript router used by the website demo must reproduce the Python golden routes
// (codebases/cool-routes/data/golden_routes.json, produced by the released Python code).
//
//   node demos/coolroutes/parity.test.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const router = require("./demo.js");
const graph = JSON.parse(readFileSync(path.join(here, "data", "graph.json"), "utf8"));
const golden = JSON.parse(readFileSync(path.join(here, "data", "golden.json"), "utf8"));
const nodeId = (i) => graph.nodes[i][0];           // index -> OSM id (what Python reports)
const close = (a, b, rel = 1e-9) => Math.abs(a - b) <= rel * Math.max(1, Math.abs(a), Math.abs(b));

let checks = 0, tieNotes = 0;
graph.stamps.forEach((stamp, si) => {
  const G = router.buildGraph(graph, si);
  assert.ok(close(G.scale, golden.scale[stamp], 1e-12), `scale ${stamp}`);
  for (const p of golden.pairs) {
    const a = router.nearestNode(G, p.start[0], p.start[1]);          // snapping uses the same projected metric
    const b = router.nearestNode(G, p.end[0], p.end[1]);
    assert.equal(nodeId(a), p.start_node, "origin snaps to the same node as Python");
    assert.equal(nodeId(b), p.end_node, "destination snaps to the same node as Python");
    const weights = { length: { kind: "length" }, cost: { kind: "cost" }, blend: { kind: "blend", w: golden.blend_w } };
    for (const [name, w] of Object.entries(weights)) {
      const exp = p.stamps[stamp][name];
      const r = router.route(G, a, b, w);
      const s = router.stats(G, r);
      const same = JSON.stringify(r.nodes.map(nodeId)) === JSON.stringify(exp.route);
      if (!same) {                                     // allow only an exact tie in total weight
        tieNotes++;
        const wf = router.weightFn(G, w);
        const total = r.edges.reduce((t, ei) => t + wf(graph.edges[ei]), 0);
        assert.fail(`route differs for ${stamp} ${name} pair ${p.start_node}->${p.end_node} (JS weight ${total})`);
      }
      assert.ok(close(s.length, exp.length), `length ${stamp} ${name}`);
      assert.ok(close(s.average_mrt, exp.average_mrt), `average_mrt ${stamp} ${name}`);
      assert.ok(close(s.corrected_mean_mrt, exp.corrected_mean_mrt), `corrected mean ${stamp} ${name}`);
      assert.ok(close(s.mrt, exp.mrt), `sum of edge means ${stamp} ${name}`);
      checks++;
    }
  }
});
console.log(`OK: ${checks} routes identical to the Python golden routes (nodes + length + MRT statistics), ${tieNotes} ties.`);
