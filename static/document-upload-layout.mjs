// The document accordion follows the public trainee portal's presentation.
// A local verification never changes the administrative conformity decision.
export function setDocumentRowResult(input, result) {
  const row = input.closest('[data-document-row]');
  if (!row) return;
  const hasFiles = Boolean(input.files?.length);
  const status = hasFiles ? result?.status || 'selected' : 'empty';
  const label = status === 'empty' ? 'À déposer' : status === 'pending' ? 'Vérification…' :
    status === 'success' ? 'Vérifié' : status === 'warning' ? result?.missing ? 'À compléter' : 'À remplacer' :
      ['unknown', 'info'].includes(status) ? 'À vérifier' : 'Déposé';
  row.dataset.documentState = status;
  row.classList.toggle('missing', status === 'empty');
  row.classList.toggle('valid', ['success', 'selected'].includes(status));
  row.classList.toggle('pending', ['pending', 'warning', 'unknown', 'info'].includes(status));
  row.querySelector('[data-document-status]').textContent = label;
  const add = row.querySelector('[data-add-document]');
  if (add) {
    add.hidden = !hasFiles;
    add.textContent = result?.missing ? `Ajouter le ${result.missing}` : 'Ajouter un fichier';
  }
}

export function attachDocumentUploadLayout(root = document) {
  root.querySelectorAll('form[data-document-layout]').forEach(form => {
    if (form.dataset.layoutAttached) return;
    form.dataset.layoutAttached = 'true';
    const rows = Array.from(form.querySelectorAll('[data-document-row]'));
    const refreshProgress = () => {
      const active = rows.filter(row => row.querySelector('input[type="file"]')?.required && !row.closest('.hidden, [hidden]'));
      const deposited = active.filter(row => row.querySelector('input[type="file"]').files?.length).length;
      const total = active.length;
      const remaining = total - deposited;
      const percent = total ? Math.round(deposited / total * 100) : 0;
      form.querySelectorAll('[data-progress-fill]').forEach(el => { el.style.width = `${percent}%`; });
      form.querySelectorAll('[data-progress-percent]').forEach(el => { el.textContent = `${percent}%`; });
      form.querySelectorAll('[data-progress-label]').forEach(el => { el.textContent = `${deposited}/${total} déposé${deposited > 1 ? 's' : ''}`; });
      form.querySelectorAll('[data-progress-text]').forEach(el => {
        el.textContent = remaining ? `${deposited}/${total} documents déposés. ${remaining} restant${remaining > 1 ? 's' : ''} à déposer.` : `Tous les documents sont déposés (${deposited}/${total}).`;
      });
      form.querySelectorAll('[data-upload-progress]').forEach(el => el.classList.toggle('is-complete', total > 0 && !remaining));
    };
    const openRow = row => {
      rows.forEach(other => { if (other !== row) other.open = false; });
      row.open = true;
    };
    rows.forEach(row => {
      const input = row.querySelector('input[type="file"]');
      if (input.multiple) {
        const add = input.ownerDocument.createElement('button');
        add.type = 'button';
        add.className = 'document-check-button document-add-file';
        add.dataset.addDocument = '';
        add.addEventListener('click', () => { delete input.dataset.replaceFileKey; input.click(); });
        input.after(add);
      }
      setDocumentRowResult(input, null);
      row.addEventListener('toggle', () => { if (row.open) rows.forEach(other => { if (other !== row) other.open = false; }); });
      input.addEventListener('change', () => {
        input.dataset.uploadHasFiles = input.files?.length ? 'true' : 'false';
        setDocumentRowResult(input, input.dataset.documentCheck ? {status:'pending'} : null);
        refreshProgress();
      });
    });
    // Native validation must reveal the first missing field inside a closed accordion.
    let invalidBatch = false;
    form.addEventListener('invalid', event => {
      if (invalidBatch) return;
      invalidBatch = true;
      queueMicrotask(() => { invalidBatch = false; });
      const row = event.target.closest('[data-document-row]');
      if (!row) return;
      openRow(row);
      let parent = row.parentElement;
      while (parent && parent !== form) {
        if (parent.tagName === 'DETAILS') parent.open = true;
        parent = parent.parentElement;
      }
    }, true);
    form.addEventListener('change', refreshProgress);
    refreshProgress();
  });
}
