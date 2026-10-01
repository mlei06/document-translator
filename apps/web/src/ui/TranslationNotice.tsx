import type { ResultReport } from '../api/queries'

export function TranslationNotice({ report }: { report: ResultReport | undefined }) {
  const preserved = (report?.diagnostics ?? [])
    .filter((diagnostic) => diagnostic.code === 'empty_translation_preserved')
    .reduce((count, diagnostic) => count + diagnostic.count, 0)
  if (!preserved) return null

  return (
    <p className="translation-notice" role="status">
      {preserved === 1 ? 'One text segment was' : `${preserved} text segments were`} left in the
      original language because the translator returned no text. Your file is ready to download.
    </p>
  )
}
