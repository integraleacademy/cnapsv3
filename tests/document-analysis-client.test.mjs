import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzeDocument } from '../static/document-analysis.mjs';
import { unavailableMessage } from '../static/document-check-rules.mjs';

const file = () => new File(['%PDF-1.4 specimen'], 'specimen.pdf', { type: 'application/pdf' });

test('a signed unsuccessful attempt survives a rate limit for persistence at deposit', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, json: async () => ({
    status: 'unknown', message: 'Limite temporaire atteinte', receipt: 'signed-server-receipt',
  }) });
  try {
    const result = await analyzeDocument(file(), 'proof_address', '', { token: 'token' });
    assert.equal(result.receipt, 'signed-server-receipt');
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ status: 'unknown', message: 'Unauthorized' }) });
    await assert.rejects(analyzeDocument(file(), 'proof_address', '', { token: 'token' }));
  } finally { globalThis.fetch = previous; }
});

test('analysis sends the document only to the same-origin endpoint with the form token', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/document-analysis');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.headers['X-Document-Check-Token'], 'session-token');
    assert.equal(options.body.get('kind'), 'proof_address');
    assert.equal(options.body.get('document').name, 'specimen.pdf');
    return { ok: true, json: async () => ({ status: 'warning', message: 'Document ancien' }) };
  };
  try {
    assert.equal((await analyzeDocument(file(), 'proof_address', '', { token: 'session-token' })).status, 'warning');
  } finally { globalThis.fetch = previous; }
});

test('network errors do not break the next analysis; cancellation prevents uploads', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    if (++calls === 1) throw new Error('offline');
    return { ok: true, json: async () => ({ status: 'unknown', message: 'À vérifier' }) };
  };
  try {
    await assert.rejects(analyzeDocument(file(), 'identity', '', { token: 'token' }));
    assert.equal((await analyzeDocument(file(), 'identity', '', { token: 'token' })).status, 'unknown');
    const controller = new AbortController(); controller.abort();
    await assert.rejects(analyzeDocument(file(), 'identity', '', { token: 'token', signal: controller.signal }), { name: 'AbortError' });
    assert.equal(calls, 2);
  } finally { globalThis.fetch = previous; }
});

test('unavailable checks use the requested document-specific instructions', () => {
  assert.equal(unavailableMessage('proof_address'), "La vérification automatique n'a pas pu aboutir. Veuillez vérifier que votre justificatif de domicile a moins de 3 mois.");
  assert.equal(unavailableMessage('identity'), "La vérification automatique n'a pas pu aboutir. Veuillez vérifier que votre pièce d’identité est bien lisible.");
  assert.match(unavailableMessage('host_identity'), /personne qui vous héberge/);
  assert.match(unavailableMessage('hosting_certificate'), /bien signée/);
  assert.match(unavailableMessage('identity_photo'), /tous les critères/);
});

test('JPEG and PNG photos reach analysis and accept a green success result', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  let started = 0;
  globalThis.fetch = async (_url, options) => {
    calls++;
    assert.equal(options.body.get('kind'), 'identity_photo');
    return { ok: true, json: async () => ({ status: 'success', title: 'Critères vérifiés', message: 'Photo nette' }) };
  };
  try {
    for (const name of ['photo.jpg', 'photo.PNG']) {
      const answer = await analyzeDocument(new File(['pixels'], name), 'identity_photo', '', { token: 'token', onStart: () => started++ });
      assert.equal(answer.status, 'success');
    }
    await assert.rejects(analyzeDocument(file(), 'identity_photo', '', { token: 'token' }));
    await assert.rejects(analyzeDocument(new File(['pixels'], 'photo.png'), 'identity', '', { token: 'token' }));
    assert.equal(calls, 2);
    assert.equal(started, 2);
  } finally { globalThis.fetch = previous; }
});
