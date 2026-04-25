'use strict';

// server.js — Express application entry point
// Registers all routes, CORS, body-parser, and health probe.
// Deployed on Railway at https://hai-backend-production.up.railway.app

const express = require('express');
const app     = express();
const PORT    = process.env.PORT || 3000;

// ── Allowed origins ─────────────────────────────────────────────────────────
// Add every domain that will call this API.
// HostGator hosts app.html and bundle.js on these origins.
const ALLOWED_ORIGINS = [
    'https://www.humaital.com',
    'https://humaital.com',
    'https://humanalignmentindex.com',
    'https://www.humanalignmentindex.com',
    'http://localhost',
    'http://localhost:3000',
    'http://localhost:5500',
    'http://127.0.0.1',
    'http://127.0.0.1:5500',
];

// ── CORS middleware ──────────────────────────────────────────────────────────
// Must be registered BEFORE all routes so preflight OPTIONS is handled.
app.use((req, res, next) => {
    const origin = req.headers.origin;

    // Allow any listed origin, or any Railway/HostGator subdomain
    const allowed =
        ALLOWED_ORIGINS.includes(origin) ||
        (origin && (
            origin.endsWith('.humaital.com') ||
            origin.endsWith('.humanalignmentindex.com') ||
            origin.endsWith('.railway.app') ||
            origin.endsWith('.hostgator.com')
        ));

    if (allowed) {
        res.setHeader('Access-Control-Allow-Origin',  origin);
        res.setHeader('Vary', 'Origin');
    } else {
        // Permit requests with no Origin header (server-to-server, health checks)
        res.setHeader('Access-Control-Allow-Origin', '*');
    }

    res.setHeader('Access-Control-Allow-Methods',  'GET, POST, PATCH, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers',  'Content-Type, Authorization, X-Requested-With');
    res.setHeader('Access-Control-Max-Age',        '86400');   // cache preflight 24h
    res.setHeader('Access-Control-Allow-Credentials', 'false');

    // Respond immediately to preflight OPTIONS — do not forward to route handlers
    if (req.method === 'OPTIONS') {
        return res.sendStatus(204);
    }

    next();
});

// ── Body parsers ─────────────────────────────────────────────────────────────
// urlencoded: parses application/x-www-form-urlencoded (what bundle.js sends)
// json: parses application/json (used by log-patch and future endpoints)
app.use(express.urlencoded({ extended: true, limit: '2mb' }));
app.use(express.json({ limit: '2mb' }));

// ── Optional secret token guard ──────────────────────────────────────────────
// When HAI_SECRET is set as a Railway environment variable, every request to
// /evaluate, /benchmark, and /log must include it as the X-HAI-Secret header.
// The WordPress proxy snippet sends this header; the browser never sees the value.
// Leave HAI_SECRET unset to disable this check during development.
const HAI_SECRET = process.env.HAI_SECRET || null;

function secretGuard(req, res, next) {
    if (!HAI_SECRET) return next();  // not configured — open access
    const provided = req.headers['x-hai-secret'] || req.body['hai_secret'] || '';
    if (provided === HAI_SECRET) return next();
    console.warn(`[HAI] Secret mismatch from ${req.headers.origin || 'unknown'}`);
    return res.status(403).json({ success: false, data: 'Forbidden.' });
}

// ── Routes ───────────────────────────────────────────────────────────────────
const evaluateRoute    = require('./src/routes/evaluate');
const benchmarkRoute   = require('./src/routes/benchmark');
const sendReportRoute  = require('./src/routes/send-report');
const logPatchRoute    = require('./src/routes/log-patch');
const healthRoute      = require('./src/routes/health');

app.use('/evaluate',    secretGuard, evaluateRoute);
app.use('/benchmark',   secretGuard, benchmarkRoute);
app.use('/send-report', sendReportRoute);
app.use('/log',         secretGuard, logPatchRoute);
app.use('/health',      healthRoute);

// ── Warmup endpoint ──────────────────────────────────────────────────────────
// Called by bundle.js before the main evaluate request to wake Railway
// out of its cold-start sleep. Returns immediately with no processing.
app.get('/warmup', (req, res) => {
    res.json({ ok: true, ts: Date.now() });
});

// ── 404 fallback ─────────────────────────────────────────────────────────────
app.use((req, res) => {
    res.status(404).json({ success: false, data: 'Endpoint not found.' });
});

// ── Global error handler ──────────────────────────────────────────────────────
app.use((err, req, res, _next) => {
    console.error('[HAI] Unhandled express error:', err);
    res.status(500).json({ success: false, data: 'An unexpected server error occurred.' });
});

// ── Start ────────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
    console.log(`[HAI] Server running on port ${PORT}`);
    console.log(`[HAI] Allowed origins: ${ALLOWED_ORIGINS.join(', ')}`);
});

module.exports = app;
