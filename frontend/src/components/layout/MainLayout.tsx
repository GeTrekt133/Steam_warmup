import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

export function MainLayout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="ml-[250px] flex-1 min-h-screen">
        <Outlet />
      </main>
    </div>
  )
}
