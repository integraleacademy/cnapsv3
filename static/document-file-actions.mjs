import { fileKey } from './document-check-rules.mjs';

export function replacementButton(input, file) {
  const button = input.ownerDocument.createElement('button');
  button.type = 'button';
  button.className = 'document-check-button';
  button.textContent = input.closest('[data-document-row]') ? 'Remplacer' : 'Remplacer ce fichier';
  button.setAttribute('aria-label', `Remplacer ${file.name}`);
  button.addEventListener('click', () => { input.dataset.replaceFileKey = fileKey(file); input.click(); });
  return button;
}

export function attachOtherFileActions(root = document) {
  root.querySelectorAll('input[type="file"]:not([data-document-check])').forEach(input => {
    if (input.dataset.replaceAttached) return;
    input.dataset.replaceAttached = 'true';
    const output = input.ownerDocument.createElement('div');
    output.className = 'document-file-actions';
    input.after(output);
    input.addEventListener('cancel', () => { delete input.dataset.replaceFileKey; });
    input.addEventListener('change', () => {
      output.replaceChildren(...Array.from(input.files || [], file => {
        const row = input.ownerDocument.createElement('div');
        row.className = 'document-file-row';
        const name = input.ownerDocument.createElement('span');
        name.textContent = file.name;
        row.append(name, replacementButton(input, file));
        return row;
      }));
    });
  });
}
