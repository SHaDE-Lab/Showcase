// Copyright 2026 The SHaDE Lab, Arizona State University
// SPDX-License-Identifier: CERN-OHL-P-2.0
//
// Starts the MaRTiny data collector:  node server.js   (settings from the environment or a .env file, see .env.example)
"use strict";
require("dotenv").config();
const { createApp } = require("./app");
const { connectDB, getDB } = require("./db");

const port = parseInt(process.env.EDGE_PORT, 10) || 8081;

connectDB()
	.then(() => {
		console.log("Connected to MongoDB");
		createApp(getDB).listen(port, () => console.log(`Data server running on port ${port}`));
	})
	.catch((err) => {
		console.error("Could not start:", err.message);
		process.exit(1);
	});
