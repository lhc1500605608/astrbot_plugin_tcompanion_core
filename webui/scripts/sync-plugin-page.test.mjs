import test from "node:test";
import assert from "node:assert/strict";
import { inlineBuiltHtml } from "./sync-plugin-page.mjs";

const sourceHtml = `<!doctype html><html><head>
<script>window.themeReady = true;</script>
<script type="module" crossorigin src="./assets/app.js"></script>
<link rel="stylesheet" crossorigin href="./assets/app.css">
</head><body><div id="root"></div></body></html>`;

test("packages a page with inline JS and CSS and escapes HTML raw-text terminators", async () => {
  const assets = {
    "./assets/app.js": `const lower = "</script>"; const mixed = \`</ScRiPt >\`; // </SCRIPT>\nwindow.AstrBotPluginPage?.ready();`,
    "./assets/app.css": `body::after { content: "</style>" }`,
  };
  const output = await inlineBuiltHtml(sourceHtml, async (path) => assets[path]);

  assert.match(output, /<script type="module">/);
  assert.match(output, /<style>body::after/);
  assert.doesNotMatch(output, /<(?:script|link)[^>]+(?:src|href)=/i);
  assert.match(output, /<\\\/script>/i);
  assert.match(output, /\\3c \/style>/i);
  assert.match(output, /AstrBotPluginPage\?\.ready\(\)/);
  assert.doesNotMatch(output, /asset_token/);
});

test("rejects an additional JavaScript chunk or external CSS asset", async () => {
  const chunkSource = { ...{
    "./assets/app.js": 'import("./lazy.js");',
    "./assets/app.css": "body { color: red; }",
  } };
  await assert.rejects(
    inlineBuiltHtml(sourceHtml, async (path) => chunkSource[path]),
    /references another module or chunk/,
  );

  const externalSource = {
    "./assets/app.js": "window.ready = true;",
    "./assets/app.css": 'body { background: url("https://example.invalid/a.png"); }',
  };
  await assert.rejects(
    inlineBuiltHtml(sourceHtml, async (path) => externalSource[path]),
    /external asset URL/,
  );
});
