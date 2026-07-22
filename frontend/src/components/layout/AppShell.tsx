import type { ReactNode } from 'react'
import { Header } from './Header'
import { TabNav } from './TabNav'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto min-h-screen max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
      <Header />
      <TabNav />
      <main>{children}</main>
    </div>
  )
}
