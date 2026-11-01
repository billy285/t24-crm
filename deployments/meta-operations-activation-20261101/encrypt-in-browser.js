/* Trusted Meta credential UI only. No network; returns ciphertext only.
 * Never print arguments, raw DOM, clipboard, secret, key or plaintext JSON.
 * Public pins remain closed until the actual USER config has been reviewed.
 */
const APPROVED_APP_ID = '3037236509957803';
const APPROVED_BUSINESS_ID = '1772407487098568';
const APPROVED_CONFIG_ID = '2328579691236435';
const APPROVED_GRAPH_VERSION = 'v26.0';
const APPROVED_CONFIG_FREEZE_SHA = '570dcfb3c372233f1fd115e59dd085247697d530a3b6248ecfb8c3d3fb48c3d4';
const APPROVED_SOURCE_SHA = '95588aa2e630784a419704bb4ce3da89965586e6';
async function encryptMetaPublisherApp(context, appId, appSecret) {
  if (typeof APPROVED_APP_ID !== 'string' || typeof APPROVED_BUSINESS_ID !== 'string' || typeof APPROVED_CONFIG_ID !== 'string' || typeof APPROVED_GRAPH_VERSION !== 'string' ||
      typeof APPROVED_CONFIG_FREEZE_SHA !== 'string' || typeof APPROVED_SOURCE_SHA !== 'string') throw new Error('ACTUAL_REVIEWED_META_PINS_REQUIRED');
  const expected = {
    host: 'iZj6c4cj7edgnhdimts4l7Z', app_id: APPROVED_APP_ID, business_id: APPROVED_BUSINESS_ID,
    config_id: APPROVED_CONFIG_ID, graph_version: APPROVED_GRAPH_VERSION,
    configuration_freeze_sha256: APPROVED_CONFIG_FREEZE_SHA,
    source_sha: APPROVED_SOURCE_SHA,
    callback: 'https://t24-crm.com/api/v1/meta-operations/oauth/callback', token_type: 'USER',
    algorithm: 'RSA-OAEP-SHA256-3072', payload_max_bytes: 318
  };
  if (!context || Object.entries(expected).some(([key,value]) => context[key] !== value) ||
      ['1139445441758834','1625116099132983'].includes(context.app_id) || !/^[0-9]{1,80}$/.test(context.app_id) || !/^[0-9]{1,80}$/.test(context.business_id) ||
      ['1146714154579519','1786801695686024','941072098875174'].includes(context.config_id) || !/^[0-9]{1,80}$/.test(context.config_id) ||
      !/^v[1-9][0-9]{0,2}\.[0-9]{1,2}$/.test(context.graph_version) ||
      !/^[a-f0-9]{64}$/.test(context.configuration_freeze_sha256) ||
      context.configuration_freeze_sha256 === '0'.repeat(64) ||
      JSON.stringify(context.requested_scopes) !== JSON.stringify(['instagram_basic','instagram_content_publish','instagram_manage_comments','pages_manage_engagement','pages_manage_posts','pages_read_engagement','pages_read_user_content','pages_show_list']) ||
      !/^[a-f0-9]{32}$/.test(context.transfer_id) || !Number.isSafeInteger(context.created_at) ||
      !Number.isSafeInteger(context.expires_at) || context.expires_at !== context.created_at + 900 ||
      context.created_at > Date.now()/1000 || Date.now()/1000 >= context.expires_at) throw new Error('META_TRANSFER_CONTEXT_REJECTED');
  if (appId !== expected.app_id || typeof appSecret !== 'string' || !/^[A-Za-z0-9_-]{16,128}$/.test(appSecret))
    throw new Error('META_CREDENTIAL_FORMAT_REJECTED');
  const unbase64 = value => Uint8Array.from(atob(value), character => character.charCodeAt(0));
  if (typeof context.public_pem !== 'string' || context.public_pem.length >= 1024 ||
      !context.public_pem.startsWith('-----BEGIN PUBLIC KEY-----\n') ||
      !context.public_pem.endsWith('-----END PUBLIC KEY-----\n')) throw new Error('META_PUBLIC_KEY_REJECTED');
  const pemHash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(context.public_pem))), byte => byte.toString(16).padStart(2,'0')).join('');
  if (pemHash !== context.public_sha256) throw new Error('META_PUBLIC_KEY_HASH_DRIFT');
  const expectedLabel = ['T24_CRM_SEPARATE_PUBLISHER_TRANSFER_V1',expected.host,expected.app_id,expected.business_id,
    expected.config_id,expected.graph_version,expected.callback,expected.source_sha,expected.configuration_freeze_sha256,
    context.transfer_id,pemHash,String(context.expires_at)].join('\n');
  const label = unbase64(context.oaep_label_base64);
  if (new TextDecoder().decode(label) !== expectedLabel) throw new Error('META_TRANSFER_LABEL_DRIFT');
  const clear = new TextEncoder().encode(JSON.stringify({app_id:appId,app_secret:appSecret}));
  if (clear.length > 318) throw new Error('META_PAYLOAD_SIZE_REJECTED');
  try {
    const spki=unbase64(context.public_pem.replace(/-----[^-]+-----|\s/g,''));
    const key=await crypto.subtle.importKey('spki',spki,{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);
    const sealed=new Uint8Array(await crypto.subtle.encrypt({name:'RSA-OAEP',label},key,clear));
    if (sealed.length !== 384) throw new Error('META_CIPHERTEXT_SIZE_REJECTED');
    return btoa(String.fromCharCode(...sealed));
  } finally { clear.fill(0); }
}
