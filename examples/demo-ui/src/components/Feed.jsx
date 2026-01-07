import { useState, useEffect } from 'react'
import { CheckCircle, Clock, AlertTriangle, Activity, MapPin, Hash } from 'lucide-react'

export function Feed() {
    const [items, setItems] = useState([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        const fetchFeed = async () => {
            try {
                const res = await fetch('/api/v1/truth/feed?limit=20')
                if (res.ok) {
                    const data = await res.json()
                    setItems(data)
                }
            } catch (err) {
                console.error("Failed to fetch feed", err)
            } finally {
                setLoading(false)
            }
        }

        fetchFeed()
        // Poll every 2 seconds for live updates
        const interval = setInterval(fetchFeed, 2000)
        return () => clearInterval(interval)
    }, [])

    if (loading && items.length === 0) return <div className="text-secondary animate-pulse">Initializing Neural Link...</div>

    return (
        <div className="flex flex-col gap-4">
            {items.map((item) => (
                <TruthCard key={item.truthkey} item={item} />
            ))}
        </div>
    )
}

function TruthCard({ item }) {
    const isVerified = item.status === 'VERIFIED_TRUE'
    const isPending = item.status === 'PENDING'

    return (
        <div className={`card flex flex-col gap-3 ${isVerified ? 'border-success' : ''}`}>
            <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                    <StatusIcon status={item.status} />
                    <span className="mono text-sm text-secondary">{item.claim_type}</span>
                </div>
                <div className="text-xs text-secondary mono" title={item.created_at}>
                    {new Date(item.updated_at).toLocaleTimeString()}
                </div>
            </div>

            <div className="flex flex-col gap-1">
                <div className="font-mono text-xs text-secondary break-all opacity-50">
                    {item.truthkey.split(':').slice(0, 4).join(':')}...
                </div>
                <div className="flex items-center justify-between mt-2">
                    <div className="flex items-center gap-4">
                        <Metric icon={Activity} label="CONF" value={item.confidence.toFixed(4)} color="var(--accent-primary)" />
                        <Metric icon={MapPin} label="OBS" value={item.observation_count} />
                    </div>
                    <span className={`badge ${isVerified ? 'verified' : isPending ? 'pending' : 'investigating'}`}>
                        {item.status}
                    </span>
                </div>
            </div>
        </div>
    )
}

function StatusIcon({ status }) {
    if (status === 'VERIFIED_TRUE') return <CheckCircle className="w-5 h-5 text-success" />
    if (status === 'PENDING') return <Clock className="w-5 h-5 text-warning" />
    return <AlertTriangle className="w-5 h-5 text-error" />
}

function Metric({ icon: Icon, label, value, color }) {
    return (
        <div className="flex items-center gap-1.5" style={{ color: color || 'inherit' }}>
            <Icon className="w-4 h-4" />
            <div className="flex flex-col">
                <span className="text-[10px] uppercase opacity-70 leading-none">{label}</span>
                <span className="font-mono text-sm font-bold leading-none">{value}</span>
            </div>
        </div>
    )
}
