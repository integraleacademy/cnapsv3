// Advisory rules only: never change a document's administrative review status.
const MONTHS = {
  janvier: 1, janv: 1, fevrier: 2, fevr: 2, mars: 3, avril: 4, avr: 4,
  mai: 5, juin: 6, juillet: 7, juil: 7, aout: 8, septembre: 9, sept: 9,
  octobre: 10, oct: 10, novembre: 11, nov: 11, decembre: 12, dec: 12,
};

export function normalizeText(text) {
  return String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[’‘]/g, "'").replace(/\u00a0/g, ' ');
}

function isoDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.toISOString().slice(0, 10);
}

export function threeMonthsBefore(today) {
  const [year, month, day] = today.split('-').map(Number);
  const start = new Date(Date.UTC(year, month - 4, 1));
  const lastDay = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0)).getUTCDate();
  return isoDate(start.getUTCFullYear(), start.getUTCMonth() + 1, Math.min(day, lastDay));
}

export function displayDate(iso) {
  return iso.split('-').reverse().join('/');
}

export function fileKey(file) {
  return `${file.name}__${file.size}__${file.lastModified}`;
}

function lastMatchIndex(pattern, text, end = false) {
  let index = -1;
  for (const match of text.matchAll(pattern)) index = match.index + (end ? match[0].length : 0);
  return index;
}

export function findIssueDates(text) {
  const normalized = normalizeText(text);
  const candidates = [];
  const patterns = [
    { re: /\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b/g, parse: m => [+m[1], +m[2], +m[3]] },
    { re: /\b(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4}|\d{2})\b/g, parse: m => [m[3].length === 2 ? 2000 + +m[3] : +m[3], +m[2], +m[1]] },
    { re: new RegExp(`\\b(\\d{1,2})(?:er)?\\s+(${Object.keys(MONTHS).join('|')})\\.?\\s+(\\d{4})\\b`, 'g'), parse: m => [+m[3], MONTHS[m[2]], +m[1]] },
  ];
  for (const { re, parse } of patterns) {
    for (const match of normalized.matchAll(re)) {
      const date = isoDate(...parse(match));
      if (!date) continue;
      const before = normalized.slice(Math.max(0, match.index - 120), match.index);
      // Use the nearest date label. Due dates, payment dates and consumption
      // periods must never make an old invoice look recent.
      const positive = lastMatchIndex(/(?:date\s+(?:de\s+|d'\s*)?(?:facture|facturation|emission|edition|delivrance|etablissement)|(?:facture|quittance)[\s\S]{0,55}?\b(?:du|en date du)\b|(?:emis(?:e)?|edite(?:e)?|etabli(?:e)?|delivre(?:e)?)\s+le)/g, before);
      const negative = lastMatchIndex(/(?:echeance|prelevement|paiement|regler|payer|consommation|periode|contrat|naissance|prochaine\s+facture|prochain\s+releve|validite)/g, before, true);
      const hasRange = /^\s*(?:au|a|[-–])\s*\d/.test(normalized.slice(match.index + match[0].length));
      if (positive >= 0 && positive > negative && !hasRange) candidates.push({ date, index: match.index });
    }
  }
  return [...new Map(candidates.map(item => [item.date, item])).values()];
}

export function assessAddressDate(text, today, { confidence = 100 } = {}) {
  const unknown = {
    status: 'unknown',
    message: "Je n'ai pas pu identifier avec certitude la date d'émission de votre justificatif. Vérifiez qu'il date de moins de 3 mois. Vous pouvez conserver ce fichier et poursuivre.",
  };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(today) || confidence < 60) return unknown;
  const dates = findIssueDates(text);
  if (!dates.length) return unknown;
  const threshold = threeMonthsBefore(today);
  const recent = dates.filter(item => item.date > threshold && item.date <= today);
  const old = dates.filter(item => item.date <= threshold);
  const future = dates.filter(item => item.date > today);
  if (future.length || (recent.length && old.length)) {
    return { status: 'unknown', message: "Plusieurs dates ou une date future ont été repérées : je ne peux pas confirmer l'ancienneté du justificatif. Vérifiez sa date d'émission. Vous pouvez poursuivre." };
  }
  const date = dates.map(item => item.date).sort().at(-1);
  if (old.length) {
    return { status: 'warning', date,
      message: `Votre justificatif de domicile semble dater de 3 mois ou plus (date d'émission repérée : ${displayDate(date)}). Souhaitez-vous le remplacer par un document plus récent ?` };
  }
  return { status: 'info', date,
    message: `Date d'émission repérée : ${displayDate(date)}. Votre justificatif semble dater de moins de 3 mois. Cette vérification reste indicative.` };
}

export function assessIdentityReadability(pages, { partial = false } = {}) {
  if (!pages.length) return { status: 'unknown', message: "Je n'ai pas pu vérifier la lisibilité de votre pièce d'identité. Vérifiez que toutes les informations sont nettes et lisibles. Vous pouvez poursuivre." };
  const scores = pages.map(page => {
    const text = normalizeText(page.text).replace(/[^a-z0-9 ]/g, ' ');
    return { confidence: Number(page.confidence) || 0, characters: text.replace(/\s/g, '').length,
      words: text.split(/\s+/).filter(word => word.length >= 2).length };
  });
  const weak = scores.some(score => score.confidence < 55 || score.characters < 25 || score.words < 4);
  if (weak) return { status: 'warning', message: "Votre pièce d'identité ne semble pas suffisamment lisible sur au moins une page. Souhaitez-vous la remplacer par un scan plus net ? Vérifiez aussi que le document est entier, sans reflet, avec le recto et le verso si nécessaire." };
  if (partial || scores.some(score => score.confidence < 70 || score.characters < 45 || score.words < 8)) {
    return { status: 'unknown', message: "La lisibilité n'a pu être vérifiée que partiellement. Vérifiez que toutes les informations sont nettes et que le document est entier. Vous pouvez conserver ce fichier et poursuivre." };
  }
  return { status: 'info', message: "Les informations contrôlées sur votre pièce d'identité semblent lisibles. Vérifiez aussi le cadrage et le recto/verso. La validation finale sera effectuée par notre équipe." };
}
