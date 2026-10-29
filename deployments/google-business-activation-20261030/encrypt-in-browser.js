/* Run in the trusted credential-creation session only. Returns ciphertext only.
 * Do not log arguments or persist the client secret. No network is performed.
 */
async function encryptGoogleClient(context, clientId, clientSecret) {
  if (context.project_id !== 't24-beauty-os-20260823' || context.project_number !== '58950527996' ||
      context.callback !== 'https://t24-crm.com/api/v1/google-business/oauth/callback' ||
      context.algorithm !== 'RSA-OAEP-SHA256-3072' || !/^[a-f0-9]{32}$/.test(context.transfer_id) ||
      Date.now() / 1000 >= context.expires_at) throw new Error('TRANSFER_CONTEXT_REJECTED');
  if (!/^58950527996-[A-Za-z0-9_-]{10,140}\.apps\.googleusercontent\.com$/.test(clientId) ||
      !/^[A-Za-z0-9_-]{16,128}$/.test(clientSecret)) throw new Error('CLIENT_FORMAT_REJECTED');
  const unbase64 = value => Uint8Array.from(atob(value), character => character.charCodeAt(0));
  const spki = unbase64(context.public_pem.replace(/-----[^-]+-----|\s/g, ''));
  const pemHash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(context.public_pem))), byte => byte.toString(16).padStart(2, '0')).join('');
  if (pemHash !== context.public_sha256) throw new Error('PUBLIC_KEY_HASH_DRIFT');
  const expectedLabel = 'T24_CRM_GOOGLE_OAUTH_TRANSFER_V1\niZj6c4cj7edgnhdimts4l7Z\nt24-beauty-os-20260823\n58950527996\n/api/v1/google-business/oauth/callback\n' + context.transfer_id + '\n' + pemHash + '\n' + context.expires_at;
  const label = unbase64(context.oaep_label_base64);
  if (new TextDecoder().decode(label) !== expectedLabel) throw new Error('TRANSFER_LABEL_DRIFT');
  const clear = new TextEncoder().encode(JSON.stringify({client_id: clientId, client_secret: clientSecret}));
  if (clear.length > 318) throw new Error('PAYLOAD_SIZE_REJECTED');
  const key = await crypto.subtle.importKey('spki', spki, {name: 'RSA-OAEP', hash: 'SHA-256'}, false, ['encrypt']);
  const sealed = new Uint8Array(await crypto.subtle.encrypt({name: 'RSA-OAEP', label}, key, clear));
  clear.fill(0);
  return btoa(String.fromCharCode(...sealed));
}
