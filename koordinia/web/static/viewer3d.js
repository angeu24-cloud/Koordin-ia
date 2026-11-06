// Vue 3D du bâtiment (three.js) : planchers, poteaux, poutres, transferts, semelles.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

let current = null;

export function render3d(host, m, focus) {
  if (current) { current.dispose(); current = null; }
  host.innerHTML = "";
  const css = getComputedStyle(document.documentElement);
  const c = (v) => new THREE.Color(css.getPropertyValue(v).trim() || "#888");
  const w = host.clientWidth, h = host.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h);
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = c("--panel");
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.2); sun.position.set(30, 60, 40); scene.add(sun);

  const matCol = new THREE.MeshStandardMaterial({ color: c("--column") });
  const matBeam = new THREE.MeshStandardMaterial({ color: c("--beam") });
  const matTr = new THREE.MeshStandardMaterial({ color: c("--transfer") });
  const matKo = new THREE.MeshStandardMaterial({ color: c("--ko") });
  const matSlab = new THREE.MeshStandardMaterial({ color: c("--slab"), transparent: true, opacity: 0.28, depthWrite: false });
  const matFoot = new THREE.MeshStandardMaterial({ color: c("--accent"), transparent: true, opacity: 0.7 });
  const box = (sx, sy, sz, mat, x, y, z) => { const g = new THREE.BoxGeometry(sx, sz, sy); const o = new THREE.Mesh(g, mat); o.position.set(x, z, -y); scene.add(o); return o; };

  const bounds = new THREE.Box3();
  m.niveaux.forEach((lv, k) => {
    const z0 = lv.altitude, z1 = lv.altitude + lv.hauteur;
    const dim = focus >= 0 && k > focus;
    lv.colonnes.forEach((col) => {
      const o = box(col.b, col.h, lv.hauteur, col.ok ? matCol : matKo, col.x, col.y, (z0 + z1) / 2);
      if (dim) { o.material = o.material.clone(); o.material.transparent = true; o.material.opacity = 0.15; }
      bounds.expandByObject(o);
    });
    lv.poutres.forEach((b) => {
      const L = Math.hypot(b.x2 - b.x1, b.y2 - b.y1); if (L < 0.05) return;
      const mat = b.transfert ? matTr : (b.ok ? matBeam : matKo);
      const g = new THREE.BoxGeometry(L, b.h, b.b);
      const o = new THREE.Mesh(g, mat);
      o.position.set((b.x1 + b.x2) / 2, z1 - b.h / 2, -(b.y1 + b.y2) / 2);
      o.rotation.y = Math.atan2(b.y2 - b.y1, b.x2 - b.x1);
      if (dim) { o.material = mat.clone(); o.material.transparent = true; o.material.opacity = 0.15; }
      scene.add(o);
    });
    (lv.dalle || []).forEach(([a, bb, cc, d]) => {
      const o = box(cc - a, d - bb, 0.2, matSlab, (a + cc) / 2, (bb + d) / 2, z1 - 0.1);
      if (dim) o.visible = false;
    });
  });
  m.semelles.forEach((f) => box(f.A, f.B, f.h, matFoot, f.x, f.y, -f.h / 2));

  const size = bounds.getSize(new THREE.Vector3()), center = bounds.getCenter(new THREE.Vector3());
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 2000);
  const r = Math.max(size.x, size.y, size.z) || 20;
  camera.position.set(center.x + r * 0.9, center.y + r * 0.8, center.z + r * 1.1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(center); controls.enableDamping = true; controls.update();
  const grid = new THREE.GridHelper(r * 3, Math.round(r * 3 / 5), c("--line"), c("--line"));
  grid.position.set(center.x, -0.01, center.z); scene.add(grid);

  let alive = true;
  const loop = () => { if (!alive) return; controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); };
  loop();
  const onResize = () => { const W = host.clientWidth, H = host.clientHeight; camera.aspect = W / H; camera.updateProjectionMatrix(); renderer.setSize(W, H); };
  window.addEventListener("resize", onResize);
  current = { dispose() { alive = false; window.removeEventListener("resize", onResize); renderer.dispose(); } };
}
