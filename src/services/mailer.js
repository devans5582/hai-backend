'use strict';

const nodemailer = require('nodemailer');

// ---------------------------------------------------------------
// SMTP transport
//
// Supports both HostGator configurations:
//   port 587 — STARTTLS (secure: false, starttls upgrades the connection)
//   port 465 — implicit SSL (secure: true)
//
// The correct setting is derived automatically from SMTP_PORT.
// Set SMTP_PORT=587 in Railway env vars for the default HostGator config.
// ---------------------------------------------------------------

function createTransport() {
    const port   = parseInt(process.env.SMTP_PORT || '587', 10);
    const secure = port === 465; // true = implicit SSL, false = STARTTLS

    return nodemailer.createTransport({
        host:   process.env.SMTP_HOST,
        port,
        secure,
        auth: {
            user: process.env.SMTP_USER,
            pass: process.env.SMTP_PASS
        },
        // For port 587 STARTTLS — require the upgrade, don't allow plaintext fallback
        requireTLS: !secure,
        // Connection and greeting timeouts — keeps the request from hanging
        connectionTimeout: 15000,
        greetingTimeout:   10000,
        socketTimeout:     30000
    });
}

// Lazily created — transport is built on first use so startup warnings
// fire correctly even if env vars are missing at module load time.
let _transport = null;
function getTransport() {
    if (!_transport) _transport = createTransport();
    return _transport;
}


// ---------------------------------------------------------------
// Attachment helper
//
// Both emails share the same PDF buffer. nodemailer accepts a
// Buffer directly — no temp file on disk needed.
// ---------------------------------------------------------------
function buildAttachment(pdfBuffer, company) {
    // Sanitise company name for use as a filename
    const safeName = (company || 'Assessment')
        .replace(/[^a-zA-Z0-9\s\-_]/g, '')
        .trim()
        .replace(/\s+/g, '_')
        .slice(0, 60);

    return {
        filename:    `HAI_Assessment_${safeName}.pdf`,
        content:     pdfBuffer,
        contentType: 'application/pdf'
    };
}


// ---------------------------------------------------------------
// sendUserEmail
//
// Sends the HTML report email to the person who ran the assessment.
// Replicates the WordPress wp_mail user email exactly.
// ---------------------------------------------------------------

/**
 * @param {object} params
 * @param {string} params.email
 * @param {string} params.company
 * @param {Buffer} params.pdfBuffer
 */
async function sendUserEmail({ email, company, pdfBuffer }) {
    const from = process.env.SMTP_FROM || `Humaital <${process.env.SMTP_USER}>`;

    const mailOptions = {
        from,
        to:      email,
        subject: `Your Humaital HAI Index Assessment for ${company}`,
        html:    [
            '<h2>Thank you for completing the HAI Index Assessment!</h2>',
            '<p>Your assessment has been generated and is attached to this email as a PDF.</p>',
            '<p>Thank you,<br>The Humaital Team</p>'
        ].join(''),
        attachments: [ buildAttachment(pdfBuffer, company) ]
    };

    await getTransport().sendMail(mailOptions);
    console.log(`[mailer] User email sent — to: ${email}, company: ${company}`);
}


// ---------------------------------------------------------------
// sendAdminEmail
//
// Sends a plain-text notification copy to info@humaital.com.
// Replicates the WordPress admin copy exactly, including Reply-To.
// ---------------------------------------------------------------

/**
 * @param {object} params
 * @param {string} params.email       - user's email (used as Reply-To)
 * @param {string} params.company
 * @param {string} params.url
 * @param {string} params.score
 * @param {string} params.confidence
 * @param {Buffer} params.pdfBuffer
 */
async function sendAdminEmail({ email, company, url, score, confidence, pdfBuffer }) {
    const adminTo   = 'info@humaital.com';
    const adminFrom = `Humaital System <${process.env.SMTP_USER || adminTo}>`;

    const text = [
        `A new HAI assessment was generated for: ${company}`,
        '',
        `User email: ${email}`,
        `Website URL: ${url}`,
        `Score: ${score}`,
        `Confidence: ${confidence}`,
        '',
        'The generated PDF is attached.'
    ].join('\n');

    const mailOptions = {
        from:     adminFrom,
        to:       adminTo,
        replyTo:  email,
        subject:  `New HAI Assessment: ${company}`,
        text,
        attachments: [ buildAttachment(pdfBuffer, company) ]
    };

    await getTransport().sendMail(mailOptions);
    console.log(`[mailer] Admin email sent — company: ${company}`);
}


module.exports = { sendUserEmail, sendAdminEmail };
