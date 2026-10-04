"use strict";

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const storageKey = `copilot-chat-sync-token:${location.origin}`;
const state = { snapshot: null, busy: false, setup: null, preview: null };
let planTimer;

function tokenFromFragment() {
    try { return new URLSearchParams(decodeURIComponent(location.hash.slice(1))).get("token"); }
    catch { return null; }
}
const initialToken = tokenFromFragment();
let token = initialToken || sessionStorage.getItem(storageKey) || "";
if (initialToken) {
    sessionStorage.setItem(storageKey, token);
    history.replaceState(null, "", location.pathname);
}

function workspaceLabel(workspace) {
    try {
        const uri = new URL(workspace.uri);
        const host = decodeURIComponent(uri.host).replace(/^ssh-remote\+/, "") || "本机";
        return `${host} · ${decodeURIComponent(uri.pathname)}`;
    } catch { return workspace.uri; }
}

function projectTree(workspaces) {
    const roots = new Map();
    const node = (label) => ({ label, children: new Map(), workspaces: [] });
    for (const workspace of workspaces) {
        let connection, host, segments;
        try {
            const uri = new URL(workspace.uri);
            const authority = decodeURIComponent(uri.host);
            connection = JSON.stringify([uri.protocol, authority]);
            host = authority.replace(/^ssh-remote\+/, "") || "本机";
            segments = uri.pathname.split("/").filter(Boolean).map(decodeURIComponent);
        } catch {
            connection = "unknown";
            host = "其他工作区";
            segments = [workspace.uri];
        }
        if (!roots.has(connection)) roots.set(connection, node(host));
        let parent = roots.get(connection);
        for (const segment of segments) {
            if (!parent.children.has(segment)) parent.children.set(segment, node(segment));
            parent = parent.children.get(segment);
        }
        parent.workspaces.push(workspace);
    }
    const compare = (a, b) => a.label.localeCompare(b.label, "zh-CN", { numeric: true, sensitivity: "variant" });
    function finish(branch) {
        const children = [...branch.children.values()].sort(compare).map(finish);
        const entries = [...branch.workspaces].sort((a, b) => a.id.localeCompare(b.id));
        return { label: branch.label, children, workspaces: entries,
            ids: [...entries.map((workspace) => workspace.id), ...children.flatMap((child) => child.ids)] };
    }
    return [...roots.values()].sort(compare).map(finish);
}

function projectTreeMarkup(workspaces, current) {
    function branch(item, root = false) {
        const entries = item.workspaces.map((workspace, index) => `<label class="project-option">
            <input type="radio" name="project-choice" value="${escapeHtml(workspace.id)}" ${workspace.id === current ? "checked" : ""}>
            <span>${item.workspaces.length > 1 ? `工作区 ${index + 1}` : "选择此项目"}<small>${escapeHtml(workspaceLabel(workspace))}${workspace.scan_error ? " · 读取异常" : ""}</small></span></label>`).join("");
        return `<li><details ${root || item.ids.includes(current) ? "open" : ""}><summary>${escapeHtml(item.label)}${root ? `（${item.ids.length}）` : ""}</summary>
            ${entries}${item.children.length ? `<ul>${item.children.map((child) => branch(child)).join("")}</ul>` : ""}</details></li>`;
    }
    const tree = projectTree(workspaces);
    return tree.length ? `<ul class="project-tree">${tree.map((item) => branch(item, true)).join("")}</ul>` : "<p>未发现项目，请先在桌面 VS Code 中打开项目。</p>";
}

function currentProject(snapshot) {
    const bound = snapshot.workspaces.filter((workspace) => workspace.bound);
    return bound.length === 1 ? bound[0] : null;
}

function blockedReason(snapshot) {
    if (!snapshot.process_check_ok) return "无法确认 VS Code 是否关闭。请刷新重试，暂不允许修改记录。";
    if (snapshot.code_processes.length) return "请关闭本机所有 VS Code 窗口，再刷新。";
    const project = currentProject(snapshot);
    if (!project) return "请选择一个项目。旧的多项目配置不会被自动修改。";
    if (project.missing) return "找不到已绑定的项目。请用原来的 SSH 别名打开一次项目，再刷新。";
    if (project.scan_error) return `无法读取项目记录：${project.scan_error}`;
    if (project.linked) return "请先迁移旧的聊天目录链接。";
    return "";
}

function canAutoApply(plan, options, snapshot) {
    return ["push", "pull"].includes(options.action) && !options.detach &&
        !plan.read_only && !plan.needs_acknowledgement && !plan.result.conflicts?.length &&
        !blockedReason(snapshot);
}

function operationSummary(result) {
    if (result.operation === "push") return `已将 ${result.published} 条新版本写入共享文件夹；请等待两台电脑的云盘同步完成。`;
    if (result.operation === "pull") return `已导入 ${result.files} 个聊天文件并更新历史索引，可以重新打开 VS Code。`;
    if (result.operation === "init") return "设置完成。可以发送本机记录。";
    if (result.operation === "bindings") return "项目选择已保存；原有聊天记录没有删除。";
    if (result.operation === "resolve") return "已选择共享版本，其他版本仍保留。请接收记录以更新本机。";
    if (result.operation === "migrate") return "旧链接已迁移为独立本机记录，原共享目录未删除。";
    if (result.operation === "repair") return "聊天索引已修复。";
    if (result.operation === "restore") return "本机聊天和索引已恢复，项目代码和编辑检查点未恢复。";
    return "操作完成。";
}

function dateLabel(value) {
    return new Date(value).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function friendlyError(error) {
    const message = error.message || String(error);
    if (/JSONL record at line|Replayed session exceeds|Compacted session exceeds|Shared revision exceeds/.test(message)) {
        return "日志可以很大，但单条操作或重放后的聊天内容超过 128 MiB 时仍无法安全同步。记录没有截断或删除，请查看技术信息。";
    }
    if (/File exceeds 8589934592|JSONL log exceeds/.test(message)) return "聊天日志超过 8 GiB 安全上限，暂不支持同步。原文件未删除或截断。";
    if (message.includes("Unpublished local changes")) return "本机有未发送的修改。请先发送，再接收。";
    if (message.includes("Editing snapshots")) return "发现旧编辑检查点，接收或修复已暂停。请先备份代码，再查看隔离方案。";
    if (/Close all VS Code|VS Code is running/.test(message)) return "请关闭本机所有 VS Code 窗口，再刷新重试。";
    if (/Preview expired|Files changed|files changed/.test(message)) return "记录在检查后发生变化，或检查已过期。请刷新后重试。";
    return message;
}

function errorBody(error) {
    return `<p class="notice error">${escapeHtml(friendlyError(error))}</p>
        <details><summary>技术信息</summary><pre>${escapeHtml(error.message || String(error))}</pre></details>`;
}

async function api(path, data) {
    const response = await fetch(path, {
        method: data === undefined ? "GET" : "POST",
        headers: { Authorization: `Bearer ${token}`, ...(data === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(data === undefined ? {} : { body: JSON.stringify(data) }),
        cache: "no-store",
    });
    const payload = await response.json();
    if (response.status === 401) {
        byId("access").hidden = false;
        byId("content").hidden = true;
    }
    if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
    return payload;
}

function showError(error) {
    byId("error-message").textContent = friendlyError(error);
    byId("error-banner").hidden = false;
}

function setBusy(busy) {
    state.busy = busy;
    for (const element of document.querySelectorAll("button, input, select")) {
        element.disabled = busy || element.dataset.blocked === "true";
    }
    byId("modal").setAttribute("aria-busy", String(busy));
    updateButtons();
    updateConfirmation();
}

async function task(work) {
    if (state.busy) return;
    setBusy(true);
    byId("error-banner").hidden = true;
    try { await work(); }
    catch (error) {
        showError(error);
        if (byId("modal").open) dialog("操作已停止", errorBody(error) + "<p>请检查结果后再重试，不要把此状态当作同步成功。</p>");
    } finally {
        byId("loading").hidden = true;
        setBusy(false);
    }
}

function updateButtons() {
    const snapshot = state.snapshot;
    const blocked = !snapshot?.configured || Boolean(blockedReason(snapshot));
    byId("send").disabled = state.busy || blocked;
    byId("receive").disabled = state.busy || blocked || Boolean(snapshot?.conflicts.length);
    byId("settings").disabled = state.busy;
    byId("choose-project").disabled = state.busy;
    byId("migrate").disabled = state.busy || !snapshot?.process_check_ok || Boolean(snapshot?.code_processes.length);
}

async function loadState() {
    const snapshot = await api("/api/state");
    state.snapshot = snapshot;
    byId("access").hidden = true;
    byId("content").hidden = false;
    byId("settings").hidden = !snapshot.configured;
    byId("demo-banner").hidden = !snapshot.demo;
    byId("setup").hidden = snapshot.configured;
    byId("handoff").hidden = !snapshot.configured;
    byId("version").textContent = `v${snapshot.version}`;
    if (!snapshot.configured) {
        if (!byId("store-path").value) byId("store-path").value = snapshot.defaults.store;
        if (!byId("storage-path").value) byId("storage-path").value = snapshot.defaults.storage;
        return;
    }
    const project = currentProject(snapshot);
    byId("project-name").textContent = project ? workspaceLabel(project) : "尚未选择单个项目";
    byId("shared-location").textContent = `共享文件夹：${snapshot.config.store}`;
    byId("shared-location").title = snapshot.config.store;
    byId("chat-counts").textContent = `聊天总数（非待同步数量）：本机 ${project?.sessions ?? "未知"} · 共享池 ${snapshot.shared?.sessions ?? "未知"}`;
    const reason = blockedReason(snapshot);
    byId("status").textContent = reason || (snapshot.demo ? "只读演示，可查看预检结果。" : "可以操作，VS Code 已关闭。");
    byId("status").className = `notice ${reason ? "warning" : "good"}`;
    byId("issues").hidden = !snapshot.issues.length;
    byId("issue-summary").textContent = `技术提示（${snapshot.issues.length}）`;
    byId("issue-list").replaceChildren(...snapshot.issues.map((issue) => {
        const paragraph = document.createElement("p");
        paragraph.textContent = issue;
        return paragraph;
    }));
    byId("old-links").hidden = !project?.linked;
    byId("conflict-notice").hidden = !snapshot.conflicts.length;
    byId("conflict-message").textContent = `${snapshot.conflicts.length} 条聊天存在不同版本。接收已暂停，请先选择要继续的版本。`;
    const recent = snapshot.activity[0];
    byId("last-operation").textContent = recent ?
        `本次打开期间最近操作 · ${dateLabel(recent.time)}：${recent.status === "error" ? `失败：${recent.result}` : operationSummary(recent.result)}${recent.status === "conflict" ? " 仍有冲突需要处理。" : ""}` :
        "本次打开期间尚无操作。";
    updateButtons();
}

function closeDialog() {
    if (state.busy) return;
    clearInterval(planTimer);
    state.preview = null;
    byId("modal").close();
}

function dialog(title, body, actions = [{ label: "知道了", run: closeDialog }]) {
    clearInterval(planTimer);
    byId("modal-title").textContent = title;
    byId("modal-body").innerHTML = body;
    byId("modal-actions").replaceChildren();
    for (const action of actions) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = action.label;
        if (action.primary) button.className = "primary";
        if (action.id) button.id = action.id;
        button.dataset.blocked = String(Boolean(action.disabled));
        button.disabled = Boolean(action.disabled);
        button.addEventListener("click", action.run);
        byId("modal-actions").append(button);
    }
    if (!byId("modal").open) byId("modal").showModal();
}

function projectPicker(workspaces, setup = false, issues = []) {
    const rows = workspaces.filter((workspace) => !workspace.missing);
    const wanted = setup ? state.setup.selected : currentProject(state.snapshot)?.id;
    const current = rows.some((workspace) => workspace.id === wanted) ? wanted : "";
    let selected = current;
    const body = `<p>一次只绑定一个项目。另一台电脑应选择同一远程目录对应的工作区。</p>
        <p class="notice warning">一个共享文件夹就是一个聊天池。更换为无关项目时，请使用独立配置和独立共享文件夹，不能直接复用此池。</p>
        <fieldset id="project-tree"><legend>展开服务器和目录，选择项目</legend>${projectTreeMarkup(rows, current)}</fieldset>
        <p class="hint">未找到？先在桌面 VS Code 中打开一次项目，再重新扫描。SSH 别名不同的工作区不会自动合并。</p>
        ${issues.map((issue) => `<p class="notice warning">${escapeHtml(issue)}</p>`).join("")}`;
    dialog(setup ? "选择要同步的项目" : "更换对应工作区", body, [
        { label: "取消", run: closeDialog },
        { label: "重新扫描", run: setup ? scanSetup : () => task(async () => { await loadState(); projectPicker(state.snapshot.workspaces); }) },
        { label: setup ? "完成设置" : "保存选择", primary: true, id: "save-project", disabled: !current,
            run: () => {
                if (!selected) return;
                if (setup) state.setup.selected = selected;
                preview(setup ? { action: "init", store: state.setup.store, storage: state.setup.storage, workspaces: [selected] } :
                    { action: "bindings", workspaces: [selected] });
            } },
    ]);
    byId("project-tree").addEventListener("change", (event) => {
        if (event.target.name !== "project-choice" || !rows.some((workspace) => workspace.id === event.target.value)) return;
        selected = event.target.value;
        const blocked = !selected;
        byId("save-project").dataset.blocked = String(blocked);
        byId("save-project").disabled = blocked || state.busy;
    });
}

function scanSetup() {
    task(async () => {
        const store = byId("store-path").value.trim();
        const storage = byId("storage-path").value.trim();
        dialog("正在查找项目", "<p>读取本机 VS Code 工作区，不会修改聊天。</p>", []);
        const scanned = await api("/api/scan", { storage });
        const previous = state.setup?.storage === storage ? state.setup.selected : "";
        state.setup = { store, storage, selected: scanned.workspaces.some((workspace) => workspace.id === previous) ? previous : "" };
        projectPicker(scanned.workspaces, true, scanned.issues);
    });
}

async function applyTicket(plan, acknowledge = false) {
    clearInterval(planTimer);
    state.preview = null;
    dialog("正在处理", "<p>请勿启动 VS Code 或关闭应用。</p>", []);
    const result = await api("/api/apply", { plan: plan.plan, acknowledge });
    await loadState();
    byId("modal").close();
    if (result.conflicts?.length) showConflicts();
}

function planBody(plan, options) {
    const result = plan.result;
    let body = "";
    if (options.action === "init") body += `<p>共享文件夹：${escapeHtml(result.store)}</p><p>项目：${escapeHtml(workspaceLabel(result.bindings[0]))}</p>`;
    if (options.action === "bindings") body += "<p>只修改工作区绑定，不删除原有聊天。新工作区仍接收当前共享池的全部记录。</p>";
    if (options.action === "push") body += `<p>将发送 ${result.would_publish} 条新版本。不同版本会保留为冲突，不会自动合并。</p>`;
    if (options.action === "pull") body += `<p>将导入 ${result.files} 个聊天文件，更新 ${result.indexes} 个历史索引。</p>`;
    if (options.action === "resolve") body += "<p>所选版本将成为后续接收的版本，其他历史仍保留。不会把两条分叉对话拼接起来。</p>";
    if (options.action === "restore") body += "<p class=\"notice warning\">恢复聊天文件和索引；不会恢复项目代码，也不会重新启用旧编辑检查点。较新的本机修改会阻止恢复。</p>";
    if (options.action === "migrate") body += "<p class=\"notice warning\">先停止每台电脑上的旧同步／链接脚本并备份记录。迁移后使用独立本机目录，原共享目录保留。</p>";
    if (options.action === "repair") body += "<p>仅修复所选项目的聊天索引，不恢复代码。</p>";
    if (result.linked) body += "<p class=\"notice warning\">设置后还需迁移旧链接，才能发送或接收。</p>";
    if (plan.needs_acknowledgement) body += `<p class="notice warning">请先独立备份并核实当前代码。隔离旧编辑快照会失去这些聊天的旧撤销／检查点，不能恢复项目代码。</p>
        <label><input id="acknowledge" type="checkbox">我已备份并接受失去旧撤销／检查点</label>`;
    if (plan.read_only) body += "<p class=\"notice\">演示模式不可执行。</p>";
    if (state.snapshot.code_processes.length || !state.snapshot.process_check_ok) body += "<p class=\"notice warning\">请先关闭 VS Code 并刷新。当前不允许执行。</p>";
    return body + '<p id="plan-expiry" class="hint"></p>';
}

function preview(options) {
    return task(async () => {
        dialog("正在检查", "<p>检查记录、冲突和备份条件，不会跳过安全校验。大日志可能需要几分钟，请勿启动 VS Code。</p>", []);
        let plan;
        try { plan = await api("/api/preview", options); }
        catch (error) {
            const actions = [{ label: "关闭", run: closeDialog }];
            if (["pull", "repair"].includes(options.action) && !options.detach && error.message.includes("Editing snapshots")) {
                actions.push({ label: "查看编辑快照隔离方案", run: () => preview({ ...options, detach: true }) });
            }
            dialog("暂时不能执行", errorBody(error) + "<p>本次预检没有修改记录。</p>", actions);
            showError(error);
            return;
        }
        if (canAutoApply(plan, options, state.snapshot)) {
            await applyTicket(plan);
            return;
        }
        state.preview = { ...plan, options, deadline: Date.now() + plan.expires_in * 1000 };
        dialog("请确认这次操作", planBody(plan, options), [
            { label: "取消", run: closeDialog },
            { label: plan.read_only ? "只读演示" : "确认执行", primary: true, id: "confirm-apply", disabled: true, run: () => {
                const current = state.preview;
                const acknowledge = byId("acknowledge")?.checked || false;
                if (current && !byId("confirm-apply").disabled) task(() => applyTicket(current, acknowledge));
            } },
        ]);
        byId("acknowledge")?.addEventListener("change", updateConfirmation);
        planTimer = setInterval(updateConfirmation, 1000);
    });
}

function updateConfirmation() {
    const plan = state.preview;
    const button = byId("confirm-apply");
    if (!plan || !button) return;
    const seconds = Math.max(0, Math.ceil((plan.deadline - Date.now()) / 1000));
    byId("plan-expiry").textContent = seconds ? `检查结果将在 ${seconds} 秒后过期。` : "检查结果已过期，请关闭后重试。";
    const blocked = !seconds || plan.read_only || !state.snapshot.process_check_ok || state.snapshot.code_processes.length > 0 ||
        (plan.needs_acknowledgement && !byId("acknowledge")?.checked);
    button.dataset.blocked = String(Boolean(blocked));
    button.disabled = state.busy || Boolean(blocked);
}

function handoff(action) {
    const project = currentProject(state.snapshot);
    if (!project || project.missing || (["push", "pull"].includes(action) && blockedReason(state.snapshot)) ||
        (action === "pull" && state.snapshot.conflicts.length)) return;
    return preview({ action, workspaces: [project.id] });
}

function settings() {
    dialog("设置", `<p>共享文件夹：${escapeHtml(state.snapshot.config.store)}</p>
        <p class="hint">本界面一次同步一个项目。无关项目请使用独立配置和共享目录；此处不提供自动混池或清空记录。</p>
        <details><summary>恢复本机聊天</summary><p class="hint">接收和修复前会自动备份。恢复操作仍需确认。</p>
        ${[...state.snapshot.backups].reverse().map((backup) => `<div class="backup"><span>${escapeHtml(backup.id)} · ${escapeHtml(backup.status)}</span>
        <button type="button" data-restore="${escapeHtml(backup.id)}">恢复此备份</button></div>`).join("") || "<p>还没有本机备份。</p>"}</details>`,
        [{ label: "关闭", run: closeDialog }, { label: "检查问题", run: diagnose }, { label: "更换对应工作区", run: () => projectPicker(state.snapshot.workspaces) }]);
}

function diagnose() {
    task(async () => {
        const result = await api("/api/doctor", {});
        const actions = [{ label: "关闭", run: closeDialog }];
        const project = currentProject(state.snapshot);
        if (project && result.issues.some((issue) => /index|cache|schema/i.test(issue))) {
            actions.push({ label: "检查索引修复方案", run: () => handoff("repair") });
        }
        dialog("检查结果", result.issues.length ? result.issues.map((issue) => `<p class="notice warning">${escapeHtml(issue)}</p>`).join("") : "<p>未发现存储问题。</p>", actions);
    });
}

function showConflicts() {
    const body = state.snapshot.conflicts.map((conflict, index) => `<article class="conflict"><h3>聊天 ${index + 1} · 不同版本</h3>
        ${conflict.heads.map((head, version) => `<div class="revision"><label><input type="radio" name="conflict-${index}" value="${escapeHtml(head.revision)}">
        版本 ${version + 1} · ${head.requests} 轮<small>${escapeHtml(dateLabel(head.last_message_date))}</small></label>
        <button type="button" data-read="${escapeHtml(head.revision)}" data-session="${escapeHtml(conflict.session)}">查看内容</button></div>`).join("")}
        <button type="button" data-resolve="${escapeHtml(conflict.session)}" data-group="conflict-${index}">继续所选版本</button></article>`).join("");
    dialog("选择要继续的聊天版本", "<p>不同历史不能自动拼接。请选择要继续的版本；未选择的版本仍会存档。</p>" + body);
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

function readRevision(session, revision) {
    task(async () => {
        const data = await api(`/api/revision?session=${encodeURIComponent(session)}&revision=${encodeURIComponent(revision)}`);
        dialog(data.customTitle || "聊天内容", `${data.requests.length > 100 ? "<p class=\"notice\">仅显示最后 100 轮，原始记录没有截断。</p>" : ""}
            ${data.requests.slice(-100).map((request) => `<article class="transcript"><h3>你</h3>${escapeHtml(textOf(request.message))}<h3>Copilot</h3>${escapeHtml(textOf(request.response) || "无文字回复")}</article>`).join("")}`,
            [{ label: "返回冲突选择", run: showConflicts }]);
    });
}

byId("refresh").addEventListener("click", () => task(loadState));
byId("dismiss-error").addEventListener("click", () => { byId("error-banner").hidden = true; });
byId("send").addEventListener("click", () => handoff("push"));
byId("receive").addEventListener("click", () => handoff("pull"));
byId("migrate").addEventListener("click", () => handoff("migrate"));
byId("settings").addEventListener("click", settings);
byId("choose-project").addEventListener("click", () => projectPicker(state.snapshot.workspaces));
byId("resolve-conflicts").addEventListener("click", showConflicts);
byId("modal-close").addEventListener("click", closeDialog);
byId("modal").addEventListener("cancel", (event) => { event.preventDefault(); closeDialog(); });
byId("setup-form").addEventListener("submit", (event) => { event.preventDefault(); scanSetup(); });
byId("storage-path").addEventListener("invalid", () => { byId("setup-advanced").open = true; });
byId("access-form").addEventListener("submit", (event) => {
    event.preventDefault();
    token = byId("access-token").value.trim();
    sessionStorage.setItem(storageKey, token);
    byId("access-token").value = "";
    task(loadState);
});
byId("modal-body").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || state.busy) return;
    if (button.dataset.restore) preview({ action: "restore", backup: button.dataset.restore });
    if (button.dataset.read) readRevision(button.dataset.session, button.dataset.read);
    if (button.dataset.resolve) {
        const chosen = document.querySelector(`input[name="${button.dataset.group}"]:checked`);
        if (!chosen) { showError(new Error("请先选择一个聊天版本。")); return; }
        preview({ action: "resolve", session: button.dataset.resolve, revision: chosen.value });
    }
});

if (token) task(loadState);
else { byId("loading").hidden = true; byId("access").hidden = false; }
