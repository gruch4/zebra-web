import { createBrowserRouter } from 'react-router'

import { AppLayout } from './components/AppLayout'
import { DesignerPage } from './pages/DesignerPage'
import { HistoryPage } from './pages/HistoryPage'
import { IntegrationsPage } from './pages/IntegrationsPage'
import { LabelsPage } from './pages/LabelsPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PrinterSettingsPage } from './pages/PrinterSettingsPage'
import { PrintersPage } from './pages/PrintersPage'
import { PrintPage } from './pages/PrintPage'
import { TemplatePrintPage } from './pages/TemplatePrintPage'
import { TemplatesPage } from './pages/TemplatesPage'

export const routes = [
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <PrintPage /> },
      { path: 'designer', element: <DesignerPage /> },
      { path: 'designer/:labelId', element: <DesignerPage /> },
      { path: 'labels', element: <LabelsPage /> },
      { path: 'templates', element: <TemplatesPage /> },
      { path: 'templates/:labelId', element: <TemplatePrintPage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'printers', element: <PrintersPage /> },
      { path: 'printers/:id', element: <PrinterSettingsPage /> },
      { path: 'integrations', element: <IntegrationsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
