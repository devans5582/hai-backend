'use strict';

// Load .env in local development only.
// On Railway/Render, environment variables are set in the platform dashboard.
if (process.env.NODE_ENV !== 'production') {
    try {
        require('fs').accessSync('.env');
        // Only require dotenv if .env file actually exists (local dev)
        require('child_process').execSync('node -e "require(\'dotenv\').config()"', { stdio: 'ignore' });
        // Fallback: manual parse if dotenv isn't installed
        const fs = require('fs');
        const lines = fs.readFileSync('.env', 'utf8').split('\n');
        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith('#')) continue;
            const eq = trimmed.indexOf('=');
            if (eq === -1) continue;
            const key = trimmed.slice(0, eq).trim();
            const val = trimmed.slice(eq + 1).trim();
            if (!process.env[key]) process.env[key] = val;
        }
    } catch (_) {
        // No .env file present — that's fine in production
    }
}

const express = require('express');
const cors    = require('cors');

const healthRouter   = require('./src/routes/health');
const evaluateRouter = require('./src/routes/evaluate');

const app  = express();
const PORT = process.env.PORT || 3000;

// ---------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------

// Open CORS — required because the iframe app (hai.humaital.com)
// is a different origin from this backend service.
// This matches the current WordPress snippet behavior (Access-Control-Allow-Origin: *).
app.use(cors());

// Parse application/x-www-form-urlencoded (what main.js currently sends)
app.use(express.urlencoded({ extended: false }));

// Parse application/json (for future use / local testing)
app.use(express.json());

// ---------------------------------------------------------------
// Routes
// ---------------------------------------------------------------

app.use('/health',   healthRouter);
app.use('/evaluate', evaluateRouter);

// Catch-all for unknown routes — returns a clean JSON 404
app.use((req, res) => {
    res.status(404).json({ success: false, data: 'Route not found.' });
});

// ---------------------------------------------------------------
// Global error handler — catches anything unhandled above
// ---------------------------------------------------------------
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
    console.error('[server] Unhandled error:', err.message || err);
    res.status(500).json({ success: false, data: 'Internal server error.' });
});

// ---------------------------------------------------------------
// Start
// ---------------------------------------------------------------
app.listen(PORT, () => {
    console.log(`[server] HAI backend running on port ${PORT}`);

    // Warn loudly at startup if the required secret is missing.
    // The /evaluate endpoint will return a clean error anyway,
    // but this makes misconfiguration obvious in deployment logs.
    if (!process.env.OPENAI_API_KEY) {
        console.warn('[server] WARNING: OPENAI_API_KEY environment variable is not set. /evaluate will fail.');
    }
});

module.exports = app; // exported for future test use
