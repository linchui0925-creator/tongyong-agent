/**
 * AIAssistant — inline-SVG anime-style AI assistant avatar used as the
 * centerContent of <OrbitImages />. Built from scratch (no external image),
 * so the page is fully self-contained and theme-aligned.
 *
 * Aesthetic: modern anime portrait with subtle "digital" cues (glowing
 * amber eyes, soft headpiece with circuit trim, holographic particle ring).
 * Colors track the dark-stone theme.
 */

export interface AIAssistantProps {
  size?: number;
  className?: string;
}

export default function AIAssistant({ size = 360, className }: AIAssistantProps) {
  return (
    <svg
      viewBox="0 0 400 400"
      width={size}
      height={size}
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="维知 AI 助手"
    >
      <defs>
        {/* Soft halo behind the head */}
        <radialGradient id="halo" cx="50%" cy="46%" r="55%">
          <stop offset="0%" stopColor="#FFB07A" stopOpacity="0.55" />
          <stop offset="55%" stopColor="#E63946" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#0B0908" stopOpacity="0" />
        </radialGradient>

        {/* Face skin gradient */}
        <linearGradient id="skin" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#FFE3CB" />
          <stop offset="100%" stopColor="#F4C7A5" />
        </linearGradient>

        {/* Hair gradient — dark with amber highlights */}
        <linearGradient id="hair" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#3A2A24" />
          <stop offset="55%" stopColor="#231613" />
          <stop offset="100%" stopColor="#0F0908" />
        </linearGradient>

        {/* Hair highlight */}
        <linearGradient id="hairHi" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#FF7A1A" stopOpacity="0" />
          <stop offset="50%" stopColor="#FF7A1A" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#FF7A1A" stopOpacity="0" />
        </linearGradient>

        {/* Iris gradient */}
        <radialGradient id="iris" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FFE0A8" />
          <stop offset="55%" stopColor="#FF7A1A" />
          <stop offset="100%" stopColor="#9A2A0F" />
        </radialGradient>

        {/* Sweater / collar */}
        <linearGradient id="collar" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#E63946" />
          <stop offset="100%" stopColor="#9A1B2A" />
        </linearGradient>

        {/* Headband metallic */}
        <linearGradient id="band" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#FFB07A" />
          <stop offset="50%" stopColor="#FFE3CB" />
          <stop offset="100%" stopColor="#FFB07A" />
        </linearGradient>

        {/* Cheek blush */}
        <radialGradient id="blush" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FF8A8A" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#FF8A8A" stopOpacity="0" />
        </radialGradient>

        {/* Particle pulse */}
        <radialGradient id="particle" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FFE3CB" stopOpacity="1" />
          <stop offset="100%" stopColor="#FFE3CB" stopOpacity="0" />
        </radialGradient>

        {/* Gentle float animation for the entire figure */}
        <style>{`
          @keyframes aiBreathe { 0%, 100% { transform: translateY(0) } 50% { transform: translateY(-4px) } }
          @keyframes aiBlink { 0%, 92%, 100% { transform: scaleY(1) } 95% { transform: scaleY(0.08) } }
          @keyframes aiEyeGlow { 0%, 100% { opacity: 0.85 } 50% { opacity: 1 } }
          @keyframes aiOrbit { 0% { transform: rotate(0deg) } 100% { transform: rotate(360deg) } }
          @keyframes aiSpark { 0%, 100% { opacity: 0.25 } 50% { opacity: 1 } }
          .ai-figure { animation: aiBreathe 5s ease-in-out infinite; transform-origin: 50% 60%; }
          .ai-eye { animation: aiBlink 6s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
          .ai-eye-glow { animation: aiEyeGlow 3s ease-in-out infinite; }
          .ai-spark { animation: aiSpark 2.4s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
          .ai-spark-b { animation: aiSpark 3.2s ease-in-out 0.6s infinite; transform-origin: center; transform-box: fill-box; }
          .ai-spark-c { animation: aiSpark 2.8s ease-in-out 1.2s infinite; transform-origin: center; transform-box: fill-box; }
        `}</style>
      </defs>

      {/* Halo */}
      <circle cx="200" cy="184" r="190" fill="url(#halo)" />

      {/* Sparkle particles around the figure */}
      <g>
        <circle className="ai-spark" cx="80" cy="120" r="3" fill="url(#particle)" />
        <circle className="ai-spark-b" cx="320" cy="100" r="2.5" fill="url(#particle)" />
        <circle className="ai-spark-c" cx="60" cy="260" r="2" fill="url(#particle)" />
        <circle className="ai-spark" cx="340" cy="240" r="3.2" fill="url(#particle)" />
        <circle className="ai-spark-b" cx="200" cy="60" r="2.6" fill="url(#particle)" />
        <circle className="ai-spark-c" cx="120" cy="340" r="2.2" fill="url(#particle)" />
        <circle className="ai-spark" cx="280" cy="340" r="2.8" fill="url(#particle)" />
      </g>

      <g className="ai-figure">
        {/* Shoulders / collar */}
        <path
          d="M70 400 C 80 320, 130 295, 165 290 L 235 290 C 270 295, 320 320, 330 400 Z"
          fill="url(#collar)"
        />
        {/* Collar trim */}
        <path
          d="M160 295 Q 200 320 240 295"
          fill="none"
          stroke="#FFE3CB"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.85"
        />
        {/* Small circuit emblem on collar */}
        <g transform="translate(200 350)" opacity="0.85">
          <circle cx="0" cy="0" r="8" fill="none" stroke="#FFE3CB" strokeWidth="1.6" />
          <circle cx="0" cy="0" r="2.6" fill="#FFE3CB" />
          <line x1="0" y1="-8" x2="0" y2="-14" stroke="#FFE3CB" strokeWidth="1.4" />
          <line x1="0" y1="8" x2="0" y2="14" stroke="#FFE3CB" strokeWidth="1.4" />
          <line x1="-8" y1="0" x2="-14" y2="0" stroke="#FFE3CB" strokeWidth="1.4" />
          <line x1="8" y1="0" x2="14" y2="0" stroke="#FFE3CB" strokeWidth="1.4" />
        </g>

        {/* Neck */}
        <path d="M178 280 L 178 305 Q 200 318 222 305 L 222 280 Z" fill="url(#skin)" />
        {/* Neck shadow */}
        <path d="M178 280 L 178 305 Q 200 318 222 305 L 222 280 Z" fill="#000" opacity="0.18" />

        {/* Head shape */}
        <path
          d="M120 200
             C 120 130, 160 92, 200 92
             C 240 92, 280 130, 280 200
             C 280 260, 245 295, 200 295
             C 155 295, 120 260, 120 200 Z"
          fill="url(#skin)"
        />

        {/* Hair — back layer */}
        <path
          d="M104 210
             C 100 130, 145 78, 200 78
             C 255 78, 300 130, 296 210
             C 296 222, 296 240, 292 256
             L 280 250
             C 282 220, 280 180, 268 158
             C 250 130, 226 116, 200 116
             C 174 116, 150 130, 132 158
             C 120 180, 118 220, 120 250
             L 108 256
             C 104 240, 104 222, 104 210 Z"
          fill="url(#hair)"
        />

        {/* Front bangs */}
        <path
          d="M132 158
             C 150 132, 178 120, 200 120
             C 222 120, 250 132, 268 158
             C 252 142, 232 134, 220 138
             C 218 124, 210 116, 200 116
             C 190 116, 182 124, 180 138
             C 168 134, 148 142, 132 158 Z"
          fill="url(#hair)"
        />
        {/* Side bangs */}
        <path
          d="M132 158
             C 122 188, 122 220, 128 246
             L 144 240
             C 140 218, 142 188, 148 168 Z"
          fill="url(#hair)"
        />
        <path
          d="M268 158
             C 278 188, 278 220, 272 246
             L 256 240
             C 260 218, 258 188, 252 168 Z"
          fill="url(#hair)"
        />
        {/* Hair highlight strands */}
        <path
          d="M150 130 Q 200 110 250 130"
          stroke="url(#hairHi)"
          strokeWidth="3"
          fill="none"
          opacity="0.6"
        />

        {/* Ears */}
        <path d="M118 200 Q 110 210 116 232 Q 124 222 122 200 Z" fill="url(#skin)" />
        <path d="M282 200 Q 290 210 284 232 Q 276 222 278 200 Z" fill="url(#skin)" />

        {/* Headband / AI crown */}
        <g>
          <path
            d="M132 134 Q 200 102 268 134 L 268 142 Q 200 116 132 142 Z"
            fill="url(#band)"
            opacity="0.95"
          />
          {/* Center jewel */}
          <circle cx="200" cy="124" r="6" fill="#E63946" />
          <circle cx="200" cy="124" r="2.4" fill="#FFE3CB" />
          {/* Side studs */}
          <circle cx="150" cy="128" r="2.2" fill="#E63946" />
          <circle cx="250" cy="128" r="2.2" fill="#E63946" />
          {/* Circuit traces on band */}
          <path d="M150 130 L 175 130 L 178 134" stroke="#FFB07A" strokeWidth="1" fill="none" opacity="0.7" />
          <path d="M250 130 L 225 130 L 222 134" stroke="#FFB07A" strokeWidth="1" fill="none" opacity="0.7" />
        </g>

        {/* Eyebrows */}
        <path d="M155 184 Q 170 178 184 184" stroke="#231613" strokeWidth="3" fill="none" strokeLinecap="round" />
        <path d="M216 184 Q 230 178 245 184" stroke="#231613" strokeWidth="3" fill="none" strokeLinecap="round" />

        {/* Eyes */}
        <g className="ai-eye">
          {/* Left eye */}
          <ellipse cx="170" cy="208" rx="14" ry="18" fill="#FFFFFF" />
          <circle cx="170" cy="210" r="11" fill="url(#iris)" />
          <circle cx="170" cy="210" r="5" fill="#0F0908" />
          <circle cx="167" cy="206" r="3" fill="#FFFFFF" />
          <circle cx="173" cy="213" r="1.6" fill="#FFFFFF" opacity="0.8" />
          {/* Eye glow */}
          <ellipse cx="170" cy="210" rx="22" ry="20" fill="#FF7A1A" className="ai-eye-glow" opacity="0.18" />

          {/* Right eye */}
          <ellipse cx="230" cy="208" rx="14" ry="18" fill="#FFFFFF" />
          <circle cx="230" cy="210" r="11" fill="url(#iris)" />
          <circle cx="230" cy="210" r="5" fill="#0F0908" />
          <circle cx="227" cy="206" r="3" fill="#FFFFFF" />
          <circle cx="233" cy="213" r="1.6" fill="#FFFFFF" opacity="0.8" />
          <ellipse cx="230" cy="210" rx="22" ry="20" fill="#FF7A1A" className="ai-eye-glow" opacity="0.18" />
        </g>

        {/* Cheeks */}
        <ellipse cx="152" cy="240" rx="14" ry="8" fill="url(#blush)" />
        <ellipse cx="248" cy="240" rx="14" ry="8" fill="url(#blush)" />

        {/* Nose */}
        <path d="M198 222 Q 200 240 204 246" stroke="#D69A78" strokeWidth="1.6" fill="none" strokeLinecap="round" />

        {/* Mouth */}
        <path
          d="M188 264 Q 200 274 212 264"
          stroke="#9A1B2A"
          strokeWidth="2.4"
          fill="none"
          strokeLinecap="round"
        />
        <path d="M192 266 Q 200 268 208 266" fill="#E63946" opacity="0.6" />

        {/* Lower hair flick */}
        <path
          d="M124 244 Q 110 280 130 308 L 144 296 Q 134 270 140 248 Z"
          fill="url(#hair)"
        />
        <path
          d="M276 244 Q 290 280 270 308 L 256 296 Q 266 270 260 248 Z"
          fill="url(#hair)"
        />
      </g>

      {/* Floor glow */}
      <ellipse cx="200" cy="386" rx="120" ry="14" fill="#FF7A1A" opacity="0.18" />
    </svg>
  );
}
