#!/usr/bin/env node
// Kills whatever process is already listening on the given port(s) before a
// dev server starts, so `npm run dev` always wins the port instead of
// falling back to 3001/3002/... or refusing to start. Windows dev-server
// processes here regularly survive a stopped terminal/background task
// (detached node.exe), which is what this exists to clean up.
"use strict";

const { execSync } = require("node:child_process");

const ports = (process.argv.slice(2).length ? process.argv.slice(2) : ["3000"]).map(String);

function freePortWindows(port) {
  let output;
  try {
    output = execSync("netstat -ano -p tcp", { encoding: "utf8" });
  } catch {
    return;
  }
  const pids = new Set();
  for (const line of output.split("\n")) {
    const match = line.match(/^\s*TCP\s+\S*:(\d+)\s+\S+\s+LISTENING\s+(\d+)/);
    if (match && match[1] === port) {
      pids.add(match[2]);
    }
  }
  for (const pid of pids) {
    try {
      execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore" });
      console.log(`[free-port] Killed process ${pid} holding port ${port}`);
    } catch {
      // Already gone between the scan and the kill; fine.
    }
  }
}

function freePortUnix(port) {
  let output;
  try {
    output = execSync(`lsof -ti tcp:${port}`, { encoding: "utf8" }).trim();
  } catch {
    return;
  }
  if (!output) return;
  for (const pid of output.split("\n").filter(Boolean)) {
    try {
      execSync(`kill -9 ${pid}`);
      console.log(`[free-port] Killed process ${pid} holding port ${port}`);
    } catch {
      // Already gone between the scan and the kill; fine.
    }
  }
}

for (const port of ports) {
  if (process.platform === "win32") {
    freePortWindows(port);
  } else {
    freePortUnix(port);
  }
}
