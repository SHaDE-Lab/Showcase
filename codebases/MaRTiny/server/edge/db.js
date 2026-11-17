// Copyright 2026 The SHaDE Lab, Arizona State University
// SPDX-License-Identifier: CERN-OHL-P-2.0
//
// One shared MongoDB connection. The address comes from MONGO_URL, never from the code.
"use strict";
const { MongoClient } = require("mongodb");

let db = null;

async function connectDB(env = process.env) {
	if (!env.MONGO_URL) throw new Error("MONGO_URL is not set (copy .env.example to .env and fill it in)");
	const client = new MongoClient(env.MONGO_URL);
	await client.connect();
	db = client.db(env.DB || env.MONGO_DB || "martiny-studio");
	// the viewer asks for the newest documents of one device, so index on (mac, time)
	for (const name of ["data", "shadow"]) await db.collection(name).createIndex({ mac: 1, time: -1 });
	return db;
}

async function getDB() {
	if (!db) throw new Error("database is not connected");
	return db;
}

module.exports = { connectDB, getDB };
