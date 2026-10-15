import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webuiDir = resolve(scriptDir, "..");
const distDir = resolve(webuiDir, "dist");
const pageDir = resolve(webuiDir, "../pages/status");

function readTag(source, start) {
  let index = start + 1;
  const nameStart = index;
  while (/[A-Za-z0-9:-]/.test(source[index] ?? "")) index += 1;
  if (index === nameStart) return null;
  const name = source.slice(nameStart, index).toLowerCase();
  const attributes = new Map();
  while (index < source.length) {
    while (/\s/.test(source[index] ?? "")) index += 1;
    if (source[index] === ">") return { name, attributes, end: index + 1 };
    if (source[index] === "/" && source[index + 1] === ">")
      return { name, attributes, end: index + 2 };
    const keyStart = index;
    while (index < source.length && !/[\s=/>]/.test(source[index])) index += 1;
    if (index === keyStart) throw new Error(`Cannot parse HTML tag near offset ${index}`);
    const key = source.slice(keyStart, index).toLowerCase();
    while (/\s/.test(source[index] ?? "")) index += 1;
    let value = "";
    if (source[index] === "=") {
      index += 1;
      while (/\s/.test(source[index] ?? "")) index += 1;
      const quote = source[index] === "'" || source[index] === '"' ? source[index++] : null;
      const valueStart = index;
      if (quote) {
        while (index < source.length && source[index] !== quote) index += 1;
        if (index >= source.length) throw new Error(`Unclosed ${quote} in <${name}>`);
        value = source.slice(valueStart, index);
        index += 1;
      } else {
        while (index < source.length && !/[\s>]/.test(source[index])) index += 1;
        value = source.slice(valueStart, index);
      }
    }
    attributes.set(key, value);
  }
  throw new Error(`Unclosed <${name}> tag`);
}

function htmlTags(source) {
  const tags = [];
  for (let index = 0; index < source.length; ) {
    const start = source.indexOf("<", index);
    if (start < 0) break;
    if (source.startsWith("<!--", start)) {
      const close = source.indexOf("-->", start + 4);
      if (close < 0) throw new Error("Unclosed HTML comment in build output");
      index = close + 3;
      continue;
    }
    if (source[start + 1] === "/" || source[start + 1] === "!" || source[start + 1] === "?") {
      index = start + 1;
      continue;
    }
    const tag = readTag(source, start);
    if (!tag) {
      index = start + 1;
      continue;
    }
    tags.push({ ...tag, start });
    index = tag.end;
    if (tag.name === "script" || tag.name === "style") {
      const closing = new RegExp(`<\\/${tag.name}\\s*>`, "ig");
      closing.lastIndex = index;
      const match = closing.exec(source);
      if (!match) throw new Error(`Unclosed <${tag.name}> in build output`);
      index = closing.lastIndex;
    }
  }
  return tags;
}

function escapeInlineScript(source) {
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, false, ts.LanguageVariant.Standard, source);
  const edits = [];
  const safeTokens = new Set([
    ts.SyntaxKind.StringLiteral,
    ts.SyntaxKind.NoSubstitutionTemplateLiteral,
    ts.SyntaxKind.TemplateHead,
    ts.SyntaxKind.TemplateMiddle,
    ts.SyntaxKind.TemplateTail,
    ts.SyntaxKind.SingleLineCommentTrivia,
    ts.SyntaxKind.MultiLineCommentTrivia,
  ]);
  while (scanner.scan() !== ts.SyntaxKind.EndOfFileToken) {
    const token = scanner.getToken();
    const start = scanner.getTokenPos();
    const end = scanner.getTextPos();
    const raw = source.slice(start, end);
    if (!/<\/script/i.test(raw)) continue;
    if (!safeTokens.has(token))
      throw new Error(`Cannot safely inline a </script sequence in JavaScript token ${ts.SyntaxKind[token]}`);
    edits.push({ start, end, value: raw.replace(/<\/script/gi, (match) => `<\\${match.slice(1)}`) });
  }
  let result = source;
  for (const edit of edits.reverse())
    result = `${result.slice(0, edit.start)}${edit.value}${result.slice(edit.end)}`;
  if (/<\/script/i.test(result)) throw new Error("Unescaped </script sequence remains in JavaScript bundle");
  const parsed = ts.createSourceFile("inline-bundle.js", result, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  if (parsed.parseDiagnostics.length)
    throw new Error("JavaScript bundle became invalid while escaping inline script content");
  let moduleReference = false;
  const inspect = (node) => {
    if (
      ts.isImportDeclaration(node) ||
      ts.isExportDeclaration(node) ||
      (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)
    ) moduleReference = true;
    ts.forEachChild(node, inspect);
  };
  inspect(parsed);
  if (moduleReference) throw new Error("Built JavaScript references another module or chunk");
  return result;
}

function escapeInlineStyle(source) {
  if (/@import\b/i.test(source)) throw new Error("Built CSS contains an external @import");
  if (/url\(\s*['\"]?(?!data:|#)/i.test(source))
    throw new Error("Built CSS contains an external asset URL");
  return source.replace(/<\/style/gi, "\\3c /style");
}

export async function inlineBuiltHtml(html, assetReader) {
  const tags = htmlTags(html);
  const modules = tags.filter((tag) => tag.name === "script" && tag.attributes.get("type") === "module");
  const stylesheets = tags.filter(
    (tag) => tag.name === "link" && tag.attributes.get("rel")?.toLowerCase().split(/\s+/).includes("stylesheet"),
  );
  if (modules.length !== 1 || stylesheets.length !== 1)
    throw new Error("Expected exactly one built module script and one stylesheet link");
  const scriptTag = modules[0];
  const styleTag = stylesheets[0];
  const scriptPath = scriptTag.attributes.get("src");
  const stylePath = styleTag.attributes.get("href");
  if (!scriptPath?.startsWith("./assets/") || !stylePath?.startsWith("./assets/"))
    throw new Error("Built assets must be local files under ./assets/");
  if (extname(scriptPath) !== ".js" || extname(stylePath) !== ".css")
    throw new Error("Unexpected built JavaScript or CSS extension");
  const scriptEnd = html.indexOf("</script", scriptTag.end);
  if (scriptEnd < 0) throw new Error("Module script has no closing tag");
  const scriptCloseEnd = html.indexOf(">", scriptEnd) + 1;
  const moduleSource = await assetReader(scriptPath);
  const styleSource = await assetReader(stylePath);
  const moduleMarkup = `<script type="module">${escapeInlineScript(moduleSource)}</script>`;
  const styleMarkup = `<style>${escapeInlineStyle(styleSource)}</style>`;
  const withScript = `${html.slice(0, scriptTag.start)}${moduleMarkup}${html.slice(scriptCloseEnd)}`;
  const adjustedStyleStart = styleTag.start > scriptTag.start
    ? styleTag.start + moduleMarkup.length - (scriptCloseEnd - scriptTag.start)
    : styleTag.start;
  const adjustedStyleEnd = styleTag.end + (styleTag.start > scriptTag.start
    ? moduleMarkup.length - (scriptCloseEnd - scriptTag.start)
    : 0);
  const output = `${withScript.slice(0, adjustedStyleStart)}${styleMarkup}${withScript.slice(adjustedStyleEnd)}`;
  const remainingTags = htmlTags(output);
  if (remainingTags.some((tag) =>
    (tag.name === "script" && tag.attributes.has("src")) ||
    (tag.name === "link" && tag.attributes.get("rel")?.toLowerCase().split(/\s+/).includes("stylesheet"))
  )) throw new Error("Self-contained plugin page still references an external script or stylesheet");
  return output;
}

async function syncPluginPage() {
  for (const required of [resolve(distDir, "index.html"), resolve(distDir, "assets")]) {
    try {
      await stat(required);
    } catch {
      throw new Error(`Missing build output ${required}; run npm run build first.`);
    }
  }
  const html = await readFile(resolve(distDir, "index.html"), "utf8");
  const page = await inlineBuiltHtml(html, async (assetPath) => {
    const filePath = resolve(distDir, assetPath.slice(2));
    if (!filePath.startsWith(`${resolve(distDir, "assets")}/`))
      throw new Error(`Asset path escapes build directory: ${assetPath}`);
    return readFile(filePath, "utf8");
  });
  await mkdir(pageDir, { recursive: true });
  await rm(resolve(pageDir, "assets"), { recursive: true, force: true });
  await rm(resolve(pageDir, "app.js"), { force: true });
  await rm(resolve(pageDir, "style.css"), { force: true });
  for (const entry of await readdir(distDir, { withFileTypes: true })) {
    if (entry.isDirectory()) continue;
    if (entry.name === "index.html") continue;
    await cp(resolve(distDir, entry.name), resolve(pageDir, entry.name), { force: true });
  }
  await writeFile(resolve(pageDir, "index.html"), page);
  console.log(`Synced self-contained plugin page to ${pageDir}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
  await syncPluginPage();
