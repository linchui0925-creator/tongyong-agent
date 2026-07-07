
const fs = require('fs');
const src = fs.readFileSync('src/components/LLM/ModelSelector.tsx', 'utf8');
const parser = require('@babel/parser');
const ast = parser.parse(src, {
  sourceType: 'module',
  plugins: ['jsx', 'typescript'],
  errorRecovery: true,
});

// Walk and find what's at the indicated line
const targetLine = 451;
function visit(n, depth=0, path='') {
  if (!n || depth > 40) return;
  if (n.loc && n.loc.start && n.loc.start.line === targetLine) {
    console.log(`L${targetLine} path=${path} type=${n.type} col=${n.loc.start.column}`);
  }
  // Stop recursing into children if this node is way past line 460
  if (n.loc && n.loc.start && n.loc.start.line > 460) return;
  for (const k in n) {
    if (k === 'loc' || k === 'extra' || k === 'tokens' || k === 'comments') continue;
    const v = n[k];
    if (Array.isArray(v)) v.forEach((x, i) => visit(x, depth+1, path + '.' + k + '[' + i + ']'));
    else if (v && typeof v === 'object' && !(v instanceof RegExp)) visit(v, depth+1, path + '.' + k);
  }
}
visit(ast, 0, 'root');
