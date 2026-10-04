"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "../src/copilot_chat_sync/web/app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../src/copilot_chat_sync/web/index.html"), "utf8");

function harness(snapshot, responses = []) {
    const elements = new Map();
    class Element {
        constructor(id) { this.id = id; this.dataset = {}; this.value = ""; this.hidden = false; this.listeners = {}; }
        addEventListener(name, callback) { this.listeners[name] = callback; }
        setAttribute() {}
        replaceChildren(...children) { this.children = children; }
        append(child) {
            this.children.push(child);
            if (child.id) elements.set(child.id, child);
        }
        showModal() { this.open = true; }
        close() { this.open = false; }
        set innerHTML(value) {
            this.markup = value;
            for (const id of ["acknowledge", "plan-expiry", "project-tree"]) elements.delete(id);
            for (const match of value.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element(match[1]));
        }
        get innerHTML() { return this.markup; }
    }
    for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element(match[1]));
    const calls = [];
    const context = {
        URL, URLSearchParams, Date, console,
        location: { origin: "http://127.0.0.1:1234", hash: "", pathname: "/" },
        sessionStorage: { getItem: () => "", setItem() {} },
        history: { replaceState() {} },
        setInterval: () => 1, clearInterval() {},
        document: {
            getElementById: (id) => elements.get(id) || null,
            querySelectorAll: () => [...elements.values()],
            querySelector: () => null,
            createElement: () => new Element(""),
        },
        fetch: async (url, options) => {
            calls.push({ url, options, body: options.body ? JSON.parse(options.body) : null });
            assert(responses.length, `Unexpected request: ${url}`);
            const response = responses.shift();
            return { ok: !response.error, status: response.error ? 400 : 200, json: async () => response.error ? { error: response.error } : response };
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    context.snapshot = snapshot;
    vm.runInContext("state.snapshot = snapshot", context);
    return { context, calls, elements, run: (code) => vm.runInContext(code, context) };
}

const project = { id: "one", uri: "vscode-remote://ssh-remote%2Bnipie/home/demo/project", bound: true, sessions: 3 };
const base = () => ({
    configured: true, workspaces: [{ ...project }], code_processes: [], process_check_ok: true,
    config: { store: "/shared/project" }, shared: { sessions: 4 }, conflicts: [], backups: [],
    issues: [], activity: [], version: "test", demo: false,
});
const ticket = (result = {}, extra = {}) => ({ plan: "verified-ticket", expires_in: 120, result, read_only: false, needs_acknowledgement: false, ...extra });

async function main() {
    let h = harness(base());
    assert.strictEqual(h.run("workspaceLabel(snapshot.workspaces[0])"), "nipie · /home/demo/project");
    assert.strictEqual(h.run("workspaceLabel({uri: 'file:///C:/project'})"), "本机 · /C:/project");
    assert.strictEqual(h.run("escapeHtml('<script>\"&')"), "&lt;script&gt;&quot;&amp;");
    assert(h.run("friendlyError(new Error('JSONL record at line 1 exceeds 128 MiB'))").includes("没有截断或删除"));
    assert(h.run("friendlyError(new Error('JSON record exceeds 2 GiB'))").includes("2 GiB"));
    assert(h.run("friendlyError(new Error('Insufficient memory for this conversation'))").includes("更多内存"));
    assert(h.run("friendlyError(new Error('File exceeds 8589934592 bytes'))").includes("8 GiB"));
    assert.strictEqual(h.run("blockedReason(snapshot)"), "");
    h.context.snapshot.workspaces.push({ ...project, id: "two" });
    assert.strictEqual(h.run("currentProject(snapshot)"), null);
    assert(h.run("blockedReason(snapshot)").includes("一个项目"));
    for (const patch of [
        { code_processes: [123] }, { process_check_ok: false },
        { workspaces: [{ ...project, missing: true }] },
        { workspaces: [{ ...project, linked: true }] },
        { workspaces: [{ ...project, scan_error: "Cannot read" }] },
    ]) {
        h = harness({ ...base(), ...patch });
        assert(h.run("blockedReason(snapshot)"));
        await h.run("handoff('push')");
        assert.strictEqual(h.calls.length, 0);
    }

    for (const action of ["push", "pull"]) {
        const result = action === "push" ? { operation: action, published: 1 } : { operation: action, files: 2 };
        h = harness(base(), [ticket(), result, base()]);
        await h.run(`handoff('${action}')`);
        assert.deepStrictEqual(h.calls.map((call) => call.url), ["/api/preview", "/api/apply", "/api/state"]);
        assert.deepStrictEqual(h.calls[0].body, { action, workspaces: ["one"] });
        assert.deepStrictEqual(h.calls[1].body, { plan: "verified-ticket", acknowledge: false });
        assert.strictEqual(h.elements.get("modal").open, false);
        assert(h.elements.get("chat-counts").textContent.includes("非待同步数量"));
        assert.strictEqual(h.run("state.busy"), false);
    }

    for (const plan of [
        ticket({}, { read_only: true }),
        ticket({}, { needs_acknowledgement: true }),
        ticket({ conflicts: ["session"] }),
    ]) {
        h = harness(base(), [plan]);
        await h.run("handoff('push')");
        assert.strictEqual(h.calls.length, 1);
        assert.strictEqual(h.elements.get("modal").open, true);
    }
    h = harness(base(), [ticket({}, { read_only: true })]);
    await h.run("handoff('push')");
    assert.strictEqual(h.elements.get("confirm-apply").disabled, true);

    h = harness(base(), [ticket({}, { needs_acknowledgement: true })]);
    await h.run("preview({action: 'pull', workspaces: ['one'], detach: true})");
    assert.strictEqual(h.elements.get("confirm-apply").disabled, true);
    h.elements.get("acknowledge").checked = true;
    h.run("updateConfirmation()");
    assert.strictEqual(h.elements.get("confirm-apply").disabled, false);
    h.run("state.preview.deadline = 0; updateConfirmation()");
    assert.strictEqual(h.elements.get("confirm-apply").disabled, true);

    h = harness(base(), [{ error: "Unpublished local changes" }]);
    await h.run("handoff('pull')");
    assert.strictEqual(h.calls.length, 1);
    assert.strictEqual(h.elements.get("error-banner").hidden, false);
    assert(h.elements.get("error-message").textContent.includes("请先发送"));
    assert(h.elements.get("modal-body").innerHTML.includes("Unpublished"));
    assert.strictEqual(h.run("state.busy"), false);

    h = harness(base(), [{ error: "Files changed; retry" }]);
    h.run("state.busy = true");
    await h.run("handoff('push')");
    assert.strictEqual(h.calls.length, 0);

    h = harness({ ...base(), conflicts: [{ session: "conflicting" }] });
    h.run("updateButtons()");
    assert.strictEqual(h.elements.get("receive").disabled, true);
    await h.run("handoff('pull')");
    assert.strictEqual(h.calls.length, 0);

    h = harness(base(), [ticket(), { error: "Preview expired or files changed" }]);
    await h.run("handoff('push')");
    assert.deepStrictEqual(h.calls.map((call) => call.url), ["/api/preview", "/api/apply"]);
    assert(h.elements.get("error-message").textContent.includes("刷新后重试"));
    assert(h.elements.get("modal-body").innerHTML.includes("不要把此状态当作同步成功"));

    h = harness({ ...base(), workspaces: [{ ...project, linked: true }] }, [ticket()]);
    await h.run("handoff('migrate')");
    assert.strictEqual(h.calls[0].body.action, "migrate");
    assert.strictEqual(h.calls.length, 1);

    h = harness(base(), [ticket({ store: "/shared/project", bindings: [project], bound: 1 })]);
    h.run("state.setup = {store: '/shared/project', storage: '/native', selected: ''}; projectPicker(snapshot.workspaces, true)");
    h.elements.get("project-tree").listeners.change({ target: { name: "project-choice", value: "one" } });
    h.elements.get("save-project").listeners.click();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepStrictEqual(h.calls[0].body, { action: "init", store: "/shared/project", storage: "/native", workspaces: ["one"] });
    assert.strictEqual(h.calls.length, 1);
    h.run("closeDialog()");
    assert.strictEqual(h.run("state.preview"), null);

    h = harness(base(), [ticket({ bound: 1, added: ["other"], removed: ["one"] })]);
    h.run("projectPicker([{id: 'other', uri: 'file:///other'}])");
    assert.strictEqual(h.elements.get("save-project").disabled, true);
    h.elements.get("project-tree").listeners.change({ target: { name: "project-choice", value: "other" } });
    assert.strictEqual(h.elements.get("save-project").disabled, false);
    h.elements.get("save-project").listeners.click();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepStrictEqual(h.calls[0].body, { action: "bindings", workspaces: ["other"] });
    assert.strictEqual(h.calls.length, 1);

    h = harness(base());
    h.run("projectPicker([{id: 'a', uri: 'file:///same'}, {id: 'b', uri: 'file:///same'}])");
    assert(h.elements.get("modal-body").innerHTML.includes("工作区 1"));
    assert(h.elements.get("modal-body").innerHTML.includes("工作区 2"));
    h.run("projectPicker([{id: 'a', uri: 'file:///%3Cscript%3E'}])");
    assert(h.elements.get("modal-body").innerHTML.includes("&lt;script&gt;"));
    assert(!h.elements.get("modal-body").innerHTML.includes("<script>"));

    const treeRows = [
        { id: "a", uri: "vscode-remote://ssh-remote%2Bnipie/home/demo/project" },
        { id: "b", uri: "vscode-remote://ssh-remote%2Bnipie/home/demo/project/child" },
        { id: "c", uri: "vscode-remote://ssh-remote%2Bnipie-proxy/home/demo/project" },
        { id: "d", uri: "vscode-remote://ssh-remote%2Bnipie/home/demo/Project" },
        { id: "e", uri: "file:///C:/project" },
        { id: "f", uri: "vscode-remote://ssh-remote%2Bnipie/home/demo/a%2Fb" },
        { id: "g", uri: "file:///" },
    ];
    h.context.treeRows = treeRows;
    const plain = (value) => JSON.parse(JSON.stringify(value));
    const tree = plain(h.run("projectTree(treeRows)"));
    assert.strictEqual(tree.length, 3);
    assert.deepStrictEqual(tree, plain(h.run("projectTree([...treeRows].reverse())")));
    assert.deepStrictEqual(tree.flatMap((root) => root.ids).sort(), treeRows.map((row) => row.id).sort());
    assert.strictEqual(tree.find((root) => root.label === "nipie").children[0].label, "home");
    const folders = tree.find((root) => root.label === "nipie").children[0].children[0].children;
    assert(folders.some((folder) => folder.label === "Project"));
    assert.strictEqual(folders.find((folder) => folder.label === "project").children[0].workspaces[0].id, "b");
    assert(folders.some((folder) => folder.label === "a/b" && !folder.children.length));
    const markup = h.run("projectTreeMarkup(treeRows, 'b')");
    assert(markup.includes('value="b" checked'));
    assert.strictEqual((markup.match(/type="radio"/g) || []).length, treeRows.length);
    assert(markup.includes("<summary>nipie"));
    assert(markup.includes("<details open><summary>child"));
    assert(markup.includes("<summary>C:"));
    assert.strictEqual(h.run("projectTree([{id:'bad',uri:'not a URI'}])[0].label"), "其他工作区");
    h.run("projectPicker(snapshot.workspaces)");
    h.elements.get("project-tree").listeners.change({ target: { name: "project-choice", value: "not-a-workspace" } });
    assert.strictEqual(h.elements.get("save-project").disabled, false);
    assert(!html.includes("<nav"));
    assert(html.includes('id="send"') && html.includes('id="receive"'));
    assert(html.indexOf('id="send"') < html.indexOf('id="old-links"'));
    assert(html.indexOf('id="receive"') < html.indexOf('id="conflict-notice"'));
    assert(html.includes('<details id="issues" hidden>'));
    console.log("Frontend checks passed: single-project scope, one-click preflight/apply, error visibility, process guards, conflicts, demo, acknowledgement, expiry, migration, escaped and duplicate project labels.");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
