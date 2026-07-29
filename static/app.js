/* ===========================================================
   Αρχείο Αποδείξεων — λογική διεπαφής
   =========================================================== */

const state = {
  businesses: [],
  categories: [],
  current: null,        // κλειδί τρέχουσας επιχείρησης
  editingId: null,      // id απόδειξης σε επεξεργασία (ή null για νέα)
};

const PROVIDERS = {
  gmail:   { host: "imap.gmail.com",            port: 993 },
  outlook: { host: "outlook.office365.com",     port: 993 },
  yahoo:   { host: "imap.mail.yahoo.com",       port: 993 },
  custom:  { host: "",                          port: 993 },
};

const $ = (id) => document.getElementById(id);

/* ---------- Βοηθητικά ---------- */
function money(v) {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("el-GR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
}
function esc(s) {
  return (s ?? "").toString().replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  // επανεκκίνηση της μικρής κίνησης εμφάνισης
  t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => t.classList.add("hidden"), 3200);
}

/* Φιλική «σχετική» ημερομηνία: σήμερα / χθες / πριν X μέρες */
function relDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - d) / 86400000);
  if (diff === 0) return "σήμερα";
  if (diff === 1) return "χθες";
  if (diff > 1 && diff < 7) return `πριν ${diff} μέρες`;
  return "";
}
function showLoader(text) { $("loaderText").textContent = text || "Παρακαλώ περιμένετε…"; $("loader").classList.remove("hidden"); }
function hideLoader() { $("loader").classList.add("hidden"); }

/* Είναι ενεργό κάποιο φίλτρο/αναζήτηση; (η ταξινόμηση δεν μετράει) */
function filtersActive() {
  return !!($("search").value || $("filterCategory").value || $("filterYear").value);
}
function toggleClearSearch() {
  $("clearSearch").classList.toggle("hidden", !$("search").value);
}
function clearFilters() {
  $("search").value = "";
  $("filterCategory").value = "";
  $("filterYear").value = "";
  toggleClearSearch();
  loadReceipts();
}

async function api(url, opts) {
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error(data.error || "Σφάλμα διακομιστή");
  return data;
}

/* ---------- Αρχικοποίηση ---------- */
async function init() {
  const cfg = await api("/api/config");
  state.businesses = cfg.businesses;
  state.categories = cfg.categories;
  state.current = cfg.businesses[0].key;

  // tabs επιχειρήσεων
  const tabs = $("bizTabs");
  tabs.innerHTML = "";
  cfg.businesses.forEach(b => {
    const el = document.createElement("button");
    el.className = "biz-tab" + (b.key === state.current ? " active" : "");
    el.dataset.key = b.key;
    el.innerHTML = `<span class="biz-name">${esc(b.name)}</span><span class="tab-count" data-count="${b.key}"></span>`;
    el.onclick = () => switchBusiness(b.key);
    tabs.appendChild(el);
  });

  // datalist κατηγοριών + φίλτρο
  const dl = $("categoryList"); dl.innerHTML = "";
  const fc = $("filterCategory");
  state.categories.forEach(c => {
    dl.insertAdjacentHTML("beforeend", `<option value="${esc(c)}">`);
    fc.insertAdjacentHTML("beforeend", `<option value="${esc(c)}">${esc(c)}</option>`);
  });

  // διαδρομή αρχείων (καθησυχαστικό για τον χρήστη — ξέρει πού ζουν τα δεδομένα)
  if (cfg.data_dir) {
    const dp = $("dataPath");
    dp.textContent = cfg.data_dir;
    dp.title = "Άνοιγμα φακέλου: " + cfg.data_dir;
    dp.onclick = openDataFolder;
  }

  bindEvents();
  await refresh();
}

function switchBusiness(key) {
  state.current = key;
  document.querySelectorAll(".biz-tab").forEach((el, i) => {
    el.classList.toggle("active", state.businesses[i].key === key);
  });
  $("search").value = "";
  $("filterCategory").value = "";
  $("filterYear").value = "";
  refresh();
}

/* ---------- Φόρτωση λίστας ---------- */
async function refresh() {
  await Promise.all([loadReceipts(), loadPending()]);
}

async function updateCounts() {
  try {
    const counts = await api("/api/counts");
    document.querySelectorAll(".tab-count").forEach(sp => {
      const n = counts[sp.dataset.count] || 0;
      sp.textContent = n ? n : "";
    });
  } catch (e) { /* σιωπηλά */ }
}

async function loadReceipts() {
  const params = new URLSearchParams({
    business: state.current,
    q: $("search").value,
    category: $("filterCategory").value,
    year: $("filterYear").value,
    sort: $("sortBy").value,
  });
  const data = await api("/api/receipts?" + params);

  // ενημέρωση φίλτρου ετών (χωρίς να χαλάσει η επιλογή)
  const fy = $("filterYear");
  const cur = fy.value;
  fy.innerHTML = '<option value="">Όλα τα έτη</option>';
  data.years.forEach(y => fy.insertAdjacentHTML("beforeend", `<option value="${esc(y)}">${esc(y)}</option>`));
  fy.value = cur;

  // στατιστικά
  $("stats").innerHTML = `
    <div class="stat-card"><div class="num">${data.count}</div><div class="lbl">Αποδείξεις (με τα φίλτρα)</div></div>
    <div class="stat-card"><div class="num">${money(data.total)}</div><div class="lbl">Σύνολο ποσών</div></div>
  `;

  // ανάλυση ανά κατηγορία
  const bd = $("breakdown"), body = $("breakdownBody");
  const cats = data.by_category || [];
  if (cats.length > 1) {
    body.innerHTML = cats.map(c => `
      <div class="bd-row"><span class="bd-cat">${esc(c.category)}</span>
      <span class="bd-amt">${money(c.total)}</span></div>`).join("");
    bd.classList.remove("hidden");
  } else {
    bd.classList.add("hidden");
  }

  // κουμπί «Καθαρισμός φίλτρων» — μόνο όταν υπάρχει ενεργό φίλτρο
  const active = filtersActive();
  $("btnClearFilters").classList.toggle("hidden", !active);
  toggleClearSearch();

  const grid = $("grid");
  grid.innerHTML = "";
  const emptyEl = $("empty");
  if (data.items.length === 0) {
    emptyEl.innerHTML = active
      ? `<div class="empty-ico">🔎</div>
         <h2>Δεν βρέθηκαν αποδείξεις με αυτά τα φίλτρα</h2>
         <p>Οι αποδείξεις σας είναι ασφαλείς — απλώς κρύβονται από την αναζήτηση/τα φίλτρα.
            Πατήστε το κουμπί για να τις δείτε ξανά όλες.</p>
         <div class="empty-actions"><button class="btn btn-primary" id="emptyClear">✕ Καθαρισμός φίλτρων</button></div>`
      : `<div class="empty-ico">🧾</div>
         <h2>Δεν υπάρχουν αποδείξεις εδώ ακόμη</h2>
         <p>Πατήστε «＋ Νέα Απόδειξη» για να προσθέσετε μια φωτογραφία ή αρχείο, ή «✉️ Λήψη από Email».</p>
         <div class="empty-actions"><button class="btn btn-primary" id="emptyAdd">＋ Νέα Απόδειξη</button></div>`;
    emptyEl.classList.remove("hidden");
    const ec = $("emptyClear"); if (ec) ec.onclick = clearFilters;
    const ea = $("emptyAdd"); if (ea) ea.onclick = openAdd;
  } else {
    emptyEl.classList.add("hidden");
    data.items.forEach(r => grid.appendChild(renderCard(r)));
  }
  updateCounts();
}

function renderCard(r) {
  const div = document.createElement("div");
  div.className = "card";
  const thumb = r.has_thumb
    ? `<div class="card-thumb" style="background-image:url('/api/receipts/${r.id}/thumb')"></div>`
    : `<div class="card-thumb">🧾</div>`;
  const srcLabel = r.source === "email" ? "Email" : (r.source === "scan" ? "Σκανάρισμα" : "");
  const srcTag = srcLabel ? `<span class="tag-source">${srcLabel}</span>` : "";
  div.innerHTML = `
    <div class="card-thumb-wrap">${thumb}${srcTag}</div>
    <div class="card-body">
      <p class="card-vendor">${esc(r.vendor) || "—"}</p>
      <p class="card-meta">📅 ${esc(r.receipt_date) || "—"}${relDate(r.receipt_date) ? ` <span class="rel">· ${relDate(r.receipt_date)}</span>` : ""}</p>
      ${r.category ? `<p class="card-meta"><span class="chip">${esc(r.category)}</span></p>` : ""}
      <p class="card-amount">${money(r.amount)}</p>
    </div>
    <div class="card-actions">
      <button class="btn btn-ghost btn-small" data-act="open">Άνοιγμα</button>
      <button class="btn btn-secondary btn-small" data-act="pdf">📄 PDF</button>
      <button class="btn btn-ghost btn-small" data-act="edit" aria-label="Επεξεργασία" title="Επεξεργασία">✏️</button>
      <button class="btn btn-ghost btn-small" data-act="del" aria-label="Διαγραφή" title="Διαγραφή">🗑️</button>
    </div>`;
  div.querySelector('[data-act="open"]').onclick = () => openReceipt(r.id);
  div.querySelector('[data-act="pdf"]').onclick = () => exportReceipt(r.id);
  div.querySelector('[data-act="edit"]').onclick = () => openEdit(r);
  div.querySelector('[data-act="del"]').onclick = () => deleteReceipt(r);
  // κλικ στη μικρογραφία = άνοιγμα της απόδειξης (η αναμενόμενη κίνηση)
  const wrap = div.querySelector(".card-thumb-wrap");
  wrap.classList.add("clickable");
  wrap.title = "Άνοιγμα απόδειξης";
  wrap.onclick = () => openReceipt(r.id);
  return div;
}

async function openReceipt(id) {
  try { await api(`/api/receipts/${id}/open`, { method: "POST" }); }
  catch (e) { toast(e.message, true); }
}

async function exportReceipt(id) {
  try {
    showLoader("Δημιουργία PDF…");
    await api(`/api/receipts/${id}/export`, { method: "POST" });
    hideLoader();
    toast("Το PDF δημιουργήθηκε και άνοιξε — μπορείτε να το εκτυπώσετε ή να το αποθηκεύσετε.");
  } catch (e) { hideLoader(); toast(e.message, true); }
}

async function deleteReceipt(r) {
  if (!confirm(`Διαγραφή της απόδειξης «${r.vendor || "χωρίς όνομα"}»;\nΑυτό δεν αναιρείται.`)) return;
  try {
    await api(`/api/receipts/${r.id}`, { method: "DELETE" });
    toast("Η απόδειξη διαγράφηκε.");
    loadReceipts();
  } catch (e) { toast(e.message, true); }
}

/* ---------- Προσθήκη / Επεξεργασία ---------- */
function setChosenFile(f) {
  const dt = new DataTransfer();
  dt.items.add(f);
  $("file").files = dt.files;
  const el = $("dzChosen");
  el.textContent = "📎 " + f.name;
  el.classList.remove("hidden");
}

function clearChosenFile() {
  $("file").value = "";
  $("dzChosen").textContent = "";
  $("dzChosen").classList.add("hidden");
}

function openAdd() {
  state.editingId = null;
  $("receiptModalTitle").textContent = "Νέα Απόδειξη";
  $("fileField").classList.remove("hidden");
  clearChosenFile();
  $("receiptId").value = "";
  $("vendor").value = "";
  $("date").value = new Date().toISOString().slice(0, 10);
  $("amount").value = "";
  $("category").value = "";
  $("notes").value = "";
  $("receiptSubmit").textContent = "Αποθήκευση";
  $("modalReceipt").classList.remove("hidden");
  setTimeout(() => $("vendor").focus(), 60);
}

function openEdit(r) {
  state.editingId = r.id;
  $("receiptModalTitle").textContent = "Επεξεργασία Απόδειξης";
  $("fileField").classList.add("hidden");   // δεν αλλάζουμε το αρχείο εδώ
  $("receiptId").value = r.id;
  $("vendor").value = r.vendor || "";
  $("date").value = r.receipt_date || "";
  $("amount").value = r.amount != null ? String(r.amount).replace(".", ",") : "";
  $("category").value = r.category || "";
  $("notes").value = r.notes || "";
  $("receiptSubmit").textContent = "Αποθήκευση αλλαγών";
  $("modalReceipt").classList.remove("hidden");
  setTimeout(() => $("vendor").focus(), 60);
}

async function submitReceipt(e) {
  e.preventDefault();
  const vendor = $("vendor").value.trim();
  const date = $("date").value;
  const amount = $("amount").value.trim();
  const category = $("category").value.trim();
  const notes = $("notes").value.trim();

  const btn = $("receiptSubmit");
  if (btn.disabled) return;           // αποφυγή διπλής υποβολής
  btn.disabled = true;
  try {
    if (state.editingId) {
      await api(`/api/receipts/${state.editingId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor, date, amount, category, notes }),
      });
      toast("Οι αλλαγές αποθηκεύτηκαν.");
    } else {
      const file = $("file").files[0];
      if (!file) { toast("Επιλέξτε πρώτα ένα αρχείο ή φωτογραφία.", true); return; }

      // προειδοποίηση για πιθανό διπλότυπο (ίδια ημερομηνία + ποσό)
      if (amount) {
        try {
          const p = new URLSearchParams({ business: state.current, date, amount });
          const dup = await api("/api/check-duplicate?" + p);
          if (dup.duplicate) {
            const who = dup.vendor ? ` («${dup.vendor}»)` : "";
            if (!confirm(`Υπάρχει ήδη απόδειξη με ίδια ημερομηνία (${date}) και ποσό (${amount} €)${who}.\n\nΝα προστεθεί κι αυτή;`)) return;
          }
        } catch (e) { /* αν αποτύχει ο έλεγχος, συνεχίζουμε κανονικά */ }
      }

      const fd = new FormData();
      fd.append("file", file);
      fd.append("business", state.current);
      fd.append("vendor", vendor);
      fd.append("date", date);
      fd.append("amount", amount);
      fd.append("category", category);
      fd.append("notes", notes);
      showLoader("Αποθήκευση απόδειξης…");
      await api("/api/receipts", { method: "POST", body: fd });
      hideLoader();
      toast("Η απόδειξη αρχειοθετήθηκε.");
    }
    closeModals();
    loadReceipts();
  } catch (err) { hideLoader(); toast(err.message, true); }
  finally { btn.disabled = false; }
}

/* ---------- Ρυθμίσεις Email ---------- */
async function openEmailSettings() {
  const data = await api("/api/email-settings?business=" + state.current);
  $("host").value = data.host || "";
  $("port").value = data.port || 993;
  $("username").value = data.username || "";
  $("folder").value = data.folder || "INBOX";
  $("sinceDays").value = data.since_days || 30;
  $("password").value = "";
  $("password").placeholder = data.has_password
    ? "•••••• (αποθηκευμένος — αφήστε κενό για να τον κρατήσετε)"
    : "Κωδικός ή App Password";
  // μάντεψε πάροχο
  let prov = "custom";
  for (const [k, v] of Object.entries(PROVIDERS)) if (v.host && v.host === data.host) prov = k;
  $("provider").value = prov;
  $("modalEmail").classList.remove("hidden");
}

function onProviderChange() {
  const p = PROVIDERS[$("provider").value];
  if (p && p.host) { $("host").value = p.host; $("port").value = p.port; }
}

async function submitEmailSettings(e) {
  e.preventDefault();
  try {
    await api("/api/email-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        business: state.current,
        host: $("host").value.trim(),
        port: $("port").value,
        username: $("username").value.trim(),
        password: $("password").value,
        folder: $("folder").value.trim(),
        since_days: $("sinceDays").value,
      }),
    });
    toast("Οι ρυθμίσεις email αποθηκεύτηκαν.");
    closeModals();
  } catch (err) { toast(err.message, true); }
}

async function syncEmail() {
  try {
    showLoader("Σύνδεση με το email και λήψη…");
    const data = await api("/api/email-sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business: state.current }),
    });
    hideLoader();
    if (data.new > 0) {
      toast(`Βρέθηκαν ${data.new} νέα παραστατικά — πατήστε «Έλεγχος τώρα».`);
    } else {
      toast("Δεν βρέθηκαν νέα παραστατικά.");
    }
    loadPending();
  } catch (e) {
    hideLoader();
    if (e.message.includes("ρυθμίσεις")) { toast(e.message, true); openEmailSettings(); }
    else toast(e.message, true);
  }
}

/* ---------- Προς έλεγχο (pending) ---------- */
async function loadPending() {
  const data = await api("/api/pending?business=" + state.current);
  const banner = $("pendingBanner");
  if (data.count > 0) {
    $("pendingCount").textContent = data.count;
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
  return data;
}

async function openReview() {
  const data = await api("/api/pending?business=" + state.current);
  const list = $("reviewList");
  list.innerHTML = "";
  if (data.count === 0) {
    list.innerHTML = '<p class="hint">Δεν υπάρχουν παραστατικά προς έλεγχο.</p>';
  }
  $("btnClearAllPending").classList.toggle("hidden", data.count === 0);
  const catOptions = state.categories.map(c => `<option value="${esc(c)}">`).join("");
  data.items.forEach(p => {
    const item = document.createElement("div");
    item.className = "review-item";
    item.innerHTML = `
      <div class="review-head">
        📨 Από: <b>${esc(p.from_addr) || "—"}</b> · Θέμα: ${esc(p.subject) || "—"} · Αρχείο: ${esc(p.original_name)}
        &nbsp;<a href="/api/pending/${p.id}/preview" target="_blank" rel="noopener">προβολή</a>
      </div>
      <div class="review-grid">
        <div class="field"><label>Προμηθευτής</label><input data-f="vendor" value="${esc(p.suggested_vendor)}"></div>
        <div class="field"><label>Ημερομηνία</label><input data-f="date" type="date" value="${esc(p.email_date)}"></div>
        <div class="field"><label>Ποσό (€)</label><input data-f="amount" inputmode="decimal" placeholder="π.χ. 54,20"></div>
        <div class="field"><label>Κατηγορία</label><input data-f="category" list="reviewCats"></div>
      </div>
      <datalist id="reviewCats">${catOptions}</datalist>
      <div class="review-actions">
        <button class="btn btn-primary" data-act="approve">✅ Αρχειοθέτηση</button>
        <button class="btn btn-ghost" data-act="discard">🗑️ Απόρριψη</button>
      </div>`;
    item.querySelector('[data-act="approve"]').onclick = () => approvePending(p.id, item);
    item.querySelector('[data-act="discard"]').onclick = () => discardPending(p.id, item);
    list.appendChild(item);
  });
  $("modalReview").classList.remove("hidden");
}

async function approvePending(pid, item) {
  const get = (f) => item.querySelector(`[data-f="${f}"]`).value;
  try {
    await api(`/api/pending/${pid}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vendor: get("vendor"), date: get("date"),
        amount: get("amount"), category: get("category"),
      }),
    });
    item.remove();
    toast("Αρχειοθετήθηκε.");
    loadReceipts(); loadPending();
    if (!$("reviewList").querySelector(".review-item")) closeModals();
  } catch (e) { toast(e.message, true); }
}

async function clearAllPending() {
  if (!confirm("Απόρριψη ΟΛΩΝ των παραστατικών που περιμένουν έλεγχο;\nΔεν θα ξαναληφθούν από το email.")) return;
  try {
    const d = await api("/api/pending/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business: state.current }),
    });
    toast(`Απορρίφθηκαν ${d.removed} παραστατικά.`);
    closeModals();
    loadPending();
  } catch (e) { toast(e.message, true); }
}

async function discardPending(pid, item) {
  if (!confirm("Απόρριψη αυτού του παραστατικού; Δεν θα ξαναληφθεί από το email.")) return;
  try {
    await api(`/api/pending/${pid}/discard`, { method: "POST" });
    item.remove();
    loadPending();
    if (!$("reviewList").querySelector(".review-item")) closeModals();
  } catch (e) { toast(e.message, true); }
}

/* ---------- Αντίγραφο ασφαλείας / Φάκελος ---------- */
async function backupData() {
  try {
    showLoader("Επιλέξτε πού θα αποθηκευτεί το αντίγραφο…");
    const data = await api("/api/backup", { method: "POST" });
    hideLoader();
    if (data.cancelled) return;
    const n = (data.count != null) ? `${data.count} αποδείξεις · ` : "";
    toast(`✅ Το αντίγραφο ασφαλείας ολοκληρώθηκε (${n}αποθηκεύτηκε στον φάκελο που επιλέξατε).`);
  } catch (e) { hideLoader(); toast(e.message, true); }
}

async function openDataFolder() {
  try { await api("/api/open-data-folder", { method: "POST" }); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Εξαγωγή όλων σε ένα PDF ---------- */
async function exportAll() {
  try {
    showLoader("Δημιουργία συγκεντρωτικού PDF…");
    const data = await api("/api/export-bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        business: state.current,
        q: $("search").value,
        category: $("filterCategory").value,
        year: $("filterYear").value,
      }),
    });
    hideLoader();
    toast(`📚 Έτοιμο! Ένα PDF με ${data.count} αποδείξεις δημιουργήθηκε και άνοιξε.`);
  } catch (e) { hideLoader(); toast(e.message, true); }
}

/* ---------- Modals ---------- */
function closeModals() {
  document.querySelectorAll(".modal").forEach(m => m.classList.add("hidden"));
}

/* ---------- Σύνδεση γεγονότων ---------- */
function bindEvents() {
  $("btnAdd").onclick = openAdd;
  $("btnSync").onclick = syncEmail;
  $("btnBackup").onclick = backupData;
  $("btnOpenFolder").onclick = openDataFolder;
  $("btnExportAll").onclick = exportAll;
  $("btnEmailSettings").onclick = openEmailSettings;
  $("btnReview").onclick = openReview;
  $("btnClearAllPending").onclick = clearAllPending;
  $("btnClearFilters").onclick = clearFilters;
  $("clearSearch").onclick = () => { $("search").value = ""; toggleClearSearch(); loadReceipts(); $("search").focus(); };
  $("receiptForm").onsubmit = submitReceipt;
  $("emailForm").onsubmit = submitEmailSettings;
  $("provider").onchange = onProviderChange;

  let searchTimer;
  $("search").oninput = () => { toggleClearSearch(); clearTimeout(searchTimer); searchTimer = setTimeout(loadReceipts, 250); };
  $("filterCategory").onchange = loadReceipts;
  $("filterYear").onchange = loadReceipts;
  $("sortBy").onchange = loadReceipts;

  document.querySelectorAll("[data-close]").forEach(b => b.onclick = closeModals);
  document.querySelectorAll(".modal").forEach(m => {
    m.addEventListener("click", (e) => { if (e.target === m) closeModals(); });
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });

  // δείξε το επιλεγμένο αρχείο
  $("file").onchange = () => {
    const f = $("file").files[0];
    if (f) setChosenFile(f); else clearChosenFile();
  };

  // Μνήμη κατηγορίας ανά προμηθευτή: μόλις γραφτεί ο προμηθευτής, προτείνει
  // την κατηγορία που είχε χρησιμοποιηθεί την τελευταία φορά (μόνο σε νέα απόδειξη).
  $("vendor").addEventListener("blur", async () => {
    if (state.editingId) return;
    const v = $("vendor").value.trim();
    if (!v || $("category").value.trim()) return;
    try {
      const d = await api("/api/suggest-category?" + new URLSearchParams({ business: state.current, vendor: v }));
      if (d.category && !$("category").value.trim()) {
        $("category").value = d.category;
        $("category").classList.add("autofilled");
        setTimeout(() => $("category").classList.remove("autofilled"), 1400);
      }
    } catch (e) { /* σιωπηλά */ }
  });

  // Μεταφορά & απόθεση (drag & drop)
  const dz = $("dropzone");
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.remove("drag");
  }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) setChosenFile(f);
  });

  // Επικόλληση εικόνας (Ctrl+V) όταν είναι ανοιχτή η φόρμα νέας απόδειξης
  document.addEventListener("paste", (e) => {
    if ($("modalReceipt").classList.contains("hidden") || state.editingId) return;
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const it of items) {
      if (it.type && it.type.startsWith("image/")) {
        const blob = it.getAsFile();
        if (blob) {
          const ext = (it.type.split("/")[1] || "png").replace("jpeg", "jpg");
          setChosenFile(new File([blob], `apo_proxeiro_${Date.now()}.${ext}`, { type: it.type }));
          toast("Η εικόνα από το πρόχειρο προστέθηκε.");
          e.preventDefault();
        }
        break;
      }
    }
  });
}

init().catch(e => { hideLoader(); toast("Σφάλμα εκκίνησης: " + e.message, true); });
