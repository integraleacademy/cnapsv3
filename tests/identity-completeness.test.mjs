import test from 'node:test';
import assert from 'node:assert/strict';
import { identityCompleteness, identityEvidenceLabel } from '../static/identity-completeness.mjs';

const page = (type, sides, confidence = 'high') => ({type, sides, confidence});
const file = (...evidence) => ({status: 'success', identity_evidence: evidence});
const front = page('identity_card', ['front']);
const back = page('identity_card', ['back']);

test('two sides work within one PDF, one page or two separate files', () => {
  for (const files of [[file(front, back)], [file(page('identity_card', ['front', 'back']))], [file(front), file(back)]]) {
    assert.equal(identityCompleteness(files).status, 'success');
  }
});
test('a passport needs only its biodata page and never asks for a verso', () => {
  const result = identityCompleteness([file(page('passport', ['passport_biodata']))]);
  assert.equal(result.status, 'success');
  assert.match(result.message, /Aucun verso n’est nécessaire/);
  assert.notEqual(identityCompleteness([file(page('passport', []))]).status, 'success');
});
test('a missing side or duplicate front cannot be marked complete', () => {
  assert.equal(identityCompleteness([file(front)]).missing, 'verso');
  assert.equal(identityCompleteness([file(back)]).missing, 'recto');
  assert.equal(identityCompleteness([file(front), file(front)]).status, 'warning');
  assert.equal(identityCompleteness([file(page('residence_permit', ['front']))]).missing, 'verso');
  assert.equal(identityCompleteness([file(page('residence_permit', ['front'])), file(page('residence_permit', ['back']))]).status, 'success');
  assert.notEqual(identityCompleteness([file(front), file(page('residence_permit', ['back']))]).status, 'success');
});
test('a readable but unidentified second page is uncertain, not falsely missing', () => {
  for (const second of [file(page('identity_card', ['back'], 'low')), file(page('uncertain', [])), file()]) {
    const result = identityCompleteness([file(front), second]);
    assert.equal(result.status, 'unknown');
    assert.equal(result.missing, undefined);
  }
  assert.equal(identityEvidenceLabel(file(front, back)), 'Carte d’identité — recto · Carte d’identité — verso');
  assert.equal(identityEvidenceLabel(file(page('passport', ['passport_biodata']))), 'Passeport — page avec photo');
  assert.equal(identityEvidenceLabel(file(page('identity_card', ['back'], 'low'))), 'Faces du document à confirmer');
});
test('uncertainty or unreadable files never become a green overall result', () => {
  for (const files of [[file(front), null], [file(front), {status:'warning'}], [file(front), {status:'unknown'}], [file(front), file(page('identity_card', ['back'], 'low'))]]) {
    assert.notEqual(identityCompleteness(files).status, 'success');
  }
  assert.equal(identityCompleteness([]), null);
  assert.equal(identityCompleteness([file(front)], {partial:true}).status, 'info');
  assert.equal(identityCompleteness([file(front)]).status, 'warning');
});
