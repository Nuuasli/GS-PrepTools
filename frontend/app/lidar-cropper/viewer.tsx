"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { CloudPreview, DisplayMode, Region, SourceInfo, XYZ } from "@/services/lidar";

interface ViewProps {
  cloud: CloudPreview;
  info: SourceInfo;
  display: DisplayMode;
  pointSize: number;
  picking: boolean;
  onPick: (center: XYZ) => void;
  region: Region | null;
  mask: Uint8Array | undefined;
  hideOutline: boolean;
  cameraCommand: { id: number; action: "reset" | "fit" };
}

type World = ReturnType<typeof setupWorld>;
const defaultDirection = new THREE.Vector3(1, -1, 0.72).normalize();

function setupWorld(container: HTMLDivElement) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor("#202020");
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute("aria-label", "Interactive 3D point cloud");
  container.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(48, 1, 0.001, 1000);
  camera.up.set(0, 0, 1);
  camera.position.copy(defaultDirection);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.zoomToCursor = true;
  controls.listenToKeyEvents(renderer.domElement);
  const pointMaterial = new THREE.PointsMaterial({ vertexColors: true, sizeAttenuation: false, size: 2 });
  const points = new THREE.Points(new THREE.BufferGeometry(), pointMaterial);
  const outline = new THREE.LineSegments(new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: "#dc7459", transparent: true, opacity: 0.62 }));
  const marker = new THREE.AxesHelper(1);
  scene.add(points, outline, marker);
  const draw = () => renderer.render(scene, camera);
  controls.addEventListener("change", draw);

  let orbitPivot: THREE.Vector3 | null = null;
  const focusOrbitPivot = () => {
    if (!orbitPivot || controls.target.equals(orbitPivot)) return;
    controls.target.copy(orbitPivot);
    controls.update();
    draw();
  };
  const setOrbitPivot = (pivot: THREE.Vector3 | null) => {
    orbitPivot = pivot;
    focusOrbitPivot();
  };
  // Pan and cursor zoom can move OrbitControls.target. Restore the chosen point
  // when the user starts rotating again.
  const onPointerDown = (event: PointerEvent) => {
    const modified = event.ctrlKey || event.metaKey || event.shiftKey;
    const rotates = event.pointerType === "touch" ? event.isPrimary : event.button === (modified ? 2 : 0);
    if (rotates && controls.enabled && controls.enableRotate) focusOrbitPivot();
  };
  const onKeyDown = (event: KeyboardEvent) => {
    const modified = event.ctrlKey || event.metaKey || event.shiftKey;
    if (modified && event.code.startsWith("Arrow") && controls.enabled && controls.enableRotate) focusOrbitPivot();
  };
  renderer.domElement.addEventListener("pointerdown", onPointerDown, true);
  renderer.domElement.addEventListener("keydown", onKeyDown, true);

  const resize = new ResizeObserver(() => {
    renderer.setSize(container.clientWidth, container.clientHeight);
    camera.aspect = container.clientWidth / Math.max(1, container.clientHeight);
    camera.updateProjectionMatrix();
    draw();
  });
  resize.observe(container);

  return { renderer, points, outline, marker, camera, controls, draw, setOrbitPivot, dispose: () => {
    resize.disconnect();
    renderer.domElement.removeEventListener("pointerdown", onPointerDown, true);
    renderer.domElement.removeEventListener("keydown", onKeyDown, true);
    controls.dispose();
    points.geometry.dispose();
    pointMaterial.dispose();
    outline.geometry.dispose();
    outline.material.dispose();
    marker.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  } };
}

function fit(world: World, info: SourceInfo, reset: boolean) {
  const { camera, controls } = world;
  const size = Math.max(1e-8, Math.hypot(...info.max_xyz.map((n, i) => n - info.min_xyz[i])));
  const direction = reset ? defaultDirection : camera.position.clone().sub(controls.target).normalize();
  const distance = (0.6 * size) / (Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * Math.min(1, camera.aspect));
  world.setOrbitPivot(null);
  controls.target.set(0, 0, 0);
  camera.position.copy(direction).multiplyScalar(distance);
  controls.minDistance = size / 50_000;
  controls.maxDistance = size * 1_000;
  camera.near = controls.minDistance / 40;
  camera.far = Math.max(controls.maxDistance * 2, distance * 4);
  camera.updateProjectionMatrix();
  controls.update();
  world.draw();
}

function colorPoints(cloud: CloudPreview, info: SourceInfo, display: DisplayMode, mask?: Uint8Array) {
  const colors = new Float32Array(cloud.count * 3);
  const color = new THREE.Color();
  const dark = new THREE.Color("#76695f");
  const light = new THREE.Color("#f6e5c9");
  const chosen = new THREE.Color("#f38c6c");
  const clear = new THREE.Color("#292827");
  const zSpan = info.max_xyz[2] - info.min_xyz[2];
  for (let i = 0; i < cloud.count; i++) {
    const start = i * 4;
    if (display === "rgb")
      color.setRGB(cloud.display[start] / 255, cloud.display[start + 1] / 255, cloud.display[start + 2] / 255, THREE.SRGBColorSpace);
    else {
      const value = display === "intensity" ? cloud.display[start + 3] / 255 :
        (zSpan ? (cloud.xyz[i * 3 + 2] - info.min_xyz[2]) / zSpan : 0.65);
      color.copy(dark).lerp(light, value);
    }
    if (mask) color.lerp(mask[i] ? chosen : clear, mask[i] ? 0.55 : 0.91);
    color.toArray(colors, i * 3);
  }
  return colors;
}

export default function PointCloudViewer({ cloud, info, display, pointSize, picking, onPick, region, mask, hideOutline, cameraCommand }: ViewProps) {
  const host = useRef<HTMLDivElement>(null);
  const world = useRef<World | null>(null);
  const origin = useRef(new THREE.Vector3());
  const currentInfo = useRef<SourceInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!host.current) return;
    try {
      world.current = setupWorld(host.current);
    } catch {
      // Context creation can fail on devices without WebGL2.
      queueMicrotask(() => setError("WebGL2 is unavailable. You can enter center coordinates and export without the viewer."));
    }
    return () => {
      world.current?.dispose();
      world.current = null;
      currentInfo.current = null;
    };
  }, []);

  useEffect(() => {
    const view = world.current;
    if (!view) return;
    origin.current.set(...info.min_xyz.map((n, i) => n + (info.max_xyz[i] - n) / 2) as XYZ);
    const positions = new Float32Array(cloud.count * 3);
    for (let i = 0; i < cloud.count; i++) {
      positions[i * 3] = cloud.xyz[i * 3] - origin.current.x;
      positions[i * 3 + 1] = cloud.xyz[i * 3 + 1] - origin.current.y;
      positions[i * 3 + 2] = cloud.xyz[i * 3 + 2] - origin.current.z;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    view.points.geometry.dispose();
    view.points.geometry = geometry;
    if (currentInfo.current !== info) {
      currentInfo.current = info;
      const canvas = view.renderer.domElement.parentElement;
      if (canvas?.clientHeight) view.camera.aspect = canvas.clientWidth / canvas.clientHeight;
      fit(view, info, true);
    }
  }, [cloud, info]);

  useEffect(() => {
    const view = world.current;
    if (!view) return;
    view.points.geometry.setAttribute("color", new THREE.BufferAttribute(colorPoints(cloud, info, display, mask), 3));
    view.points.material.size = pointSize;
    view.draw();
  }, [cloud, info, display, mask, pointSize]);

  useEffect(() => {
    if (world.current && cameraCommand.id) fit(world.current, info, cameraCommand.action === "reset");
  }, [cameraCommand, info]);

  useEffect(() => {
    const view = world.current;
    if (!view) return;
    const visible = region && [...region.center, region.radius, region.height ?? 0]
      .every((value) => Math.abs(value) <= 1e30);
    view.marker.visible = Boolean(visible);
    view.outline.visible = Boolean(visible) && !hideOutline;
    if (region && visible) {
      const wire = region.shape === "sphere" ? new THREE.SphereGeometry(region.radius, 20, 12) :
        new THREE.CylinderGeometry(region.radius, region.radius, region.height ?? 1, 24);
      if (region.shape === "cylinder") {
        if (region.axis === "z") wire.rotateX(Math.PI / 2);
        else if (region.axis === "x") wire.rotateZ(Math.PI / 2);
      }
      view.outline.geometry.dispose();
      view.outline.geometry = new THREE.EdgesGeometry(wire);
      wire.dispose();
      view.outline.position.set(...region.center).sub(origin.current);
      view.marker.position.copy(view.outline.position);
      view.marker.scale.setScalar(region.radius * 0.14);
    }
    view.draw();
  }, [region, cloud, hideOutline]);

  useEffect(() => {
    const view = world.current;
    if (!view || !picking) return;
    const canvas = view.renderer.domElement;
    view.controls.enabled = false;
    const ray = new THREE.Raycaster();
    const pick = (event: PointerEvent) => {
      if (event.button !== 0) return;
      const rect = canvas.getBoundingClientRect();
      ray.params.Points = {
        threshold: view.camera.position.distanceTo(view.controls.target) *
          Math.tan(THREE.MathUtils.degToRad(view.camera.fov / 2)) * Math.max(10, pointSize * 2) / rect.height,
      };
      ray.setFromCamera(new THREE.Vector2(
        2 * (event.clientX - rect.left) / rect.width - 1,
        1 - 2 * (event.clientY - rect.top) / rect.height,
      ), view.camera);
      const point = ray.intersectObject(view.points)[0];
      if (point?.index !== undefined) {
        const start = point.index * 3;
        const center: XYZ = [cloud.xyz[start], cloud.xyz[start + 1], cloud.xyz[start + 2]];
        view.setOrbitPivot(new THREE.Vector3(...center).sub(origin.current));
        onPick(center);
      }
    };
    canvas.addEventListener("pointerup", pick);
    return () => { canvas.removeEventListener("pointerup", pick); view.controls.enabled = true; };
  }, [picking, onPick, cloud, pointSize]);

  return (
    <div className="absolute inset-0">
      <div ref={host} className={`h-full w-full [&_canvas]:block ${picking ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing"}`} />
      {error && <p className="absolute inset-0 grid place-content-center px-8 text-center text-sm text-white/75">{error}</p>}
    </div>
  );
}
