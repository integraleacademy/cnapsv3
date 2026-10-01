import { analyzeDocument } from './document-analysis.mjs';
import { unavailableMessage, checkPresentation } from './document-check-rules.mjs';
import { documentCheckModal } from './document-check-modal.mjs?v=accordion-3';
import { replacementButton, attachOtherFileActions } from './document-file-actions.mjs';
import { identityCompleteness, identityEvidenceLabel } from './identity-completeness.mjs';
import { attachDocumentUploadLayout, setDocumentRowResult } from './document-upload-layout.mjs?v=accordion-3';

function button(label, action, secondary = false) {
  const element = document.createElement('button');
  element.type = 'button';
  element.className = secondary ? 'document-check-button secondary' : 'document-check-button';
  element.textContent = label;
  element.addEventListener('click', action);
  return element;
}

function cardFor(input, file, kind) {
  const compact = Boolean(input.closest('[data-document-row]'));
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
  const faces = document.createElement('p');
  faces.className = 'document-check-evidence';
  faces.hidden = true;
  const critical = document.createElement('p');
  critical.className = 'document-check-critical';
  critical.hidden = true;
  const actions = document.createElement('div');
  actions.className = 'document-check-actions';
  actions.append(replacementButton(input, file));
  const reminder = document.createElement('p');
  reminder.className = 'document-check-note';
  reminder.textContent = "Vérification indicative. Notre équipe effectuera le contrôle final.";
  card.append(heading, name, faces, message, critical);
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
      card.querySelector('input[name="document_analysis_receipts"]')?.remove();
      if (typeof result.receipt === 'string') {
        const receipt = document.createElement('input');
        receipt.type = 'hidden';
        receipt.name = 'document_analysis_receipts';
        receipt.value = result.receipt;
        card.append(receipt);
      }
      card.setAttribute('aria-busy', 'false');
      card.className = `document-check document-check--${result.status}`;
      icon.textContent = result.status === 'success' ? '✓' : result.status === 'warning' ? '!' : 'i';
      title.textContent = result.title || (result.status === 'warning' ? 'Document à vérifier' : result.status === 'success' ? 'Vérification réussie' : 'À vérifier par vos soins');
      message.textContent = result.message;
      message.hidden = !result.message || (compact && result.status === 'success');
      heading.hidden = compact && ['identity', 'host_identity'].includes(kind) && result.status === 'success';
      if (['identity', 'host_identity'].includes(kind) && result.status === 'success') {
        faces.textContent = identityEvidenceLabel(result);
        faces.hidden = compact;
      }
      reminder.hidden = compact || (kind === 'identity_photo' && result.status === 'success');
      critical.textContent = result.critical || '';
      critical.hidden = !result.critical;
      actions.replaceChildren(replacementButton(input, file));
      if (['warning', 'unknown'].includes(result.status)) {
        reminder.textContent = "Vous pouvez conserver ce fichier et poursuivre. Notre équipe effectuera le contrôle final.";
        const keep = button('Conserver ce fichier', () => {
            keep.remove();
            reminder.textContent = 'Fichier conservé. Vous pouvez poursuivre ; notre équipe effectuera le contrôle final.';
          }, true);
        actions.append(keep);
      }
    },
  };
}

export function attachDocumentChecks(root = document, analyze = analyzeDocument) {
  const modal = documentCheckModal(root);
  attachDocumentUploadLayout(root);
  attachOtherFileActions(root);
  const identityGroups = new Map();
  const identityState = new Map();
  const refreshIdentity = (input, kind) => {
    const key = `${kind}:${Array.from(root.querySelectorAll('form')).indexOf(input.form)}`;
    let group = identityGroups.get(key);
    if (!group) {
      const element = document.createElement('div');
      element.className = 'identity-completeness';
      element.setAttribute('role', 'status');
      element.setAttribute('aria-live', 'polite');
      input.before(element);
      group = { element, form: input.form, kind };
      identityGroups.set(key, group);
    }
    const results = Array.from(identityState.values()).filter(state => state.input.form === group.form && state.kind === kind).flatMap(state => state.results);
    const result = identityCompleteness(results, { partial: input.form?.dataset.identityPartial === 'true' });
    for (const state of identityState.values()) {
      if (state.input.form === group.form && state.kind === kind) setDocumentRowResult(state.input, result);
    }
    group.element.replaceChildren();
    group.element.hidden = !result;
    if (!result) return;
    const compact = Boolean(input.closest('[data-document-row]'));
    if (compact && (result.status === 'pending' || (!result.missing && results.some(item => item?.status !== 'success')))) group.element.hidden = true;
    group.element.className = `identity-completeness document-check document-check--${result.status}`;
    const title = document.createElement('strong'); title.textContent = result.title;
    const message = document.createElement('p'); message.textContent = result.message;
    message.hidden = compact && result.status === 'success';
    group.element.append(title, message);
    if (result.missing && input.multiple && !compact) group.element.append(button(`Ajouter le ${result.missing}`, () => {
      delete input.dataset.replaceFileKey;
      input.click();
    }));
  };
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
      const identity = ['identity', 'host_identity'].includes(kind);
      const state = { input, kind, results: files.map(() => null) };
      if (identity) { identityState.set(input, state); refreshIdentity(input, kind); }
      const record = (index, result) => {
        if (identity) { state.results[index] = result; refreshIdentity(input, kind); }
        else setDocumentRowResult(input, result);
      };
      for (const [index, file] of files.entries()) {
        const card = cardFor(input, file, kind);
        output.append(card.element);
        if (cache.has(file)) { card.result(cache.get(file)); record(index, cache.get(file)); continue; }
        card.pending(kind);
        const job = modal.begin(input, file, kind, signal);
        // No submit handler, required field or custom validity is added here.
        // Even an unavailable analysis service must leave the form usable.
        Promise.resolve().then(() => analyze(file, kind, today, { signal, token: input.form?.dataset.checkToken, onStart: job.start })).then(result => {
          if (current !== revision || signal.aborted) return;
          cache.set(file, result);
          card.result(result);
          record(index, result);
        }).catch(() => {
          if (current !== revision || signal.aborted) return;
          const result = { status: 'unknown', message: unavailableMessage(kind) };
          card.result(result);
          record(index, result);
        }).finally(job.finish);
      }
    });
  });
}

if (typeof document !== 'undefined') attachDocumentChecks();
