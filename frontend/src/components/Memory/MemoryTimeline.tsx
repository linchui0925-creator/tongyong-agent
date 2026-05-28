import { useMemo } from 'react'
import './MemoryTimeline.css'

interface Memory {
  id: string
  type: string
  content: string
  importance: number
  created_at: string
  updated_at?: string
  session_id?: string
}

interface MemoryTimelineProps {
  memories: Memory[]
  onMemoryClick?: (memory: Memory) => void
  maxHeight?: string
}

function MemoryTimeline({ memories, onMemoryClick, maxHeight = '600px' }: MemoryTimelineProps) {
  const groupedMemories = useMemo(() => {
    const groups: Record<string, Memory[]> = {}
    
    memories.forEach(memory => {
      const date = new Date(memory.created_at)
      const dateKey = date.toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
      
      if (!groups[dateKey]) {
        groups[dateKey] = []
      }
      groups[dateKey].push(memory)
    })
    
    // Sort groups by date (newest first)
    const sortedGroups = Object.entries(groups).sort(([dateA], [dateB]) => {
      const dateObjA = new Date(dateA)
      const dateObjB = new Date(dateB)
      return dateObjB.getTime() - dateObjA.getTime()
    })
    
    return sortedGroups
  }, [memories])

  const getTypeColor = (type: string): string => {
    const colors: Record<string, string> = {
      '操作习惯': '#1890ff',
      '分析结论': '#52c41a',
      '关键决策': '#faad14',
      '其他': '#666666'
    }
    return colors[type] || '#666666'
  }

  const getTypeIcon = (type: string): string => {
    const icons: Record<string, string> = {
      '操作习惯': '🎯',
      '分析结论': '📊',
      '关键决策': '💡',
      '其他': '📝'
    }
    return icons[type] || '📝'
  }

  const formatTime = (dateStr: string): string => {
    const date = new Date(dateStr)
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const renderImportance = (importance: number): string => {
    return '★'.repeat(importance) + '☆'.repeat(5 - importance)
  }

  if (memories.length === 0) {
    return (
      <div className="memory-timeline empty">
        <div className="empty-state">
          <span className="empty-icon">📭</span>
          <p>暂无记忆记录</p>
          <span className="empty-hint">开始对话后，记忆会自动记录在这里</span>
        </div>
      </div>
    )
  }

  return (
    <div className="memory-timeline" style={{ maxHeight }}>
      <div className="timeline-header">
        <h3>记忆时间线</h3>
        <span className="memory-count">{memories.length} 条记忆</span>
      </div>
      
      <div className="timeline-content">
        {groupedMemories.map(([date, dateMemories]) => (
          <div key={date} className="timeline-group">
            <div className="timeline-date">
              <span className="date-badge">{date}</span>
              <span className="date-count">{dateMemories.length} 条</span>
            </div>
            
            <div className="timeline-items">
              {dateMemories.map(memory => (
                <div
                  key={memory.id}
                  className="timeline-item"
                  onClick={() => onMemoryClick?.(memory)}
                >
                  <div className="item-header">
                    <span className="item-icon">{getTypeIcon(memory.type)}</span>
                    <span
                      className="item-type"
                      style={{ backgroundColor: getTypeColor(memory.type) }}
                    >
                      {memory.type}
                    </span>
                    <span className="item-importance">
                      {renderImportance(memory.importance)}
                    </span>
                  </div>
                  
                  <div className="item-content">
                    {memory.content}
                  </div>
                  
                  <div className="item-footer">
                    <span className="item-time">
                      {formatTime(memory.created_at)}
                    </span>
                    {memory.updated_at && memory.updated_at !== memory.created_at && (
                      <span className="item-updated">
                        已更新: {formatTime(memory.updated_at)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default MemoryTimeline
