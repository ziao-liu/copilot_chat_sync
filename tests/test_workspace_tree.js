"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "../src/copilot_chat_sync/web/app.js"), "utf8");
const context = { URL };
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("function workspaceParts("), source.indexOf("function dateLabel(")), context);
const plain = (value) => JSON.parse(JSON.stringify(value));
const workspaces = [
    { id: "one", uri: "vscode-remote://ssh-remote%2Batlas/home/demo/project", bound: true },
    { id: "two", uri: "vscode-remote://ssh-remote+atlas/home/demo/project/experiments", bound: true },
    { id: "three", uri: "vscode-remote://ssh-remote%2Batlas/home/demo/project", bound: false },
    { id: "four", uri: "vscode-remote://ssh-remote%2Batlas-proxy/home/demo/project", bound: true },
    { id: "five", uri: "vscode-remote://ssh-remote%2Batlas/home/demo/Project", bound: true, missing: true },
    { id: "six", uri: "file:///C:/Users/demo/project", bound: true },
    { id: "seven", uri: "vscode-remote://ssh-remote%2Batlas/home/demo/a%2Fb", bound: true },
];

const original = JSON.stringify(workspaces);
const tree = plain(context.workspaceTree(workspaces));
assert.strictEqual(tree.length, 3);
assert.deepStrictEqual(tree.flatMap((connection) => connection.ids).sort(), workspaces.map((workspace) => workspace.id).sort());
assert.deepStrictEqual(tree, plain(context.workspaceTree([...workspaces].reverse())));
assert.strictEqual(JSON.stringify(workspaces), original);
const atlas = tree.find((connection) => connection.label === "atlas");
assert.strictEqual(atlas.children[0].label, "/home/demo");
const folders = atlas.children[0].children;
assert(folders.some((folder) => folder.label === "Project"));
const project = folders.find((folder) => folder.label === "project");
assert.deepStrictEqual(project.workspaces.map((workspace) => workspace.id), ["one", "three"]);
assert.strictEqual(project.children[0].label, "experiments");
assert(folders.some((folder) => folder.label === "a/b" && !folder.children.length));
assert.strictEqual(tree.find((connection) => connection.kind === "local").children[0].label, "C:/Users/demo");
assert.deepStrictEqual(plain(context.workspaceTree([])), []);
assert.strictEqual(context.workspaceTree([{ id: "root", uri: "file:///" }])[0].workspaces[0].id, "root");
assert.strictEqual(context.workspaceTree([{ id: "invalid", uri: "not a URI" }])[0].children[0].workspaces[0].id, "invalid");

const selection = new Set(["one"]);
assert.strictEqual(context.workspaceSelection(workspaces, selection, "select").partial, true);
context.applyWorkspaceSelection(workspaces, selection, workspaces.map((workspace) => workspace.id), true, "select");
assert.deepStrictEqual([...selection].sort(), ["four", "one", "seven", "six", "two"]);
assert.strictEqual(context.workspaceSelection(workspaces, selection, "select").checked, true);
context.applyWorkspaceSelection(workspaces.slice(0, 2), selection, ["one", "two", "four"], false, "select");
assert.deepStrictEqual([...selection].sort(), ["four", "seven", "six"]);
assert.strictEqual(context.workspaceSelection([workspaces[2], workspaces[4]], selection, "select").disabled, true);
context.applyWorkspaceSelection(workspaces, selection, ["three", "five"], true, "setup-scope");
assert(selection.has("three"));
assert(!selection.has("five"));
selection.add("five");
context.applyWorkspaceSelection(workspaces, selection, ["five"], false, "scope");
assert(!selection.has("five"));
assert.strictEqual(context.workspaceSelection([workspaces[4]], selection, "scope").disabled, true);

context.document = { getElementById: () => ({ value: "" }) };
context.state = { collapsed: new Set() };
vm.runInContext(source.slice(source.indexOf("const byId ="), source.indexOf("const storageKey =")), context);
vm.runInContext(source.slice(source.indexOf("function badge("), source.indexOf("function workspaceParts(")), context);
vm.runInContext(source.slice(source.indexOf("function workspaceTreeMarkup("), source.indexOf("function treeContext(")), context);
const markup = context.workspaceTreeMarkup(workspaces, new Set(), "select");
assert.strictEqual((markup.match(/data-select=/g) || []).length, workspaces.length);
assert(markup.includes("Workspace 1") && markup.includes("Workspace 2"));
const escaped = context.workspaceTreeMarkup([{ id: "escaped", uri: "vscode-remote://ssh-remote%2Batlas/home/demo/%3Cb%3Eproject%3C%2Fb%3E" }], new Set(), "scope");
assert(escaped.includes("&lt;b&gt;project&lt;/b&gt;"));
assert(!escaped.includes("<b>project</b>"));

console.log("Workspace tree tests passed: hierarchy, identity, sorting, duplicates, encoded paths, scoped selection, unavailable workspaces and escaped rendering.");