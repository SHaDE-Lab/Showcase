// Tests for the data collector, run with:  node --test test/     (needs express and cors installed: npm install)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const { createApp, normaliseMac, validateReading, ValidationError } = require("../app");

// A tiny in-memory stand-in for the MongoDB calls the app makes.
function fakeDb() {
	const tables = {};
	const table = (name) => (tables[name] = tables[name] || []);
	return {
		tables,
		collection: (name) => ({
			insertOne: async (doc) => { table(name).push({ ...doc }); },
			distinct: async (key) => [...new Set(table(name).map((d) => d[key]))].sort(),
			find: (flt = {}) => {
				let rows = table(name).filter((d) => Object.entries(flt).every(([k, v]) => d[k] === v));
				const cur = {
					sort: (s) => { const [k, dir] = Object.entries(s)[0]; rows = [...rows].sort((a, b) => (a[k] - b[k]) * dir); return cur; },
					limit: (n) => { rows = rows.slice(0, n); return cur; },
					toArray: async () => rows,
				};
				return cur;
			},
		}),
	};
}

async function withServer(db, fn, env = {}) {
	const server = http.createServer(createApp(async () => db, env));
	await new Promise((r) => server.listen(0, "127.0.0.1", r));
	const base = `http://127.0.0.1:${server.address().port}`;
	try { await fn(base); } finally { await new Promise((r) => server.close(r)); }
}
const get = async (base, path) => { const r = await fetch(base + path, { redirect: "manual" }); return { status: r.status, text: await r.text(), headers: r.headers }; };
const MSG = encodeURIComponent('{"Temperature":31.5,"Humidity":22,"UV_Intensity":7.2,"Dallas1":30.1,"Dallas2":null,"Wind_Speed":3.1,"Battery_Voltage":12.4}');

test("mac addresses: both spellings normalise, everything else is refused", () => {
	assert.equal(normaliseMac("24_6f_28_aa_bb_cc"), "24:6F:28:AA:BB:CC");
	assert.equal(normaliseMac("24:6F:28:AA:BB:CC"), "24:6F:28:AA:BB:CC");
	for (const bad of ["", "nonsense", "24:6F:28:AA:BB", "../../x", undefined, null, 5, { $ne: "" }, ["24:6F:28:AA:BB:CC"]])
		assert.throws(() => normaliseMac(bad), ValidationError);
});

test("readings: only the known numeric fields, or null", () => {
	assert.deepEqual(validateReading('{"Temperature":30,"Humidity":null}'), { Temperature: 30, Humidity: null });
	for (const bad of ["not json", "[]", "null", '{"Temperature":"hot"}', '{"Temperature":true}', '{"Surprise":1}', '{"Temperature":{"$gt":0}}', "5"])
		assert.throws(() => validateReading(bad), ValidationError);
});

test("updateData stores a message with the device id and a timestamp", async () => {
	const db = fakeDb();
	await withServer(db, async (base) => {
		const before = Date.now();
		const r = await get(base, `/updateData?data=${MSG}&mac=24:6F:28:AA:BB:CC`);
		assert.equal(r.status, 200); assert.equal(r.text, "1");
		const doc = db.tables.data[0];
		assert.equal(doc.mac, "24:6F:28:AA:BB:CC"); assert.equal(doc.Temperature, 31.5); assert.equal(doc.Dallas2, null);
		assert.ok(doc.time >= before && doc.time <= Date.now());
	});
});

test("updateData accepts the url-encoded form the firmware sends (the mac colon becomes %3A)", async () => {
	const db = fakeDb();
	await withServer(db, async (base) => {
		const r = await get(base, `/updateData?data=${MSG}&mac=24%3A6F%3A28%3AAA%3ABB%3ACC`);
		assert.equal(r.status, 200); assert.equal(db.tables.data[0].mac, "24:6F:28:AA:BB:CC");
	});
});

test("updateData refuses bad input and stores nothing", async () => {
	const db = fakeDb();
	await withServer(db, async (base) => {
		const cases = [
			"/updateData", `/updateData?data=${MSG}`, "/updateData?mac=24:6F:28:AA:BB:CC",
			`/updateData?data=${MSG}&mac=nope`, "/updateData?data=%7Bbroken&mac=24:6F:28:AA:BB:CC",
			`/updateData?data=${encodeURIComponent('{"admin":1}')}&mac=24:6F:28:AA:BB:CC`,
			`/updateData?data[$ne]=1&mac=24:6F:28:AA:BB:CC`, `/updateData?data=${MSG}&mac[$ne]=1`,
		];
		for (const path of cases) assert.equal((await get(base, path)).status, 400, path);
		assert.equal(db.tables.data, undefined);
	});
});

test("getIds, getLatest and getLatestImageData", async () => {
	const db = fakeDb();
	const A = "24:6F:28:AA:BB:01", B = "24:6F:28:AA:BB:02";
	for (const [mac, time] of [[A, 100], [A, 300], [A, 200], [B, 400]]) await db.collection("data").insertOne({ mac, time, Temperature: time });
	await db.collection("shadow").insertOne({ _id: "x", mac: A, time: 5 });
	await db.collection("shadow").insertOne({ _id: "y", mac: A, time: 9 });
	await withServer(db, async (base) => {
		assert.deepEqual(JSON.parse((await get(base, "/getIds")).text), [A, B]);
		assert.deepEqual(JSON.parse((await get(base, `/getLatest?id=${A}`)).text).map((d) => d.time), [300, 200, 100]);
		assert.deepEqual(JSON.parse((await get(base, `/getLatest?id=${A}&limit=2`)).text).map((d) => d.time), [300, 200]);
		assert.equal(JSON.parse((await get(base, "/getLatest")).text)[0].mac, B);
		assert.equal(JSON.parse((await get(base, `/getLatestImageData?id=${A}`)).text)._id, "y");
		assert.equal((await get(base, `/getLatestImageData?id=${B}`)).text, "null");
	});
});

test("a query cannot be hijacked with an object in the id", async () => {
	await withServer(fakeDb(), async (base) => {
		for (const path of ["/getLatest?id[$ne]=x", "/getLatestImageData?id[$gt]=", "/getLatest?id=not-a-mac"])
			assert.equal((await get(base, path)).status, 400, path);
	});
});

test("limit is kept within 1 to 100", async () => {
	const db = fakeDb();
	for (let t = 1; t <= 150; t++) await db.collection("data").insertOne({ mac: "24:6F:28:AA:BB:01", time: t });
	await withServer(db, async (base) => {
		assert.equal(JSON.parse((await get(base, "/getLatest?limit=100000")).text).length, 100);
		assert.equal(JSON.parse((await get(base, "/getLatest?limit=0")).text).length, 10);
		assert.equal(JSON.parse((await get(base, "/getLatest?limit=-5")).text).length, 1);
	});
});

test("CORS header only when configured, root redirect only when configured, healthz always", async () => {
	await withServer(fakeDb(), async (base) => {
		assert.equal((await get(base, "/healthz")).headers.get("access-control-allow-origin"), null);
		assert.equal((await get(base, "/")).status, 200);
		assert.equal(JSON.parse((await get(base, "/healthz")).text).status, "ok");
	});
	await withServer(fakeDb(), async (base) => {
		assert.equal((await get(base, "/healthz")).headers.get("access-control-allow-origin"), "https://viewer.example.org");
		const r = await get(base, "/");
		assert.equal(r.status, 302); assert.equal(r.headers.get("location"), "https://viewer.example.org/view");
	}, { CORS_ORIGIN: "https://viewer.example.org", VIEW_URL: "https://viewer.example.org/view" });
});
