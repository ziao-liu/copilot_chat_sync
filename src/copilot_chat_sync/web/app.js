"use strict";

const byId = (identifier) => document.getElementById(identifier);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const icon = (name, extra = "") => `<i data-lucide="${name}" ${extra}></i>`;
const number = (value) => new Intl.NumberFormat("en").format(value ?? 0);
const storageKey = `copilot-chat-sync-token:${location.origin}`;
function tokenFromFragment() {
    try {
        return new URLSearchParams(decodeURIComponent(location.hash.slice(1))).get("token");
    } catch {
        return null;
    }
}
const initialToken = tokenFromFragment();
let token = initialToken || sessionStorage.getItem(storageKey) || "";
if (initialToken) {
    sessionStorage.setItem(storageKey, token);
    history.replaceState(null, "", location.pathname);
}

const state = { snapshot: null, selected: null, view: "sync", mode: "push", busy: false, choices: {}, preview: null, setup: null, scope: null, collapsed: new Set() };
const actionLabels = { init: "Setup", bindings: "Workspaces", push: "Send", pull: "Receive", migrate: "Old setup", repair: "Repair", resolve: "Resolve", restore: "Restore" };
let toastTimer;
let planTimer;

function icons() {
    if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.65, "aria-hidden": "true" } });
}

function badge(label, kind = "neutral") {
    return `<span class="badge ${kind}">${escapeHtml(label)}</span>`;
}

function workspaceParts(workspace) {
    try {
        const parsed = new URL(workspace.uri);
        return { host: decodeURIComponent(parsed.host).replace(/^ssh-remote\+/, "") || "Local folder", path: decodeURIComponent(parsed.pathname) };
    } catch {
        return { host: "Workspace", path: workspace.uri };
    }
}

function decodedUri(uri) {
    try { return decodeURIComponent(uri); }
    catch { return uri; }
}

function workspaceTree(workspaces) {
    const connections = new Map();
    const makeNode = (key, label, path, kind) => ({ key, label, path, kind, children: new Map(), workspaces: [] });
    for (const workspace of workspaces) {
        let connection, host, segments, local = false, absolute = true;
        try {
            const parsed = new URL(workspace.uri);
            const authority = decodeURIComponent(parsed.host);
            connection = JSON.stringify([parsed.protocol, authority]);
            local = parsed.protocol === "file:" && !authority;
            host = local ? "This computer" : workspaceParts(workspace).host;
            segments = parsed.pathname.split("/").filter(Boolean).map(decodedUri);
            absolute = parsed.pathname.startsWith("/") && !(local && /^[a-zA-Z]:$/.test(segments[0] || ""));
        } catch {
            connection = "unknown";
            host = "Other workspaces";
            segments = [workspace.uri];
            absolute = false;
        }
        if (!connections.has(connection)) connections.set(connection, makeNode(connection, host, host, local ? "local" : "connection"));
        let parent = connections.get(connection);
        for (let index = 0; index < segments.length; index += 1) {
            const segment = segments[index];
            if (!parent.children.has(segment)) {
                const path = (absolute ? "/" : "") + segments.slice(0, index + 1).join("/");
                parent.children.set(segment, makeNode(JSON.stringify([connection, ...segments.slice(0, index + 1)]), index === 0 && absolute ? "/" + segment : segment, path, "folder"));
            }
            parent = parent.children.get(segment);
        }
        parent.workspaces.push(workspace);
    }
    const compare = (left, right) => left.label.localeCompare(right.label, "en", { numeric: true, sensitivity: "variant" });
    function finish(node) {
        let label = node.label;
        while (node.kind === "folder" && !node.workspaces.length && node.children.size === 1) {
            const child = [...node.children.values()][0];
            if (child.workspaces.length) break;
            label += "/" + child.label;
            node = child;
        }
        const children = [...node.children.values()].sort(compare).map(finish);
        const entries = [...node.workspaces].sort((left, right) => left.id.localeCompare(right.id));
        return { key: node.key, label, path: node.path, kind: node.kind, children, workspaces: entries,
            ids: [...entries.map((workspace) => workspace.id), ...children.flatMap((child) => child.ids)] };
    }
    return [...connections.values()].sort(compare).map(finish);
}

function workspaceSelection(workspaces, selection, field) {
    const ids = workspaces.filter((workspace) => field === "select" ? workspace.bound && !workspace.missing : !workspace.missing || selection.has(workspace.id)).map((workspace) => workspace.id);
    const selected = ids.filter((identifier) => selection.has(identifier)).length;
    return { ids, checked: ids.length > 0 && selected === ids.length, partial: selected > 0 && selected < ids.length, disabled: !ids.length };
}

function applyWorkspaceSelection(workspaces, selection, identifiers, checked, field) {
    const allowed = new Set(workspaceSelection(workspaces, selection, field).ids);
    for (const identifier of identifiers) {
        if (!allowed.has(identifier)) continue;
        if (checked) selection.add(identifier);
        else selection.delete(identifier);
    }
}

function dateLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Unknown date";
    return date.toLocaleString("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function setBusy(value) {
    state.busy = value;
    byId("refresh").disabled = value;
    byId("diagnostics").disabled = value || !state.snapshot?.configured;
    byId("modal-close").disabled = value;
    byId("modal").setAttribute("aria-busy", String(value));
    for (const button of document.querySelectorAll("#modal-actions button")) {
        button.disabled = value || button.dataset.blocked === "true";
    }
    if (state.snapshot?.configured) refreshWorkspaceSelection();
    else updateHandoff();
    for (const root of byId("modal-body").querySelectorAll("[data-workspace-tree]")) updateTreeSelection(root);
}

function showError(error) {
    byId("error-message").textContent = error.message || String(error);
    byId("error-banner").hidden = false;
    toast(error.message || String(error));
}

function toast(message) {
    clearTimeout(toastTimer);
    byId("toast").textContent = message;
    byId("toast").hidden = false;
    toastTimer = setTimeout(() => { byId("toast").hidden = true; }, 7000);
}

async function api(path, data) {
    const response = await fetch(path, {
        method: data === undefined ? "GET" : "POST",
        headers: { "Authorization": `Bearer ${token}`, ...(data === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(data === undefined ? {} : { body: JSON.stringify(data) }),
        cache: "no-store",
    });
    const payload = await response.json();
    if (response.status === 401) {
        byId("access").hidden = false;
        byId("content").hidden = true;
        byId("loading").hidden = true;
    }
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    return payload;
}

async function task(work) {
    if (state.busy) return;
    setBusy(true);
    byId("error-banner").hidden = true;
    try {
        await work();
    } catch (error) {
        byId("loading").hidden = true;
        showError(error);
    } finally {
        setBusy(false);
        icons();
    }
}

async function loadState() {
    const snapshot = await api("/api/state");
    state.snapshot = snapshot;
    const bound = snapshot.workspaces.filter((workspace) => workspace.bound && !workspace.missing).map((workspace) => workspace.id);
    state.selected = state.selected === null ? new Set(bound) : new Set([...state.selected].filter((identifier) => bound.includes(identifier)));
    byId("loading").hidden = true;
    byId("access").hidden = true;
    byId("content").hidden = false;
    byId("demo-badge").hidden = !snapshot.demo;
    byId("hostname").textContent = snapshot.demo ? "Demo workstation" : snapshot.hostname;
    byId("hostname").title = snapshot.hostname;
    byId("sidebar-version").textContent = `v${snapshot.version}`;
    byId("footer-version").textContent = snapshot.version;
    byId("group-name").textContent = snapshot.config?.store.split(/[\\/]/).filter(Boolean).pop() || "Local configuration";
    byId("group-name").title = snapshot.config?.store || snapshot.config_path;
    const running = snapshot.code_processes.length > 0;
    byId("code-state").className = `status-item ${running || !snapshot.process_check_ok ? "warning" : "good"}`;
    byId("code-state").innerHTML = `${icon(running ? "code-xml" : snapshot.process_check_ok ? "circle-check" : "circle-alert")}${running ? "VS Code running / writes blocked" : snapshot.process_check_ok ? "VS Code closed" : "Process check unavailable"}`;
    const alertCount = snapshot.issues.length;
    byId("alerts-button").hidden = alertCount === 0;
    byId("alert-label").textContent = `${number(alertCount)} alert${alertCount === 1 ? "" : "s"}`;
    byId("conflict-count").textContent = number(snapshot.conflicts.length);
    byId("conflict-count").hidden = snapshot.conflicts.length === 0;
    byId("setup").hidden = snapshot.configured;
    byId("main-navigation").hidden = !snapshot.configured;
    byId("diagnostics").hidden = !snapshot.configured;
    if (!snapshot.configured) {
        if (!byId("store-path").value) byId("store-path").value = snapshot.defaults.store;
        if (!byId("storage-path").value) byId("storage-path").value = snapshot.defaults.storage;
        byId("setup-config").textContent = snapshot.config_path;
        if (!byId("store-path").value || !byId("storage-path").value) byId("setup-advanced").open = true;
        updateSetupLocations();
    } else {
        renderMetrics();
        renderWorkspaces();
        renderConflicts();
        renderBackups();
        renderSettings();
        renderActivity();
    }
    selectView(state.view);
    icons();
}

function updateSetupLocations() {
    byId("setup-store").textContent = byId("store-path").value.trim() || "Choose a shared folder";
    byId("setup-storage").textContent = byId("storage-path").value.trim() || "Choose the local VS Code data folder";
}

function selectView(view) {
    state.view = view;
    for (const button of document.querySelectorAll("[data-view]")) {
        const active = button.dataset.view === view;
        button.classList.toggle("active", active);
        if (active) button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
    }
    const names = { sync: ["LOCAL & SHARED", "Synchronization"], conflicts: ["REVIEW & RESOLVE", "Conflicts"], backups: ["LOCAL RECOVERY", "Backups"], settings: ["SCOPE & IDENTITY", "Settings"] };
    const labels = names[view];
    byId("view-eyebrow").textContent = state.snapshot?.configured === false ? "STEP 1 OF 3" : labels[0];
    byId("view-title").textContent = state.snapshot?.configured === false ? "Set up sync" : labels[1];
    for (const section of document.querySelectorAll(".view")) section.hidden = section.id !== `view-${view}` || !state.snapshot?.configured;
}

function renderMetrics() {
    const snapshot = state.snapshot;
    const shared = snapshot.shared || {};
    const bound = snapshot.workspaces.filter((workspace) => workspace.bound);
    byId("metric-sessions").textContent = number(shared.sessions);
    byId("metric-revisions").textContent = `${number(shared.revisions)} retained revisions`;
    byId("metric-workspaces").textContent = number(bound.length);
    byId("metric-hosts").textContent = `${number(new Set(bound.map((workspace) => workspaceParts(workspace).host)).size)} host entries`;
    byId("metric-writers").textContent = number(shared.writers?.length);
    byId("metric-conflicts").textContent = number(snapshot.conflicts.length);
    byId("metric-conflicts").classList.toggle("has-conflicts", snapshot.conflicts.length > 0);
    byId("metric-conflict-state").textContent = snapshot.conflicts.length ? "Awaiting a version choice" : "No competing histories";
}

function filteredWorkspaces() {
    const search = byId("workspace-search").value.trim().toLowerCase();
    const filter = byId("workspace-filter").value;
    return (state.snapshot?.workspaces || []).filter((workspace) =>
        decodedUri(workspace.uri).toLowerCase().includes(search) &&
        (filter === "all" || (filter === "bound" ? workspace.bound : !workspace.bound)));
}

function workspaceTreeMarkup(workspaces, selection, field) {
    const detailed = field === "select";
    const searching = detailed && Boolean(byId("workspace-search").value.trim());
    function leaf(workspace, label, depth, duplicate = false) {
        const parts = workspaceParts(workspace);
        let status = "";
        if (workspace.missing) status = badge("Unavailable", "danger");
        else if (detailed && !workspace.bound) status = badge("Not selected");
        else if (workspace.linked) status = badge("Old link", "warning");
        else if (workspace.editing_snapshots) status = badge("Snapshots", "warning");
        else if (detailed) status = badge("Ready", "good");
        const metadata = detailed ? `<span class="tree-number" data-label="Chats">${number(workspace.sessions)}</span><span class="tree-number" data-label="Indexed">${workspace.indexed === undefined ? "-" : number(workspace.indexed)}</span><span class="tree-status">${status}</span>` : `<span class="tree-chat-count">${number(workspace.sessions)} chats</span>${status}`;
        return `<li><label class="tree-row tree-leaf tree-level-${Math.min(depth, 4)}" title="${escapeHtml(workspace.uri)}"><span class="tree-spacer"></span><input type="checkbox" data-${field}="${escapeHtml(workspace.id)}" aria-label="Select ${escapeHtml(parts.host)} ${escapeHtml(parts.path)}${duplicate ? " " + escapeHtml(workspace.id) : ""}" ${selection.has(workspace.id) ? "checked" : ""}>${icon("folder")}<span class="tree-name"><strong>${escapeHtml(label)}</strong>${duplicate ? `<small>${escapeHtml(workspace.id)}</small>` : ""}</span><span class="tree-meta">${metadata}</span></label></li>`;
    }
    function branch(node, depth, host) {
        if (node.kind === "folder" && !node.children.length && node.workspaces.length === 1) return leaf(node.workspaces[0], node.label, depth);
        const key = JSON.stringify([field, node.key]);
        const own = node.workspaces.map((workspace, index) => leaf(workspace, node.workspaces.length > 1 ? `Workspace ${index + 1}` : "This folder", depth + 1, node.workspaces.length > 1)).join("");
        return `<li><details class="workspace-branch ${node.kind === "folder" ? "" : "tree-connection"}" data-tree-key="${escapeHtml(key)}" data-search-open="${searching}" ${searching || !state.collapsed.has(key) ? "open" : ""}><summary class="tree-row tree-group-row tree-level-${Math.min(depth, 4)}" title="${escapeHtml(node.path)}"><span class="tree-toggle">${icon("chevron-right")}</span><input type="checkbox" data-tree-members="${escapeHtml(JSON.stringify(node.ids))}" aria-label="Select available workspaces in ${escapeHtml(host)} ${escapeHtml(node.path)}">${icon(node.kind === "folder" ? "folder" : node.kind === "local" ? "laptop" : "server")}<span class="tree-name">${escapeHtml(node.label)}</span><span class="tree-count" title="${node.ids.length} workspaces">${number(node.ids.length)}</span></summary><ul>${own}${node.children.map((child) => branch(child, depth + 1, host)).join("")}</ul></details></li>`;
    }
    return `<ul class="workspace-tree ${detailed ? "" : "compact-tree"}" data-workspace-tree="${field}">${workspaceTree(workspaces).map((node) => branch(node, 0, node.label)).join("")}</ul>`;
}

function treeContext(field) {
    if (field === "select") return { rows: filteredWorkspaces(), selected: state.selected };
    if (field === "scope") return { rows: state.snapshot.workspaces, selected: state.scope };
    return { rows: state.setup.workspaces, selected: state.setup.selected };
}

function updateTreeSelection(root) {
    if (!root) return;
    const field = root.dataset.workspaceTree;
    const context = treeContext(field);
    const rows = new Map(context.rows.map((workspace) => [workspace.id, workspace]));
    for (const input of root.querySelectorAll('input[type="checkbox"]')) {
        const identifier = input.getAttribute("data-" + field);
        const members = identifier === null ? JSON.parse(input.dataset.treeMembers) : [identifier];
        const status = workspaceSelection(members.map((member) => rows.get(member)).filter(Boolean), context.selected, field);
        input.checked = identifier === null ? status.checked : context.selected.has(identifier);
        input.indeterminate = identifier === null && status.partial;
        input.disabled = state.busy || status.disabled;
        input.closest(".tree-row").classList.toggle("is-selected", identifier !== null && input.checked);
    }
}

function refreshWorkspaceSelection() {
    const status = workspaceSelection(filteredWorkspaces(), state.selected, "select");
    byId("select-all").disabled = state.busy || status.disabled;
    byId("select-all").checked = status.checked;
    byId("select-all").indeterminate = status.partial;
    updateTreeSelection(byId("workspace-rows").querySelector("[data-workspace-tree]"));
    updateHandoff();
}

function changeTreeSelection(event) {
    const input = event.target;
    const root = input.closest("[data-workspace-tree]");
    if (!root || input.type !== "checkbox") return;
    const field = root.dataset.workspaceTree;
    const context = treeContext(field);
    const identifier = input.getAttribute("data-" + field);
    const members = identifier === null ? JSON.parse(input.dataset.treeMembers) : [identifier];
    if (!state.busy) applyWorkspaceSelection(context.rows, context.selected, members, input.checked, field);
    if (field === "select") refreshWorkspaceSelection();
    else {
        updateTreeSelection(root);
        if (field === "setup-scope") {
            const button = byId("review-setup");
            button.dataset.blocked = String(!context.selected.size);
            button.disabled = state.busy || !context.selected.size;
        }
    }
}

function rememberTreeExpansion(event) {
    const branch = event.target;
    if (!branch.isConnected || !branch.matches("details[data-tree-key]") || branch.dataset.searchOpen === "true") return;
    if (branch.open) state.collapsed.delete(branch.dataset.treeKey);
    else state.collapsed.add(branch.dataset.treeKey);
}

function expandWorkspaceTree(open) {
    for (const branch of byId("workspace-rows").querySelectorAll("details[data-tree-key]")) {
        branch.open = open;
        rememberTreeExpansion({ target: branch });
    }
}

function renderWorkspaces() {
    const rows = filteredWorkspaces();
    byId("workspace-total").textContent = number(state.snapshot.workspaces.length);
    byId("workspace-rows").innerHTML = workspaceTreeMarkup(rows, state.selected, "select");
    byId("workspace-empty").hidden = rows.length > 0;
    const unconfigured = !state.snapshot.workspaces.some((workspace) => workspace.bound && !workspace.missing);
    byId("workspace-empty-title").textContent = unconfigured ? "No workspaces selected" : "No matching workspaces";
    byId("empty-choose").hidden = !unconfigured;
    byId("clear-filter").hidden = unconfigured;
    byId("expand-workspaces").disabled = !rows.length;
    byId("collapse-workspaces").disabled = !rows.length;
    byId("scan-time").textContent = `Refreshed ${new Date().toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit" })}`;
    refreshWorkspaceSelection();
    icons();
}

function updateHandoff() {
    const selected = state.selected?.size || 0;
    byId("selection-count").textContent = `${number(selected)} selected`;
    byId("handoff-count").textContent = number(selected);
    const push = state.mode === "push";
    byId("route-source").textContent = push ? "This device" : "Sync folder";
    byId("route-target").textContent = push ? "Sync folder" : "This device";
    byId("route-source-icon").outerHTML = icon(push ? "laptop" : "cloud", 'id="route-source-icon"');
    byId("route-target-icon").outerHTML = icon(push ? "cloud" : "laptop", 'id="route-target-icon"');
    byId("detach-row").hidden = push;
    const linked = state.snapshot?.workspaces.some((workspace) => workspace.linked && state.selected?.has(workspace.id));
    byId("migration-notice").hidden = !linked;
    const button = byId("preview-handoff");
    button.innerHTML = `${state.busy ? '<span class="spinner"></span>' : icon("scan-eye")}<span>${state.busy ? "Working" : `Review ${push ? "send" : "receive"}`}</span>`;
    for (const identifier of ["preview-handoff", "preview-repair", "preview-migrate", "prepare-links"]) byId(identifier).disabled = state.busy || !selected;
    if (linked) button.disabled = true;
    for (const mode of document.querySelectorAll("[data-mode]")) {
        mode.classList.toggle("selected", mode.dataset.mode === state.mode);
        mode.setAttribute("aria-pressed", String(mode.dataset.mode === state.mode));
    }
    const writeState = state.snapshot?.demo ? "Read-only demo" : state.snapshot?.code_processes.length ? "VS Code must be closed" : "Confirmation required";
    byId("write-state").innerHTML = `${icon("lock-keyhole")}<span>${writeState}</span>`;
    icons();
}

function renderActivity() {
    const entries = state.snapshot.activity;
    byId("activity-list").innerHTML = entries.length ? entries.map((entry, index) =>
        `<div class="activity-row">${icon(entry.status === "error" ? "circle-alert" : "circle-check")}<strong>${escapeHtml(actionLabels[entry.action] || entry.action)}</strong><button class="text-button result" data-activity="${index}">${escapeHtml(entry.status === "error" ? entry.result : operationSummary(entry.result))}</button><time>${dateLabel(entry.time)}</time></div>`).join("") : `<div class="empty-activity">${icon("history")}<span>No operations in this panel session</span></div>`;
}

function operationSummary(result) {
    if (result.operation === "push") return `${number(result.published ?? result.would_publish)} sent to sync folder / ${number(result.unchanged)} unchanged`;
    if (result.operation === "bindings") return `${number(result.bound)} workspaces selected`;
    if (result.operation === "resolve") return "Version selected; other histories retained";
    if (result.operation === "init") return `${number(result.bound)} workspaces connected`;
    if (result.operation === "migrate") return `${number(result.workspaces.reduce((total, workspace) => total + workspace.files, 0))} chats retained / ${number(result.workspaces.length)} links detached`;
    return `${number(result.files)} files / ${number(result.indexes ?? result.databases)} indexes`;
}

function empty(iconName, text) {
    return `<div class="empty-state">${icon(iconName)}<h3>${escapeHtml(text)}</h3></div>`;
}

function renderConflicts() {
    const conflicts = state.snapshot.conflicts;
    byId("conflict-total").textContent = `${number(conflicts.length)} session${conflicts.length === 1 ? "" : "s"}`;
    byId("conflict-list").innerHTML = conflicts.length ? conflicts.map((conflict) => {
        const chosen = state.choices[conflict.session];
        return `<article class="conflict-item"><div class="conflict-header">${icon("git-fork")}<code>${escapeHtml(conflict.session)}</code>${badge(`${conflict.heads.length} versions`, "warning")}</div>${conflict.heads.map((head, index) =>
            `<div class="revision-row"><label><input type="radio" name="revision-${conflict.session}" data-choice="${conflict.session}" value="${head.revision}" ${chosen === head.revision ? "checked" : ""}><div><strong>Version ${index + 1} <span class="muted">/ ${number(head.requests)} turns</span></strong><small>${dateLabel(head.last_message_date)} / writer ${escapeHtml(head.writer.slice(0, 8))}</small><small title="${head.revision}">${head.revision.slice(0, 16)}</small></div></label><div class="revision-actions"><button class="icon-button" data-revision="${head.revision}" data-session="${conflict.session}" title="Read version ${index + 1}" aria-label="Read version ${index + 1}">${icon("eye")}</button><button class="icon-button" data-download="${head.revision}" data-session="${conflict.session}" title="Download version ${index + 1} JSON" aria-label="Download version ${index + 1} JSON">${icon("download")}</button></div></div>`).join("")}<div class="conflict-footer"><button class="button secondary" data-resolve="${conflict.session}" ${!chosen ? "disabled" : ""}>${icon("git-merge")}Preview resolution</button></div></article>`;
    }).join("") : empty("git-merge", "No competing histories");
}

function renderBackups() {
    const backups = [...state.snapshot.backups].reverse();
    byId("backup-total").textContent = `${number(backups.length)} retained`;
    byId("backup-list").innerHTML = backups.length ? backups.map((backup) => {
        const date = backup.id.slice(0, 8);
        const timestamp = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}T${backup.id.slice(9, 11)}:${backup.id.slice(11, 13)}:${backup.id.slice(13, 15)}Z`;
        const kind = backup.migrations ? "Link migration" : backup.files ? "Conversation import" : "Index snapshot";
        return `<div class="backup-row">${icon("archive")}<div class="backup-identity"><strong>${dateLabel(timestamp)}</strong><code>${escapeHtml(backup.id)}</code></div><div class="backup-counts">${escapeHtml(kind)}<br>${number(backup.files)} files / ${number(backup.databases)} indexes</div><div>${badge(backup.status, backup.status === "complete" ? "good" : backup.status === "restored" ? "neutral" : "warning")}</div><button class="button secondary" data-restore="${backup.id}">${icon("rotate-ccw")}Preview restore</button></div>`;
    }).join("") : empty("archive", "No local recovery snapshots");
}

function renderSettings() {
    const snapshot = state.snapshot;
    const values = [["Configuration file", snapshot.config_path], ["Shared store", snapshot.config.store], ["Workspace storage", snapshot.config.storage], ["This device ID", snapshot.config.device]];
    byId("config-details").innerHTML = values.map(([label, value], index) => `<div class="config-row"><dt>${label}</dt><dd>${escapeHtml(value)}</dd><button class="icon-button" data-copy-config="${index}" title="Copy ${label.toLowerCase()}" aria-label="Copy ${label.toLowerCase()}">${icon("copy")}</button></div>`).join("");
    byId("writers-list").innerHTML = (snapshot.shared?.writers || []).map((writer) => `<div class="writer-row">${icon("laptop")}<code>${escapeHtml(writer)}</code>${badge(writer === snapshot.config.device ? "This device" : "Historical writer", writer === snapshot.config.device ? "good" : "neutral")}</div>`).join("") || empty("laptop", "No revision writers recorded");
}

function closeDialog() {
    if (state.busy) return;
    clearInterval(planTimer);
    state.preview = null;
    byId("modal").close();
}

function dialog(title, body, actions = [], eyebrow = "REVIEW") {
    clearInterval(planTimer);
    byId("modal-title").textContent = title;
    byId("modal-eyebrow").textContent = eyebrow;
    byId("modal-body").innerHTML = body;
    byId("modal-actions").replaceChildren();
    for (const action of actions) {
        const button = document.createElement("button");
        button.className = `button ${action.primary ? "primary" : "secondary"}`;
        button.innerHTML = `${action.icon ? icon(action.icon) : ""}${escapeHtml(action.label)}`;
        button.dataset.blocked = String(Boolean(action.disabled));
        button.disabled = Boolean(action.disabled);
        if (action.id) button.id = action.id;
        button.addEventListener("click", action.run);
        byId("modal-actions").append(button);
    }
    if (!byId("modal").open) byId("modal").showModal();
    for (const root of byId("modal-body").querySelectorAll("[data-workspace-tree]")) updateTreeSelection(root);
    icons();
}

function detailDisclosure(data) {
    return `<details><summary>Raw result</summary><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre></details>`;
}

function showScope() {
    if (state.busy || !state.snapshot?.configured) return;
    scopeDialog();
}

function scopeRows(rows, selection, field) {
    return `<div class="scope-list">${workspaceTreeMarkup(rows, selection, field)}</div>`;
}

function scopeDialog() {
    const rows = state.snapshot.workspaces;
    state.scope = new Set(rows.filter((workspace) => workspace.bound).map((workspace) => workspace.id));
    const body = rows.length ? scopeRows(rows, state.scope, "scope") : empty("folder-search", "No workspaces discovered");
    dialog("Choose workspaces", body, [{ label: "Cancel", run: closeDialog }, { label: "Review selection", primary: true, icon: "scan-eye", run: () => {
        const workspaces = [...document.querySelectorAll("[data-scope]:checked")].map((input) => input.dataset.scope);
        preview({ action: "bindings", workspaces });
    } }], "THIS COMPUTER");
}

function setupScopeDialog() {
    state.preview = null;
    const setup = state.setup;
    const body = setup.workspaces.length ? scopeRows(setup.workspaces, setup.selected, "setup-scope") : empty("folder-search", "No workspaces found in this VS Code installation");
    const warnings = setup.issues.map((issue) => `<div class="notice warning">${icon("circle-alert")}<span>${escapeHtml(issue)}</span></div>`).join("");
    dialog("Choose workspaces", body + warnings, [{ label: "Back", run: closeDialog }, { label: "Scan again", icon: "refresh-cw", run: scanSetup }, {
        label: "Review setup", id: "review-setup", icon: "arrow-right", primary: true, disabled: !setup.selected.size,
        run: () => preview({ action: "init", store: setup.store, storage: setup.storage, workspaces: [...setup.selected] }),
    }], "STEP 2 OF 3");
}

function scanSetup() {
    task(async () => {
        dialog("Finding workspaces", '<div class="loading-state"><span class="spinner"></span>Reading this computer</div>', [], "READ ONLY");
        const store = byId("store-path").value.trim();
        const storage = byId("storage-path").value.trim();
        try {
            const scanned = await api("/api/scan", { storage });
            const previous = state.setup?.storage === storage ? state.setup.selected : new Set();
            const selected = new Set(scanned.workspaces.filter((workspace) => previous.has(workspace.id)).map((workspace) => workspace.id));
            state.setup = { store, storage, workspaces: scanned.workspaces, issues: scanned.issues, selected };
            setupScopeDialog();
        } catch (error) {
            byId("setup-advanced").open = true;
            dialog("Cannot read workspaces", `<div class="notice error">${icon("circle-alert")}<span>${escapeHtml(error.message)}</span></div>`, [{ label: "Back", run: closeDialog }], "NO CHANGES APPLIED");
        }
    });
}

function planBody(plan, options) {
    const result = plan.result;
    const metrics = [];
    for (const [key, label] of [["would_publish", "New revisions"], ["unchanged", "Unchanged"], ["files", "Conversation files"], ["indexes", "Indexes"], ["databases", "Indexes"], ["editing_snapshots_to_quarantine", "Snapshots quarantined"], ["bound", "Selected workspaces"], ["migrations", "Link migrations"]]) {
        if (typeof result[key] === "number") metrics.push([label, result[key]]);
    }
    if (Array.isArray(result.added)) metrics.push(["Added to scope", result.added.length]);
    if (Array.isArray(result.removed)) metrics.push(["Removed from scope", result.removed.length]);
    if (options.action === "migrate") metrics.push(["Old links", result.workspaces.length], ["Chats retained", result.workspaces.reduce((total, workspace) => total + workspace.files, 0)]);
    let content = metrics.length ? `<div class="plan-grid">${metrics.map(([label, value]) => `<div class="plan-metric"><span>${label}</span><strong>${number(value)}</strong></div>`).join("")}</div>` : "";
    if (options.workspaces?.length) {
        const selected = options.action === "init" ? result.bindings : state.snapshot.workspaces.filter((workspace) => options.workspaces.includes(workspace.id));
        content += `<ul class="plan-list">${selected.map((workspace) => { const parts = workspaceParts(workspace); return `<li>${icon("server")}<span>${escapeHtml(parts.host)}<br><span class="muted">${escapeHtml(parts.path)}</span></span></li>`; }).join("")}</ul>`;
    }
    if (options.action === "init") content += `<ul class="plan-list"><li>${icon("cloud")}<span>${escapeHtml(result.store)}</span></li><li>${icon("folder")}<span>${escapeHtml(result.storage)}</span></li></ul>`;
    if (result.linked) content += `<div class="notice warning">${icon("unlink")}<span>${number(result.linked)} selected workspaces still use old shared links. Migration is required before sending or receiving.</span></div>`;
    if (options.action === "migrate") content += `<div class="notice warning">${icon("unlink")}<span>Previous sync/link scripts must be stopped on every computer before applying. Existing shared files are retained.</span></div>`;
    if (options.action === "resolve") content += `<div class="notice warning">${icon("git-fork")}<span>The selected version becomes the shared head. Other revisions stay archived.<br>${escapeHtml(options.revision.slice(0, 20))}</span></div>`;
    if (options.action === "restore") content += `<div class="notice warning">${icon("rotate-ccw")}<span>Restore chat files and index keys from ${escapeHtml(options.backup)}. Editing checkpoints remain quarantined.</span></div>`;
    if (result.conflicts?.length) content += `<div class="notice warning">${icon("git-fork")}<span>${result.conflicts.length} competing histories. Both versions will be retained.</span></div>`;
    if (plan.needs_acknowledgement) content += `<label class="checkbox-row"><input type="checkbox" id="acknowledge"><span>I accept losing access to the affected chat undo / checkpoints. Current project code is not restored.</span></label>`;
    if (plan.read_only) content += `<div class="notice warning">${icon("eye")}<span>Demo data. Applying changes is disabled.</span></div>`;
    else if (state.snapshot.code_processes.length || !state.snapshot.process_check_ok) content += `<div class="notice warning">${icon("lock-keyhole")}<span>VS Code is running or its process state is unavailable. Apply is blocked.</span></div>`;
    content += `<div id="plan-expiry" class="small muted">Preview valid for 2 minutes</div>${detailDisclosure(result)}`;
    return content;
}

function preview(options) {
    task(async () => {
        dialog("Preparing preview", '<div class="loading-state"><span class="spinner"></span>Checking local and shared state</div>', [], "PREFLIGHT");
        let plan;
        try {
            plan = await api("/api/preview", options);
        } catch (error) {
            const actions = [{ label: "Close", run: closeDialog }];
            if (["pull", "repair"].includes(options.action) && !options.detach && error.message.includes("Editing snapshots")) {
                actions.push({ label: "Preview with quarantine", icon: "shield-alert", primary: true, run: () => preview({ ...options, detach: true }) });
            }
            dialog("Preview blocked", `<div class="notice error">${icon("circle-alert")}<span>${escapeHtml(error.message)}</span></div>`, actions, "NO CHANGES APPLIED");
            return;
        }
        state.preview = { ...plan, options, deadline: Date.now() + plan.expires_in * 1000 };
        const labels = { push: "Review send", pull: "Review receive", init: "Review setup", bindings: "Review workspaces", repair: "Review index repair", migrate: "Review link migration", resolve: "Review resolution", restore: "Review restoration" };
        const blocked = plan.read_only || state.snapshot.code_processes.length > 0 || !state.snapshot.process_check_ok || plan.needs_acknowledgement;
        const setup = options.action === "init" && state.setup;
        dialog(labels[options.action], planBody(plan, options), [{ label: setup ? "Back" : "Cancel", run: setup ? setupScopeDialog : closeDialog },
            { label: plan.read_only ? "Read-only demo" : "Confirm & apply", id: "confirm-apply", primary: true, icon: "check", disabled: blocked, run: applyPlan }], setup ? "STEP 3 OF 3 / NO CHANGES YET" : "PREVIEW / NO CHANGES YET");
        byId("acknowledge")?.addEventListener("change", updateConfirmation);
        planTimer = setInterval(updateConfirmation, 1000);
    });
}

function updateConfirmation() {
    const plan = state.preview;
    if (!plan || !byId("confirm-apply")) return;
    const seconds = Math.max(0, Math.ceil((plan.deadline - Date.now()) / 1000));
    byId("plan-expiry").textContent = seconds ? `Preview expires in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}` : "Preview expired. Close and preview again.";
    const blocked = !seconds || plan.read_only || state.snapshot.code_processes.length > 0 || !state.snapshot.process_check_ok || (plan.needs_acknowledgement && !byId("acknowledge")?.checked);
    byId("confirm-apply").dataset.blocked = String(Boolean(blocked));
    byId("confirm-apply").disabled = Boolean(blocked) || state.busy;
}

function applyPlan() {
    const plan = state.preview;
    if (!plan || byId("confirm-apply").disabled) return;
    const acknowledge = byId("acknowledge")?.checked || false;
    task(async () => {
        clearInterval(planTimer);
        dialog("Applying changes", '<div class="loading-state"><span class="spinner"></span>Running the verified operation</div>', [], "IN PROGRESS");
        try {
            const result = await api("/api/apply", { plan: plan.plan, acknowledge });
            state.preview = null;
            if (["init", "bindings"].includes(plan.options.action)) state.selected = null;
            await loadState();
            if (plan.options.action === "init" && !result.bound) {
                scopeDialog();
                return;
            }
            dialog(result.conflicts?.length ? "Published with conflicts" : plan.options.action === "init" ? "This computer is connected" : "Operation complete", `<div class="plan-label">${escapeHtml(operationSummary(result))}</div>${result.backup ? `<div class="notice warning">${icon("archive")}<span>Local backup: ${escapeHtml(result.backup)}</span></div>` : ""}${detailDisclosure(result)}`, [{ label: "Done", primary: true, run: closeDialog }], result.conflicts?.length ? "REVIEW REQUIRED" : "COMPLETE");
        } catch (error) {
            state.preview = null;
            dialog("Operation stopped", `<div class="notice error">${icon("circle-alert")}<span>${escapeHtml(error.message)}</span></div>`, [{ label: "Close", run: closeDialog }], "CHECK RESULT BEFORE RETRYING");
            showError(error);
        }
    });
}

function handoff(action) {
    const options = { action, workspaces: [...state.selected] };
    if (action === "pull" || action === "repair") options.detach = byId("detach").checked;
    preview(options);
}

function textOf(value) {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.map(textOf).filter(Boolean).join("\n\n");
    if (!value || typeof value !== "object") return "";
    if (typeof value.text === "string") return value.text;
    if (value.parts) return textOf(value.parts);
    if (typeof value.value === "string") return value.value;
    if (value.content) return textOf(value.content);
    if (value.pastTenseMessage) return textOf(value.pastTenseMessage);
    return "";
}

function readRevision(session, revision, download = false) {
    task(async () => {
        const data = await api(`/api/revision?session=${encodeURIComponent(session)}&revision=${encodeURIComponent(revision)}`);
        if (download) {
            const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
            const link = document.createElement("a");
            link.href = objectUrl;
            link.download = `${session}-${revision.slice(0, 12)}.json`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
            toast("Revision downloaded");
            return;
        }
        const turns = data.requests.slice(-100);
        const body = `${data.requests.length > 100 ? '<div class="notice warning">Showing the last 100 turns. The JSON download contains the full conversation.</div>' : ""}${turns.map((request) => `<article class="transcript-turn"><div class="turn-role">YOU</div><div class="transcript-text">${escapeHtml(textOf(request.message))}</div><div class="turn-role assistant">COPILOT</div><div class="transcript-text">${escapeHtml(textOf(request.response) || "No text response recorded")}</div></article>`).join("")}`;
        dialog(data.customTitle || "Conversation preview", body, [{ label: "Close", run: closeDialog }], "READ ONLY / ARCHIVED REVISION");
    });
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => { if (!state.busy) selectView(button.dataset.view); }));
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
    if (state.busy) return;
    state.mode = button.dataset.mode;
    byId("detach").checked = false;
    updateHandoff();
}));
byId("refresh").addEventListener("click", () => task(loadState));
byId("dismiss-error").addEventListener("click", () => { byId("error-banner").hidden = true; });
byId("workspace-search").addEventListener("input", renderWorkspaces);
byId("workspace-filter").addEventListener("change", renderWorkspaces);
byId("clear-filter").addEventListener("click", () => { byId("workspace-search").value = ""; byId("workspace-filter").value = "all"; renderWorkspaces(); });
byId("select-all").addEventListener("change", (event) => {
    const rows = filteredWorkspaces();
    if (!state.busy) applyWorkspaceSelection(rows, state.selected, rows.map((workspace) => workspace.id), event.target.checked, "select");
    refreshWorkspaceSelection();
});
byId("workspace-rows").addEventListener("change", changeTreeSelection);
byId("workspace-rows").addEventListener("toggle", rememberTreeExpansion, true);
byId("expand-workspaces").addEventListener("click", () => expandWorkspaceTree(true));
byId("collapse-workspaces").addEventListener("click", () => expandWorkspaceTree(false));
byId("manage-workspaces").addEventListener("click", showScope);
byId("settings-scope").addEventListener("click", showScope);
byId("empty-choose").addEventListener("click", showScope);
byId("preview-handoff").addEventListener("click", () => handoff(state.mode));
byId("preview-repair").addEventListener("click", () => handoff("repair"));
byId("preview-migrate").addEventListener("click", () => handoff("migrate"));
byId("prepare-links").addEventListener("click", () => handoff("migrate"));
byId("modal-close").addEventListener("click", closeDialog);
byId("modal").addEventListener("cancel", (event) => { event.preventDefault(); closeDialog(); });
byId("modal-body").addEventListener("change", changeTreeSelection);
byId("modal-body").addEventListener("toggle", rememberTreeExpansion, true);
for (const identifier of ["store-path", "storage-path"]) {
    byId(identifier).addEventListener("input", updateSetupLocations);
    byId(identifier).addEventListener("invalid", () => { byId("setup-advanced").open = true; });
}
byId("setup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    scanSetup();
});
byId("access-form").addEventListener("submit", (event) => {
    event.preventDefault();
    token = byId("access-token").value.trim();
    sessionStorage.setItem(storageKey, token);
    byId("access-token").value = "";
    task(loadState);
});
byId("alerts-button").addEventListener("click", () => {
    dialog("Local state alerts", state.snapshot.issues.map((issue) => `<div class="notice warning">${icon("circle-alert")}<span>${escapeHtml(issue)}</span></div>`).join(""), [{ label: "Close", run: closeDialog }], "DIAGNOSTICS");
});
byId("diagnostics").addEventListener("click", () => task(async () => {
    const result = await api("/api/doctor", {});
    dialog("Diagnostics", `${result.issues.length ? result.issues.map((issue) => `<div class="notice warning">${icon("circle-alert")}<span>${escapeHtml(issue)}</span></div>`).join("") : '<div class="plan-label">No storage issues detected.</div>'}${detailDisclosure(result)}`, [{ label: "Close", run: closeDialog }], "READ ONLY");
}));
byId("conflict-list").addEventListener("change", (event) => {
    if (!event.target.dataset.choice) return;
    state.choices[event.target.dataset.choice] = event.target.value;
    renderConflicts();
    icons();
});
byId("conflict-list").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || state.busy) return;
    if (button.dataset.revision) readRevision(button.dataset.session, button.dataset.revision);
    if (button.dataset.download) readRevision(button.dataset.session, button.dataset.download, true);
    if (button.dataset.resolve) preview({ action: "resolve", session: button.dataset.resolve, revision: state.choices[button.dataset.resolve] });
});
byId("backup-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-restore]");
    if (button) preview({ action: "restore", backup: button.dataset.restore });
});
byId("config-details").addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy-config]");
    if (button) task(async () => { await navigator.clipboard.writeText(button.parentElement.querySelector("dd").textContent); toast("Copied"); });
});
byId("activity-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-activity]");
    if (!button) return;
    const entry = state.snapshot.activity[Number(button.dataset.activity)];
    dialog("Operation details", `<pre>${escapeHtml(JSON.stringify(entry, null, 2))}</pre>`, [{ label: "Close", run: closeDialog }]);
});

icons();
if (!token) {
    byId("loading").hidden = true;
    byId("access").hidden = false;
    byId("diagnostics").disabled = true;
} else {
    task(loadState);
}