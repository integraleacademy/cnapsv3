/* A preparation guide only: no uploads, storage or extra submission requirements. */
(() => {
  const guide = document.getElementById('preparation-guide');
  const stage = document.getElementById('public-form-stage');
  if (!guide || !stage) return;

  const profiles = [...guide.querySelectorAll('[data-prep-profile]')];
  const readyInputs = [...guide.querySelectorAll('[data-prep-ready]')];
  const progress = guide.querySelector('[data-prep-progress]');
  const count = guide.querySelector('[data-prep-count]');

  function updateProgress() {
    const active = readyInputs.filter(input => {
      const extra = input.closest('[data-prep-extra]');
      return !extra || profiles.some(profile => profile.dataset.prepProfile === extra.dataset.prepExtra && profile.checked);
    });
    const checked = active.filter(input => input.checked).length;
    count.textContent = `${checked} / ${active.length}`;
    progress.max = active.length;
    progress.value = checked;
    readyInputs.forEach(input => input.closest('[data-prep-card]').classList.toggle('is-prepared', input.checked));
    guide.querySelector('[data-prep-finish-title]').textContent = checked === active.length
      ? 'Votre checklist est complète !' : 'Vos documents sont prêts ?';
  }

  function syncProfile(profile, fromForm = false) {
    const formInput = document.getElementById(profile.dataset.prepProfile);
    if (!formInput) return;
    if (fromForm) profile.checked = formInput.checked;
    else if (formInput.checked !== profile.checked) {
      formInput.checked = profile.checked;
      formInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    const extra = guide.querySelector(`[data-prep-extra="${profile.dataset.prepProfile}"]`);
    extra.classList.toggle('is-applicable', profile.checked);
    extra.querySelector('[data-prep-details]').hidden = !profile.checked;
    profile.setAttribute('aria-expanded', String(profile.checked));
    profile.closest('.prep-profile').classList.toggle('is-selected', profile.checked);
    const hosted = document.getElementById('prep-heberge').checked;
    guide.querySelector('[data-prep-address-owner]').textContent = hosted
      ? 'Au nom de votre hébergeant, à l’adresse où vous résidez.' : 'À votre nom et à votre adresse.';
    updateProgress();
  }

  profiles.forEach(profile => {
    profile.addEventListener('change', () => syncProfile(profile));
    document.getElementById(profile.dataset.prepProfile)?.addEventListener('change', () => syncProfile(profile, true));
    syncProfile(profile, true);
  });
  readyInputs.forEach(input => input.addEventListener('change', () => {
    const extra = input.closest('[data-prep-extra]');
    if (input.checked && extra) {
      const profile = profiles.find(item => item.dataset.prepProfile === extra.dataset.prepExtra);
      if (profile && !profile.checked) {
        profile.checked = true;
        syncProfile(profile);
      }
    }
    updateProgress();
  }));

  function showForm(open) {
    stage.hidden = !open;
    guide.hidden = open;
    // Upload progress ignores hidden ancestors. Refresh it after revealing the form.
    if (open) stage.querySelector('form').dispatchEvent(new Event('change', { bubbles: true }));
    const title = document.getElementById(open ? 'public-form-title' : 'prep-title');
    title.focus({ preventScroll: true });
    title.scrollIntoView({ block: 'start', behavior: 'instant' });
  }
  document.querySelectorAll('[data-prep-start]').forEach(link => link.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    showForm(true);
  }));
  document.querySelectorAll('[data-prep-return]').forEach(link => link.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    profiles.forEach(profile => syncProfile(profile, true));
    showForm(false);
  }));
})();
