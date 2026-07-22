import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '@/app/App'
import { PipelineProvider } from '@/app/providers/PipelineProvider'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PipelineProvider>
      <App />
    </PipelineProvider>
  </StrictMode>,
)
