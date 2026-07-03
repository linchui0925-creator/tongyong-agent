import React, { useRef, useEffect } from 'react';
import { useFrame, Canvas } from '@react-three/fiber';
import * as THREE from 'three';

const Warrior: React.FC<{ side: 'left' | 'right'; progress: number }> = ({ side, progress }) => {
  const groupRef = useRef<THREE.Group>(null);
  const swordRef = useRef<THREE.Mesh>(null);
  const dir = side === 'left' ? 1 : -1;

  useFrame((_) => {
    if (!groupRef.current || !swordRef.current) return;
    
    // 入场到对峙
    if (progress < 0.3) {
      const p = progress / 0.3;
      groupRef.current.position.x = dir * (5 - p * 3);
      groupRef.current.rotation.y = dir * Math.PI / 4 * (1 - p);
    } 
    // 攻击动作
    else if (progress < 0.45) {
      const p = (progress - 0.3) / 0.15;
      groupRef.current.position.x = dir * (2 - p * 1.2);
      swordRef.current.rotation.x = -Math.PI / 2 * Math.sin(p * Math.PI);
    }
    // 收招退场
    else if (progress < 0.6) {
      const p = (progress - 0.45) / 0.15;
      groupRef.current.position.x = dir * (0.8 + p * 6);
      groupRef.current.visible = p < 0.95;
    } else {
      groupRef.current.visible = false;
    }
  });

  return (
    <group ref={groupRef}>
      {/* 身体 */}
      <mesh position={[0, 1, 0]}>
        <capsuleGeometry args={[0.3, 1.2, 4, 8]} />
        <meshBasicMaterial color="#000" />
      </mesh>
      {/* 头 */}
      <mesh position={[0, 2.2, 0]}>
        <sphereGeometry args={[0.35, 16, 16]} />
        <meshBasicMaterial color="#000" />
      </mesh>
      {/* 手臂 */}
      <mesh position={[dir * 0.5, 1.2, 0]} rotation={[0, 0, dir * -Math.PI / 3]}>
        <capsuleGeometry args={[0.15, 0.8, 4, 8]} />
        <meshBasicMaterial color="#000" />
      </mesh>
      {/* 剑 */}
      <mesh ref={swordRef} position={[dir * 1.2, 1.2, 0]} rotation={[0, 0, dir * -Math.PI / 3]}>
        <cylinderGeometry args={[0.03, 0.03, 2.5, 8]} />
        <meshBasicMaterial color="#e5e5e5" />
      </mesh>
      {/* 斗篷 */}
      <mesh position={[dir * -0.1, 0.5, -0.2]} rotation={[0, 0, dir * 0.3]}>
        <coneGeometry args={[0.8, 2, 8]} />
        <meshBasicMaterial color="#000" />
      </mesh>
    </group>
  );
};

const SwordSplash: React.FC<{ progress: number }> = ({ progress }) => {
  const particlesRef = useRef<THREE.Points | null>(null);
  const count = 200;
  const positions = useRef(new Float32Array(count * 3)).current;
  const velocities = useRef(new Float32Array(count * 3)).current;

  useEffect(() => {
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2;
      const r = Math.random() * 0.5;
      positions[i * 3] = Math.cos(theta) * r;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 1;
      positions[i * 3 + 2] = Math.sin(theta) * r;
      velocities[i * 3] = (Math.random() - 0.5) * 10;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 5;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 10;
    }
  }, []);

  useFrame((_, delta) => {
    if (!particlesRef.current || progress < 0.4 || progress > 0.55) return;
    const p = (progress - 0.4) / 0.15;
    const geometry = particlesRef.current.geometry as THREE.BufferGeometry;
    const pos = geometry.attributes.position.array as Float32Array;
    
    for (let i = 0; i < count; i++) {
      pos[i * 3] += velocities[i * 3] * delta * p;
      pos[i * 3 + 1] += velocities[i * 3 + 1] * delta * p - 1 * delta;
      pos[i * 3 + 2] += velocities[i * 3 + 2] * delta * p;
    }
    geometry.attributes.position.needsUpdate = true;
    const mat = particlesRef.current.material as THREE.PointsMaterial;
    mat.opacity = 1 - (p - 0.2) * 2;
  });

  if (progress < 0.4 || progress > 0.55) return null;

  return (
    <points ref={particlesRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={count}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial size={0.05} color="#000" transparent opacity={0.8} />
    </points>
  );
};

const FlashEffect: React.FC<{ progress: number }> = ({ progress }) => {
  const meshRef = useRef<THREE.Mesh>(null);
  useFrame(() => {
    if (!meshRef.current) return;
    const mat = meshRef.current.material as THREE.MeshBasicMaterial;
    if (progress >= 0.4 && progress <= 0.42) {
      const p = (progress - 0.4) / 0.02;
      mat.opacity = p < 0.5 ? p * 2 : 2 - p * 2;
    } else {
      mat.opacity = 0;
    }
  });
  return (
    <mesh ref={meshRef} position={[0, 1, 0]}>
      <planeGeometry args={[10, 10]} />
      <meshBasicMaterial color="#fff" transparent opacity={0} />
    </mesh>
  );
};

export const WarriorFight3D: React.FC<{ progress: number }> = ({ progress }) => {
  return (
    <div className="fixed inset-0 z-10 pointer-events-none">
      <Canvas camera={{ position: [0, 2, 8], fov: 50 }} gl={{ alpha: true, antialias: true }}>
        <ambientLight intensity={1} />
        <Warrior side="left" progress={progress} />
        <Warrior side="right" progress={progress} />
        <SwordSplash progress={progress} />
        <FlashEffect progress={progress} />
      </Canvas>
    </div>
  );
};
