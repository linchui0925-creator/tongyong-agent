import { useTheme } from '../../theme/ThemeContext'
import { themes } from '../../theme/themes'
import './BranchCanopy.css'

/**
 * BranchCanopy — 四季春 (W5-3) 真实枝桠背景
 *
 * 4 边各 7 根主枝, 每根用 cubic-bezier 加扭转模拟真实树木弯曲。
 * 主枝/枝/嫩枝 3 级递进变细, 末端放小绿点 (嫩芽)。
 * 用 SAFE 矩形 (中间会话区) 做 ray cast 截断: 任何 path 进入 SAFE 前停下,
 * 形成"环绕中间会话"的边框效果。
 *
 * mulberry32 种子 PRNG 保证每次渲染一致。
 */

function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface Seg {
  d: string
  level: number // 0=主枝, 1=分枝, 2=嫩枝
}

interface Tip {
  x: number
  y: number
}

// 中间会话区 (viewBox 0-100), 枝桠不能进入
const SAFE = { x1: 22, y1: 22, x2: 78, y2: 78 }

function lengthToSafe(x: number, y: number, angle: number, margin: number): number {
  // 沿射线 (x+t·cos, y+t·sin) 进入 SAFE 的最小 t
  const dx = Math.cos(angle)
  const dy = Math.sin(angle)
  const candidates: number[] = []
  if (dx > 1e-6) candidates.push((SAFE.x1 - x) / dx)
  if (dx < -1e-6) candidates.push((SAFE.x2 - x) / dx)
  if (dy > 1e-6) candidates.push((SAFE.y1 - y) / dy)
  if (dy < -1e-6) candidates.push((SAFE.y2 - y) / dy)
  const valid = candidates.filter((t) => t > 0)
  return valid.length > 0 ? Math.min(...valid) - margin : Infinity
}

function buildTree(
  rng: () => number,
  x: number,
  y: number,
  angle: number,
  requestedLength: number,
  level: number,
  out: { segs: Seg[]; tips: Tip[] },
): void {
  if (level > 2) {
    out.tips.push({ x, y })
    return
  }
  // 主枝 margin 大 (留 2 单位缓冲); 分枝/嫩枝 margin 小
  const margin = level === 0 ? 2.0 : 0.8
  const maxLen = lengthToSafe(x, y, angle, margin)
  const actualLen = Math.min(requestedLength, maxLen)
  if (actualLen < 1.2) {
    out.tips.push({ x, y })
    return
  }

  // Cubic bezier with twist: 2 个控制点垂直于方向偏移, 模拟自然弯曲
  const twist = (rng() - 0.5) * 0.7
  const perpX = -Math.sin(angle)
  const perpY = Math.cos(angle)

  const cp1X = x + Math.cos(angle) * actualLen * 0.28 + perpX * twist * actualLen * 0.35
  const cp1Y = y + Math.sin(angle) * actualLen * 0.28 + perpY * twist * actualLen * 0.35
  const cp2X = x + Math.cos(angle) * actualLen * 0.72 + perpX * twist * actualLen * 0.45
  const cp2Y = y + Math.sin(angle) * actualLen * 0.72 + perpY * twist * actualLen * 0.45
  const endX = x + Math.cos(angle) * actualLen
  const endY = y + Math.sin(angle) * actualLen

  out.segs.push({
    d: `M ${x.toFixed(2)} ${y.toFixed(2)} C ${cp1X.toFixed(2)} ${cp1Y.toFixed(2)}, ${cp2X.toFixed(2)} ${cp2Y.toFixed(2)}, ${endX.toFixed(2)} ${endY.toFixed(2)}`,
    level,
  })

  // 分叉: 65% 概率 2 子枝, 35% 概率 3 子枝
  const numChildren = rng() < 0.65 ? 2 : 3
  for (let i = 0; i < numChildren; i++) {
    let childAngle: number
    if (numChildren === 2) {
      // 二叉: 左右各偏 36-66° + 随机扰动
      const spread = Math.PI / 5 + rng() * (Math.PI / 6)
      childAngle = angle + (i === 0 ? -1 : 1) * spread + (rng() - 0.5) * 0.25
    } else {
      // 三叉: 一枝继续直行, 两枝左右张开
      if (i === 0) {
        childAngle = angle + (rng() - 0.5) * 0.4
      } else {
        const side = i === 1 ? -1 : 1
        childAngle = angle + side * (Math.PI / 3.5 + rng() * 0.3) + (rng() - 0.5) * 0.2
      }
    }
    // 子枝长度: 0.55-0.75 父枝
    const childLength = actualLen * (0.55 + rng() * 0.2)
    buildTree(rng, endX, endY, childAngle, childLength, level + 1, out)
  }
}

type Edge = 't' | 'r' | 'b' | 'l'

function buildEdge(rng: () => number, edge: Edge, count: number) {
  const segs: Seg[] = []
  const tips: Tip[] = []
  for (let i = 0; i < count; i++) {
    // 沿边均匀取 count 个种子点 + 位置扰动
    const t = (i + 0.5 + (rng() - 0.5) * 0.45) / count
    let x = 0, y = 0, baseAngle = 0
    if (edge === 't') {
      x = t * 100; y = 0; baseAngle = Math.PI / 2 + (rng() - 0.5) * 0.5
    } else if (edge === 'b') {
      x = t * 100; y = 100; baseAngle = -Math.PI / 2 + (rng() - 0.5) * 0.5
    } else if (edge === 'l') {
      x = 0; y = t * 100; baseAngle = 0 + (rng() - 0.5) * 0.5
    } else {
      x = 100; y = t * 100; baseAngle = Math.PI + (rng() - 0.5) * 0.5
    }
    // 主枝长 14-22, 递归 3 层 (level 0/1/2)
    buildTree(rng, x, y, baseAngle, 14 + rng() * 8, 0, { segs, tips })
  }
  return { segs, tips }
}

const EDGES: Edge[] = ['t', 'r', 'b', 'l']
const ALL_SEGS: Seg[] = []
const ALL_TIPS: Tip[] = []
;(function build() {
  const rng = mulberry32(20240716)
  EDGES.forEach((edge) => {
    const r = buildEdge(rng, edge, 7)
    ALL_SEGS.push(...r.segs)
    ALL_TIPS.push(...r.tips)
  })
})()

function BranchCanopy() {
  const { theme } = useTheme()
  const season = themes[theme].season

  return (
    <div className={`branch-canopy branch-canopy--${season}`} aria-hidden="true">
      <svg
        className="branch-canopy__svg"
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
        xmlns="http://www.w3.org/2000/svg"
      >
        <g className="branches">
          {ALL_SEGS.map((s, i) => (
            <path key={i} d={s.d} pathLength="1" className={`branch branch--l${s.level}`} />
          ))}
        </g>
        <g className="buds">
          {ALL_TIPS.map((p, i) => (
            <circle key={i} cx={p.x} cy={p.y} r="0.5" className="bud" />
          ))}
        </g>
      </svg>
    </div>
  )
}

export default BranchCanopy
