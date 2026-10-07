// Parse the web modules as real ES modules (node --check passes .js files it treats as CommonJS).
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
let bad = 0;
for (const f of process.argv.slice(2)) {
  try { new vm.SourceTextModule(readFileSync(f, 'utf8'), { identifier: f }); console.log('OK   ' + f); }
  catch (e) { bad++; console.log('FAIL ' + f + ': ' + e.message); }
}
process.exit(bad ? 1 : 0);
