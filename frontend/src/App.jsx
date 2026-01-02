import { Feed } from './components/Feed'
import { Radio } from 'lucide-react'

function App() {
  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between mb-8 border-b border-white/10 pb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-accent-primary/10 rounded-lg">
            <Radio className="w-6 h-6 text-accent-primary animate-pulse" />
          </div>
          <div>
            <h1 className="text-2xl neon-text">KAORI PULSE</h1>
            <div className="text-secondary text-sm">Real-time Truth Extraction Protocol</div>
          </div>
        </div>
        <div className="flex gap-4">
          <div className="text-right">
            <div className="text-xs text-secondary uppercase">Network Status</div>
            <div className="text-success font-mono">ONLINE</div>
          </div>
        </div>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent-primary"></span>
            Inbound Feed
          </h2>
          <Feed />
        </div>

        <div className="space-y-6">
          <div className="card bg-bg-card/50">
            <h3 className="text-sm uppercase text-secondary mb-4">Node Metrics</h3>
            <div className="space-y-4 font-mono text-sm">
              <div className="flex justify-between">
                <span>TPS</span>
                <span className="text-accent-primary">12.4</span>
              </div>
              <div className="flex justify-between">
                <span>Pending</span>
                <span className="text-warning">0</span>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
