"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

export default function ThreeBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Scene setup
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x090a0f, 0.0015);

    // Camera setup
    const camera = new THREE.PerspectiveCamera(
      60,
      window.innerWidth / window.innerHeight,
      1,
      1000
    );
    camera.position.set(0, 50, 150);
    camera.lookAt(0, 0, 0);

    // Renderer
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);

    // ── Create 3D Wave Particle Grid ──────────────────────────────────────────
    const countX = 70;
    const countY = 40;
    const sep = 8;
    const numParticles = countX * countY;

    const positions = new Float32Array(numParticles * 3);
    const scales = new Float32Array(numParticles);
    const colors = new Float32Array(numParticles * 3);

    const cyanColor = new THREE.Color(0x00f5d4);
    const blueColor = new THREE.Color(0x3b82f6);

    let i = 0;
    let c = 0;
    for (let ix = 0; ix < countX; ix++) {
      for (let iy = 0; iy < countY; iy++) {
        const x = (ix - countX / 2) * sep;
        const z = (iy - countY / 2) * sep;
        positions[i] = x;
        positions[i + 1] = 0;
        positions[i + 2] = z;

        scales[c] = 1;

        // Color gradient cyan -> electric blue
        const mix = ix / countX;
        const color = cyanColor.clone().lerp(blueColor, mix);
        colors[i] = color.r;
        colors[i + 1] = color.g;
        colors[i + 2] = color.b;

        i += 3;
        c++;
      }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("scale", new THREE.BufferAttribute(scales, 1));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    // Particle Material
    const pMaterial = new THREE.PointsMaterial({
      size: 2.2,
      vertexColors: true,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
    });

    const particles = new THREE.Points(geometry, pMaterial);
    scene.add(particles);

    // ── Floating Acoustic Node Orbs ──────────────────────────────────────────
    const orbGroup = new THREE.Group();
    const orbGeometry = new THREE.IcosahedronGeometry(4, 1);

    for (let o = 0; o < 12; o++) {
      const orbMaterial = new THREE.MeshBasicMaterial({
        color: o % 2 === 0 ? 0x00f5d4 : 0x7c3aed,
        wireframe: true,
        transparent: true,
        opacity: 0.25,
      });
      const orb = new THREE.Mesh(orbGeometry, orbMaterial);
      orb.position.set(
        (Math.random() - 0.5) * 400,
        Math.random() * 80 + 10,
        (Math.random() - 0.5) * 300
      );
      orb.userData = {
        rotSpeedX: (Math.random() - 0.5) * 0.01,
        rotSpeedY: (Math.random() - 0.5) * 0.01,
        floatSpeed: Math.random() * 0.02 + 0.005,
        offset: Math.random() * Math.PI * 2,
      };
      orbGroup.add(orb);
    }
    scene.add(orbGroup);

    // ── Animation Loop ────────────────────────────────────────────────────────
    let animationFrameId: number;
    let count = 0;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);

      count += 0.03;

      // Animate wave grid positions
      const posAttr = geometry.attributes.position as THREE.BufferAttribute;
      const posArray = posAttr.array as Float32Array;

      let idx = 0;
      for (let ix = 0; ix < countX; ix++) {
        for (let iy = 0; iy < countY; iy++) {
          posArray[idx + 1] =
            Math.sin((ix + count) * 0.3) * 6 + Math.sin((iy + count) * 0.5) * 6;
          idx += 3;
        }
      }
      posAttr.needsUpdate = true;

      // Animate floating orbs
      orbGroup.children.forEach((mesh) => {
        const orb = mesh as THREE.Mesh;
        orb.rotation.x += orb.userData.rotSpeedX;
        orb.rotation.y += orb.userData.rotSpeedY;
        orb.position.y += Math.sin(count * orb.userData.floatSpeed + orb.userData.offset) * 0.15;
      });

      // Subtle camera sway
      camera.position.x = Math.sin(count * 0.1) * 15;
      camera.lookAt(0, 0, 0);

      renderer.render(scene, camera);
    };

    animate();

    // ── Resize Listener ───────────────────────────────────────────────────────
    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };

    window.addEventListener("resize", handleResize);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("resize", handleResize);
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      geometry.dispose();
      pMaterial.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: "100vw",
        height: "100vh",
        zIndex: -1,
        pointerEvents: "none",
        opacity: 0.85,
      }}
    />
  );
}
