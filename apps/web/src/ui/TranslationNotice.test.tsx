import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { TranslationNotice } from './TranslationNotice'

afterEach(cleanup)

it('explains preserved original text without claiming the whole document failed', () => {
  render(
    <TranslationNotice
      report={{ diagnostics: [{ code: 'empty_translation_preserved', count: 1 }] }}
    />,
  )
  expect(screen.getByRole('status')).toHaveTextContent(
    'One text segment was left in the original language',
  )
  expect(screen.getByRole('status')).toHaveTextContent('Your file is ready to download.')
})

it('aggregates the document warning and does not display layout diagnostics', () => {
  render(
    <TranslationNotice
      report={{
        diagnostics: [
          { code: 'empty_translation_preserved', count: 2 },
          { code: 'empty_translation_preserved', count: 3 },
          { code: 'unresolved_fit', count: 4 },
        ],
      }}
    />,
  )
  expect(screen.getByRole('status')).toHaveTextContent('5 text segments were left')
  expect(screen.queryByText(/unresolved/)).toBeNull()
})

it('does not warn for ordinary results or while the report is loading', () => {
  const { rerender } = render(<TranslationNotice report={undefined} />)
  expect(screen.queryByRole('status')).toBeNull()
  rerender(<TranslationNotice report={{ diagnostics: [{ code: 'unresolved_fit', count: 4 }] }} />)
  expect(screen.queryByRole('status')).toBeNull()
})
