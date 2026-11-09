#!/usr/bin/env node
/**
 * Render docs/*.md to styled html (backup-drill-design.html style).
 *
 * Usage:
 *   node scripts/render_docs.js docs/backup-drill-design.md
 *   node scripts/render_docs.js            # render all md with an html twin
 *
 * The html twin is a pandoc-style rendering of the md source:
 * fixed <style> header + masthead + markdown-it body.
 * md is the single source of truth — never hand-edit the html output.
 * Requires frontend/node_modules (markdown-it); run from the repo root or scripts/.
 */
const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const MarkdownIt = require(path.join(repoRoot, 'frontend/node_modules/markdown-it'));

const STYLE = `:root { color-scheme: light; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif; color: #262f36; background: #f5f7f9; margin: 0; line-height: 1.7; }
.page { max-width: 980px; margin: 24px auto 60px; background: #fff; border: 1px solid #e3e8ec; border-radius: 8px; padding: 48px 56px; box-shadow: 0 1px 4px rgba(0,0,0,.05); }
h1 { font-size: 26px; border-bottom: 2px solid #1652f0; padding-bottom: 12px; margin-top: 8px; }
h2 { font-size: 20px; margin-top: 40px; border-left: 4px solid #1652f0; padding-left: 10px; }
h3 { font-size: 16px; margin-top: 28px; }
h4 { font-size: 14px; }
blockquote { margin: 16px 0; padding: 10px 16px; background: #f0f5ff; border-left: 4px solid #1652f0; color: #3d4d5c; border-radius: 0 4px 4px 0; }
blockquote p { margin: 4px 0; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; background: #eef1f4; padding: 1px 5px; border-radius: 3px; font-size: 90%; color: #c7254e; }
pre { background: #1e2530; color: #d8dee9; padding: 16px 20px; border-radius: 6px; overflow-x: auto; font-size: 13px; line-height: 1.55; }
pre code { background: none; color: inherit; padding: 0; font-size: 100%; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }
th { background: #f0f4f8; color: #3d4d5c; font-weight: 600; }
th, td { border: 1px solid #e3e8ec; padding: 8px 12px; text-align: left; vertical-align: top; }
tr:nth-child(even) td { background: #fafcfe; }
strong { color: #1a2430; }
hr { border: none; border-top: 1px solid #e3e8ec; margin: 32px 0; }
a { color: #1652f0; text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { padding-left: 24px; }
li { margin: 4px 0; }
.masthead { display: flex; align-items: center; justify-content: space-between; color: #7a8794; font-size: 12px; margin-bottom: 4px; }
.masthead .tag { background: #e8f0fe; color: #1652f0; border-radius: 3px; padding: 2px 8px; font-weight: 600; }
`;

function slugify(text) {
  // pandoc-style header ids: keep CJK, strip punctuation, spaces to -
  return text.replace(/[`*_~]/g, '').trim().replace(/\s+/g, '-');
}

function render(mdPath) {
  const mdSrc = fs.readFileSync(mdPath, 'utf8');
  const md = new MarkdownIt({ html: true });

  const env = { docSlug: path.basename(mdPath, '.md') };
  md.use((mdit) => {
    mdit.core.ruler.push('header_ids', (state) => {
      state.tokens.forEach((tok, i) => {
        if (tok.type === 'heading_open') {
          const inline = state.tokens[i + 1];
          const text = inline.children
            ? inline.children.filter((c) => c.type === 'text' || c.type === 'code_inline')
                .map((c) => c.content).join('')
            : '';
          tok.attrSet('id', slugify(text));
        }
      });
    });
  });

  const title = (mdSrc.match(/^# (.+)$/m) || ['', path.basename(mdPath)])[1];
  const body = md.render(mdSrc);

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>
${STYLE}
</style>
</head>
<body>
<div class="page">
<div class="masthead"><span>open-cdm / docs</span><span class="tag">${title}</span></div>

${body}
</div>
</body>
</html>
`;
  const outPath = mdPath.replace(/\.md$/, '.html');
  fs.writeFileSync(outPath, html);
  return outPath;
}

const targets = process.argv.length > 2
  ? process.argv.slice(2)
  : fs.readdirSync(path.join(repoRoot, 'docs'))
      .filter((f) => f.endsWith('.md'))
      .filter((f) => fs.existsSync(path.join(repoRoot, 'docs', f.replace(/\.md$/, '.html'))))
      .map((f) => path.join(repoRoot, 'docs', f));

for (const t of targets) {
  console.log(`${t} -> ${render(t)}`);
}
