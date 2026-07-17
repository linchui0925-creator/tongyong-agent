/**
 * AmbientScene — 维知 The Thinking Loom 拓扑线场
 *
 * 100 个节点缓慢漂浮, 邻近对之间画细线。
 * 中心用径向蒙版做"呼吸的空白" (不硬切, 让视线落到聊天上)。
 * 颜色取自主题的 4 个 accent, 不同主题下气质不同。
 * prefers-reduced-motion → 静止渲染一帧。
 */

import { useEffect, useRef } from 'react';

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  hue: 0 | 1 | 2 | 3;
}

const COUNT = 110;
const MAX_DIST = 110;
const MIN_DIST_FACTOR = 0.04;
const MAX_DIST_FACTOR = 0.12;

export default function AmbientScene() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

    let width = 0;
    let height = 0;
    let dpr = 1;
    const nodes: Node[] = [];
    const pointer = { x: -9999, y: -9999, active: false };

    const readAccent = (varName: string, fallback: string): string => {
      const v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
      return v || fallback;
    };

    const accents = ['#b8302a', '#2a4d8f', '#c69a3a', '#6b3d8e'];
    let colors = accents.slice();

    const refreshThemeColors = () => {
      const a1 = readAccent('--accent', accents[0]);
      const a2 = readAccent('--accent-2', accents[1]);
      const a3 = readAccent('--accent-3', accents[2]);
      const a4 = readAccent('--accent-4', accents[3]);
      colors = [a1, a2, a3, a4];
    };

    refreshThemeColors();
    const themeObserver = new MutationObserver(refreshThemeColors);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    const rand = (a: number, b: number) => a + Math.random() * (b - a);

    const init = () => {
      nodes.length = 0;
      for (let i = 0; i < COUNT; i++) {
        nodes.push({
          x: Math.random(),
          y: Math.random(),
          vx: rand(-0.00006, 0.00006),
          vy: rand(-0.00006, 0.00006),
          hue: (i % 4) as 0 | 1 | 2 | 3,
        });
      }
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const onMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.x = e.clientX - rect.left;
      pointer.y = e.clientY - rect.top;
      pointer.active = true;
    };
    const onLeave = () => { pointer.active = false; pointer.x = -9999; };

    const step = () => {
      ctx.clearRect(0, 0, width, height);

      // 1. 移动 + 边缘环绕
      for (const n of nodes) {
        n.x = (n.x + n.vx + 1) % 1;
        n.y = (n.y + n.vy + 1) % 1;
      }

      // 2. 节点之间的连线 (O(n^2) 但 N=110 还行)
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        const ax = a.x * width;
        const ay = a.y * height;
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const bx = b.x * width;
          const by = b.y * height;
          const dx = ax - bx;
          const dy = ay - by;
          const d = Math.hypot(dx, dy);
          if (d < MAX_DIST) {
            const alpha = (1 - d / MAX_DIST);
            const a0 = MIN_DIST_FACTOR + (MAX_DIST_FACTOR - MIN_DIST_FACTOR) * alpha;
            const color = colors[(a.hue + b.hue) % 4];
            ctx.beginPath();
            ctx.moveTo(ax, ay);
            ctx.lineTo(bx, by);
            ctx.strokeStyle = hexToRgba(color, a0);
            ctx.lineWidth = 0.6;
            ctx.stroke();
          }
        }
      }

      // 3. 节点本身 (很小的点, 仅作锚点)
      for (const n of nodes) {
        const x = n.x * width;
        const y = n.y * height;
        ctx.beginPath();
        ctx.arc(x, y, 0.9, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(colors[n.hue], 0.32);
        ctx.fill();
      }

      // 4. 鼠标近端的柔光 (很轻, 30px 半径)
      if (pointer.active) {
        for (const n of nodes) {
          const x = n.x * width;
          const y = n.y * height;
          const d = Math.hypot(x - pointer.x, y - pointer.y);
          if (d < 90) {
            ctx.beginPath();
            ctx.moveTo(pointer.x, pointer.y);
            ctx.lineTo(x, y);
            ctx.strokeStyle = hexToRgba(colors[n.hue], 0.18 * (1 - d / 90));
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // 5. 中央径向蒙版: 让聊天区域更"呼吸"
      const cx = width / 2;
      const cy = height / 2;
      const innerR = Math.min(width, height) * 0.18;
      const outerR = Math.min(width, height) * 0.55;
      const grad = ctx.createRadialGradient(cx, cy, innerR, cx, cy, outerR);
      grad.addColorStop(0, 'rgba(0,0,0,1)');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.globalCompositeOperation = 'destination-out';
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);
      ctx.globalCompositeOperation = 'source-over';
    };

    const drawStatic = () => {
      // 单帧静止
      step();
    };

    let raf = 0;
    const loop = () => {
      step();
      raf = requestAnimationFrame(loop);
    };

    init();
    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerleave', onLeave);

    if (reduced) {
      drawStatic();
    } else {
      raf = requestAnimationFrame(loop);
    }

    return () => {
      cancelAnimationFrame(raf);
      themeObserver.disconnect();
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerleave', onLeave);
    };
  }, []);

  return (
    <div className="ambient-loom" aria-hidden="true">
      <canvas ref={canvasRef} className="ambient-loom-canvas" />
    </div>
  );
}

/** 兼容 'rgb(...)' / 颜色名 / 十六进制, 返回 rgba() 字符串 */
function hexToRgba(color: string, alpha: number): string {
  if (!color) return `rgba(184, 48, 42, ${alpha})`;
  const c = color.trim();
  if (c.startsWith('#')) {
    const hex = c.slice(1);
    const full = hex.length === 3
      ? hex.split('').map(ch => ch + ch).join('')
      : hex;
    if (full.length !== 6) return `rgba(184, 48, 42, ${alpha})`;
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  // 已是 rgb(...) — 直接替换 alpha
  const m = c.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const parts = m[1].split(',').map(s => s.trim());
    if (parts.length >= 3) {
      return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${alpha})`;
    }
  }
  return c;
}
