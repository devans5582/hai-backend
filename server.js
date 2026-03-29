'use strict';

// Load .env in local development only.
if (process.env.NODE_ENV !== 'production') {
    try {
        require('fs').accessSync('.env');
        require('child_process').execSync('node -e "require(\'dotenv\').config()"', { stdio: 'ignore' });
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
    } catch (_) {}
}

const express = require('express');
const cors    = require('cors');

const healthRouter     = require('./src/routes/health');
const evaluateRouter   = require('./src/routes/evaluate');
const benchmarkRouter  = require('./src/routes/benchmark');
const sendReportRouter = require('./src/routes/send-report');

const app  = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.urlencoded({ extended: false }));
app.use(express.json());

// Routes
app.use('/health',      healthRouter);
app.use('/evaluate',    evaluateRouter);
app.use('/benchmark',   benchmarkRouter);
app.use('/send-report', sendReportRouter);

// NEW PATCH ROUTE
app.use('/log', require('./src/routes/log-patch'));

// Catch-all
app.use((req, res) => {
    res.status(404).json({ success: false, data: 'Route not found.' });
});

// Error handler
app.use((err, req, res, next) => {
    console.error('[server] Unhandled error:', err.message || err);
    res.status(500).json({ success: false, data: 'Internal server error.' });
});

// Start server
app.listen(PORT, () => {
    console.log(`[server] HAI backend running on port ${PORT}`);

    if (!process.env.OPENAI_API_KEY) {
        console.warn('[server] WARNING: OPENAI_API_KEY not set.');
    }
    if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
        console.warn('[server] WARNING: SUPABASE vars not set.');
    }
    if (!process.env.SMTP_HOST || !process.env.SMTP_USER || !process.env.SMTP_PASS) {
        console.warn('[server] WARNING: SMTP not set.');
    }
});

module.exports = app;
