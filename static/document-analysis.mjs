// Document pixels are analysed server-side. The OpenAI key never reaches the browser.
let queue = Promise.resolve();

function stopped() { return new DOMException('Analysis cancelled', 'AbortError'); }

export function analyzeDocument(file, kind, _today, { signal, token } = {}) {
  const task = queue.then(async () => {
    if (signal?.aborted) throw stopped();
    if (!token || !/\.pdf$/i.test(file.name) || !file.size || file.size > 5 * 1024 * 1024) {
      throw new Error('Analysis unavailable');
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true });
    const timeout = setTimeout(abort, 35000);
    try {
      const body = new FormData();
      body.append('kind', kind);
      body.append('document', file, file.name);
      const response = await fetch('/api/document-analysis', {
        method: 'POST', body, signal: controller.signal, credentials: 'same-origin',
        headers: { 'X-Document-Check-Token': token },
      });
      if (!response.ok) throw new Error('Analysis unavailable');
      const result = await response.json();
      if (!['info', 'warning', 'unknown'].includes(result.status) || typeof result.message !== 'string') {
        throw new Error('Invalid analysis');
      }
      return result;
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', abort);
    }
  });
  // Avoid sending recto, verso and proof of address simultaneously.
  queue = task.catch(() => {});
  return task;
}
