#!/usr/bin/env node
/**
 * Lightweight SuperCollider bridge using supercolliderjs.
 * Communicates with Ambiance via newline-delimited JSON messages.
 */
"use strict";

const path = require("path");
const readline = require("readline");

let supercollider;
try {
    supercollider = require("supercolliderjs");
} catch (error) {
    process.stderr.write(
        JSON.stringify({
            severity: "fatal",
            message: "supercolliderjs is not installed. Run `npm install supercolliderjs`.",
            details: error && error.message ? error.message : String(error),
        }) + "\n"
    );
    process.exit(1);
}

const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
});

let lang = null;
let server = null;
let shuttingDown = false;
let nextRequestId = 1;

function normalizePaths(items = []) {
    return items
        .filter(Boolean)
        .map((item) => path.resolve(item));
}

async function bootRuntime(payload = {}) {
    if (lang) {
        return {
            ok: true,
            info: "already booted",
        };
    }
    const langOptions = Object.assign({}, payload.lang || {});
    const includePaths = normalizePaths(
        payload.includePaths || (langOptions.conf && langOptions.conf.includePaths) || []
    );
    langOptions.conf = langOptions.conf || {};
    langOptions.conf.includePaths = includePaths;
    if (payload.sclang && !langOptions.sclang) {
        langOptions.sclang = payload.sclang;
    }

    lang = await supercollider.lang.boot(langOptions);
    const serverOptions = Object.assign({}, payload.server || {});
    server = await supercollider.server.boot(serverOptions);
    return { ok: true };
}

async function evaluateCode(payload = {}) {
    if (!lang) {
        throw new Error("SuperCollider language has not been booted");
    }
    const code = payload.code;
    if (!code || typeof code !== "string") {
        throw new Error("Missing `code` string for evaluate command");
    }
    const asString = Boolean(payload.asString);
    const result = await lang.interpret(code, undefined, asString, true, true);
    if (result && typeof result === "object" && "result" in result) {
        return { ok: true, result: result.result, stdout: result.stdout, stderr: result.stderr };
    }
    return { ok: true, result };
}

async function sendServerMessage(payload = {}) {
    if (!server) {
        throw new Error("SuperCollider server has not been booted");
    }
    const address = payload.address;
    const args = Array.isArray(payload.args) ? payload.args : [];
    if (!address) {
        throw new Error("Missing OSC address for server message");
    }
    server.send.msg(address, ...args);
    return { ok: true };
}

async function shutdownRuntime() {
    shuttingDown = true;
    try {
        if (server && server.running) {
            await server.quit();
        }
    } catch (error) {
        // ignore shutdown errors
    }
    try {
        if (lang) {
            await lang.quit();
        }
    } catch (error) {
        // ignore shutdown errors
    }
    process.exit(0);
}

function postResponse(data) {
    process.stdout.write(JSON.stringify(data) + "\n");
}

function serializeError(error) {
    if (!error) {
        return { message: "Unknown error" };
    }
    const payload = {
        message: error && error.message ? error.message : String(error),
    };
    if (error.stack) {
        payload.stack = error.stack;
    }
    if (error.stdout) {
        payload.stdout = error.stdout;
    }
    if (error.stderr) {
        payload.stderr = error.stderr;
    }
    if (error.code) {
        payload.code = error.code;
    }
    return payload;
}

async function handleRequest(message) {
    const { id, command } = message;
    const respond = (payload) => postResponse(Object.assign({ id, ok: true }, payload || {}));
    const respondError = (error) =>
        postResponse(
            Object.assign(
                {
                    id,
                    ok: false,
                },
                serializeError(error)
            )
        );

    try {
        switch (command) {
            case "ping":
                respond({ message: "pong" });
                break;
            case "boot":
                await bootRuntime(message.options || {});
                respond({ message: "booted" });
                break;
            case "eval":
                respond(await evaluateCode(message));
                break;
            case "send":
                respond(await sendServerMessage(message));
                break;
            case "shutdown":
                respond({ message: "shutting down" });
                await shutdownRuntime();
                break;
            default:
                throw new Error(`Unknown command: ${command}`);
        }
    } catch (error) {
        respondError(error);
    }
}

rl.on("line", (line) => {
    const trimmed = line.trim();
    if (!trimmed.length) {
        return;
    }
    let message;
    try {
        message = JSON.parse(trimmed);
    } catch (error) {
        postResponse({
            id: nextRequestId++,
            ok: false,
            message: `Invalid JSON: ${error && error.message ? error.message : error}`,
        });
        return;
    }
    if (typeof message.id === "undefined") {
        message.id = nextRequestId++;
    }
    handleRequest(message);
});

process.on("SIGINT", () => {
    if (!shuttingDown) {
        shutdownRuntime();
    }
});

process.on("SIGTERM", () => {
    if (!shuttingDown) {
        shutdownRuntime();
    }
});
