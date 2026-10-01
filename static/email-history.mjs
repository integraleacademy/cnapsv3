// Load the private, sandboxed preview only when its mail is opened.
document.querySelectorAll('.mail-entry').forEach(entry => {
  entry.addEventListener('toggle', () => {
    const frame = entry.querySelector('iframe[data-mail-src]');
    if (entry.open && frame && !frame.hasAttribute('src')) frame.src = frame.dataset.mailSrc;
  });
});
