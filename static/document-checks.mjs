import { analyzeDocument } from './document-analysis.mjs';
import { fileKey, unavailableMessage, checkPresentation } from './document-check-rules.mjs';
import { documentCheckModal } from './document-check-modal.mjs';

function button(label, action, secondary = false) {
  const element = document.createElement('button');
  element.type = 'button';
  element.className = secondary ? 'document-check-button secondary' : 'document-check-button';
  element.textContent = label;
  element.addEventListener('click', action);
  return element;
}

function cardFor(input, file, kind) {
  const card = document.createElement('div');
  card.className = 'document-check document-check--pending';
  const name = document.createElement('strong');
  name.textContent = file.name;
  name.className = 'document-check-filename';
  const heading = document.createElement('div');
  heading.className = 'document-check-heading';
  const icon = document.createElement('span');
  icon.className = 'document-check-icon';
  icon.setAttribute('aria-hidden', 'true');
  const title = document.createElement('strong');
  heading.append(icon, title);
  const message = document.createElement('p');
  const critical = document.createElement('p');
  critical.className = 'document-check-critical';
  critical.hidden = true;
  const actions = document.createElement('div');
  actions.className = 'document-check-actions';
  const reminder = document.createElement('p');
  reminder.className = 'document-check-note';
  reminder.textContent = "Vérification indicative. Notre équipe effectuera le contrôle final.";
  card.append(heading, name, message, critical);
  if (kind === 'hosting_certificate') {
    const signatureReminder = document.createElement('p');
    signatureReminder.className = 'document-check-signature';
    signatureReminder.textContent = "Avez-vous vérifié que l'attestation d'hébergement est bien signée par la personne qui vous héberge ?";
    card.append(signatureReminder);
  }
  card.append(actions, reminder);
  return {
    element: card,
    pending(kind) {
      card.setAttribute('aria-busy', 'true');
      title.textContent = 'Vérification en cours';
      message.textContent = checkPresentation[kind].pending;
    },
    result(result) {
      card.setAttribute('aria-busy', 'false');
      card.className = `document-check document-check--${result.status}`;
      icon.textContent = result.status === 'success' ? '✓' : result.status === 'warning' ? '!' : 'i';
      title.textContent = result.title || (result.status === 'warning' ? 'Document à vérifier' : result.status === 'success' ? 'Vérification réussie' : 'À vérifier par vos soins');
      message.textContent = result.message;
      critical.textContent = result.critical || '';
      critical.hidden = !result.critical;
      actions.replaceChildren();
      if (['warning', 'unknown'].includes(result.status)) {
        reminder.textContent = "Vous pouvez conserver ce fichier et poursuivre. Notre équipe effectuera le contrôle final.";
        actions.append(
          button('Remplacer ce fichier', () => {
            // The public form adds recto/verso files cumulatively. It uses this
            // key to replace just this file after a new selection, not on cancel.
            input.dataset.replaceFileKey = fileKey(file);
            input.click();
          }),
          button('Conserver ce fichier', () => {
            actions.replaceChildren();
            reminder.textContent = 'Fichier conservé. Vous pouvez poursuivre ; notre équipe effectuera le contrôle final.';
          }, true),
        );
      }
    },
  };
}

export function attachDocumentChecks(root = document, analyze = analyzeDocument) {
  const modal = documentCheckModal(root);
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
        const card = cardFor(input, file, kind);
        output.append(card.element);
        if (cache.has(file)) { card.result(cache.get(file)); continue; }
        card.pending(kind);
        const job = modal.begin(input, file, kind, signal);
        // No submit handler, required field or custom validity is added here.
        // Even an unavailable analysis service must leave the form usable.
        Promise.resolve().then(() => analyze(file, kind, today, { signal, token: input.form?.dataset.checkToken, onStart: job.start })).then(result => {
          if (current !== revision || signal.aborted) return;
          cache.set(file, result);
          card.result(result);
        }).catch(() => {
          if (current !== revision || signal.aborted) return;
          card.result({ status: 'unknown', message: unavailableMessage(kind) });
        }).finally(job.finish);
      }
    });
  });
}

if (typeof document !== 'undefined') attachDocumentChecks();
