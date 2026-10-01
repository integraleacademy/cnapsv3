import { checkPresentation } from './document-check-rules.mjs';

// One modal per page, including when several recto/verso files are queued.
const instances = new WeakMap();
export function documentCheckModal(root) {
  if (instances.has(root)) return instances.get(root);
  const dialog = root.querySelector('.document-analysis-modal');
  const jobs = new Map();
  let dismissed = false;
  let active;
  let returnFocus;
  const close = () => {
    if (!dialog?.open) return;
    dialog.close();
    if (returnFocus?.isConnected) {
      const row = returnFocus.closest('[data-document-row]');
      const target = row && !row.open ? row.querySelector('summary') : returnFocus;
      target?.focus({ preventScroll: true });
    }
  };
  const dismiss = () => { dismissed = true; close(); };
  dialog?.querySelectorAll('[data-analysis-dismiss]').forEach(button => button.addEventListener('click', dismiss));
  dialog?.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
  const paint = () => {
    if (!dialog || !jobs.size) return;
    const job = jobs.get(active) || jobs.values().next().value;
    const presentation = checkPresentation[job.kind];
    dialog.querySelector('[data-analysis-label]').textContent = presentation.label;
    dialog.querySelector('[data-analysis-filename]').textContent = job.file.name;
    dialog.querySelector('[data-analysis-steps]').replaceChildren(...presentation.steps.map(text => {
      const item = dialog.ownerDocument.createElement('li'); item.textContent = text; return item;
    }));
    dialog.querySelector('[data-analysis-wait]').textContent = jobs.size > 1
      ? `${jobs.size} fichiers à vérifier. Chaque fichier sera analysé à son tour.`
      : 'Cela peut prendre quelques instants.';
  };
  const api = {
    begin(input, file, kind, signal) {
      const id = Symbol();
      if (!jobs.size) { dismissed = false; returnFocus = input; }
      jobs.set(id, { file, kind });
      paint();
      if (dialog && !dialog.open && !dismissed && typeof dialog.showModal === 'function') dialog.showModal();
      const finish = () => {
        signal?.removeEventListener('abort', finish);
        if (!jobs.delete(id)) return;
        if (active === id) active = undefined;
        if (jobs.size) paint(); else close();
      };
      signal?.addEventListener('abort', finish, { once: true });
      return { finish, start: () => { if (jobs.has(id)) { active = id; paint(); } } };
    },
  };
  instances.set(root, api);
  return api;
}
