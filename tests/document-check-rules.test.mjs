import test from 'node:test';
import assert from 'node:assert/strict';
import { threeMonthsBefore, findIssueDates, assessAddressDate, assessIdentityReadability } from '../static/document-check-rules.mjs';

const today = '2026-10-01';
test('three calendar months, including month ends and leap years', () => {
  assert.equal(threeMonthsBefore(today), '2026-07-01');
  assert.equal(threeMonthsBefore('2026-05-31'), '2026-02-28');
  assert.equal(threeMonthsBefore('2024-05-31'), '2024-02-29');
});

test('old, exactly three months old, and recent issue dates', () => {
  assert.equal(assessAddressDate('Facture du 30/06/2026', today).status, 'warning');
  assert.equal(assessAddressDate('Facture du 01/07/2026', today).status, 'warning');
  assert.equal(assessAddressDate('Facture du 02/07/2026', today).status, 'info');
  assert.equal(assessAddressDate('Facture du 01/10/2026', today).status, 'info');
});

test('French months, ISO, short years, labels and line breaks', () => {
  for (const text of [
    'Facture du 5 septembre 2026', 'Émise le 2026-09-05',
    "Date d’émission :\n05.09.26", 'Facture EDF n° FA123 du 05/09/2026',
    'Quittance de loyer du 05/09/2026', 'Date de facturation : 05/09/2026',
  ]) assert.equal(assessAddressDate(text, today).date, '2026-09-05', text);
});

test('a recent due date or consumption period does not hide an old issue date', () => {
  const text = "Facture du 01/05/2026\nDate d'échéance : 15/09/2026\nPériode de consommation du 01/08/2026 au 31/08/2026\nProchaine facture du 30/10/2026";
  assert.deepEqual(findIssueDates(text).map(item => item.date), ['2026-05-01']);
  assert.equal(assessAddressDate(text, today).status, 'warning');
});

test('old consumption period does not make a recent invoice outdated', () => {
  const text = 'Consommation du 01/01/2026 au 31/01/2026\nDate de facture : 15/09/2026';
  assert.equal(assessAddressDate(text, today).status, 'info');
});

test('missing, invalid, future, ambiguous dates and weak OCR remain uncertain', () => {
  for (const text of [
    '01/09/2026', 'Date de naissance : 01/09/1990', 'Facture du 31/02/2026',
    'Date de paiement : 01/09/2026', 'Facture du 02/10/2026',
    'Facture du 01/06/2026\nFacture du 01/09/2026',
  ]) assert.equal(assessAddressDate(text, today).status, 'unknown', text);
  assert.equal(assessAddressDate('Facture du 01/09/2026', today, { confidence: 40 }).status, 'unknown');
});

const readable = { text: 'SPECIMEN DOCUMENT DE TEST REPUBLIQUE FRANCAISE NOM EXEMPLE PRENOM TEST DATE DE NAISSANCE 01 01 1990 NATIONALITE FRANCAISE', confidence: 91 };
test('readability needs actual recognised text, not high confidence alone', () => {
  assert.equal(assessIdentityReadability([readable]).status, 'info');
  assert.equal(assessIdentityReadability([{ text: '', confidence: 99 }]).status, 'warning');
  assert.equal(assessIdentityReadability([{ ...readable, confidence: 20 }]).status, 'warning');
  assert.equal(assessIdentityReadability([{ ...readable, confidence: 63 }]).status, 'unknown');
});

test('both sides are checked, partial and unavailable checks stay uncertain', () => {
  assert.equal(assessIdentityReadability([readable, { text: '', confidence: 0 }]).status, 'warning');
  assert.equal(assessIdentityReadability([readable], { partial: true }).status, 'unknown');
  assert.equal(assessIdentityReadability([]).status, 'unknown');
});
