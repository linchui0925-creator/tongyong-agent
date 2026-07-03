import React, { useState, useEffect, useRef, useCallback } from 'react';

import EvilEye from '../EvilEye/EvilEye';
import './SplashScreen.css';

const SPLASH_SEEN_KEY = 'ty_splash_seen_v2';

function markSplashSeen() {
  try {
    window.localStorage.setItem(SPLASH_SEEN_KEY, '1');
  } catch {
    // ignore
  }
}

interface SplashScreenProps {
  onFinish: () => void;
}

export const SplashScreen: React.FC<SplashScreenProps> = ({ onFinish }) => {
  // 0 = fully open, 1 = fully closed. Animated by an rAF tween.
  const [closeAmount, setCloseAmount] = useState(0);
  const [isHovering, setIsHovering] = useState(false);
  const [glowBoost, setGlowBoost] = useState(0);
  const [isFinishing, setIsFinishing] = useState(false);

  const targetRef = useRef(0);
  const valueRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const stopRaf = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const tick = useCallback(() => {
    rafRef.current = null;
    const target = targetRef.current;
    const cur = valueRef.current;
    const diff = target - cur;
    if (Math.abs(diff) < 0.002) {
      valueRef.current = target;
      setCloseAmount(target);
      return;
    }
    // Closing is fast (~0.25s feel), opening is slow (~1.2s feel).
    const rate = diff > 0 ? 9.0 : 1.4;
    const next = cur + diff * rate * 0.016;
    const clamped = Math.max(0, Math.min(1, next));
    valueRef.current = clamped;
    setCloseAmount(clamped);
    rafRef.current = requestAnimationFrame(tick);
  }, []);

  const startRaf = useCallback(() => {
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(tick);
  }, [tick]);

  useEffect(() => stopRaf, [stopRaf]);

  const setTarget = useCallback(
    (t: number) => {
      targetRef.current = t;
      startRaf();
    },
    [startRaf]
  );

  const handleMouseEnter = () => {
    setIsHovering(true);
    setTarget(1);
    setGlowBoost(0.6);
  };

  const handleMouseLeave = () => {
    setIsHovering(false);
    setTarget(0);
    setGlowBoost(0);
  };

  // Click the eye to enter the chat page. Brief flash, then navigate.
  const handleEyeClick = () => {
    if (isFinishing) return;
    setIsFinishing(true);
    setGlowBoost(2.4);
    setTimeout(() => {
      markSplashSeen();
      onFinish();
    }, 320);
  };

  const handleSkip = () => {
    if (isFinishing) return;
    setIsFinishing(true);
    markSplashSeen();
    onFinish();
  };

  return (
    <div className="splash-root">
      <div className="bg-particles">
        {Array.from({ length: 50 }).map((_, i) => (
          <div
            key={i}
            className="particle"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 5}s`,
              animationDuration: `${2 + Math.random() * 4}s`,
            }}
          />
        ))}
      </div>

      <div className="splash-content">
        <h1 className="splash-title">
          <span className="gold-text">通用AI助手</span>
        </h1>
        <p className="splash-subtitle">开启你的智能会话之旅</p>

        <div
          className="eye-container"
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
          onClick={handleEyeClick}
        >
          <EvilEye
            eyeColor="#D4AF37"
            intensity={1.8}
            glowIntensity={0.6}
            scale={1.2}
            flameSpeed={0.8}
            closeAmount={closeAmount}
            glowBoost={glowBoost}
          />
        </div>

        <p className="splash-tip" aria-live="polite">
          {isHovering ? '点击眼睛进入会话' : '将鼠标移动到眼睛上 · 轻点进入'}
        </p>

        <button className="skip-button" onClick={handleSkip}>
          跳过
        </button>
      </div>

      <div className="bg-glow" />
    </div>
  );
};

export function shouldShowSplash(): boolean {
  try {
    return window.localStorage.getItem(SPLASH_SEEN_KEY) !== '1';
  } catch {
    return true;
  }
}
