import { analyzeDocument } from './document-analysis.mjs';
import { fileKey, unavailableMessage } from './document-check-rules.mjs';

function button(label, action, secondary = false) {
  const element = document.createElement('button');
  element.type = 'button';
  element.className = secondary ? 'document-check-button secondary' : 'document-check-button';
  element.textContent = label;
  element.addEventListener('click', action);
  return element;
}

function cardFor(input, file) {
  const card = document.createElement('div');
  card.className = 'document-check document-check--pending';
  const name = document.createElement('strong');
  name.textContent = file.name;
  const message = document.createElement('p');
  const actions = document.createElement('div');
  actions.className = 'document-check-actions';
  const reminder = document.createElement('p');
  reminder.className = 'document-check-note';
  reminder.textContent = "Ce contrôle ne bloque pas l'envoi de votre demande.";
  card.append(name, message, actions, reminder);
  return {
    element: card,
    pending(kind) {
      card.setAttribute('aria-busy', 'true');
      message.textContent = kind === 'proof_address'
        ? 'Un instant, je vérifie votre justificatif de domicile…'
        : "Un instant, je vérifie la lisibilité de votre pièce d'identité…";
    },
    result(result) {
      card.setAttribute('aria-busy', 'false');
      card.className = `document-check document-check--${result.status}`;
      message.textContent = result.message;
      actions.replaceChildren();
      if (['warning', 'unknown', 'reminder'].includes(result.status)) {
        actions.append(
          button('Remplacer ce fichier', () => {
            // The public form adds recto/verso files cumulatively. It uses this
            // key to replace just this file after a new selection, not on cancel.
            input.dataset.replaceFileKey = fileKey(file);
            input.click();
          }),
          button(result.status === 'reminder' ? 'Oui, elle est bien signée' : 'Conserver ce fichier', () => {
            actions.replaceChildren();
            reminder.textContent = result.status === 'reminder'
              ? "Signature confirmée. Vous pouvez poursuivre."
              : 'Fichier conservé. Vous pouvez poursuivre ; notre équipe effectuera le contrôle final.';
          }, true),
        );
      }
    },
  };
}

export function attachDocumentChecks(root = document, analyze = analyzeDocument) {
  root.querySelectorAll('input[data-document-check]').forEach(input => {
    if (input.dataset.checkAttached) return;
    input.dataset.checkAttached = 'true';
    const output = document.createElement('div');
    output.className = 'document-check-results';
    output.setAttribute('role', 'status');
    output.setAttribute('aria-live', 'polite');
    input.after(output);
    let controller;
    let revision = 0;
    const cache = new WeakMap();

    input.addEventListener('cancel', () => { delete input.dataset.replaceFileKey; });
    input.addEventListener('change', () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      const current = ++revision;
      const kind = input.dataset.documentCheck;
      const today = input.form?.dataset.checkDate;
      output.replaceChildren();
      const files = Array.from(input.files || []);
      for (const file of files) {
        const card = cardFor(input, file);
        output.append(card.element);
        if (kind === 'hosting_certificate') {
          card.result({ status: 'reminder', message: "Avez-vous vérifié que l'attestation d'hébergement est bien signée par la personne qui vous héberge ?" });
          continue;
        }
        if (cache.has(file)) { card.result(cache.get(file)); continue; }
        card.pending(kind);
        // No submit handler, required field or custom validity is added here.
        // Even an unavailable analysis service must leave the form usable.
        Promise.resolve().then(() => analyze(file, kind, today, { signal, token: input.form?.dataset.checkToken })).then(result => {
          if (current !== revision || signal.aborted) return;
          cache.set(file, result);
          card.result(result);
        }).catch(() => {
          if (current !== revision || signal.aborted) return;
          card.result({ status: 'unknown', message: unavailableMessage(kind) });
        });
      }
    });
  });
}

if (typeof document !== 'undefined') attachDocumentChecks();
