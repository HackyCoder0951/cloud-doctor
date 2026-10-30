// Prints infra/nginx/cloud-doctor.conf with the tagged lines overridden, e.g.
//   node scripts/render-nginx.mjs --upstream 10.0.0.5:9000 --root /var/www/cd --listen 0.0.0.0:80 > cloud-doctor.conf
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const conf = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'infra', 'nginx', 'cloud-doctor.conf');
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith('--') ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const SAFE = /^[A-Za-z0-9_.:\/-]+$/; // no spaces, quotes, semicolons or braces: nothing that could inject directives
for (const [k, v] of Object.entries(args)) if (!['upstream', 'root', 'listen'].includes(k) || !v || !SAFE.test(v)) { console.error(`bad argument --${k} ${v ?? ''}`); process.exit(2); }

let text = readFileSync(conf, 'utf8');
if (args.upstream) text = text.replace(/^(\s*)server [^;]+;(\s*# @upstream)/m, `$1server ${args.upstream};$2`);
if (args.listen) text = text.replace(/^(\s*)listen [^;]+;(\s*# @listen)/m, `$1listen ${args.listen};$2`);
if (args.root) text = text.replace(/^(\s*)root [^;]+;(\s*# @root)/m, `$1root ${args.root};$2`);
process.stdout.write(text);
