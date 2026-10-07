/* The 3D digital twin: a Three.js mannequin posed by worksheet angles.

   const twin = new Twin(containerEl, labelsEl);
   twin.setPose(angles, 'left'); twin.setHeat({trunk: 0.7, ...}); twin.setRisk(3);
   twin.onPick = seg => ...; twin.dispose();
*/
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

const rad = THREE.MathUtils.degToRad;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const num = v => (v === null || v === undefined || isNaN(v)) ? 0 : Number(v);

const DIM = { hip: 0.96, trunk: 0.50, shoulderW: 0.19, hipW: 0.10, neck: 0.09, head: 0.115,
              upper: 0.30, fore: 0.26, hand: 0.10, thigh: 0.45, shank: 0.43, foot: 0.22 };
const NEUTRAL = new THREE.Color(0x3f4b66);
const BAND_HEX = [0x4ade80, 0x9be15d, 0xffc53d, 0xff6b6b, 0xc03cff];

function heatColour(t) {
  const g = new THREE.Color(0x4ade80), a = new THREE.Color(0xffc53d), r = new THREE.Color(0xff6b6b);
  return t < 0.5 ? g.clone().lerp(a, t * 2) : a.clone().lerp(r, (t - 0.5) * 2);
}
function segmentMaterial(ghost) {
  if (ghost) return new THREE.MeshBasicMaterial({ color: 0x4f8cff, wireframe: true, transparent: true, opacity: 0.10, depthWrite: false });
  return new THREE.MeshStandardMaterial({ color: NEUTRAL, roughness: 0.42, metalness: 0.25, emissive: NEUTRAL, emissiveIntensity: 0.18 });
}

class Mannequin {
  constructor(scene, ghost = false) {
    this.ghost = ghost; this.scene = scene;
    this.root = new THREE.Group(); this.root.position.y = DIM.hip;
    this.nodes = {}; this.meshes = {}; this.targets = {}; this.labels = {};
    this.build();
  }
  capsule(len, r, seg, parent, dir = -1, cap = 8) {
    const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, Math.max(0.01, len - 2 * r), cap, 20), segmentMaterial(this.ghost));
    m.position.y = dir * len / 2; m.castShadow = m.receiveShadow = !this.ghost; m.userData.segment = seg;
    parent.add(m); (this.meshes[seg] = this.meshes[seg] || []).push(m); return m;
  }
  pivot(name, parent, x, y, z) {
    const o = new THREE.Object3D(); o.position.set(x, y, z); parent.add(o);
    this.nodes[name] = o; this.targets[name] = new THREE.Quaternion(); return o;
  }
  build() {
    const D = DIM;
    const pelvis = new THREE.Mesh(new THREE.CapsuleGeometry(0.085, 0.16, 6, 16), segmentMaterial(this.ghost));
    pelvis.rotation.x = Math.PI / 2; pelvis.position.y = 0.02; pelvis.castShadow = !this.ghost; pelvis.userData.segment = 'trunk';
    this.root.add(pelvis); this.meshes.trunk = [pelvis];
    const chest = this.pivot('chest', this.root, 0, 0.04, 0);
    this.capsule(D.trunk, 0.13, 'trunk', chest, +1);
    const bar = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, D.shoulderW * 2 - 0.12, 4, 14), segmentMaterial(this.ghost));
    bar.rotation.x = Math.PI / 2; bar.position.y = D.trunk - 0.02; bar.userData.segment = 'trunk'; bar.castShadow = !this.ghost;
    chest.add(bar); this.meshes.trunk.push(bar);
    const neck = this.pivot('neck', chest, 0, D.trunk + 0.02, 0);
    this.capsule(D.neck + 0.04, 0.045, 'neck', neck, +1, 4);
    const head = new THREE.Mesh(new THREE.SphereGeometry(D.head, 28, 22), segmentMaterial(this.ghost));
    head.position.y = D.neck + D.head + 0.01; head.castShadow = !this.ghost; head.userData.segment = 'neck';
    neck.add(head); this.meshes.neck.push(head);
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.022, 0.05, 10), segmentMaterial(this.ghost));
    nose.rotation.z = -Math.PI / 2; nose.position.set(D.head + 0.01, D.neck + D.head, 0); nose.userData.segment = 'neck';
    neck.add(nose); this.meshes.neck.push(nose);
    for (const [side, z] of [['left', +1], ['right', -1]]) {
      const sh = this.pivot('shoulder_' + side, chest, 0, D.trunk - 0.02, z * D.shoulderW);
      this.capsule(D.upper, 0.055, 'upper_arm_' + side, sh);
      const el = this.pivot('elbow_' + side, sh, 0, -D.upper, 0);
      this.capsule(D.fore, 0.047, 'lower_arm_' + side, el);
      const wr = this.pivot('wrist_' + side, el, 0, -D.fore, 0);
      const hand = new THREE.Mesh(new THREE.BoxGeometry(0.035, D.hand, 0.07), segmentMaterial(this.ghost));
      hand.position.y = -D.hand / 2; hand.castShadow = !this.ghost; hand.userData.segment = 'hand_' + side;
      wr.add(hand); this.meshes['hand_' + side] = [hand];
      const hip = this.pivot('hip_' + side, this.root, 0, 0, z * D.hipW);
      this.capsule(D.thigh, 0.075, 'legs', hip);
      const knee = this.pivot('knee_' + side, hip, 0, -D.thigh, 0);
      this.capsule(D.shank, 0.058, 'legs', knee);
      const ankle = this.pivot('ankle_' + side, knee, 0, -D.shank, 0);
      const foot = new THREE.Mesh(new THREE.BoxGeometry(D.foot, 0.05, 0.085), segmentMaterial(this.ghost));
      foot.position.set(D.foot / 2 - 0.05, -0.05, 0); foot.castShadow = !this.ghost; foot.userData.segment = 'legs';
      ankle.add(foot); this.meshes.legs.push(foot);
    }
    this.scene.add(this.root);
  }
  label(name, node, offsetY = 0, left = false) {
    if (this.ghost) return;
    const el = document.createElement('div'); el.className = 'jl' + (left ? ' left' : '');
    const obj = new CSS2DObject(el); obj.position.set(0, offsetY, 0); node.add(obj); this.labels[name] = el;
  }
  setPose(a, side) {
    const T = this.targets, e = new THREE.Euler();
    const q = (x, y, z) => new THREE.Quaternion().setFromEuler(e.set(rad(x), rad(y), rad(z), 'YXZ'));
    const trunk = num(a.trunk_flexion);
    T.chest.copy(q(-num(a.trunk_side_bend), num(a.trunk_twist), -trunk));
    T.neck.copy(q(-num(a.neck_side_bend), num(a.neck_twist), -num(a.neck_flexion)));
    for (const [s, z] of [['left', +1], ['right', -1]]) {
      const arm = a[s] || {};
      T['shoulder_' + s].copy(q(-z * num(arm.upper_arm_abduction), 0, num(arm.upper_arm_flexion)));
      T['elbow_' + s].copy(q(0, 0, num(arm.elbow_flexion)));
      T['wrist_' + s].copy(q(-z * num(arm.wrist_deviation), 0, num(arm.wrist_flexion)));
      const thigh = clamp(num(a[s + '_hip_flexion']) - trunk, -40, 120);
      const knee = num(a[s + '_knee_flexion']);
      T['hip_' + s].copy(q(0, 0, thigh)); T['knee_' + s].copy(q(0, 0, -knee));
      T['ankle_' + s].copy(q(0, 0, clamp(knee - thigh, -50, 60)));
    }
    if (this.ghost) return;
    const gov = side || 'left', other = gov === 'left' ? 'right' : 'left';
    const L = this.labels, arm = a[gov] || {};
    const set = (k, text, dim) => { if (L[k]) { L[k].innerHTML = '<span class="dot"></span>' + text; L[k].classList.toggle('dim', !!dim); } };
    set('trunk', '<b>Trunk</b> ' + num(a.trunk_flexion).toFixed(0) + '°');
    set('neck', '<b>Neck</b> ' + num(a.neck_flexion).toFixed(0) + '°');
    set('shoulder', '<b>Upper arm</b> ' + num(arm.upper_arm_flexion).toFixed(0) + '°');
    set('elbow', '<b>Elbow</b> ' + num(arm.elbow_flexion).toFixed(0) + '°');
    set('wrist', '<b>Wrist</b> ' + num(arm.wrist_flexion).toFixed(0) + '°');
    set('knee', '<b>Knee</b> ' + num(a[gov + '_knee_flexion']).toFixed(0) + '°');
    set('other', '<b>' + other + ' arm</b> ' + num((a[other] || {}).upper_arm_flexion).toFixed(0) + '°', true);
  }
  attachLabels(side) {
    for (const el of Object.values(this.labels)) el.remove();
    for (const n of Object.values(this.nodes)) n.children.filter(c => c.isCSS2DObject).forEach(c => n.remove(c));
    this.labels = {};
    const other = side === 'left' ? 'right' : 'left';
    this.label('trunk', this.nodes.chest, DIM.trunk * 0.55, true);
    this.label('neck', this.nodes.neck, DIM.neck + DIM.head + 0.02);
    this.label('shoulder', this.nodes['shoulder_' + side], -0.06);
    this.label('elbow', this.nodes['elbow_' + side], 0);
    this.label('wrist', this.nodes['wrist_' + side], -0.02);
    this.label('knee', this.nodes['knee_' + side], 0, true);
    this.label('other', this.nodes['elbow_' + other], 0, true);
  }
  setHeat(heat) {
    if (this.ghost) return;
    for (const [seg, meshes] of Object.entries(this.meshes)) {
      const t = heat[seg];
      const c = (t === undefined || t === null) ? NEUTRAL : heatColour(clamp(t, 0, 1));
      for (const m of meshes) { m.material.color.copy(c); m.material.emissive.copy(c); m.material.emissiveIntensity = (t === undefined || t === null) ? 0.18 : 0.22 + 0.5 * clamp(t, 0, 1); }
    }
  }
  update(k) { for (const [name, node] of Object.entries(this.nodes)) node.quaternion.slerp(this.targets[name], k); }
}

export class Twin {
  constructor(container, labelsEl) {
    this.container = container; this.onPick = null; this.disposed = false;
    const w = container.clientWidth || 800, h = container.clientHeight || 600;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.1;
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(this.renderer.domElement);
    this.labelRenderer = new CSS2DRenderer({ element: labelsEl }); this.labelRenderer.setSize(w, h);

    const scene = this.scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x070910, 6, 14);
    this.camera = new THREE.PerspectiveCamera(36, w / h, 0.1, 60);
    this.camera.position.set(1.1, 1.55, 3.9);
    const controls = this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    controls.target.set(0, 0.98, 0); controls.enableDamping = true; controls.dampingFactor = 0.06; controls.enablePan = false;
    controls.minDistance = 1.8; controls.maxDistance = 7; controls.maxPolarAngle = Math.PI * 0.55;
    controls.autoRotate = true; controls.autoRotateSpeed = 0.55;
    let idle = null;
    controls.addEventListener('start', () => { controls.autoRotate = false; clearTimeout(idle); });
    controls.addEventListener('end', () => { idle = setTimeout(() => { controls.autoRotate = true; }, 9000); });

    scene.add(new THREE.HemisphereLight(0x8fb4ff, 0x0a0c14, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(2.5, 4.5, 3); key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048); key.shadow.camera.left = -3; key.shadow.camera.right = 3; key.shadow.camera.top = 4; key.shadow.camera.bottom = -1; key.shadow.radius = 4;
    scene.add(key);
    const rim = new THREE.PointLight(0x4f8cff, 6, 9, 1.6); rim.position.set(-2.4, 1.8, -1.6); scene.add(rim);
    this.riskLight = new THREE.PointLight(0x4ade80, 0, 7, 1.8); this.riskLight.position.set(1.6, 0.4, 1.8); scene.add(this.riskLight);

    const floor = new THREE.Mesh(new THREE.CircleGeometry(4.5, 96), new THREE.MeshStandardMaterial({ color: 0x0b0e17, roughness: 0.95, metalness: 0.05 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
    const grid = new THREE.GridHelper(12, 48, 0x1c2438, 0x131827); grid.material.transparent = true; grid.material.opacity = 0.55; grid.position.y = 0.002; scene.add(grid);
    this.ring = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.66, 96), new THREE.MeshBasicMaterial({ color: 0x4f8cff, transparent: true, opacity: 0.35, side: THREE.DoubleSide }));
    this.ring.rotation.x = -Math.PI / 2; this.ring.position.y = 0.004; scene.add(this.ring);
    const P = 500, pos = new Float32Array(P * 3);
    for (let i = 0; i < P; i++) { pos[i * 3] = (Math.random() - 0.5) * 9; pos[i * 3 + 1] = Math.random() * 3.2; pos[i * 3 + 2] = (Math.random() - 0.5) * 9; }
    this.particles = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(pos, 3)),
      new THREE.PointsMaterial({ color: 0x6f9cff, size: 0.018, transparent: true, opacity: 0.55, depthWrite: false }));
    scene.add(this.particles);

    this.twin = new Mannequin(scene, false);
    this.ghost = new Mannequin(scene, true);
    this.ghost.setPose({ left: {}, right: {} }, 'left');
    this.twin.attachLabels('left'); this.twin.setPose({ left: {}, right: {} }, 'left');
    for (const el of Object.values(this.twin.labels)) el.style.opacity = 0;

    this.ray = new THREE.Raycaster(); this.pointer = new THREE.Vector2(); this.downAt = null;
    const dom = this.renderer.domElement;
    dom.addEventListener('pointermove', ev => { dom.style.cursor = this.pick(ev) ? 'pointer' : 'grab'; });
    dom.addEventListener('pointerdown', ev => { this.downAt = [ev.clientX, ev.clientY]; });
    dom.addEventListener('pointerup', ev => {
      if (!this.downAt || Math.hypot(ev.clientX - this.downAt[0], ev.clientY - this.downAt[1]) > 6) return;
      const seg = this.pick(ev); if (seg && this.onPick) this.onPick(seg);
    });
    // defer to the next frame so a resize never re-triggers the observer in the same pass
    this.ro = new ResizeObserver(() => requestAnimationFrame(() => this.resize())); this.ro.observe(container);
    this.clock = new THREE.Clock();
    this.frame = this.frame.bind(this); this.frame();
  }
  pick(ev) {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(this.pointer, this.camera);
    const hits = this.ray.intersectObject(this.twin.root, true).filter(h => h.object.userData.segment);
    return hits.length ? hits[0].object.userData.segment : null;
  }
  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight; if (!w || !h) return;
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h); this.labelRenderer.setSize(w, h);
    const dist = w < 520 ? 5.2 : w < 760 ? 4.5 : 3.9;
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.camera.position.copy(this.controls.target).addScaledVector(dir, dist);
  }
  frame() {
    if (this.disposed) return;
    const dt = Math.min(this.clock.getDelta(), 0.05), k = 1 - Math.pow(0.001, dt * 1.6), t = this.clock.elapsedTime;
    this.twin.update(k); this.ghost.update(k);
    this.particles.rotation.y = t * 0.012; this.particles.position.y = Math.sin(t * 0.25) * 0.05;
    this.ring.material.opacity = 0.28 + 0.12 * Math.sin(t * 1.8);
    this.controls.update(); this.renderer.render(this.scene, this.camera); this.labelRenderer.render(this.scene, this.camera);
    requestAnimationFrame(this.frame);
  }
  setPose(angles, side) {
    this.twin.attachLabels(side || 'left'); this.twin.setPose(angles, side || 'left');
    for (const el of Object.values(this.twin.labels)) el.style.opacity = '';
  }
  setHeat(heat, labelHeat) {
    this.twin.setHeat(heat || {});
    if (labelHeat) for (const [k, t] of Object.entries(labelHeat)) {
      const el = this.twin.labels[k]; if (!el) continue;
      const dot = el.querySelector('.dot'); if (dot) dot.style.background = t > 0.65 ? '#ff6b6b' : t > 0.3 ? '#ffc53d' : '#4ade80';
    }
  }
  setRisk(level) {
    const hex = BAND_HEX[Math.max(0, Math.min(4, level))];
    this.riskLight.color.setHex(hex); this.riskLight.intensity = 1.5 + level * 1.2; this.ring.material.color.setHex(hex);
  }
  dispose() {
    this.disposed = true; this.ro.disconnect(); this.controls.dispose();
    this.renderer.dispose(); this.renderer.domElement.remove();
    for (const el of Object.values(this.twin.labels)) el.remove();
  }
}
