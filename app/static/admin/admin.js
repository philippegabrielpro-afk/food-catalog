"use strict";
// This pilot uses a shared admin key, in memory only. No browser persistence.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = {key: "", epoch: 0, query: "", offset: 0, total: 0, limit: 30, food: null, dirty: false, searchVersion: 0, detailVersion: 0};
  let noticeTimer;
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const date = (value) => new Date(value).toLocaleString("fr-FR");
  const number = (value) => Number(value).toLocaleString("fr-FR", {maximumFractionDigits: 4});
  function nutrition(ref) {
    if (!ref || ref.qualifier === "missing") return "Non renseigné";
    if (ref.qualifier === "traces") return "Traces";
    return `${ref.qualifier === "less_than" ? "< " : ""}${number(ref.carbs_per_100g)} g/100 g`;
  }
  function notify(message, error = false) {
    clearTimeout(noticeTimer);
    $("#notice").textContent = message;
    $("#notice").classList.remove("hidden");
    $("#notice").classList.toggle("error", error);
    noticeTimer = setTimeout(() => $("#notice").classList.add("hidden"), error ? 12000 : 6000);
  }
  function errorMessage(error) { if (error.name !== "AbortError") notify(error.message, true); }
  function leaveEditor() {
    return !state.dirty || window.confirm("Vous avez des changements non enregistrés. Les abandonner ?");
  }
  function logout() {
    state.key = ""; state.epoch++; state.searchVersion++; state.detailVersion++; state.food = null; state.dirty = false;
    $("#admin-key").value = "";
    $("#workspace").classList.add("hidden"); $("#logout").classList.add("hidden");
    $("#login-panel").classList.remove("hidden");
    ["#food-list", "#editor", "#import-list", "#audit-list", "#import-result"].forEach((selector) => $(selector).replaceChildren());
    $("#admin-key").focus();
  }
  async function api(path, options = {}) {
    const epoch = state.epoch;
    const response = await fetch(`/v1/admin${path}`, {...options, credentials: "omit", cache: "no-store", headers: {"X-API-Key": state.key, "Content-Type": "application/json"}});
    if (epoch !== state.epoch) throw new DOMException("Session terminée", "AbortError");
    if (response.status === 401) { logout(); throw new Error("Clé invalide ou session expirée. Reconnectez-vous."); }
    const data = await response.json();
    if (epoch !== state.epoch) throw new DOMException("Session terminée", "AbortError");
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((item) => `${item.loc.slice(1).join(".")} : ${item.msg}`).join(" · ") : data.detail;
      throw new Error(detail || `Erreur ${response.status}`);
    }
    return data;
  }
  async function busy(button, callback) {
    button.disabled = true;
    try { await callback(); } catch (error) { errorMessage(error); } finally { button.disabled = false; }
  }
  async function loadFoods() {
    const version = ++state.searchVersion;
    $("#food-count").textContent = "Chargement…";
    const page = await api(`/foods?q=${encodeURIComponent(state.query)}&offset=${state.offset}&limit=${state.limit}`);
    if (version !== state.searchVersion) return;
    state.total = page.total;
    $("#food-count").textContent = `${page.total.toLocaleString("fr-FR")} aliment${page.total === 1 ? "" : "s"}`;
    $("#food-list").innerHTML = page.items.length ? page.items.map((food) => `<button type="button" class="food-item${state.food?.id === food.id ? " selected" : ""}" data-food-id="${escape(food.id)}"><strong>${escape(food.canonical_name)}</strong><small>${escape(nutrition(food.reference))} · ${escape(food.reference?.source || "Sans référence")}</small></button>`).join("") : '<p class="empty">Aucun aliment trouvé. Essayez un terme plus simple ou créez une fiche.</p>';
    $("#previous").disabled = state.offset === 0;
    $("#next").disabled = state.offset + state.limit >= page.total;
    $("#page-label").textContent = page.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, page.total)}` : "0";
  }
  function input(name, label, value = "", options = "", full = false) {
    return `<div class="field${full ? " full" : ""}"><label for="field-${name}">${label}</label><input id="field-${name}" name="${name}" value="${escape(value)}" ${options}></div>`;
  }
  function referenceFields(ref = {}) {
    const manual = (ref.source || "").toLowerCase() !== "ciqual";
    return `<div class="form-grid">
      ${input("source", "Source de la nouvelle valeur", manual ? ref.source || "manual" : "manual", 'required minlength="2" maxlength="80"')}
      ${input("source_version", "Nouvelle version (unique pour ce code)", "", 'required maxlength="80" placeholder="Ex. 2026-09-17 ou 2"')}
      ${input("external_code", "Code de référence (facultatif)", manual ? ref.external_code || "" : "", 'maxlength="80" placeholder="Vide : code interne automatique"', true)}
      ${input("carbs_per_100g", "Glucides pour 100 g", ref.carbs_per_100g ?? "", 'type="number" min="0" max="100" step="any"')}
      <div class="field"><label for="field-qualifier">Qualification</label><select id="field-qualifier" name="qualifier"><option value="exact">Valeur numérique</option><option value="less_than">Inférieur à la valeur</option><option value="traces">Traces (sans valeur numérique)</option><option value="missing">Non renseigné</option></select></div>
      ${input("raw_value", "Valeur telle que publiée (facultatif)", "", 'maxlength="80" placeholder="Ex. 32,9 ou &lt; 0,5"', true)}
      ${input("source_url", "Lien de provenance (http/https)", "", 'type="url" maxlength="1000"', true)}
      ${input("license_name", "Licence (facultatif)", "", 'maxlength="120"', true)}
    </div>`;
  }
  function renderEditor(food) {
    state.food = food; state.dirty = false;
    const ref = food?.reference;
    $("#editor").innerHTML = `<div class="editor-heading"><span class="eyebrow">${food ? "Fiche aliment" : "Création"}</span><h2>${escape(food?.canonical_name || "Un nouvel aliment")}</h2><p>${food ? `Dernière modification : ${escape(date(food.updated_at))}` : "Un aliment générique, sans contexte personnel ni médical."}</p></div>
      <form id="metadata-form"><div class="form-grid">
        ${input("canonical_name", "Nom de l’aliment", food?.canonical_name || "", 'required minlength="2" maxlength="300"', true)}
        ${input("group_name", "Catégorie", food?.group_name || "", 'maxlength="180"')}
        ${input("subgroup_name", "Sous-catégorie", food?.subgroup_name || "", 'maxlength="180"')}
        <div class="field full"><label for="field-aliases">Synonymes · un par ligne</label><textarea id="field-aliases" name="aliases" placeholder="Riz maison&#10;Riz basmati cuit">${escape((food?.aliases || []).join("\n"))}</textarea></div>
        <div class="field full"><label for="field-tags">Tags · un par ligne</label><textarea id="field-tags" name="tags" placeholder="cuit&#10;céréales">${escape((food?.tags || []).join("\n"))}</textarea></div>
      </div>${food ? '<div class="form-actions"><button class="primary" type="submit">Enregistrer les libellés</button></div>' : `<div class="reference-section"><h3>Première référence nutritionnelle</h3><p class="hint">Ne saisissez pas une correction personnelle. La source Ciqual est réservée à l’import officiel.</p>${referenceFields()}</div><div class="form-actions"><button class="primary" type="submit">Créer l’aliment</button></div>`}</form>
      ${food ? `<section class="reference-section"><h3>Référence utilisée par défaut</h3><div class="reference-summary"><strong>${escape(nutrition(ref))}</strong><p>${escape(ref?.source || "Sans source")} · ${escape(ref?.source_version || "—")} · Code ${escape(ref?.external_code || "—")}</p></div><p class="reference-note">Les valeurs publiées ne sont pas écrasées. Une correction générique crée une nouvelle version, utilisée par défaut. Les références Ciqual restent consultables.</p><button id="show-reference-form" class="secondary" type="button">+ Ajouter une nouvelle valeur</button><form id="reference-form" class="reference-form hidden"><h3>Nouvelle référence</h3>${referenceFields(ref)}<div class="form-actions"><button id="cancel-reference" class="secondary" type="button">Annuler</button><button class="primary" type="submit">Ajouter cette version</button></div></form><div class="reference-history"><h3>Historique des valeurs · ${food.references.length} version(s)</h3>${food.references.map((item) => `<article class="reference-card"><div class="reference-top"><strong>${escape(nutrition(item))}</strong>${item.preferred ? '<span class="badge">Utilisée par défaut</span>' : `<button class="secondary" type="button" data-prefer="${escape(item.id)}">Utiliser par défaut</button>`}</div><p>${escape(item.source)} · version ${escape(item.source_version)} · code ${escape(item.external_code)}</p><p>Valeur brute : ${escape(item.raw_value || "—")} · ${escape(date(item.created_at))}</p><p>Licence : ${escape(item.license_name || "Non renseignée")}${item.source_url && /^https?:\/\//.test(item.source_url) ? ` · <a href="${escape(item.source_url)}" target="_blank" rel="noopener noreferrer">Provenance</a>` : ""}</p></article>`).join("")}</div><button id="food-audit" class="quiet" type="button">Voir le journal de cette fiche</button><div id="food-audit-list"></div></section>` : ""}`;
    $("#metadata-form").addEventListener("submit", saveMetadata);
    $("#editor").querySelectorAll("input, textarea, select").forEach((element) => element.addEventListener("input", () => {state.dirty = true;}));
    if (!food) { $("#field-source_version").value = "1"; return; }
    $("#show-reference-form").addEventListener("click", () => { $("#reference-form").classList.remove("hidden"); $("#field-source_version").focus(); });
    $("#cancel-reference").addEventListener("click", () => {
      if (leaveEditor()) renderEditor(state.food);
    });
    $("#reference-form").addEventListener("submit", saveReference);
    $("#food-audit").addEventListener("click", (event) => busy(event.target, async () => renderAudit($("#food-audit-list"), await api(`/audit?food_id=${food.id}`))));
  }
  function metadataPayload(form) {
    const data = new FormData(form);
    return {canonical_name: data.get("canonical_name").trim(), group_name: data.get("group_name").trim() || null, subgroup_name: data.get("subgroup_name").trim() || null, aliases: data.get("aliases").split("\n").map((value) => value.trim()).filter(Boolean), tags: data.get("tags").split("\n").map((value) => value.trim()).filter(Boolean)};
  }
  function referencePayload(form) {
    const data = new FormData(form);
    const value = data.get("carbs_per_100g").trim();
    const qualifier = data.get("qualifier");
    if (["exact", "less_than"].includes(qualifier) && value === "") throw new Error("Indiquez une valeur numérique, ou choisissez « Non renseigné ».");
    if (["missing", "traces"].includes(qualifier) && value !== "") throw new Error("Effacez la valeur numérique pour « Traces » ou « Non renseigné ».");
    return {source: data.get("source").trim(), source_version: data.get("source_version").trim(), external_code: data.get("external_code").trim() || null, carbs_per_100g: value === "" ? null : Number(value), qualifier, raw_value: data.get("raw_value").trim(), source_url: data.get("source_url").trim() || null, license_name: data.get("license_name").trim() || null};
  }
  async function saveMetadata(event) {
    event.preventDefault();
    const form = event.target;
    await busy(form.querySelector('[type="submit"]'), async () => {
      const creating = !state.food;
      const payload = {...metadataPayload(form), ...(creating ? referencePayload(form) : {})};
      if (!window.confirm(creating ? "Créer cet aliment et sa référence dans le catalogue générique ?" : "Enregistrer ces libellés et tags ? Les valeurs nutritionnelles restent inchangées.")) return;
      const saved = await api(creating ? "/foods" : `/foods/${state.food.id}`, {method: creating ? "POST" : "PATCH", body: JSON.stringify(payload)});
      const food = creating ? await api(`/foods/${saved.id}`) : saved;
      renderEditor(food);
      notify(creating ? "Aliment créé." : "Libellés enregistrés. Références conservées.");
      await loadFoods();
    });
  }
  async function saveReference(event) {
    event.preventDefault();
    const form = event.target;
    await busy(form.querySelector('[type="submit"]'), async () => {
      const payload = referencePayload(form);
      if (!window.confirm(`Ajouter la version « ${payload.source_version} » (${nutrition(payload)}) et l’utiliser par défaut ? Les versions précédentes seront conservées. Les changements de libellés non enregistrés seront abandonnés.`)) return;
      renderEditor(await api(`/foods/${state.food.id}/references`, {method: "POST", body: JSON.stringify(payload)}));
      notify("Nouvelle version ajoutée. Historique conservé."); await loadFoods();
    });
  }
  async function loadImports() {
    const imports = await api("/imports");
    $("#import-list").innerHTML = imports.length ? `<table><thead><tr><th>Source / version</th><th>État</th><th>Aliments</th><th>Date</th><th>SHA-256 du fichier</th></tr></thead><tbody>${imports.map((item) => `<tr><td>${escape(item.source)}<br>${escape(item.source_version)}</td><td>${escape(item.status)}</td><td>${escape(item.row_count)}</td><td>${escape(date(item.imported_at))}</td><td class="hash">${escape(item.file_sha256)}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucun import terminé.</p>';
  }
  const actionNames = {food_created: "Aliment créé", food_updated: "Fiche et référence mises à jour", metadata_updated: "Libellés modifiés", reference_added: "Nouvelle référence ajoutée", preferred_reference_changed: "Référence par défaut changée", ciqual_import_requested: "Import Ciqual demandé"};
  function renderAudit(container, entries) {
    container.innerHTML = entries.length ? entries.map((item) => `<article class="audit-entry"><strong>${escape(actionNames[item.action] || item.action)}</strong><p>${escape(item.after.canonical_name || item.after.source || "Catalogue")} · ${escape(date(item.created_at))} · Clé d’administration partagée</p><details><summary>Voir les données avant / après</summary><pre>${escape(JSON.stringify({avant: item.before, apres: item.after}, null, 2))}</pre></details></article>`).join("") : '<p class="empty">Aucune action enregistrée.</p>';
  }
  async function tab(name) {
    if (name !== "catalog" && !leaveEditor()) return;
    if (name !== "catalog" && state.dirty) renderEditor(state.food);
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("hidden", view.id !== `${name}-view`));
    document.querySelectorAll(".tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
    if (name === "imports") await loadImports();
    if (name === "audit") renderAudit($("#audit-list"), await api("/audit"));
  }
  $("#login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    busy(event.target.querySelector("button"), async () => {
      if (location.protocol !== "https:" && !["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)) throw new Error("Connexion bloquée : utilisez HTTPS pour transmettre la clé.");
      state.key = $("#admin-key").value.trim(); $("#admin-key").value = ""; state.epoch++;
      try { state.query = ""; state.offset = 0; $("#search").value = ""; await loadFoods(); }
      catch (error) { logout(); throw error; }
      $("#login-panel").classList.add("hidden"); $("#workspace").classList.remove("hidden"); $("#logout").classList.remove("hidden");
      $("#editor").innerHTML = '<div class="empty-editor"><span class="eyebrow">Chaque détail compte</span><h2>Choisissez un aliment</h2><p>Consultez ses références ou enrichissez ses synonymes et ses tags.</p></div>';
      await tab("catalog");
    });
  });
  $("#logout").addEventListener("click", () => {if (leaveEditor()) logout();});
  $("#search-form").addEventListener("submit", (event) => {event.preventDefault(); state.query = $("#search").value.trim(); state.offset = 0; busy(event.target.querySelector("button"), loadFoods);});
  $("#refresh-foods").addEventListener("click", (event) => busy(event.target, loadFoods));
  $("#previous").addEventListener("click", () => {state.offset = Math.max(0, state.offset - state.limit); loadFoods().catch(errorMessage);});
  $("#next").addEventListener("click", () => {if (state.offset + state.limit < state.total) {state.offset += state.limit; loadFoods().catch(errorMessage);}});
  $("#food-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-food-id]");
    if (!button || !leaveEditor()) return;
    const version = ++state.detailVersion;
    busy(button, async () => {
      const food = await api(`/foods/${button.dataset.foodId}`);
      if (version !== state.detailVersion) return;
      renderEditor(food); await loadFoods();
      if (window.innerWidth < 850) $("#editor").scrollIntoView({behavior: "smooth"});
    });
  });
  $("#new-food").addEventListener("click", async () => {if (leaveEditor()) {state.detailVersion++; await tab("catalog"); renderEditor(null); $("#field-canonical_name").focus();}});
  $("#editor").addEventListener("click", (event) => {
    const button = event.target.closest("[data-prefer]");
    if (!button || !leaveEditor()) return;
    busy(button, async () => {
      if (!window.confirm("Utiliser cette référence par défaut ? Aucune valeur historique ne sera modifiée.")) return;
      renderEditor(await api(`/foods/${state.food.id}/references/${button.dataset.prefer}/prefer`, {method: "POST"}));
      notify("Référence par défaut modifiée."); await loadFoods();
    });
  });
  document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => tab(button.dataset.tab).catch(errorMessage)));
  $("#import-ciqual").addEventListener("click", (event) => busy(event.target, async () => {
    if (!window.confirm("Importer le fichier Ciqual fourni avec cette version ? Le premier chargement peut prendre plusieurs secondes. Ne relancez pas pendant l’import.")) return;
    $("#import-result").textContent = "Import en cours…";
    try {
      const result = await api("/imports/ciqual", {method: "POST"});
      $("#import-result").innerHTML = `<p class="import-feedback">${escape(result.source)} ${escape(result.source_version)} : ${result.duplicate ? "déjà importé, aucun doublon créé" : `${result.rows} lignes · ${result.foods_created} créations · ${result.foods_updated} mises à jour`}.</p>`;
      await loadImports(); await loadFoods();
    } catch (error) { $("#import-result").textContent = "Import non confirmé. Consultez l’erreur, puis vérifiez l’historique avant de relancer."; throw error; }
  }));
  $("#refresh-audit").addEventListener("click", (event) => busy(event.target, async () => renderAudit($("#audit-list"), await api("/audit"))));
  window.addEventListener("beforeunload", (event) => {if (state.dirty) {event.preventDefault(); event.returnValue = "";}});
  window.addEventListener("pagehide", logout);
})();
