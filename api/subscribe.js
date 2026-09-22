// api/subscribe.js
// Vercel serverless function: appends a submitted email to a private
// GitHub Gist holding the recipient list. notify.py reads from the same
// Gist, so both stay in sync. CORS-enabled so this works whether the
// form is submitted from the Vercel domain or from GitHub Pages.

const GITHUB_API = 'https://api.github.com';

// Browser origins allowed to call this endpoint.
const ALLOWED_ORIGINS = [
  'https://air-ballers.vercel.app',
  'https://gchrisovelidis.github.io',
];

module.exports = async function handler(req, res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    // Preflight request — browsers send this automatically before
    // a cross-origin POST with a JSON body.
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST, OPTIONS');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { email } = req.body || {};
  if (!email || typeof email !== 'string' || !isValidEmail(email)) {
    return res.status(400).json({ error: 'Please provide a valid email address.' });
  }
  const cleanEmail = email.trim().toLowerCase();

  const { GIST_TOKEN, GIST_ID, RECIPIENTS_FILENAME } = process.env;
  if (!GIST_TOKEN || !GIST_ID) {
    console.error('Missing required environment variables (GIST_TOKEN / GIST_ID)');
    return res.status(500).json({ error: 'Server misconfigured.' });
  }
  const filename = RECIPIENTS_FILENAME || 'recipients.txt';

  try {
    // 1. Fetch the current gist content
    const getRes = await fetch(`${GITHUB_API}/gists/${GIST_ID}`, {
      headers: {
        Authorization: `Bearer ${GIST_TOKEN}`,
        Accept: 'application/vnd.github+json',
      },
    });

    if (!getRes.ok) {
      const errBody = await getRes.text();
      console.error('Gist GET failed', getRes.status, errBody);
      return res.status(502).json({ error: 'Could not reach the recipients list.' });
    }

    const gistData = await getRes.json();
    const file = gistData.files && gistData.files[filename];
    if (!file) {
      console.error(`Gist has no file named "${filename}"`);
      return res.status(500).json({ error: 'Server misconfigured.' });
    }
    const currentContent = file.content;

    // 2. Check for duplicates (ignore comment lines and blanks)
    const existingEmails = currentContent
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
      .map((l) => l.toLowerCase());

    if (existingEmails.includes(cleanEmail)) {
      return res.status(200).json({ status: 'already_subscribed' });
    }

    // 3. Append the new email, preserving header/comments
    const newContent = currentContent.replace(/\n?$/, '') + `\n${cleanEmail}\n`;

    // 4. Save it back to the gist
    const patchRes = await fetch(`${GITHUB_API}/gists/${GIST_ID}`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${GIST_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        files: {
          [filename]: { content: newContent },
        },
      }),
    });

    if (!patchRes.ok) {
      const errBody = await patchRes.text();
      console.error('Gist PATCH failed', patchRes.status, errBody);
      return res.status(502).json({ error: 'Could not save your subscription.' });
    }

    return res.status(200).json({ status: 'subscribed' });
  } catch (err) {
    console.error('Subscribe error:', err);
    return res.status(500).json({ error: 'Unexpected server error.' });
  }
};

function isValidEmail(str) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(str);
}
