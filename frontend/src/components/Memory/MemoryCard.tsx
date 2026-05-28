import './MemoryCard.css'

interface Memory {
    id: string
    type: string
    content: string
    importance: number
    created_at: string
}

interface MemoryCardProps {
    memory: Memory
}

function MemoryCard({ memory }: MemoryCardProps) {
    const getTypeColor = (type: string) => {
        const colors: Record<string, string> = {
            '操作习惯': '#1890ff',
            '分析结论': '#52c41a',
            '关键决策': '#faad14'
        }
        return colors[type] || '#666'
    }

    const formatDate = (dateStr: string) => {
        if (!dateStr) return ''
        try {
            return new Date(dateStr).toLocaleString('zh-CN')
        } catch {
            return dateStr
        }
    }

    return (
        <div className="memory-card">
            <div className="memory-card-header">
                <span 
                    className="memory-type"
                    style={{ backgroundColor: getTypeColor(memory.type) }}
                >
                    {memory.type}
                </span>
                <span className="memory-importance">
                    {'★'.repeat(Math.min(memory.importance, 5))}
                </span>
            </div>
            <div className="memory-content">
                {memory.content}
            </div>
            <div className="memory-time">
                {formatDate(memory.created_at)}
            </div>
        </div>
    )
}

export default MemoryCard