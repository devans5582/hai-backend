'use strict';

const { Router } = require('express');
const router = Router();

// GET /health
// Returns a simple liveness check.
// Used by deployment platforms for health probes and by the frontend
// (future) to warm the service on page load and avoid cold-start delays.
router.get('/', (req, res) => {
    res.status(200).json({
        status:  'ok',
        service: 'hai-backend',
        ts:      new Date().toISOString()
    });
});

module.exports = router;
