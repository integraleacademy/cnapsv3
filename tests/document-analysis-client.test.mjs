import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzeDocument } from '../static/document-analysis.mjs';
import { unavailableMessage } from '../static/document-check-rules.mjs';

const file = () => new File(['%PDF-1.4 specimen'], 'specimen.pdf', { type: 'application/pdf' });

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
  assert.equal(unavailableMessage('host_identity'), unavailableMessage('identity'));
});
