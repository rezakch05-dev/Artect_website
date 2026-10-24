import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { unzipSync, strFromU8 } from 'https://cdn.jsdelivr.net/npm/fflate@0.8.2/esm/browser.js';

const $ = id => document.getElementById(id);
const viewport = $('viewport');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0c1016);
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10000);
camera.position.set(4, 3, 5);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1;
viewport.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x667080, 2));
const keyLight = new THREE.DirectionalLight(0xffffff, 2);
keyLight.position.set(5, 8, 6); scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0x9bc6ff, 0.65);
fillLight.position.set(-5, 2, -4); scene.add(fillLight);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.07;
const loader = new GLTFLoader();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const markerGroup = new THREE.Group(); scene.add(markerGroup);
const targetDot = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffd166 }));
targetDot.visible = false; scene.add(targetDot);

let modelRoot = null, modelName = '', modelBounds = null, modelHash = '', modelByteLength = 0;
let annotations = [], activeIndex = -1, selectedPoint = null;
let selectionMode = false, editingId = null, transitionToken = 0;
let activePivotMode = 'annotation', walkthroughEnabled = false, walkthroughOverride = null, transitioning = false;
const heldKeys = new Set();
let dragAction = null, lastPointerX = 0, lastPointerY = 0, lookYaw = 0, lookPitch = 0;

function status(message, type = '') { $('status').textContent = message; $('status').className = 'status ' + type; }
function hint(message) { $('viewerHint').textContent = message; }
function setEnabled(ids, enabled) { ids.forEach(id => { $(id).disabled = !enabled; }); }
function setMode(select) {
  selectionMode = select;
  controls.enabled = !select && !walkthroughEnabled;
  $('selectModeBtn').classList.toggle('primary', select);
  $('freeModeBtn').classList.toggle('primary', !select);
  renderer.domElement.style.cursor = select ? 'crosshair' : (activePivotMode === 'camera' ? 'move' : 'grab');
  hint(select ? 'روی سطح مدل کلیک کن تا محل Annotation مشخص شود.' : 'ناوبری آزاد فعال است. Walk-through با کلیدهای جهت‌نما حرکت می‌کند؛ Shift حرکت را سریع‌تر می‌کند.');
}
function setWalkthrough(enabled, manualChange = false) {
  if (manualChange) walkthroughOverride = Boolean(enabled);
  walkthroughEnabled = Boolean(enabled);
  heldKeys.clear(); dragAction = null;
  // Walk-through owns mouse/keyboard input while active; OrbitControls must not compete.
  controls.enabled = !walkthroughEnabled && !selectionMode;
  if (walkthroughEnabled) {
    syncLookAnglesFromCamera();
    controls.target.copy(viewTargetWorld());
  }
  $('walkModeBtn').textContent = `Walk-through: ${walkthroughEnabled ? 'روشن' : 'خاموش'}`;
  $('walkModeBtn').classList.toggle('walk-on', walkthroughEnabled);
  $('walkAutoBtn').classList.toggle('walk-on', walkthroughOverride === null);
  renderer.domElement.style.cursor = selectionMode ? 'crosshair' : (walkthroughEnabled ? 'grab' : (activePivotMode === 'camera' ? 'crosshair' : 'grab'));
  if (walkthroughEnabled) hint('Walk-through روشن است: ↑ و ↓ در راستای دید دوربین، ← و → حرکت جانبی؛ کلیک چپ و کشیدن ماوس برای تغییر جهت نگاه، کلیک راست برای جابه‌جایی نما و چرخ موس برای زوم. با Shift سریع‌تر حرکت کن.');
  else hint(selectionMode ? 'روی سطح مدل کلیک کن تا محل Annotation مشخص شود.' : 'Walk-through خاموش است؛ در حالت ناوبری آزاد از کنترل‌های عادی مدل استفاده کن.');
}
function syncWalkthroughToActiveAnnotation() {
  // null means automatic mode; an explicit user toggle becomes a persistent override.
  if (walkthroughOverride !== null) setWalkthrough(walkthroughOverride, false);
  else setWalkthrough(activePivotMode === 'camera', false);
}
function syncLookAnglesFromCamera() {
  camera.rotation.order = 'YXZ';
  const euler = new THREE.Euler(0, 0, 0, 'YXZ').setFromQuaternion(camera.quaternion, 'YXZ');
  lookYaw = euler.y; lookPitch = euler.x;
}
function modelCenter() {
  if (!modelBounds) return new THREE.Vector3();
  return modelBounds.getCenter(new THREE.Vector3());
}
function pivotTargetWorld(mode, annotationPosition = selectedPoint) {
  if (mode === 'annotation' && annotationPosition && modelRoot) return modelToWorld(annotationPosition);
  if (mode === 'model') return modelCenter();
  return viewTargetWorld();
}
function viewTargetWorld() {
  const direction = new THREE.Vector3(); camera.getWorldDirection(direction);
  const diagonal = modelBounds ? modelBounds.getSize(new THREE.Vector3()).length() : 1;
  return camera.position.clone().addScaledVector(direction, Math.max(diagonal * 0.25, 0.5));
}
function updateFirstPersonTarget() {
  controls.target.copy(viewTargetWorld());
}
function applyPivotMode(mode, annotationPosition = selectedPoint) {
  activePivotMode = ['annotation', 'camera', 'model'].includes(mode) ? mode : 'annotation';
  $('pivotMode').value = activePivotMode;
  if (activePivotMode === 'camera') {
    controls.enabled = !walkthroughEnabled && !selectionMode;
    syncLookAnglesFromCamera();
    const target = viewTargetWorld();
    controls.target.copy(target);
    if (controls.enabled) controls.update();
  } else {
    controls.enabled = !walkthroughEnabled && !selectionMode;
    const target = pivotTargetWorld(activePivotMode, annotationPosition);
    // Preserve the current free-navigation target while Walk-through is active.
    if (!walkthroughEnabled) controls.target.copy(target);
    if (controls.enabled) controls.update();
  }
  renderer.domElement.style.cursor = selectionMode ? 'crosshair' : (walkthroughEnabled ? 'grab' : (activePivotMode === 'camera' ? 'crosshair' : 'grab'));
  syncWalkthroughToActiveAnnotation();
  // If automatic Walk-through just turned off, restore the selected pivot for OrbitControls.
  if (!walkthroughEnabled && !selectionMode) {
    controls.enabled = true;
    controls.target.copy(activePivotMode === 'camera' ? viewTargetWorld() : pivotTargetWorld(activePivotMode, annotationPosition));
    controls.update();
  }
}
function isTypingTarget(target) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

function resize() {
  const w = Math.max(viewport.clientWidth, 1), h = Math.max(viewport.clientHeight, 1);
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize); resize();

function modelToWorld(position) { modelRoot.updateWorldMatrix(true, false); return modelRoot.localToWorld(new THREE.Vector3(...position)); }
function worldToModel(position) { modelRoot.updateWorldMatrix(true, false); return modelRoot.worldToLocal(position.clone()); }
function toArray(v) { return [Number(v.x.toFixed(6)), Number(v.y.toFixed(6)), Number(v.z.toFixed(6))]; }
function captureCameraPose(pivotMode = activePivotMode, annotationPosition = selectedPoint) {
  const targetWorld = pivotMode === 'camera' ? viewTargetWorld() : pivotTargetWorld(pivotMode, annotationPosition);
  return { position: toArray(worldToModel(camera.position)), target: toArray(worldToModel(targetWorld)) };
}

function disposeObject(root) {
  root.traverse(obj => {
    if (obj.geometry) obj.geometry.dispose();
    if (obj.material) {
      const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
      materials.forEach(mat => {
        for (const value of Object.values(mat)) {
          if (value && value.isTexture) value.dispose();
        }
        mat.dispose();
      });
    }
  });
}
function clearMarkers() {
  while (markerGroup.children.length) {
    const child = markerGroup.children[0]; markerGroup.remove(child);
    if (child.geometry) child.geometry.dispose();
    if (child.material) child.material.dispose();
  }
}
function fitModel() {
  if (!modelRoot) return;
  modelRoot.updateMatrixWorld(true);
  modelBounds = new THREE.Box3().setFromObject(modelRoot);
  if (modelBounds.isEmpty()) { status('مدل بارگذاری شد اما هندسهٔ قابل‌نمایشی پیدا نشد.', 'error'); return; }
  const center = modelBounds.getCenter(new THREE.Vector3());
  const size = modelBounds.getSize(new THREE.Vector3());
  const dim = Math.max(size.x, size.y, size.z) || 1;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(dim * 1.4, dim * 0.9, dim * 1.6));
  camera.near = Math.max(dim / 1000, 0.001); camera.far = dim * 100;
  camera.updateProjectionMatrix(); controls.update();
}
function refreshMarkers() {
  clearMarkers();
  if (!modelRoot) return;
  const diagonal = modelBounds ? modelBounds.getSize(new THREE.Vector3()).length() : 1;
  annotations.forEach((ann, index) => {
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(1, 18, 12),
      new THREE.MeshStandardMaterial({ color: index === activeIndex ? 0xffd166 : 0x65d4c4, emissive: index === activeIndex ? 0x5a3b00 : 0x124d46 })
    );
    marker.position.copy(modelToWorld(ann.position));
    marker.scale.setScalar(Math.max(diagonal * 0.012, 0.025));
    marker.userData.annotationId = ann.id;
    markerGroup.add(marker);
  });
  if (selectedPoint) {
    const marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffd166 }));
    marker.position.copy(modelToWorld(selectedPoint)); marker.scale.setScalar(Math.max(diagonal * 0.014, 0.03)); markerGroup.add(marker);
  }
}
function renderList() {
  const root = $('annotationList'); root.replaceChildren();
  if (!annotations.length) { const p = document.createElement('p'); p.textContent = 'هنوز Annotation ثبت نشده است.'; root.appendChild(p); }
  annotations.forEach((ann, index) => {
    const row = document.createElement('div'); row.className = 'ann' + (index === activeIndex ? ' active' : '');
    const num = document.createElement('div'); num.className = 'num'; num.textContent = String(index + 1);
    const text = document.createElement('div'); text.className = 'anntext';
    const title = document.createElement('strong'); title.textContent = ann.title || `Annotation ${index + 1}`;
    const desc = document.createElement('small');
    const pivotLabels = { annotation: 'نقطهٔ انتخابی', camera: 'خود دوربین', model: 'مرکز مدل' };
    desc.textContent = `${ann.description || 'بدون توضیحات'} · مرکز چرخش: ${pivotLabels[ann.pivotMode || 'annotation']}`; text.append(title, desc);
    const go = document.createElement('button'); go.textContent = 'نما'; go.title = 'رفتن به این نما'; go.onclick = () => goToAnnotation(index);
    const edit = document.createElement('button'); edit.textContent = 'ویرایش'; edit.onclick = () => editAnnotation(index);
    const del = document.createElement('button'); del.textContent = '×'; del.className = 'danger'; del.title = 'حذف'; del.onclick = () => deleteAnnotation(index);
    row.append(num, text, go, edit, del); root.appendChild(row);
  });
  $('deleteAllBtn').disabled = annotations.length === 0;
  $('exportJsonBtn').disabled = annotations.length === 0;
  $('exportBtn').disabled = !modelRoot || annotations.length === 0;
  $('prevBtn').disabled = annotations.length === 0; $('nextBtn').disabled = annotations.length === 0;
  refreshMarkers();
}
function buildData() {
  return {
    schema: 'artect.annotation-tour', schemaVersion: 1,
    model: { fileName: modelName, fileSize: modelByteLength, sha256: modelHash, coordinateSpace: 'model-local', coordinateConvention: 'Three.js coordinates relative to the loaded GLB scene root; keep the same GLB root transform on playback.' },
    tour: { loop: false, transition: 'smooth', annotations: annotations.map((ann, index) => ({
      id: ann.id, order: index + 1, title: ann.title, description: ann.description,
      position: ann.position, pivotMode: ann.pivotMode || 'annotation', camera: { position: ann.camera.position, target: ann.camera.target }
    })) }
  };
}
function validVector(v) { return Array.isArray(v) && v.length === 3 && v.every(n => Number.isFinite(n)); }
function importAnnotationData(data) {
  if (!modelRoot) throw new Error('ابتدا فایل GLB را بارگذاری کن و سپس ZIP Annotation را وارد کن.');
  if (data?.schema !== 'artect.annotation-tour' || !Array.isArray(data?.tour?.annotations)) throw new Error('ساختار JSON با فرمت artect.annotation-tour سازگار نیست.');
  const parsed = data.tour.annotations.map((a, i) => {
    if (!validVector(a.position) || !validVector(a.camera?.position) || !validVector(a.camera?.target)) throw new Error(`مختصات Annotation شمارهٔ ${i + 1} نامعتبر است.`);
    return { id: a.id || crypto.randomUUID(), title: String(a.title || `Annotation ${i + 1}`), description: String(a.description || ''), position: a.position, pivotMode: ['annotation', 'camera', 'model'].includes(a.pivotMode) ? a.pivotMode : 'annotation', camera: { position: a.camera.position, target: a.camera.target } };
  });
  annotations = parsed; activeIndex = -1; selectedPoint = null; editingId = null; targetDot.visible = false; renderList();
  status(`${annotations.length} Annotation از JSON وارد شد.`, 'ok');
}
async function loadModel(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.glb')) { status('این نسخه فقط فایل GLB را می‌پذیرد؛ یک فایل با پسوند .glb انتخاب کن.', 'error'); return; }
  status('در حال خواندن فایل GLB…'); hint('در حال خواندن فایل سه‌بعدی…');
  try {
    const buffer = await file.arrayBuffer();
    const newHash = await sha256Hex(buffer);
    loader.parse(buffer, '', gltf => {
      if (modelRoot) { scene.remove(modelRoot); disposeObject(modelRoot); }
      clearMarkers(); modelRoot = gltf.scene; scene.add(modelRoot); modelName = file.name; modelHash = newHash; modelByteLength = file.size;
      annotations = []; activeIndex = -1; selectedPoint = null; editingId = null; modelBounds = null; targetDot.visible = false;
      activePivotMode = 'annotation'; walkthroughOverride = null;
      $('annTitle').value = ''; $('annDesc').value = ''; $('pointStatus').textContent = 'هنوز نقطه‌ای انتخاب نشده'; $('saveAnnBtn').disabled = true; $('cancelEditBtn').disabled = true;
      fitModel(); setEnabled(['selectModeBtn','freeModeBtn','fitBtn','resetBtn','walkModeBtn','walkAutoBtn','loadZipBtn'], true); $('pivotMode').value = 'annotation'; setWalkthrough(false, false); controls.enabled = true; setMode(false);
      $('modelBadge').textContent = file.name; renderList();
      status('مدل GLB با موفقیت بارگذاری شد.', 'ok'); hint('نما را تنظیم کن، «انتخاب نقطه» را بزن و روی سطح مدل کلیک کن.');
    }, error => {
      console.error(error); status('فایل انتخاب شد اما ساختار GLB معتبر نیست: ' + (error?.message || 'خطای تجزیهٔ فایل'), 'error'); hint('یک فایل GLB معتبر انتخاب کن.');
    });
  } catch (error) {
    console.error(error); status('خواندن فایل ناموفق بود: ' + (error?.message || error), 'error'); hint('فایل به‌درستی خوانده نشد.');
  }
}
renderer.domElement.addEventListener('click', event => {
  if (!modelRoot || !selectionMode) return;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObject(modelRoot, true).filter(hit => hit.object.isMesh);
  if (!hits.length) { status('سطحی انتخاب نشد؛ روی خود مدل کلیک کن.', 'error'); return; }
  selectedPoint = toArray(worldToModel(hits[0].point)); targetDot.position.copy(hits[0].point); targetDot.visible = true;
  if (activePivotMode !== 'camera') applyPivotMode(activePivotMode, selectedPoint);
  $('pointStatus').textContent = selectedPoint.map(n => n.toFixed(3)).join(', '); $('saveAnnBtn').disabled = false;
  refreshMarkers(); status('نقطه انتخاب شد؛ عنوان را وارد و ذخیره کن.', 'ok');
});
function clearForm() {
  editingId = null; selectedPoint = null; targetDot.visible = false;
  $('annTitle').value = ''; $('annDesc').value = ''; $('pointStatus').textContent = 'هنوز نقطه‌ای انتخاب نشده';
  $('saveAnnBtn').disabled = true; $('cancelEditBtn').disabled = true;
  const restoreMode = activeIndex >= 0 && annotations[activeIndex] ? (annotations[activeIndex].pivotMode || 'annotation') : 'annotation';
  applyPivotMode(restoreMode, activeIndex >= 0 && annotations[activeIndex] ? annotations[activeIndex].position : null);
  refreshMarkers();
}
function saveAnnotation() {
  if (!selectedPoint) { status('ابتدا روی سطح مدل یک نقطه انتخاب کن.', 'error'); return; }
  const title = $('annTitle').value.trim() || `Annotation ${annotations.length + 1}`;
  const description = $('annDesc').value.trim();
  const pivotMode = $('pivotMode').value;
  applyPivotMode(pivotMode, selectedPoint);
  const cameraPose = captureCameraPose(pivotMode, selectedPoint);
  if (editingId) {
    const ann = annotations.find(item => item.id === editingId);
    if (!ann) { status('Annotation موردنظر برای ویرایش پیدا نشد.', 'error'); return; }
    Object.assign(ann, { title, description, position: [...selectedPoint], pivotMode, camera: cameraPose });
    activeIndex = annotations.findIndex(item => item.id === editingId);
  } else {
    annotations.push({ id: crypto.randomUUID(), title, description, position: [...selectedPoint], pivotMode, camera: cameraPose });
    activeIndex = annotations.length - 1;
  }
  clearForm(); renderList(); status('Annotation ذخیره شد.', 'ok');
}
function editAnnotation(index) {
  const ann = annotations[index]; editingId = ann.id; selectedPoint = [...ann.position];
  $('annTitle').value = ann.title; $('annDesc').value = ann.description; $('pivotMode').value = ann.pivotMode || 'annotation';
  $('pointStatus').textContent = ann.position.map(n => Number(n).toFixed(3)).join(', ');
  $('saveAnnBtn').disabled = false; $('cancelEditBtn').disabled = false; activeIndex = index;
  goToAnnotation(index, false); setMode(true); status('ویرایش فعال است؛ برای تغییر نقطه روی مدل کلیک کن یا اطلاعات را اصلاح کن.');
}
function deleteAnnotation(index) {
  annotations.splice(index, 1); if (activeIndex >= annotations.length) activeIndex = annotations.length - 1;
  renderList(); status('Annotation حذف شد.', 'ok');
}
function goToAnnotation(index, animate = true) {
  if (!annotations.length || index < 0 || index >= annotations.length) return;
  if (selectionMode) setMode(false);
  activeIndex = index; const ann = annotations[index];
  const pivotMode = ['annotation', 'camera', 'model'].includes(ann.pivotMode) ? ann.pivotMode : 'annotation';
  $('pivotMode').value = pivotMode; activePivotMode = pivotMode; syncWalkthroughToActiveAnnotation();
  const endPosition = modelToWorld(ann.camera.position);
  const endTarget = pivotMode === 'annotation' ? modelToWorld(ann.position) : pivotMode === 'model' ? modelCenter() : modelToWorld(ann.camera.target);
  transitionToken++; const token = transitionToken;
  const finish = () => {
    if (token !== transitionToken) return;
    transitioning = false; camera.position.copy(endPosition); camera.lookAt(endTarget);
    if (pivotMode === 'camera') {
      controls.enabled = !walkthroughEnabled && !selectionMode; syncLookAnglesFromCamera();
      controls.target.copy(walkthroughEnabled ? viewTargetWorld() : endTarget);
      if (walkthroughEnabled) updateFirstPersonTarget(); else if (controls.enabled) controls.update();
    } else {
      controls.enabled = !walkthroughEnabled && !selectionMode; controls.target.copy(endTarget); if (controls.enabled) controls.update();
    }
    renderer.domElement.style.cursor = selectionMode ? 'crosshair' : (walkthroughEnabled ? 'grab' : (pivotMode === 'camera' ? 'grab' : 'grab'));
  };
  if (!animate) { finish(); }
  else {
    const startPosition = camera.position.clone(), startTarget = controls.target.clone(), started = performance.now();
    transitioning = true; controls.enabled = false;
    function step(now) {
      if (token !== transitionToken) return;
      const t = Math.min(1, (now - started) / 700), eased = t * t * (3 - 2 * t);
      camera.position.lerpVectors(startPosition, endPosition, eased);
      const intermediateTarget = startTarget.clone().lerp(endTarget, eased);
      camera.lookAt(intermediateTarget);
      if (t < 1) requestAnimationFrame(step); else finish();
    }
    requestAnimationFrame(step);
  }
  targetDot.position.copy(modelToWorld(ann.position));
  targetDot.scale.setScalar(Math.max(modelBounds.getSize(new THREE.Vector3()).length() * 0.014, 0.03)); targetDot.visible = true;
  renderList(); status(`نمای ${index + 1} از ${annotations.length}: ${ann.title}`, 'ok');
}
function download(blob, filename) {
  const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = filename;
  document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500);
}
function safeName(name) { return (name || 'model').replace(/\.(glb|gltf)$/i, '').replace(/[^\w\-]+/g, '_') || 'model'; }
function exportJson() { download(new Blob([JSON.stringify(buildData(), null, 2)], { type: 'application/json;charset=utf-8' }), safeName(modelName) + '_annotations.json'); }
// Create a standards-compliant uncompressed ZIP without an additional JSZip CDN dependency.
function crc32(bytes) { let crc = 0xffffffff; for (const byte of bytes) { crc ^= byte; for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0); } return (crc ^ 0xffffffff) >>> 0; }
function makeZip(files) {
  const enc = new TextEncoder(), localParts = [], centralParts = []; let offset = 0;
  for (const file of files) {
    const name = enc.encode(file.name), body = enc.encode(file.content), crc = crc32(body);
    const local = new Uint8Array(30 + name.length + body.length), lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true); lv.setUint16(4, 20, true); lv.setUint16(6, 0x0800, true); lv.setUint16(8, 0, true); lv.setUint16(10, 0, true); lv.setUint16(12, 0x21, true); lv.setUint32(14, crc, true); lv.setUint32(18, body.length, true); lv.setUint32(22, body.length, true); lv.setUint16(26, name.length, true); lv.setUint16(28, 0, true); local.set(name, 30); local.set(body, 30 + name.length); localParts.push(local);
    const central = new Uint8Array(46 + name.length), cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true); cv.setUint16(8, 0x0800, true); cv.setUint16(10, 0, true); cv.setUint16(12, 0, true); cv.setUint16(14, 0x21, true); cv.setUint32(16, crc, true); cv.setUint32(20, body.length, true); cv.setUint32(24, body.length, true); cv.setUint16(28, name.length, true); cv.setUint16(30, 0, true); cv.setUint16(32, 0, true); cv.setUint16(34, 0, true); cv.setUint16(36, 0, true); cv.setUint32(38, 0, true); cv.setUint32(42, offset, true); central.set(name, 46); centralParts.push(central); offset += local.length;
  }
  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0), end = new Uint8Array(22), ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true); ev.setUint16(4, 0, true); ev.setUint16(6, 0, true); ev.setUint16(8, files.length, true); ev.setUint16(10, files.length, true); ev.setUint32(12, centralSize, true); ev.setUint32(16, offset, true); ev.setUint16(20, 0, true);
  return new Blob([...localParts, ...centralParts, end], { type: 'application/zip' });
}
function sha256Hex(buffer) {
  if (!globalThis.crypto?.subtle) throw new Error('برای اعتبارسنجی SHA-256، برنامه را با run_windows.bat یا یک سرور محلی باز کن.');
  return crypto.subtle.digest('SHA-256', buffer).then(hash => Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join(''));
}
function exportZip() {
  if (!modelRoot || !annotations.length) { status('ابتدا مدل و حداقل یک Annotation لازم است.', 'error'); return; }
  const data = buildData();
  const manifest = {
    schema: 'artect.annotation-tour-package', schemaVersion: 1,
    annotationFile: 'annotations.json',
    model: { fileName: modelName, fileSize: modelByteLength, sha256: modelHash }
  };
  const readme = `Artect Annotation Tour package v1\n\nContains annotations.json and manifest.json. Import this ZIP only with the exact GLB file used to create it. Compatibility is verified via SHA-256 of the original GLB bytes. A re-exported or modified GLB may have a different fingerprint.\n`;
  const blob = makeZip([
    { name: 'annotations.json', content: JSON.stringify(data, null, 2) },
    { name: 'manifest.json', content: JSON.stringify(manifest, null, 2) },
    { name: 'README.txt', content: readme }
  ]);
  download(blob, safeName(modelName) + '_annotation_tour.zip'); status('فایل ZIP همراه با اثرانگشت مدل آماده شد.', 'ok');
}
async function importZip(file) {
  if (!modelRoot || !modelHash) throw new Error('ابتدا فایل GLB را بارگذاری کن.');
  if (!file || !file.name.toLowerCase().endsWith('.zip')) throw new Error('برای ورود Annotation فقط فایل ZIP پذیرفته می‌شود.');
  status('در حال بررسی ZIP و تطبیق آن با مدل…');
  const archive = unzipSync(new Uint8Array(await file.arrayBuffer()));
  const names = Object.keys(archive);
  const annotationPath = names.find(name => name.toLowerCase().split('/').pop() === 'annotations.json');
  if (!annotationPath) throw new Error('داخل ZIP فایل annotations.json پیدا نشد.');
  const manifestPath = names.find(name => name.toLowerCase().split('/').pop() === 'manifest.json');
  const data = JSON.parse(strFromU8(archive[annotationPath]));
  const manifest = manifestPath ? JSON.parse(strFromU8(archive[manifestPath])) : null;
  if (data?.schema !== 'artect.annotation-tour' || data?.schemaVersion !== 1 || !Array.isArray(data?.tour?.annotations)) throw new Error('ساختار annotations.json با فرمت Artect سازگار نیست.');
  if (!manifest || manifest.schema !== 'artect.annotation-tour-package' || manifest.schemaVersion !== 1 || manifest.annotationFile !== 'annotations.json') throw new Error('ZIP باید manifest.json معتبر نسخهٔ ۱ را در کنار annotations.json داشته باشد.');
  const dataHash = String(data?.model?.sha256 || '').toLowerCase();
  const manifestHash = String(manifest?.model?.sha256 || '').toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(dataHash) || !/^[0-9a-f]{64}$/.test(manifestHash)) throw new Error('اثر انگشت SHA-256 در ZIP وجود ندارد یا معتبر نیست؛ ZIP را از نسخهٔ جدید Studio خروجی بگیر.');
  if (dataHash !== manifestHash) throw new Error('اطلاعات مدل در annotations.json و manifest.json با هم مطابقت ندارند.');
  const expectedHash = dataHash;
  if (expectedHash !== modelHash.toLowerCase()) {
    const bundleName = manifest?.model?.fileName || data?.model?.fileName || 'نامشخص';
    throw new Error(`این ZIP متعلق به مدل دیگری است و وارد نشد. مدل داخل ZIP: ${bundleName}؛ مدل فعلی: ${modelName}. باید دقیقاً همان فایل GLB اولیه را انتخاب کنی.`);
  }
  if (Number(data?.model?.fileSize) !== modelByteLength || Number(manifest?.model?.fileSize) !== modelByteLength) throw new Error('اندازهٔ فایل GLB با اطلاعات ZIP مطابقت ندارد.');
  importAnnotationData(data);
  status(`ZIP معتبر است؛ ${annotations.length} Annotation برای همین مدل وارد شد.`, 'ok');
}
$('fileInput').addEventListener('change', event => { loadModel(event.target.files?.[0]); event.target.value = ''; });
$('loadZipBtn').onclick = () => $('zipInput').click();
$('zipInput').addEventListener('change', async event => {
  const file = event.target.files?.[0]; if (!file) return;
  try { await importZip(file); }
  catch (error) { console.error(error); status(error.message || 'خواندن ZIP ناموفق بود.', 'error'); }
  event.target.value = '';
});
$('selectModeBtn').onclick = () => setMode(true); $('freeModeBtn').onclick = () => setMode(false);
$('fitBtn').onclick = fitModel;
$('resetBtn').onclick = () => activeIndex >= 0 ? goToAnnotation(activeIndex, false) : fitModel();
$('saveAnnBtn').onclick = saveAnnotation; $('cancelEditBtn').onclick = () => { clearForm(); status('ویرایش لغو شد.'); };
$('deleteAllBtn').onclick = () => { if (confirm('همهٔ Annotationها حذف شوند؟')) { annotations = []; activeIndex = -1; clearForm(); renderList(); status('همهٔ Annotationها حذف شدند.', 'ok'); } };
$('exportJsonBtn').onclick = exportJson; $('exportBtn').onclick = exportZip;
$('prevBtn').onclick = () => goToAnnotation(activeIndex <= 0 ? annotations.length - 1 : activeIndex - 1);
$('nextBtn').onclick = () => goToAnnotation(activeIndex < 0 ? 0 : (activeIndex + 1) % annotations.length);
$('walkModeBtn').onclick = () => setWalkthrough(!walkthroughEnabled, true);
$('walkAutoBtn').onclick = () => { walkthroughOverride = null; syncWalkthroughToActiveAnnotation(); status('حالت خودکار فعال شد؛ Walk-through بر اساس Annotation فعال تنظیم می‌شود.', 'ok'); };
$('pivotMode').addEventListener('change', event => {
  activePivotMode = event.target.value;
  applyPivotMode(activePivotMode, selectedPoint || (activeIndex >= 0 ? annotations[activeIndex].position : null));
});

// Walk-through input is deliberately independent from Annotation records.
// Left drag: look around in place. Right drag: pan the view (the model appears to move).
// Mouse wheel: dolly along the current view direction. Arrow keys: move relative to camera.
renderer.domElement.style.touchAction = 'none';
renderer.domElement.addEventListener('contextmenu', event => {
  if (walkthroughEnabled) event.preventDefault();
});
renderer.domElement.addEventListener('pointerdown', event => {
  if (!modelRoot || selectionMode) return;
  const wantsLook = event.button === 0 && walkthroughEnabled;
  const wantsPan = event.button === 2 && walkthroughEnabled;
  if (!wantsLook && !wantsPan) return;
  dragAction = wantsLook ? 'look' : 'pan';
  lastPointerX = event.clientX; lastPointerY = event.clientY;
  if (dragAction === 'look') syncLookAnglesFromCamera();
  try { renderer.domElement.setPointerCapture(event.pointerId); } catch (_) {}
  event.preventDefault();
});
window.addEventListener('pointermove', event => {
  if (!dragAction || !modelRoot) return;
  const dx = event.clientX - lastPointerX, dy = event.clientY - lastPointerY;
  lastPointerX = event.clientX; lastPointerY = event.clientY;
  if (dragAction === 'look') {
    lookYaw -= dx * 0.0035;
    lookPitch = THREE.MathUtils.clamp(lookPitch - dy * 0.0035, -Math.PI / 2 + 0.02, Math.PI / 2 - 0.02);
    camera.rotation.order = 'YXZ'; camera.rotation.set(lookPitch, lookYaw, 0);
    // Keep the same current view direction as the OrbitControls target if Walk-through is later switched off.
    controls.target.copy(viewTargetWorld());
  } else if (dragAction === 'pan' && walkthroughEnabled) {
    const viewDistance = Math.max(camera.position.distanceTo(controls.target), modelBounds ? modelBounds.getSize(new THREE.Vector3()).length() * 0.2 : 1);
    const worldPerPixel = (2 * viewDistance * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / Math.max(viewport.clientHeight, 1);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).normalize();
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion).normalize();
    const pan = right.multiplyScalar(-dx * worldPerPixel).add(up.multiplyScalar(dy * worldPerPixel));
    camera.position.add(pan); controls.target.add(pan);
  }
});
function stopDragging(event) {
  if (dragAction && event?.pointerId !== undefined) {
    try { if (renderer.domElement.hasPointerCapture(event.pointerId)) renderer.domElement.releasePointerCapture(event.pointerId); } catch (_) {}
  }
  dragAction = null;
}
window.addEventListener('pointerup', stopDragging);
window.addEventListener('pointercancel', stopDragging);
window.addEventListener('blur', () => { heldKeys.clear(); dragAction = null; });
renderer.domElement.addEventListener('wheel', event => {
  if (!walkthroughEnabled || !modelRoot || selectionMode) return;
  event.preventDefault();
  const forward = camera.getWorldDirection(new THREE.Vector3()).normalize();
  const diagonal = modelBounds ? modelBounds.getSize(new THREE.Vector3()).length() : 1;
  const amount = Math.max(diagonal * 0.07, 0.02) * THREE.MathUtils.clamp(Math.abs(event.deltaY) / 100, 0.2, 3);
  const movement = forward.multiplyScalar((event.deltaY > 0 ? -1 : 1) * amount);
  camera.position.add(movement); controls.target.add(movement);
}, { passive: false });
window.addEventListener('keydown', event => {
  if (!modelRoot || !walkthroughEnabled || selectionMode || isTypingTarget(event.target)) return;
  if (event.code === 'ShiftLeft' || event.code === 'ShiftRight') { heldKeys.add(event.code); return; }
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.code)) {
    event.preventDefault(); heldKeys.add(event.code);
  }
});
window.addEventListener('keyup', event => heldKeys.delete(event.code));
function moveWalkthrough(deltaSeconds) {
  if (!walkthroughEnabled || !modelRoot || transitioning || heldKeys.size === 0) return;
  // Forward/back follow the camera's full look direction (including pitch).
  const forward = camera.getWorldDirection(new THREE.Vector3()).normalize();
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).normalize();
  const direction = new THREE.Vector3();
  if (heldKeys.has('ArrowUp')) direction.add(forward);
  if (heldKeys.has('ArrowDown')) direction.sub(forward);
  if (heldKeys.has('ArrowRight')) direction.add(right);
  if (heldKeys.has('ArrowLeft')) direction.sub(right);
  if (direction.lengthSq() === 0) return;
  direction.normalize();
  const diagonal = modelBounds ? modelBounds.getSize(new THREE.Vector3()).length() : 1;
  const speed = Math.max(diagonal * 0.12, 0.02) * (heldKeys.has('ShiftLeft') || heldKeys.has('ShiftRight') ? 3 : 1);
  const movement = direction.multiplyScalar(speed * deltaSeconds);
  camera.position.add(movement); controls.target.add(movement);
}
let frameTime = performance.now();
function animate(now) {
  requestAnimationFrame(animate);
  const dt = Math.min((now - frameTime) / 1000 || 0, 0.05); frameTime = now;
  moveWalkthrough(dt);
  if (controls.enabled) controls.update();
  renderer.render(scene, camera);
}
requestAnimationFrame(animate);
  const dt = Math.min((now - frameTime) / 1000 || 0, 0.05); frameTime = now;
  moveWalkthrough(dt);
  if (controls.enabled) controls.update();
  renderer.render(scene, camera);
}
requestAnimationFrame(animate);
