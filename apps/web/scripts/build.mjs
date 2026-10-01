import { build } from 'vite'

// Await all bundling and output writes. A rejected build still exits unsuccessfully.
await build()

// Native file handles can keep Vite alive after a completed build on Windows.
process.exit(0)
