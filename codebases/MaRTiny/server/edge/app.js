// Copyright 2026 The SHaDE Lab, Arizona State University
// SPDX-License-Identifier: CERN-OHL-P-2.0
//
// The MaRTiny data collector: receives the sensor message the ESP32-CAM sends and serves it, and the photo results, to a viewer.
// createApp takes a function that returns the database, so the tests can hand it an in-memory one.
//
//   GET /updateData?data={json}&mac=AA:BB:..   store one sensor message (the firmware's request, so it stays a GET)
//   GET /getIds                                device ids that have sent data
//   GET /getLatest?id=AA:BB:..&limit=10        newest sensor messages, one device or all
//   GET /getLatestImageData?id=AA:BB:..        newest analysed photo of a device
//   GET /healthz                               liveness check
"use strict";
const express = require("express");
const cors = require("cors");

const MAC_RE = /^[0-9A-Fa-f]{2}([:_-][0-9A-Fa-f]{2}){5}$/;
const READING_FIELDS = ["Temperature", "Humidity", "UV_Intensity", "Dallas1", "Dallas2", "Wind_Speed", "Battery_Voltage"];

class ValidationError extends Error {}

// 24_6f_28_aa_bb_cc and 24:6F:28:AA:BB:CC are the same device. Anything that is not a plain string is refused, so a request
// such as ?id[$ne]=x (which Express turns into an object) can never reach a database query.
function normaliseMac(mac) {
	if (typeof mac !== "string" || !MAC_RE.test(mac)) throw new ValidationError("mac must be a MAC address such as 24:6F:28:AA:BB:CC");
	return mac.replace(/[_-]/g, ":").toUpperCase();
}

// Only the fields the Arduino sends, each a finite number or null.
function validateReading(text) {
	let values;
	try {
		values = JSON.parse(text);
	} catch (e) {
		throw new ValidationError("data is not valid JSON");
	}
	if (values === null || typeof values !== "object" || Array.isArray(values)) throw new ValidationError("data must be a JSON object");
	const unknown = Object.keys(values).filter((k) => !READING_FIELDS.includes(k));
	if (unknown.length) throw new ValidationError("unknown field(s): " + unknown.join(", "));
	for (const [k, v] of Object.entries(values)) {
		if (v !== null && !(typeof v === "number" && Number.isFinite(v))) throw new ValidationError(k + " must be a number or null");
	}
	return values;
}

function createApp(getDb, env = process.env) {
	const app = express();
	if (env.CORS_ORIGIN) app.use(cors({ origin: env.CORS_ORIGIN }));
	app.disable("x-powered-by");

	const wrap = (fn) => async (req, res) => {
		try {
			await fn(req, res);
		} catch (e) {
			if (e instanceof ValidationError) return res.status(400).json({ error: e.message });
			console.error(e);
			res.status(500).json({ error: "server error" });
		}
	};
	const optionalMac = (v) => (v === undefined ? null : normaliseMac(v));

	app.get("/healthz", (req, res) => res.json({ status: "ok" }));

	app.get("/getIds", wrap(async (req, res) => {
		const db = await getDb();
		res.json(await db.collection("data").distinct("mac"));
	}));

	app.get("/getLatest", wrap(async (req, res) => {
		const mac = optionalMac(req.query.id);
		const limit = Math.min(Math.max(parseInt(req.query.limit, 10) || 10, 1), 100);
		const db = await getDb();
		res.json(await db.collection("data").find(mac ? { mac } : {}).sort({ time: -1 }).limit(limit).toArray());
	}));

	app.get("/getLatestImageData", wrap(async (req, res) => {
		const mac = optionalMac(req.query.id);
		const db = await getDb();
		const rows = await db.collection("shadow").find(mac ? { mac } : {}).sort({ time: -1 }).limit(1).toArray();
		res.json(rows[0] || null);
	}));

	app.get("/updateData", wrap(async (req, res) => {
		const { data, mac } = req.query;
		if (typeof data !== "string" || mac === undefined) throw new ValidationError("data and mac are required");
		const doc = validateReading(data);
		doc.mac = normaliseMac(mac);
		doc.time = Date.now();
		const db = await getDb();
		await db.collection("data").insertOne(doc);
		res.send("1");
	}));

	app.get("/", (req, res) => (env.VIEW_URL ? res.redirect(env.VIEW_URL) : res.type("text").send("MaRTiny data collector")));

	return app;
}

module.exports = { createApp, normaliseMac, validateReading, ValidationError, READING_FIELDS };
