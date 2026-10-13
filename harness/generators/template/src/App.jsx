import { Link, Route, Routes } from 'react-router-dom'
import Home from './pages/Home.jsx'

// Add a page: create src/pages/<Name>.jsx, import it here, and add one <Route>.
export default function App() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <nav className="flex gap-4 border-b border-slate-200 px-6 py-4">
        <Link to="/" className="font-semibold">Home</Link>
      </nav>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Home />} />
        </Routes>
      </main>
    </div>
  )
}
