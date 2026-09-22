// api/subscribe.js
// Vercel serverless function: appends a submitted email to recipients.txt
// via the GitHub Contents API, so notify.py's existing pipeline picks it
// up with zero changes on its end.

const GITHUB_API = 'https://api.github.com';

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { email } = req.body || {};
  if (!email || typeof email !== 'string' || !isValidEmail(email)) {
    return res.status(400).json({ error: 'Please provide a valid email address.' });
  }
  const cleanEmail = email.trim().toLowerCase();

  const {
    GITHUB_TOKEN,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_BRANCH,
    RECIPIENTS_PATH,
  } = process.env;

  if (!GITHUB_TOKEN || !GITHUB_OWNER || !GITHUB_REPO) {
    console.error('Missing required environment variables (GITHUB_TOKEN / GITHUB_OWNER / GITHUB_REPO)');
    return res.status(500).json({ error: 'Server misconfigured.' });
  }

  const branch = GITHUB_BRANCH || 'main';
  const path = RECIPIENTS_PATH || 'recipients.txt';
  const baseFileUrl = `${GITHUB_API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${path}`;

  try {
    // 1. Fetch the current file (need its sha + content to update it)
    const getRes = await fetch(`${baseFileUrl}?ref=${branch}`, {
      headers: {
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
      },
    });

    if (!getRes.ok) {
      const errBody = await getRes.text();
      console.error('GitHub GET failed', getRes.status, errBody);
      return res.status(502).json({ error: 'Could not reach the recipients list.' });
    }

    const fileData = await getRes.json();
    const currentContent = Buffer.from(fileData.content, 'base64').toString('utf-8');

    // 2. Check for duplicates (ignore comment lines and blanks, same as notify.py would)
    const existingEmails = currentContent
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
      .map((l) => l.toLowerCase());

    if (existingEmails.includes(cleanEmail)) {
      return res.status(200).json({ status: 'already_subscribed' });
    }

    // 3. Append the new email on its own line, preserving the header/comments
    const newContent = currentContent.replace(/\n?$/, '') + `\n${cleanEmail}\n`;
    const newContentEncoded = Buffer.from(newContent, 'utf-8').toString('base64');

    // 4. Commit the update back to GitHub
    const putRes = await fetch(baseFileUrl, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: 'chore: add subscriber via site form',
        content: newContentEncoded,
        sha: fileData.sha,
        branch,
      }),
    });

    if (!putRes.ok) {
      const errBody = await putRes.text();
      console.error('GitHub PUT failed', putRes.status, errBody);
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
