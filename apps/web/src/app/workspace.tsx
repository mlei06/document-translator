// Shared UI actions for the signed-in workspace (header, menus, panels and the stage).
import { createContext, useContext } from 'react'
import type { Job } from '../api/client'
import type { Line } from '../lenny/Speech'

export interface Workspace {
  /** Say something for a moment (theme change, settings); restoreSpeech returns to the flow. */
  say: (line: Line) => void
  restoreSpeech: () => void
  toast: (message: string) => void
  pickFiles: () => void
  feedSamples: () => void
  openHistory: () => void
  openSettings: () => void
  startOver: () => void
  signOut: () => void
  /** Put a job's bubble on the meadow (new submissions, restores, retranslations). */
  addBubble: (job: Job, from?: { x: number; y: number } | null) => void
  onMeadow: (jobId: string) => boolean
  /** A deleted source document: its bubbles and preview go too (downloads are revoked). */
  forgetDocument: (docId: string) => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)

export function useWorkspace(): Workspace {
  const ws = useContext(WorkspaceContext)
  if (!ws) throw new Error('useWorkspace outside the workspace')
  return ws
}
