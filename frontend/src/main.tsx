import '@mantine/core/styles.css'
import '@mantine/dates/styles.css'
import '@mantine/notifications/styles.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { App } from './App'
import { createQueryClient } from './api/queryClient'
import { AppProviders } from './AppProviders'
import { APP_NAME } from './config'

document.title = APP_NAME

const root = document.getElementById('root')
if (!root) {
  throw new Error('index.html has no #root element')
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <AppProviders queryClient={createQueryClient()}>
        <App />
      </AppProviders>
    </BrowserRouter>
  </StrictMode>,
)
