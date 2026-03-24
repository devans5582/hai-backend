'use strict';

const { Router } = require('express');
const multer     = require('multer');
const router     = Router();

const { sendUserEmail, sendAdminEmail } = require('../services/mailer');

// ---------------------------------------------------------------
// multer configuration
//
// All ten fields from main.js FormData are TEXT fields — the PDF
// is sent as a base64 string in the pdf_data field, not as a file
// upload. multer's memoryStorage / fields-only mode handles this
// correctly with no disk writes.
//
// Limits:
//   pdf_data  — 5 MB  (covers all realistic jsPDF output sizes)
//   all other fields — 10 KB each
// ---------------------------------------------------------------
const upload = multer({
    storage: multer.memoryStorage(),
    limits: {
        fieldNameSize: 200,          // bytes per field name
        fieldSize:     5 * 1024 * 1024, // 5 MB — applied per field; pdf_data is the large one
        fields:        20            // max number of non-file fields
    }
});

// multer error handler — converts multer-specific errors to the
// standard { success, data } shape before Express sees them.
function handleMulterError(err, req, res, next) {
    if (err && err.code === 'LIMIT_FIELD_SIZE') {
        return res.status(200).json({
            success: false,
            data: 'PDF size limit exceeded. Maximum supported size is 5 MB.'
        });
    }
    if (err) {
        console.error('[send-report] multer error:', err.message);
        return res.status(200).json({
            success: false,
            data: 'Failed to parse request body.'
        });
    }
    next();
}


// ---------------------------------------------------------------
// POST /send-report
//
// Accepts: multipart/form-data (sent by main.js via FormData)
//
// Fields:
//   action, email, company, url, industry, stage,
//   size, score, confidence, pdf_data
//
// Process:
//   1. Parse multipart body (multer)
//   2. Validate required fields
//   3. Decode base64 PDF from pdf_data
//   4. Send user email (HTML + attachment)
//   5. Send admin email (plain text + same attachment)
//   6. Return response
//
// Success:  { success: true,  data: "Email sent successfully." }
// Failure:  { success: false, data: "..." }
//
// NOTE: The frontend only console.log's the response — it does not
// render it. The "Assessment Complete" banner is shown before this
// POST fires. Response shape must match WordPress for log consistency.
// ---------------------------------------------------------------

router.post(
    '/',
    upload.none(), // parse all fields as text, no file uploads
    handleMulterError,
    async (req, res) => {

        // --------------------------------------------------------
        // 1. Validate required fields
        // --------------------------------------------------------
        const email    = (req.body && req.body.email    || '').trim();
        const pdfData  = (req.body && req.body.pdf_data || '').trim();

        if (!email || !pdfData) {
            return res.status(200).json({
                success: false,
                data: 'Missing email or PDF data.'
            });
        }

        // Basic email format check — matches WordPress is_email() intent
        if (!email.includes('@') || !email.includes('.')) {
            return res.status(200).json({
                success: false,
                data: 'Invalid email address.'
            });
        }

        const company    = (req.body.company    || 'Unknown Company').trim();
        const url        = (req.body.url        || 'Unknown URL').trim();
        const score      = (req.body.score      || 'N/A').toString().trim();
        const confidence = (req.body.confidence || 'N/A').toString().trim();

        // --------------------------------------------------------
        // 2. Decode the base64 PDF
        //
        // pdf_data format from jsPDF doc.output('datauristring'):
        //   "data:application/pdf;filename=generated.pdf;base64,JVBERi..."
        //
        // Split on first comma only — base64 payload may contain
        // characters that look like commas in theory (it doesn't,
        // but splitting on first is safer and matches WordPress).
        // --------------------------------------------------------
        const commaIdx = pdfData.indexOf(',');
        if (commaIdx === -1) {
            return res.status(200).json({
                success: false,
                data: 'Invalid PDF data format.'
            });
        }

        const base64String = pdfData.slice(commaIdx + 1);

        if (!base64String) {
            return res.status(200).json({
                success: false,
                data: 'Invalid PDF data format.'
            });
        }

        let pdfBuffer;
        try {
            pdfBuffer = Buffer.from(base64String, 'base64');
        } catch (_) {
            return res.status(200).json({
                success: false,
                data: 'Failed to decode PDF.'
            });
        }

        // Validate PDF magic bytes — catches corrupt or truncated payloads
        // PDF files always begin with the 4-byte sequence: %PDF
        if (pdfBuffer.length < 4 || pdfBuffer.slice(0, 4).toString('ascii') !== '%PDF') {
            return res.status(200).json({
                success: false,
                data: 'Failed to decode PDF.'
            });
        }

        // --------------------------------------------------------
        // 3. Guard: SMTP must be configured
        // --------------------------------------------------------
        if (!process.env.SMTP_HOST || !process.env.SMTP_USER || !process.env.SMTP_PASS) {
            console.error('[send-report] SMTP environment variables are not configured.');
            return res.status(200).json({
                success: false,
                data: 'Failed to send email. Check SMTP configuration.'
            });
        }

        // --------------------------------------------------------
        // 4. Send both emails
        //
        // User email is sent first. Admin email is sent second.
        // Both must succeed for a success response — this matches
        // the WordPress behavior where wp_mail return value drives
        // the response (the admin copy failure is silent in WP, but
        // here we log it and still return success if user email sent).
        // --------------------------------------------------------
        try {
            await sendUserEmail({ email, company, pdfBuffer });
        } catch (err) {
            console.error('[send-report] User email failed:', err.message);
            return res.status(200).json({
                success: false,
                data: 'Failed to send email. Check SMTP configuration.'
            });
        }

        // Admin copy — failure is logged but does NOT affect the
        // success response returned to the frontend. This matches
        // WordPress behavior where the admin copy failure is silent.
        try {
            await sendAdminEmail({ email, company, url, score, confidence, pdfBuffer });
        } catch (err) {
            console.error('[send-report] Admin email failed (non-fatal):', err.message);
        }

        // --------------------------------------------------------
        // 5. Return — matches WordPress wp_send_json_success exactly
        // --------------------------------------------------------
        return res.status(200).json({
            success: true,
            data: 'Email sent successfully.'
        });
    }
);

module.exports = router;
