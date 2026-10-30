// Fails (exit 1) when src/api/schema.d.ts is stale relative to ../contracts/openapi.yaml.
// Regenerates into a temp file with the pinned openapi-typescript and compares byte for byte.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const committed = join(root, 'src/api/schema.d.ts');
const dir = mkdtempSync(join(tmpdir(), 'cd-api-'));
const fresh = join(dir, 'schema.d.ts');
try {
  execFileSync(
    process.execPath,
    [join(root, 'node_modules/openapi-typescript/bin/cli.js'), join(root, '../contracts/openapi.yaml'), '-o', fresh],
    { stdio: ['ignore', 'ignore', 'inherit'], cwd: root },
  );
  if (readFileSync(committed, 'utf8') !== readFileSync(fresh, 'utf8')) {
    console.error('src/api/schema.d.ts is STALE: run `npm run gen:api` and commit the result.');
    process.exit(1);
  }
  console.log('ok: src/api/schema.d.ts is up to date with contracts/openapi.yaml');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
