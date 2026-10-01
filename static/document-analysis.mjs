import { assessAddressDate, assessIdentityReadability, findIssueDates } from './document-check-rules.mjs';

// Pinned browser libraries. Only their code/models are downloaded; document
// bytes and recognised text stay in the browser until the usual form submission.
const PDF_BASE = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@6.3.289';
const OCR_BASE = 'https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0';
const OCR_CORE = 'https://cdn.jsdelivr.net/npm/tesseract.js-core@7.0.0';
const OCR_LANG = 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/fra@1.0.0/4.0.0_best_int';
let librariesPromise;
let queue = Promise.resolve();

export async function browserLibraries() {
  if (!librariesPromise) {
    librariesPromise = import(`${PDF_BASE}/legacy/build/pdf.min.mjs`).then(pdfjs => {
      pdfjs.GlobalWorkerOptions.workerSrc = `${PDF_BASE}/legacy/build/pdf.worker.min.mjs`;
      return {
        pdfjs,
        pdfOptions: { standardFontDataUrl: `${PDF_BASE}/standard_fonts/`, cMapUrl: `${PDF_BASE}/cmaps/`, cMapPacked: true, wasmUrl: `${PDF_BASE}/wasm/` },
        createWorker: async () => {
          const { default: Tesseract } = await import(`${OCR_BASE}/dist/tesseract.esm.min.js`);
          return Tesseract.createWorker('fra', 1, {
            workerPath: `${OCR_BASE}/dist/worker.min.js`, corePath: OCR_CORE,
            langPath: OCR_LANG, logger: () => {}, errorHandler: () => {},
          });
        },
        makeCanvas: () => document.createElement('canvas'),
        canvasImage: canvas => canvas,
      };
    }).catch(error => { librariesPromise = undefined; throw error; });
  }
  return librariesPromise;
}

function stopped() { return new DOMException('Analysis cancelled', 'AbortError'); }
function assertActive(context) { if (context.cancelled) throw stopped(); }

async function readRenderedPage(page, context, libraries) {
  assertActive(context);
  const base = page.getViewport({ scale: 1 });
  const scale = Math.min(3, 1800 / Math.max(base.width, base.height));
  const viewport = page.getViewport({ scale });
  const canvas = libraries.makeCanvas();
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  try {
    context.stage = 'pdf-render';
    const drawing = canvas.getContext('2d', { alpha: false });
    await page.render({ canvasContext: drawing, viewport, background: '#ffffff' }).promise;
    assertActive(context);
    if (!context.worker) {
      context.stage = 'ocr-load';
      context.worker = await libraries.createWorker();
      if (context.cancelled) { await context.worker.terminate(); throw stopped(); }
      context.stage = 'ocr-settings';
      await context.worker.setParameters({ tessedit_pageseg_mode: '3', user_defined_dpi: '200' });
    }
    context.stage = 'ocr-read';
    const { data } = await context.worker.recognize(libraries.canvasImage(canvas));
    assertActive(context);
    return { text: data.text || '', confidence: data.confidence || 0 };
  } finally {
    canvas.width = canvas.height = 1;
    page.cleanup();
  }
}

async function inspect(file, kind, today, context, libraries) {
  assertActive(context);
  if (!/\.pdf$/i.test(file.name) || file.size > 5 * 1024 * 1024) throw new Error('Unsupported document');
  context.pdfTask = libraries.pdfjs.getDocument({
    data: new Uint8Array(await file.arrayBuffer()), isEvalSupported: false,
    ...libraries.pdfOptions,
  });
  // A password dialog must not trap the form. The normal upload remains usable.
  context.pdfTask.onPassword = () => { void context.pdfTask.destroy(); };
  const pdf = await context.pdfTask.promise;
  assertActive(context);

  if (kind === 'proof_address') {
    let nativeText = '';
    for (let number = 1; number <= Math.min(pdf.numPages, 5); number++) {
      const page = await pdf.getPage(number);
      const content = await page.getTextContent();
      nativeText += '\n' + content.items.map(item => `${item.str || ''}${item.hasEOL ? '\n' : ' '}`).join('');
      page.cleanup();
      assertActive(context);
    }
    const nativeResult = assessAddressDate(nativeText, today);
    if (findIssueDates(nativeText).length) return nativeResult;
    // Scans often have no text layer. Read the actual visible pages with OCR.
    let ocrText = '';
    const confidences = [];
    for (let number = 1; number <= Math.min(pdf.numPages, 2); number++) {
      const page = await pdf.getPage(number);
      const reading = await readRenderedPage(page, context, libraries);
      ocrText += '\n' + reading.text;
      if (reading.text.trim()) confidences.push(reading.confidence);
    }
    return assessAddressDate(ocrText, today, { confidence: confidences.length ? Math.min(...confidences) : 0 });
  }

  const pages = [];
  for (let number = 1; number <= Math.min(pdf.numPages, 2); number++) {
    // Always OCR the rendered identity document: a hidden text layer does not
    // demonstrate that a human can read a blurred or blank scan.
    pages.push(await readRenderedPage(await pdf.getPage(number), context, libraries));
  }
  return assessIdentityReadability(pages, { partial: pdf.numPages > pages.length });
}

export async function analyzeWithLibraries(file, kind, today, libraries, { signal, timeoutMs = 90000 } = {}) {
  const context = { cancelled: false, worker: null, pdfTask: null, stage: 'pdf-open' };
  let rejectCancellation;
  const cancellation = new Promise((_, reject) => { rejectCancellation = reject; });
  const cancel = () => {
    context.cancelled = true;
    rejectCancellation(stopped());
    void context.worker?.terminate().catch(() => {});
    void context.pdfTask?.destroy().catch(() => {});
  };
  const timeout = setTimeout(cancel, timeoutMs);
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  try {
    return await Promise.race([inspect(file, kind, today, context, libraries), cancellation]);
  } catch (error) {
    if (!context.cancelled) {
      // Do not log filenames, document contents, OCR text or PDF parser errors.
      // OCR initialisation only loads public code/models, so its error is safe.
      const detail = ['ocr-load', 'ocr-settings'].includes(context.stage)
        ? String(error?.message || error) : String(error?.name || 'Error');
      console.warn(`[document-check] ${context.stage}: ${detail}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', cancel);
    await context.worker?.terminate().catch(() => {});
    await context.pdfTask?.destroy().catch(() => {});
  }
}

export function analyzeDocument(file, kind, today, { signal } = {}) {
  const task = queue.then(async () => {
    if (signal?.aborted) throw stopped();
    let timeout;
    let abort;
    let libraries;
    try {
      libraries = await Promise.race([
        browserLibraries(),
        new Promise((_, reject) => {
          abort = () => reject(stopped());
          signal?.addEventListener('abort', abort, { once: true });
          timeout = setTimeout(abort, 20000);
        }),
      ]);
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', abort);
    }
    return analyzeWithLibraries(file, kind, today, libraries, { signal });
  });
  // One document/one OCR worker at a time, including after errors or cancellation.
  queue = task.catch(() => {});
  return task;
}
