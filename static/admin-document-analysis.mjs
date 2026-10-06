// Recover an unchecked proof of address from its saved file, without replacing it.
let queue = Promise.resolve();

function attachSavedDocumentChecks(root = document) {
  for (const form of root.querySelectorAll('form[data-saved-document-check]')) {
    const id = form.dataset.savedDocumentCheck;
    const button = root.querySelector(`button[form="${form.id}"]`);
    const progress = root.getElementById(`analysis-progress-${id}`);
    const output = root.getElementById(`analysis-result-${id}`);
    const run = (onlyMissing = false) => {
      if (button.disabled) return;
      button.disabled = true;
      progress.textContent = 'Vérification en attente…';
      const task = queue.then(async () => {
        progress.textContent = 'Vérification du fichier enregistré en cours…';
        const body = new FormData(form);
        if (onlyMissing) body.set('only_missing', '1');
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 45000);
        try {
          const response = await fetch(form.action, {
            method: 'POST', body, credentials: 'same-origin',
            headers: { Accept: 'application/json' }, signal: controller.signal,
          });
          if (!response.ok || response.redirected) throw new Error('Check unavailable');
          const result = await response.json();
          if (typeof result.html !== 'string' || !result.analysis?.status) throw new Error('Invalid result');
          output.innerHTML = result.html;
          button.textContent = 'Relancer la vérification';
          progress.textContent = 'Résultat enregistré. Le statut de conformité reste inchangé.';
        } catch {
          progress.textContent = 'Impossible de récupérer le résultat. Actualisez la page pour vérifier s’il a été enregistré, puis relancez si nécessaire.';
        } finally {
          clearTimeout(timeout);
          button.disabled = false;
        }
      });
      queue = task.catch(() => {});
    };
    form.addEventListener('submit', event => { event.preventDefault(); run(); });
    if (form.hasAttribute('data-check-missing')) run(true);
  }
}

if (typeof document !== 'undefined') attachSavedDocumentChecks();
