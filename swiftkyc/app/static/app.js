/* =========================================================================
   SwiftKYC — app.js frontend logic
   .
   - Uses exact field names: doc_type, doc_number
   - Detects OCR success by next_step === "SELFIE"
   - Admin filters: status, doc_type, created_from, created_to
   - All on-screen messages auto-hide after ~5.5s
   - Camera lifecycle management (start/stop)
   ========================================================================= */

const BASE_API = 'http://127.0.0.1:8000'; // <-- SET YOUR BACKEND URL HERE

const MSG_AUTO_HIDE_MS = 5500; // ~5.5s

/* ================== STATE ================== */
const state = {
  sessionId: localStorage.getItem('swiftkyc_session') || null,
  name: null, mobile: null, age: null,
  documentType: null, documentNumber: null,
  lastOcrResponse: null,
  activeStream: null
};

/* ================== UTILITIES ================== */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from((root || document).querySelectorAll(sel));

function cloneTpl(id) {
  const tpl = document.getElementById(id);
  if (!tpl) throw new Error('Template not found: ' + id);
  return tpl.content.cloneNode(true);
}

function setMain(node) {
  const app = document.getElementById('app');
  app.innerHTML = '';
  app.appendChild(node);
}

/* show a message inside an element (element node or selector). Auto-hides after MSG_AUTO_HIDE_MS */
function showMessage(target, text) {
  let el;
  if (typeof target === 'string') el = document.querySelector(target);
  else el = target;
  if (!el) return console.warn('showMessage: target not found', target);
  el.textContent = text;
  el.style.opacity = '1';
  if (el._hideTimer) clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => { el.textContent = ''; el._hideTimer = null; }, MSG_AUTO_HIDE_MS);
}

/* API fetch wrapper; throws on non-OK */
async function apiFetch(path, opts = {}) {
  const url = (BASE_API || '') + path;
  const res = await fetch(url, opts);
  const ct = res.headers.get('content-type') || '';
  let body = null;
  if (ct.includes('application/json')) {
    body = await res.json();
  } else {
    const text = await res.text().catch(() => null);
    try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  }
  if (!res.ok) {
    const errMsg = (body && (body.detail || body.message)) ? (body.detail || body.message) : (typeof body === 'string' ? body : `HTTP ${res.status}`);
    const err = new Error(errMsg || `HTTP ${res.status}`);
    err.status = res.status; err.body = body;
    throw err;
  }
  return body;
}

/* stop any active camera stream */
function stopActiveStream() {
  if (state.activeStream) {
    try { state.activeStream.getTracks().forEach(t => t.stop()); } catch (e) {}
    state.activeStream = null;
  }
}

/* ================== NAVIGATION & BOOT ================== */
function boot() {
  // Header buttons
  $('#nav-home')?.addEventListener('click', () => showHome());
  $('#nav-admin')?.addEventListener('click', () => renderAdminList());
  $('#start-digital-kyc')?.addEventListener('click', () => renderCreateSession());
  $('#open-admin')?.addEventListener('click', () => renderAdminList());

  // Quick warning if BASE_API is not set
  if (!BASE_API) {
    const warning = document.createElement('div');
    warning.className = 'card';
    warning.style.margin = '8px 0';
    warning.innerHTML = `<strong style="color:var(--accent-teal)">Configuration:</strong> BASE_API is not set in <code>app.js</code>. Set it to your backend (e.g. http://127.0.0.1:8000).`;
    const root = document.getElementById('root');
    root.insertBefore(warning, root.children[1]);
  }

  showHome();

  // modal OK button
  $('#videoKycOk')?.addEventListener('click', () => {
    document.getElementById('modal-video-kyc').classList.add('hidden');
    document.getElementById('modal-video-kyc').setAttribute('aria-hidden', 'true');
  });

  // header nav duplicates (defensive)
  $('#nav-home')?.addEventListener('click', showHome);
  $('#nav-admin')?.addEventListener('click', renderAdminList);

  // cleanup streams on page close
  window.addEventListener('beforeunload', () => stopActiveStream());
  window.addEventListener('pagehide', () => stopActiveStream());
}

/* ================== VIEWS: CUSTOMER WIZARD ================== */

function showHome() {
  stopActiveStream();
  const frag = cloneTpl('tpl-home');
  const node = frag.firstElementChild;
  setMain(node);

  node.querySelector('[data-action="start-kyc"]')?.addEventListener('click', () => renderCreateSession());
  node.querySelector('[data-action="video-kyc"]')?.addEventListener('click', () => {
    const modal = document.getElementById('modal-video-kyc');
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  });
  // header/landing quick buttons
  $('#start-digital-kyc')?.addEventListener('click', () => renderCreateSession());
  $('#open-admin')?.addEventListener('click', () => renderAdminList());
}

/* Create Session: POST /api/v1/kyc/session {name,mobile} => session_id */
function renderCreateSession() {
  stopActiveStream();
  const frag = cloneTpl('tpl-create-session');
  const node = frag.firstElementChild;
  setMain(node);

  const form = node.querySelector('#form-create-session');
  const msgEl = node.querySelector('#create-session-msg');

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const name = form.querySelector('#i-name').value.trim();
    const mobile = form.querySelector('#i-mobile').value.trim();
    const age = parseInt(form.querySelector('#i-age').value, 10);
    if (!name || !/^\d{10}$/.test(mobile)) return showMessage(msgEl, 'Enter a valid name and 10-digit mobile.');
    if (Number.isNaN(age) || age < 18) return showMessage(msgEl, 'You must be 18 years or older.');

    showMessage(msgEl, 'Creating session...');
    try {
      const body = await apiFetch('/api/v1/kyc/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, mobile })
      });
      const sid = body.session_id || body.sessionId || body.id;
      if (!sid) throw new Error('No session_id in response');
      state.sessionId = sid;
      state.name = name; state.mobile = mobile; state.age = age;
      localStorage.setItem('swiftkyc_session', sid);
      showMessage(msgEl, 'Session created — continuing...');
      setTimeout(() => renderSelectDocument(), 300);
    } catch (err) {
      console.error(err);
      showMessage(msgEl, 'Create session failed: ' + (err.message || 'server error'));
    }
  });

  node.querySelector('[data-action="cancel-to-home"]')?.addEventListener('click', () => showHome());
}

/* Select Document: POST /select-document with {doc_type} */
function renderSelectDocument() {
  stopActiveStream();
  const frag = cloneTpl('tpl-select-document');
  const node = frag.firstElementChild;
  setMain(node);

  node.querySelectorAll('.doc-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const docType = btn.getAttribute('data-doc');
      if (!state.sessionId) return showMessage(node, 'Session missing, start again.');
      try {
        const resp = await apiFetch(`/api/v1/kyc/session/${state.sessionId}/select-document`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doc_type: docType })
        });
        // resp contains document_id, next_step etc.
        state.documentType = resp.doc_type || docType;
        renderEnterDocNumber();
      } catch (err) {
        console.error(err);
        showMessage(node, 'Select document failed: ' + (err.message || 'server error'));
      }
    });
  });
}

/* Enter doc number: POST /enter-doc-number {doc_number} */
function renderEnterDocNumber() {
  stopActiveStream();
  const frag = cloneTpl('tpl-enter-doc-number');
  const node = frag.firstElementChild;
  setMain(node);

  const form = node.querySelector('#form-doc-number');
  const msgEl = node.querySelector('#doc-number-msg');

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const docno = form.querySelector('#i-docno').value.trim();
    if (!docno) return showMessage(msgEl, 'Enter the document number.');
    if (!state.sessionId) return showMessage(msgEl, 'Session missing.');
    try {
      const resp = await apiFetch(`/api/v1/kyc/session/${state.sessionId}/enter-doc-number`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_number: docno })
      });
      state.documentNumber = resp.doc_number || docno;
      renderUploadDocument();
    } catch (err) {
      console.error(err);
      showMessage(msgEl, 'Saving document number failed: ' + (err.message || 'server error'));
    }
  });

  node.querySelector('[data-action="back-to-select"]')?.addEventListener('click', () => renderSelectDocument());
}

/* Upload document (file or camera) -> POST /validate-document (multipart file: file)
   Behavior: If response.next_step === "SELFIE" => success -> go to selfie
             If response.next_step === "SCAN_DOC" => OCR failed -> show retry
*/
function renderUploadDocument() {
  stopActiveStream();
  const frag = cloneTpl('tpl-upload-document');
  const node = frag.firstElementChild;
  setMain(node);

  node.querySelector('#upload-doc-type').textContent = state.documentType || 'Document';

  const sourceSel = node.querySelector('#source-select');
  const sourceArea = node.querySelector('#source-area');
  const preview = node.querySelector('#doc-preview');
  const uploadBtn = node.querySelector('#upload-doc-btn');
  const cancelBtn = node.querySelector('#cancel-upload-doc');
  const uploadMsg = node.querySelector('#upload-msg');

  let chosenFile = null;
  let localStream = null;

  function resetPreview() {
    preview.innerHTML = 'No file selected';
  }

  function setPreview(fileOrUrl) {
    preview.innerHTML = '';
    const img = document.createElement('img');
    img.alt = 'Preview';
    img.style.maxWidth = '100%';
    img.style.borderRadius = '8px';
    if (typeof fileOrUrl === 'string') img.src = fileOrUrl;
    else img.src = URL.createObjectURL(fileOrUrl);
    preview.appendChild(img);
  }

  async function setupFileInput() {
    stopLocalCamera();
    sourceArea.innerHTML = `<input id="file-input" type="file" accept="image/*">`;
    const fi = node.querySelector('#file-input');
    fi.addEventListener('change', () => {
      if (fi.files && fi.files[0]) {
        chosenFile = fi.files[0];
        setPreview(chosenFile);
      }
    });
  }

  function stopLocalCamera() {
    if (localStream) {
      try { localStream.getTracks().forEach(t => t.stop()); } catch (e) {}
      localStream = null;
    }
    state.activeStream = null;
  }

  async function setupCameraCapture() {
    sourceArea.innerHTML = `<div><video id="doc-video" autoplay playsinline></video>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button id="doc-capture" class="primary-outline">Capture</button>
        <button id="doc-close" class="ghost">Close</button>
      </div></div>`;
    const video = sourceArea.querySelector('#doc-video');
    const captureBtn = sourceArea.querySelector('#doc-capture');
    const closeBtn = sourceArea.querySelector('#doc-close');
    try {
      const constraints = { video: { facingMode: 'environment', width: { ideal: 1280 } } };
      localStream = await navigator.mediaDevices.getUserMedia(constraints);
      state.activeStream = localStream;
      video.srcObject = localStream;
      await video.play();
    } catch (err) {
      console.error(err);
      showMessage(uploadMsg, 'Camera error: ' + (err.message || 'permission denied'));
      return;
    }
    captureBtn.addEventListener('click', () => {
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        chosenFile = blob;
        setPreview(blob);
      }, 'image/jpeg', 0.9);
    });
    closeBtn.addEventListener('click', () => {
      stopLocalCamera();
      sourceArea.innerHTML = '';
      setupFileInput();
      resetPreview();
    });
  }

  // initialize
  setupFileInput();

  sourceSel.addEventListener('change', () => {
    chosenFile = null;
    resetPreview();
    if (sourceSel.value === 'file') setupFileInput();
    else setupCameraCapture();
  });

  cancelBtn.addEventListener('click', () => {
    stopLocalCamera();
    showHome();
  });

  uploadBtn.addEventListener('click', async () => {
    if (!chosenFile) return showMessage(uploadMsg, 'Please choose or capture a file first.');
    if (!state.sessionId) return showMessage(uploadMsg, 'Session missing — start again.');

    // replace main with OCR progress template
    const ocrFrag = cloneTpl('tpl-ocr-progress');
    const ocrNode = ocrFrag.firstElementChild;
    setMain(ocrNode);
    const progressBar = ocrNode.querySelector('#ocr-progress-bar');
    const resultEl = ocrNode.querySelector('#ocr-result');

    // animate progress until response
    let progress = 5;
    progressBar.style.width = '5%';
    const progTimer = setInterval(() => {
      progress = Math.min(92, progress + (Math.random() * 12));
      progressBar.style.width = `${progress}%`;
    }, 400);

    try {
      const fd = new FormData();
      fd.append('file', chosenFile, 'document.jpg');

      const res = await fetch((BASE_API || '') + `/api/v1/kyc/session/${state.sessionId}/validate-document`, {
        method: 'POST',
        body: fd
      });

      clearInterval(progTimer);
      progressBar.style.width = '100%';

      const ct = res.headers.get('content-type') || '';
      let data;
      if (ct.includes('application/json')) data = await res.json();
      else {
        const txt = await res.text().catch(() => null);
        try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = { next_step: 'SCAN_DOC', reason: txt }; }
      }

      // backend uses next_step to indicate whether OCR passed to SELFIE or stayed in SCAN_DOC
      const nextStep = data.next_step || data.nextStep;
      state.lastOcrResponse = data;

      if (!res.ok) {
        const reason = (data && (data.reason || data.detail)) || 'OCR validation failed';
        resultEl.textContent = 'OCR failed: ' + reason;
        showMessage(resultEl, 'OCR failed: ' + reason);
        setTimeout(() => renderUploadDocument(), 1200);
        return;
      }

      // success response may still have next_step === SCAN_DOC (meaning OCR mismatch)
      if (nextStep === 'SELFIE') {
        // success - advance to selfie
        resultEl.innerHTML = `<div class="kv"><strong>Document uploaded</strong></div>
          <div class="muted small" style="margin-top:8px">Storage: ${data.storage_url || 'uploaded'}</div>`;
        const proceedBtn = document.createElement('button'); proceedBtn.className = 'primary'; proceedBtn.textContent = 'Proceed to Selfie';
        const retryBtn = document.createElement('button'); retryBtn.className = 'ghost'; retryBtn.textContent = 'Retry Upload';
        const actions = document.createElement('div'); actions.style.marginTop = '12px'; actions.appendChild(proceedBtn); actions.appendChild(retryBtn);
        resultEl.appendChild(actions);
        proceedBtn.addEventListener('click', () => renderSelfieUpload());
        retryBtn.addEventListener('click', () => renderUploadDocument());
      } else {
        // OCR did not match — next_step likely SCAN_DOC
        const msg = (data.reason || `OCR did not match. Please re-upload a clearer image.`);
        resultEl.textContent = msg;
        showMessage(resultEl, msg);
        // allow user to retry
        const retryTimer = setTimeout(() => renderUploadDocument(), 1200);
      }
    } catch (err) {
      clearInterval(progTimer);
      progressBar.style.width = '100%';
      console.error(err);
      showMessage(resultEl, 'Upload/OCR failed: ' + (err.message || 'server error'));
      setTimeout(() => renderUploadDocument(), 1200);
    }
  });
}

/* Selfie upload: camera-only -> POST /selfie (multipart file)
   After upload, server returns full session object; show Status page.
*/
function renderSelfieUpload() {
  stopActiveStream();
  const frag = cloneTpl('tpl-selfie-upload');
  const node = frag.firstElementChild;
  setMain(node);

  const video = node.querySelector('#selfie-video');
  const canvas = node.querySelector('#selfie-canvas');
  const captureBtn = node.querySelector('#capture-selfie');
  const uploadBtn = node.querySelector('#upload-selfie');
  const cancelBtn = node.querySelector('#cancel-selfie');
  const preview = node.querySelector('#selfie-preview');

  let localStream = null;
  let capturedBlob = null;

  async function startCamera() {
    try {
      const constraints = { video: { facingMode: 'user', width: { ideal: 720 } } };
      localStream = await navigator.mediaDevices.getUserMedia(constraints);
      state.activeStream = localStream;
      video.srcObject = localStream;
      await video.play();
    } catch (err) {
      console.error(err);
      showMessage(preview, 'Camera error: ' + (err.message || 'permission denied'));
    }
  }

  function stopCamera() {
    if (localStream) {
      try { localStream.getTracks().forEach(t => t.stop()); } catch (e) {}
      localStream = null;
      state.activeStream = null;
    }
  }

  captureBtn.addEventListener('click', () => {
    if (!video.videoWidth) return showMessage(preview, 'Camera not ready — try again.');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      capturedBlob = blob;
      preview.innerHTML = '';
      const img = document.createElement('img'); img.src = URL.createObjectURL(blob);
      img.style.maxWidth = '100%'; img.style.borderRadius = '8px';
      preview.appendChild(img);
    }, 'image/jpeg', 0.9);
  });

  uploadBtn.addEventListener('click', async () => {
    if (!capturedBlob) return showMessage(preview, 'Capture a selfie first.');
    if (!state.sessionId) return showMessage(preview, 'Session missing.');
    showMessage(preview, 'Uploading selfie...');
    try {
      const fd = new FormData();
      fd.append('file', capturedBlob, 'selfie.jpg');
      const res = await fetch((BASE_API || '') + `/api/v1/kyc/session/${state.sessionId}/selfie`, { method: 'POST', body: fd });
      if (!res.ok) {
        const txt = await res.text().catch(() => null);
        throw new Error(txt || 'Upload failed');
      }
      // backend returns session object; proceed to status
      stopCamera();
      renderStatusPage();
    } catch (err) {
      console.error(err);
      showMessage(preview, 'Selfie upload failed: ' + (err.message || 'server error'));
    }
  });

  cancelBtn.addEventListener('click', () => {
    stopCamera();
    renderUploadDocument();
  });

  // start camera on view load
  startCamera();
}

/* Status page: GET /api/v1/kyc/session/{session_id} */
async function renderStatusPage() {
  stopActiveStream();
  const frag = cloneTpl('tpl-status');
  const node = frag.firstElementChild;
  setMain(node);

  const infoWrap = node.querySelector('#status-info');
  const rawWrap = node.querySelector('#status-raw');
  const refreshBtn = node.querySelector('#refresh-status');
  const homeBtn = node.querySelector('#to-home');

  async function loadStatus() {
    infoWrap.innerHTML = 'Loading...';
    rawWrap.textContent = '';
    try {
      if (!state.sessionId) throw new Error('No session id stored.');
      const data = await apiFetch(`/api/v1/kyc/session/${state.sessionId}`);
      // build key value grid
      infoWrap.innerHTML = '';
      const grid = document.createElement('div');
      grid.className = 'status-grid';
      const kv = (k, v) => `<div class="kv"><strong>${k}</strong><div style="margin-top:6px">${v ?? '—'}</div></div>`;
      grid.innerHTML = kv('Session ID', data.session_id || state.sessionId) +
                       kv('Status', data.status || '—') +
                       kv('Current Step', data.current_step || data.currentStep || '—') +
                       kv('Customer ID', data.customer_id || data.customerId || '—');
      infoWrap.appendChild(grid);
      rawWrap.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      console.error(err);
      infoWrap.textContent = 'Failed to load status: ' + (err.message || 'server error');
    }
  }

  refreshBtn.addEventListener('click', loadStatus);
  homeBtn.addEventListener('click', () => showHome());

  await loadStatus();
}

/* ================== ADMIN DASHBOARD ================== */

/* Render admin sessions list + filters */
function renderAdminList() {
  stopActiveStream();
  const frag = cloneTpl('tpl-admin-list');
  const node = frag.firstElementChild;
  setMain(node);

  const help = document.getElementById("help-tips");
  if (help) help.classList.add("hidden");

  const fStatus = node.querySelector('#f-status');
  const fDoc = node.querySelector('#f-doc');
  const fDate = node.querySelector('#f-date'); // single date input
  const btnApply = node.querySelector('#f-apply');
  const btnReset = node.querySelector('#f-reset');

  const sessionsWrap = node.querySelector('#sessions-list-wrap');
  const sessionsEmpty = node.querySelector('#sessions-empty');
  const detailWrap = { classList: { add(){}, remove(){} } }; 

  async function loadSessions(filters = {}) {
    sessionsWrap.innerHTML = 'Loading...';
    detailWrap.classList.add('hidden');
    sessionsEmpty.classList.add('hidden');

    const params = new URLSearchParams();
    if (filters.status) params.append('status', filters.status);
    if (filters.doc_type) params.append('doc_type', filters.doc_type);
    if (filters.created_from) params.append('created_from', filters.created_from);
    if (filters.created_to) params.append('created_to', filters.created_to);

    try {
      const url = `/api/v1/admin/kyc/sessions` + (params.toString() ? `?${params.toString()}` : '');
      const data = await apiFetch(url);
      if (!Array.isArray(data) || data.length === 0) {
        sessionsWrap.innerHTML = '';
        sessionsEmpty.classList.remove('hidden');
        return;
      }
      sessionsEmpty.classList.add('hidden');
      // build table
      const table = document.createElement('table'); table.className = 'table';
      table.innerHTML = `<thead><tr><th>Session ID</th><th>Customer ID</th><th>Document</th><th>Status</th><th>Created</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      data.forEach(s => {
        const tr = document.createElement('tr');
        const sid = s.session_id || s.id || '—';
        const cid = s.customer_id || '—';
        const doc = s.primary_doc_type || s.doc_type || '—';
        const status = s.status || '—';
        const created = s.created_at || s.created || '—';
        tr.innerHTML = `<td>${sid}</td><td>${cid}</td><td>${doc}</td><td>${status}</td><td>${created}</td>`;
        tr.addEventListener('click', () => renderAdminDetail(sid));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      sessionsWrap.innerHTML = '';
      sessionsWrap.appendChild(table);
    } catch (err) {
      console.error(err);
      sessionsWrap.textContent = 'Failed to load sessions: ' + (err.message || 'server error');
    }
  }


/* Render detail panel for a session — clean, popup, improved UX */
async function renderAdminDetail(sessionId) {
  const modal = document.getElementById("modal-session-detail");
  const body = document.getElementById("session-detail-modal-body");
  const closeBtn = document.getElementById("session-detail-close");

  /* Show modal + loading */
  body.innerHTML = `<div class="muted">Loading...</div>`;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");

  /* Close helpers */
  function closeModal() {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    closeBtn.removeEventListener("click", closeModal);
    document.removeEventListener("keydown", onKey);
    modal.removeEventListener("click", onBackdrop);
  }
  function onKey(e) { if (e.key === "Escape") closeModal(); }
  function onBackdrop(e) { if (e.target === modal) closeModal(); }

  closeBtn.addEventListener("click", closeModal);
  document.addEventListener("keydown", onKey);
  modal.addEventListener("click", onBackdrop);

  try {
    const data = await apiFetch(`/api/v1/admin/kyc/sessions/${sessionId}`);

    /* Build Documents List */
    let docs = `<div class="muted small">No documents</div>`;
    if (Array.isArray(data.documents) && data.documents.length > 0) {
      docs = data.documents
        .map(doc => `
          <div style="margin-bottom:10px;">
            <div><strong>Type:</strong> ${doc.doc_type || "—"}</div>
            <div><strong>Number:</strong> ${doc.doc_number || "—"}</div>
            <div><strong>Valid:</strong> ${
              typeof doc.is_valid === "boolean" ? (doc.is_valid ? "Yes" : "No") : "—"
            }</div>
            <div><strong>Quality:</strong> ${doc.quality_score ?? "—"}</div>
          </div>
        `)
        .join("");
    }

    /* Main session detail layout */
    body.innerHTML = `
      <div>
        <h4>Session ${data.session_id}</h4>
        <div class="muted small">Status: <strong>${data.status}</strong></div>
        <div class="muted small" style="margin-top:6px">
          Step: <strong>${data.current_step}</strong>
        </div>

        <div class="kv" style="margin-top:14px">
          <strong>Customer</strong>
          <div style="margin-top:6px">ID: ${data.customer_id}</div>
        </div>

        <div class="kv" style="margin-top:14px">
          <strong>Document(s)</strong>
          <div style="margin-top:6px">${docs}</div>
        </div>

        <div class="kv" style="margin-top:14px">
          <strong>Meta</strong>
          <div style="margin-top:6px">
            Retries — select: ${data.retries_select},
            scan: ${data.retries_scan},
            upload: ${data.retries_upload},
            selfie: ${data.retries_selfie}<br>
            Created: ${data.created_at}<br>
            Updated: ${data.updated_at}
          </div>
        </div>
      </div>
    `;

/* --- ACTION BAR (Approve / Reject / Approved Badge) --- */
const actions = document.createElement("div");
actions.className = "session-actions";
actions.style.position = "sticky";
actions.style.bottom = "0";
actions.style.background = "rgba(13, 26, 32, 0.9)";
actions.style.padding = "12px 0";
actions.style.marginTop = "20px";
actions.style.display = "flex";
actions.style.gap = "10px";

/* Helper to refresh after an action */
async function doAction(url, verb, successText, failText) {
  try {
    await apiFetch(url, { method: verb });
    showMessage(body, successText);
    if (typeof loadSessions === "function") loadSessions(getCurrentFilters());
    setTimeout(() => renderAdminDetail(sessionId), 400);
  } catch (e) {
    showMessage(body, (failText || "Action failed") + ": " + (e.message || "server error"));
  }
}

/* APPROVED: show badge + allow Reject */
if (data.status === "APPROVED") {
  const badge = document.createElement("div");
  badge.textContent = "Approved ✓";
  badge.style.background = "rgba(0, 200, 120, 0.25)";
  badge.style.color = "#00e08a";
  badge.style.border = "1px solid rgba(0, 200, 120, 0.35)";
  badge.style.padding = "10px 16px";
  badge.style.borderRadius = "8px";
  badge.style.fontWeight = "600";
  badge.style.fontSize = "15px";
  badge.style.width = "fit-content";
  actions.appendChild(badge);

  // add Reject button (admins may now reject even approved sessions)
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "ghost";
  rejectBtn.textContent = "Reject";
  actions.appendChild(rejectBtn);

  rejectBtn.addEventListener("click", async () => {
    await doAction(`/api/v1/admin/kyc/sessions/${sessionId}/reject`, "POST", "Session rejected", "Reject failed");
  });

/* REJECTED: show Approve only */
} else if (data.status === "REJECTED") {
  const approveBtn = document.createElement("button");
  approveBtn.className = "primary";
  approveBtn.textContent = "Approve";
  actions.appendChild(approveBtn);

  approveBtn.addEventListener("click", async () => {
    await doAction(`/api/v1/admin/kyc/sessions/${sessionId}/approve`, "POST", "Session approved", "Approve failed");
  });

/* IN_PROGRESS or KYC_CHECK: show both Approve + Reject */
} else if (data.status === "IN_PROGRESS" || data.status === "KYC_CHECK") {
  const approveBtn = document.createElement("button");
  approveBtn.className = "primary";
  approveBtn.textContent = "Approve";

  const rejectBtn = document.createElement("button");
  rejectBtn.className = "ghost";
  rejectBtn.textContent = "Reject";

  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);

  approveBtn.addEventListener("click", async () => {
    await doAction(`/api/v1/admin/kyc/sessions/${sessionId}/approve`, "POST", "Session approved", "Approve failed");
  });

  rejectBtn.addEventListener("click", async () => {
    await doAction(`/api/v1/admin/kyc/sessions/${sessionId}/reject`, "POST", "Session rejected", "Reject failed");
  });

} else {
  // For any other status (if any), still allow admins to approve/reject both ways
  const approveBtn = document.createElement("button");
  approveBtn.className = "primary";
  approveBtn.textContent = "Approve";
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "ghost";
  rejectBtn.textContent = "Reject";
  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);

  approveBtn.addEventListener("click", async () => {
    await doAction(`/api/v1/admin/kyc/sessions/${sessionId}/approve`, "POST", "Session approved", "Approve failed");
  });

  rejectBtn.addEventListener("click", async () => {
    await doAction(`/api/v1/admin/kyc/sessions/${sessionId}/reject`, "POST", "Session rejected", "Reject failed");
  });
}

/* Append action bar only when it has content */
if (actions.children.length > 0) {
  body.appendChild(actions);
}

  } catch (err) {
    console.error(err);
    body.innerHTML = `<div class="muted">Failed to load detail.</div>`;
  }
}


  function getCurrentFilters() {
    const f = {};
    if (fStatus && fStatus.value) f.status = fStatus.value;
    if (fDoc && fDoc.value) f.doc_type = fDoc.value;

    if (fDate && fDate.value) {
      // fDate.value is in local YYYY-MM-DD. We build UTC range covering that day.
      // Construct start-of-day UTC and end-of-day UTC ISO strings.
      const parts = fDate.value.split('-'); // [YYYY,MM,DD]
      if (parts.length === 3) {
        const y = Number(parts[0]), m = Number(parts[1]) - 1, d = Number(parts[2]);
        // created_from = 00:00:00 UTC of that date
        const createdFrom = new Date(Date.UTC(y, m, d, 0, 0, 0)).toISOString();
        // created_to = 23:59:59 UTC of that date
        const createdTo = new Date(Date.UTC(y, m, d, 23, 59, 59)).toISOString();
        f.created_from = createdFrom;
        f.created_to = createdTo;
      }
    }
    return f;
  }


  btnApply.addEventListener('click', () => loadSessions(getCurrentFilters()));
  btnReset.addEventListener('click', () => {
  fStatus.value = '';
  fDoc.value = '';
  if (fDate) fDate.value = '';
  loadSessions({});
});


  // initial load
  loadSessions({});
}

/* ================== STARTUP ================== */
boot();
