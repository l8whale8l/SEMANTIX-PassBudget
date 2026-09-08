// Copy CesiumJS runtime assets into public/cesium/ so the globe runs fully offline (no Cesium Ion,
// no CDN). Vite serves public/ as-is in dev and copies it into dist/ on build, so the Workers,
// the bundled Assets (including the public-domain Natural Earth II base imagery), ThirdParty, and
// the Widgets CSS all load from the same origin with the external internet blocked.
//
// Runs from `predev` / `prebuild` (see package.json). public/cesium/ is generated, not committed
// (see .gitignore). Pure fs — no native modules — so it is safe on the repo's non-ASCII path.

import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = join(here, '..')
const cesiumBuild = join(frontendRoot, 'node_modules', 'cesium', 'Build', 'Cesium')
const target = join(frontendRoot, 'public', 'cesium')

// Only what the runtime needs. (We deliberately omit online imagery/terrain providers' data — the
// base layer is the bundled Natural Earth II under Assets.)
const SUBDIRS = ['Workers', 'Assets', 'ThirdParty', 'Widgets']

if (!existsSync(cesiumBuild)) {
  console.error(
    `[copy-cesium-assets] cesium build not found at ${cesiumBuild}. Run "npm install" first.`,
  )
  process.exit(1)
}

rmSync(target, { recursive: true, force: true })
mkdirSync(target, { recursive: true })
for (const sub of SUBDIRS) {
  const from = join(cesiumBuild, sub)
  if (!existsSync(from)) {
    console.error(`[copy-cesium-assets] missing ${from}`)
    process.exit(1)
  }
  cpSync(from, join(target, sub), { recursive: true })
}
console.log(`[copy-cesium-assets] copied ${SUBDIRS.join(', ')} -> public/cesium/`)
