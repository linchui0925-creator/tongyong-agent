import { useEffect, useRef } from 'react';

export default function AmbientScene() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    let frame = 0;
    let width = 0;
    let height = 0;
    const pointer = { x: -1000, y: -1000 };
    const particles = Array.from({ length: innerWidth < 700 ? 14 : 38 }, (_, i) => ({
      x: Math.random(), y: Math.random(), vx: (Math.random() - .5) * .00013,
      vy: (Math.random() - .5) * .00013, r: 1 + Math.random() * 1.7,
      hue: i % 3 === 0 ? 275 : i % 3 === 1 ? 195 : 155,
    }));
    const resize = () => {
      width = canvas.clientWidth; height = canvas.clientHeight;
      const dpr = Math.min(devicePixelRatio, 2);
      canvas.width = width * dpr; canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const move = (e: PointerEvent) => { pointer.x = e.clientX; pointer.y = e.clientY; };
    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      particles.forEach((p, i) => {
        p.x = (p.x + p.vx + 1) % 1; p.y = (p.y + p.vy + 1) % 1;
        const x = p.x * width, y = p.y * height;
        const distance = Math.hypot(x - pointer.x, y - pointer.y);
        const glow = distance < 180 ? .75 : .32;
        ctx.beginPath(); ctx.arc(x, y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${p.hue},95%,72%,${glow})`; ctx.fill();
        particles.slice(i + 1).forEach(q => {
          const qx = q.x * width, qy = q.y * height, d = Math.hypot(x - qx, y - qy);
          if (d < 115) {
            ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(qx, qy);
            ctx.strokeStyle = `rgba(150,130,255,${.08 * (1 - d / 115)})`; ctx.stroke();
          }
        });
      });
      frame = requestAnimationFrame(draw);
    };
    resize(); draw(); addEventListener('resize', resize); addEventListener('pointermove', move);
    return () => { cancelAnimationFrame(frame); removeEventListener('resize', resize); removeEventListener('pointermove', move); };
  }, []);

  return <canvas ref={canvasRef} className="ambient-scene" aria-hidden="true" />;
}
