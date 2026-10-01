import type { CSSProperties } from 'react'
import { typeOf } from '../lib/format'

export function FileIcon({ format }: { format: string }) {
  const type = typeOf(format)
  return (
    <span
      className="ficon"
      style={{ '--tc': type.tc } as CSSProperties}
      role="img"
      aria-label={type.label}
    >
      <b>{type.tag}</b>
    </span>
  )
}
