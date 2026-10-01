// A selected file is not automatically declared compliant: an admin reviews it.
document.querySelectorAll('input[data-identity-photo]').forEach((input) => {
  const status = document.createElement('p');
  status.className = 'photo-file-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const preview = document.createElement('img');
  preview.className = 'photo-preview';
  preview.alt = "Aperçu de votre photo d'identité";
  preview.hidden = true;
  input.after(status, preview);
  let previewUrl;

  input.addEventListener('change', () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    preview.removeAttribute('src');
    preview.hidden = true;
    status.textContent = '';
    status.className = 'photo-file-status';
    const file = input.files[0];
    if (!file) return;
    const validType = !file.type || ['image/jpeg', 'image/png'].includes(file.type);
    if (!/\.(jpe?g|png)$/i.test(file.name) || !validType || file.size === 0 || file.size > 5 * 1024 * 1024) {
      input.value = '';
      status.classList.add('photo-file-error');
      status.textContent = "Sélectionnez une photo JPEG ou PNG valide de 5 Mo maximum. Les PDF et HEIC ne sont pas acceptés.";
      return;
    }
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    preview.hidden = false;
    status.textContent = `Photo sélectionnée : ${file.name}. La conformité sera contrôlée par notre équipe après l'envoi.`;
  });
});
