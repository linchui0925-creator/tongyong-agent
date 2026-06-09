/**
 * 全局 React 错误边界 — 兜住子组件 render 期的同步异常，
 * 避免一处组件（如 TokenUsageBar 字段缺失）抛 TypeError 把整棵 React 树打挂、白屏。
 *
 * 用法：在父组件里 <ErrorBoundary>{children}</ErrorBoundary>，
 * 崩了渲染 fallback（默认一个占位卡片），用户可点"重试"清掉 errorState 重渲染。
 *
 * 注意：ErrorBoundary 只能挡 render / lifecycle / constructor 里的同步抛错，
 * 挡不住异步回调、事件处理、SSR 错误，这些要 try/catch 自己处理。
 */
import { Component, type ReactNode } from 'react'

type Props = {
  children: ReactNode
  fallback?: ReactNode
  /** 触发 fallback 时调用，常用于上报埋点 */
  onError?: (error: Error, errorInfo: { componentStack: string }) => void
}

type State = {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: { componentStack: string }) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] caught:', error, errorInfo)
    this.props.onError?.(error, errorInfo)
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div
          style={{
            padding: '24px',
            margin: '16px',
            border: '1px solid #f5c6cb',
            borderRadius: 8,
            background: '#f8d7da',
            color: '#721c24',
            fontFamily: 'system-ui, sans-serif',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8 }}>⚠ 组件渲染异常</div>
          <div style={{ fontSize: 13, marginBottom: 12, opacity: 0.85 }}>
            {this.state.error?.message || '未知错误'}
          </div>
          <button
            onClick={this.handleRetry}
            style={{
              padding: '6px 12px',
              border: '1px solid #721c24',
              borderRadius: 4,
              background: '#fff',
              color: '#721c24',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary