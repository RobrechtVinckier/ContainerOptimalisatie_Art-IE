import "./style.css";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  COLOR_PALETTE,
  YARD_CONFIG,
  cloneStacks,
  summarizeStacks,
} from "./yardModel.js";
import {
  getAlgorithmSettings,
  requestRandomConfiguration,
  requestSolvePlan,
  updateAlgorithmSettings,
} from "./backendClient.js";

const SCALE = 0.72;
const CONTAINER_DIM = Object.freeze({
  x: YARD_CONFIG.containerMeters.width * SCALE,
  y: YARD_CONFIG.containerMeters.height * SCALE,
  z: YARD_CONFIG.containerMeters.length * SCALE,
});
const CONTAINER_VISUAL_HEIGHT = CONTAINER_DIM.y * 0.96;
const STACK_BASE_OFFSET_Y = 0.008;

const STACK_GAP = Object.freeze({
  x: 0.22,
  y: 0.02,
  z: 0.3,
});

const STEP = Object.freeze({
  x: CONTAINER_DIM.x + STACK_GAP.x,
  y: CONTAINER_VISUAL_HEIGHT + STACK_GAP.y,
  z: CONTAINER_DIM.z + STACK_GAP.z,
});

const YARD_WIDTH_WORLD = YARD_CONFIG.width * STEP.x;
const LANE_WIDTH_WORLD = YARD_CONFIG.truckLaneWidth * STEP.x;
const TOTAL_WIDTH_WORLD = YARD_WIDTH_WORLD + LANE_WIDTH_WORLD;
const YARD_LENGTH_WORLD = YARD_CONFIG.length * STEP.z;

const CONTAINER_MIN_X = -TOTAL_WIDTH_WORLD / 2;
const LANE_MIN_X = CONTAINER_MIN_X + YARD_WIDTH_WORLD;
const YARD_MIN_Z = -YARD_LENGTH_WORLD / 2;

const app = document.querySelector("#app");
app.innerHTML = `
  <div class="layout-shell">
    <header class="topbar reveal-a">
      <div>
        <h1>Container Yard Optimizer</h1>
        <p>5 x 10 x 4 yard, one truck lane, low-poly crane simulation, weighted crane cost (length = 10x width).</p>
      </div>
    </header>

    <section class="toolbar reveal-b">
      <button id="generate-btn" class="btn primary">Generate Random 130</button>
      <button id="solve-btn" class="btn">Solve With Backend Plan</button>
      <button id="pause-btn" class="btn" disabled>Pause</button>
      <label class="speed-box" for="speed-slider">
        <span>Playback Speed</span>
        <input id="speed-slider" type="range" min="0.25" max="100" step="0.05" value="1" />
        <output id="speed-value">1.00x</output>
      </label>
      <label class="pass-box" for="passthrough-toggle">
        <input id="passthrough-toggle" type="checkbox" />
        <span>Passthrough</span>
      </label>
      <button id="algo-apply-btn" class="btn">Apply Algo Settings</button>
      <div class="status-text" id="status-text">Ready.</div>
    </section>

    <main class="content-grid">
      <section class="scene-panel reveal-c">
        <div id="scene-host"></div>
        <div class="scene-legend">
          <span><i class="swatch red"></i>Red</span>
          <span><i class="swatch green"></i>Green</span>
          <span><i class="swatch blue"></i>Blue</span>
          <span class="lane-note">Right lane reserved for passing trucks</span>
        </div>
      </section>

      <aside class="side-panel reveal-d">
        <div class="stats-grid">
          <div class="stat-card">
            <label>Total Containers</label>
            <strong id="stat-total">0</strong>
          </div>
          <div class="stat-card">
            <label>Placement Score</label>
            <strong id="stat-score">0%</strong>
          </div>
          <div class="stat-card">
            <label>Move Progress</label>
            <strong id="stat-progress">-</strong>
          </div>
          <div class="stat-card">
            <label>Weighted Cost</label>
            <strong id="stat-cost">0</strong>
          </div>
        </div>

        <section class="algo-settings">
          <h3>Algorithm Settings</h3>
          <div class="algo-grid">
            <label><span>Lambda</span><input id="algo-lam" type="number" min="0" step="0.1" value="1" /></label>
            <label><span>Tabu Iterations</span><input id="algo-tabu-iters" type="number" min="1" step="1" value="1500" /></label>
            <label><span>Tabu Length</span><input id="algo-tabu-len" type="number" min="1" step="1" value="200" /></label>
            <label><span>X Radius</span><input id="algo-x-radius" type="number" min="0" step="1" value="2" /></label>
            <label><span>Top Groups</span><input id="algo-top-groups" type="number" min="1" step="1" value="5" /></label>
            <label><span>Night Budget (s)</span><input id="algo-night-budget" type="number" min="1" step="100" value="28800" /></label>
          </div>
        </section>

        <div class="projection-grid" id="projection-grid">
          <article class="projection-card" data-view="top"><header><h3>Top</h3><button class="eye-btn" data-view="top" aria-label="Focus top view">Eye</button></header><canvas id="view-top" width="240" height="160"></canvas></article>
          <article class="projection-card" data-view="bottom"><header><h3>Bottom</h3><button class="eye-btn" data-view="bottom" aria-label="Focus bottom view">Eye</button></header><canvas id="view-bottom" width="240" height="160"></canvas></article>
          <article class="projection-card" data-view="front"><header><h3>Front</h3><button class="eye-btn" data-view="front" aria-label="Focus front view">Eye</button></header><canvas id="view-front" width="240" height="160"></canvas></article>
          <article class="projection-card" data-view="back"><header><h3>Back</h3><button class="eye-btn" data-view="back" aria-label="Focus back view">Eye</button></header><canvas id="view-back" width="240" height="160"></canvas></article>
          <article class="projection-card" data-view="left"><header><h3>Left</h3><button class="eye-btn" data-view="left" aria-label="Focus left view">Eye</button></header><canvas id="view-left" width="240" height="160"></canvas></article>
          <article class="projection-card" data-view="right"><header><h3>Right</h3><button class="eye-btn" data-view="right" aria-label="Focus right view">Eye</button></header><canvas id="view-right" width="240" height="160"></canvas></article>
        </div>
      </aside>
    </main>
  </div>
`;

const refs = {
  sceneHost: document.getElementById("scene-host"),
  generateBtn: document.getElementById("generate-btn"),
  solveBtn: document.getElementById("solve-btn"),
  pauseBtn: document.getElementById("pause-btn"),
  speedSlider: document.getElementById("speed-slider"),
  speedValue: document.getElementById("speed-value"),
  passthroughToggle: document.getElementById("passthrough-toggle"),
  algoApplyBtn: document.getElementById("algo-apply-btn"),
  algoLam: document.getElementById("algo-lam"),
  algoTabuIters: document.getElementById("algo-tabu-iters"),
  algoTabuLen: document.getElementById("algo-tabu-len"),
  algoXRadius: document.getElementById("algo-x-radius"),
  algoTopGroups: document.getElementById("algo-top-groups"),
  algoNightBudget: document.getElementById("algo-night-budget"),
  statusText: document.getElementById("status-text"),
  statTotal: document.getElementById("stat-total"),
  statScore: document.getElementById("stat-score"),
  statProgress: document.getElementById("stat-progress"),
  statCost: document.getElementById("stat-cost"),
  eyeButtons: Array.from(document.querySelectorAll(".eye-btn")),
  projections: {
    top: document.getElementById("view-top"),
    bottom: document.getElementById("view-bottom"),
    front: document.getElementById("view-front"),
    back: document.getElementById("view-back"),
    left: document.getElementById("view-left"),
    right: document.getElementById("view-right"),
  },
};

const state = {
  stacks: null,
  solving: false,
  paused: false,
  speed: 1,
  runToken: 0,
  moveCursor: 0,
  moveTotal: 0,
  weightedCost: 0,
  carryingId: null,
  passthrough: false,
  selectedContainerIds: new Set(),
  projectionHitMaps: {},
  selectedProjectionCell: null,
  algorithmSettings: null,
};

const colorToHex = {
  red: new THREE.Color(COLOR_PALETTE.red),
  green: new THREE.Color(COLOR_PALETTE.green),
  blue: new THREE.Color(COLOR_PALETTE.blue),
};

const world = initWorld(refs.sceneHost);
state.cranePose = {
  x: stackXToWorld(2),
  z: stackZToWorld(0),
  hookY: world.crane.travelHookY,
};

refs.generateBtn.addEventListener("click", () => {
  generateScenario();
});

refs.solveBtn.addEventListener("click", () => {
  solveScenario();
});

refs.pauseBtn.addEventListener("click", () => {
  if (!state.solving) {
    return;
  }

  state.paused = !state.paused;
  refs.pauseBtn.textContent = state.paused ? "Resume" : "Pause";
  refs.statusText.textContent = state.paused ? "Paused." : "Running backend move sequence.";
});

refs.speedSlider.addEventListener("input", (event) => {
  state.speed = Number(event.target.value);
  refs.speedValue.textContent = `${state.speed.toFixed(2)}x`;
});

refs.passthroughToggle.addEventListener("change", (event) => {
  state.passthrough = event.target.checked;
  applyContainerSelectionStyles();
});

refs.algoApplyBtn.addEventListener("click", () => {
  applyAlgorithmSettings();
});

for (const eyeButton of refs.eyeButtons) {
  eyeButton.addEventListener("click", () => {
    snapCameraToView(eyeButton.dataset.view);
  });
}

for (const [view, canvas] of Object.entries(refs.projections)) {
  canvas.addEventListener("click", (event) => {
    onProjectionCanvasClick(view, event);
  });
}

startRenderLoop();
await loadAlgorithmSettings();
await generateScenario();

function initWorld(host) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#e8f0f8");

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 450);
  camera.position.set(18, 24, 72);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 5.8, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.maxDistance = 170;
  controls.minDistance = 20;
  controls.minPolarAngle = 0.02;
  controls.maxPolarAngle = Math.PI - 0.02;

  host.appendChild(renderer.domElement);

  const ambient = new THREE.AmbientLight("#ffffff", 0.92);
  scene.add(ambient);

  const sunLight = new THREE.DirectionalLight("#fff4dc", 1.25);
  sunLight.position.set(52, 64, 34);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  sunLight.shadow.camera.near = 1;
  sunLight.shadow.camera.far = 220;
  sunLight.shadow.camera.left = -65;
  sunLight.shadow.camera.right = 65;
  sunLight.shadow.camera.top = 65;
  sunLight.shadow.camera.bottom = -65;
  scene.add(sunLight);

  const fillLight = new THREE.DirectionalLight("#b8d8ff", 0.62);
  fillLight.position.set(-30, 26, -22);
  scene.add(fillLight);

  const environmentGroup = new THREE.Group();
  const containerRoot = new THREE.Group();
  scene.add(environmentGroup);
  scene.add(containerRoot);

  buildGround(environmentGroup);
  const trucks = buildTrucks(environmentGroup);

  const crane = buildCrane(environmentGroup);

  const containerVisuals = new Map();

  const clock = new THREE.Clock();

  function onResize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) {
      return;
    }
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  const resizeObserver = new ResizeObserver(onResize);
  resizeObserver.observe(host);
  window.addEventListener("resize", onResize);
  onResize();

  return {
    scene,
    camera,
    renderer,
    controls,
    environmentGroup,
    containerRoot,
    containerVisuals,
    crane,
    trucks,
    clock,
    onResize,
  };
}

function buildGround(group) {
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(TOTAL_WIDTH_WORLD + 22, YARD_LENGTH_WORLD + 30),
    new THREE.MeshStandardMaterial({
      color: "#d9e2eb",
      roughness: 0.9,
      metalness: 0.05,
    }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  group.add(ground);

  const yardPad = new THREE.Mesh(
    new THREE.PlaneGeometry(YARD_WIDTH_WORLD, YARD_LENGTH_WORLD),
    new THREE.MeshStandardMaterial({
      color: "#8da8be",
      roughness: 0.8,
      metalness: 0.04,
    }),
  );
  yardPad.rotation.x = -Math.PI / 2;
  yardPad.position.set(CONTAINER_MIN_X + YARD_WIDTH_WORLD / 2, 0.01, 0);
  yardPad.receiveShadow = true;
  group.add(yardPad);

  const lanePad = new THREE.Mesh(
    new THREE.PlaneGeometry(LANE_WIDTH_WORLD, YARD_LENGTH_WORLD),
    new THREE.MeshStandardMaterial({
      color: "#a3afbb",
      roughness: 0.87,
      metalness: 0.08,
    }),
  );
  lanePad.rotation.x = -Math.PI / 2;
  lanePad.position.set(LANE_MIN_X + LANE_WIDTH_WORLD / 2, 0.015, 0);
  lanePad.receiveShadow = true;
  group.add(lanePad);

  const stripeMat = new THREE.MeshStandardMaterial({ color: "#ffd248", roughness: 0.55 });
  const arrowCount = Math.floor(YARD_LENGTH_WORLD / 8);
  for (let i = 0; i < arrowCount; i += 1) {
    const z = YARD_MIN_Z + 3 + i * 8;
    const shaft = new THREE.Mesh(new THREE.BoxGeometry(LANE_WIDTH_WORLD * 0.08, 0.05, 1.9), stripeMat);
    shaft.position.set(LANE_MIN_X + LANE_WIDTH_WORLD / 2, 0.035, z);
    group.add(shaft);

    const head = new THREE.Mesh(new THREE.ConeGeometry(LANE_WIDTH_WORLD * 0.16, 0.8, 3), stripeMat);
    head.rotation.x = -Math.PI / 2;
    head.position.set(LANE_MIN_X + LANE_WIDTH_WORLD / 2, 0.035, z + 1.25);
    group.add(head);
  }

  const gridMaterial = new THREE.LineBasicMaterial({ color: "#6e8ca8" });
  const gridPoints = [];

  for (let ix = 0; ix <= YARD_CONFIG.width; ix += 1) {
    const x = CONTAINER_MIN_X + ix * STEP.x;
    gridPoints.push(new THREE.Vector3(x, 0.06, YARD_MIN_Z));
    gridPoints.push(new THREE.Vector3(x, 0.06, YARD_MIN_Z + YARD_LENGTH_WORLD));
  }

  for (let iz = 0; iz <= YARD_CONFIG.length; iz += 1) {
    const z = YARD_MIN_Z + iz * STEP.z;
    gridPoints.push(new THREE.Vector3(CONTAINER_MIN_X, 0.06, z));
    gridPoints.push(new THREE.Vector3(CONTAINER_MIN_X + YARD_WIDTH_WORLD, 0.06, z));
  }

  const gridGeometry = new THREE.BufferGeometry().setFromPoints(gridPoints);
  const gridLines = new THREE.LineSegments(gridGeometry, gridMaterial);
  group.add(gridLines);

  const railMaterial = new THREE.MeshStandardMaterial({ color: "#5b6771", metalness: 0.35, roughness: 0.52 });
  for (const x of [getRailX().left, getRailX().right]) {
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.33, 0.2, YARD_LENGTH_WORLD + 8), railMaterial);
    rail.position.set(x, 0.1, 0);
    rail.receiveShadow = true;
    group.add(rail);
  }
}

function buildTrucks(group) {
  const trucks = [];
  const laneCenterX = LANE_MIN_X + LANE_WIDTH_WORLD / 2;
  const laneStartZ = YARD_MIN_Z - CONTAINER_DIM.z - 8;
  const routeLength = YARD_LENGTH_WORLD + CONTAINER_DIM.z + 22;
  const carrierColors = Object.keys(COLOR_PALETTE);
  const truckCount = 3;

  for (let index = 0; index < truckCount; index += 1) {
    const randomContainerColor = carrierColors[Math.floor(Math.random() * carrierColors.length)];
    const truck = createTruckModel({
      cabColor: index % 2 === 0 ? "#2f8b57" : "#3f78bb",
      containerColor: randomContainerColor,
    });

    truck.position.set(laneCenterX, 0.02, laneStartZ + (routeLength * index) / truckCount);
    truck.userData.routeStart = laneStartZ;
    truck.userData.routeLength = routeLength;
    truck.userData.progress = index / truckCount;
    truck.userData.speed = 0.06;
    trucks.push(truck);
    group.add(truck);
  }

  return trucks;
}

function createTruckModel({ cabColor, containerColor }) {
  const group = new THREE.Group();
  const truckWidth = Math.min(LANE_WIDTH_WORLD * 0.82, CONTAINER_DIM.x * 0.92);
  const containerLength = CONTAINER_DIM.z * 0.93;
  const trailerLength = containerLength + 1.35;
  const wheelRadius = 0.18;
  const wheelThickness = 0.12;
  const trailerCenterZ = 0;
  const trailerDeckTopY = wheelRadius + 0.32;
  const cabFrontZ = trailerLength * 0.5 + 2.2;

  const metalFrame = new THREE.MeshStandardMaterial({ color: "#2f3844", roughness: 0.62, metalness: 0.35 });
  const trimMaterial = new THREE.MeshStandardMaterial({ color: "#5f6e7c", roughness: 0.5, metalness: 0.4 });
  const cabMaterial = new THREE.MeshStandardMaterial({ color: cabColor, roughness: 0.48, metalness: 0.18 });

  const trailerDeck = new THREE.Mesh(new THREE.BoxGeometry(truckWidth, 0.14, trailerLength), metalFrame);
  trailerDeck.position.set(0, trailerDeckTopY, trailerCenterZ);
  trailerDeck.castShadow = true;
  group.add(trailerDeck);

  const trailerSpine = new THREE.Mesh(new THREE.BoxGeometry(truckWidth * 0.22, 0.26, trailerLength * 0.96), trimMaterial);
  trailerSpine.position.set(0, trailerDeckTopY - 0.1, trailerCenterZ);
  trailerSpine.castShadow = true;
  group.add(trailerSpine);

  const containerHeight = CONTAINER_VISUAL_HEIGHT * 0.78;
  const cargoContainer = createHaulContainer(containerColor, truckWidth * 0.97, containerHeight, containerLength);
  cargoContainer.position.set(0, trailerDeckTopY + containerHeight * 0.5 + 0.08, trailerCenterZ - 0.08);
  group.add(cargoContainer);

  const kingPinPlate = new THREE.Mesh(new THREE.BoxGeometry(truckWidth * 0.4, 0.1, 0.62), trimMaterial);
  kingPinPlate.position.set(0, trailerDeckTopY - 0.04, trailerLength * 0.5 + 0.22);
  kingPinPlate.castShadow = true;
  group.add(kingPinPlate);

  const chassis = new THREE.Mesh(new THREE.BoxGeometry(truckWidth * 0.74, 0.22, 2.2), metalFrame);
  chassis.position.set(0, wheelRadius + 0.18, trailerLength * 0.5 + 0.98);
  chassis.castShadow = true;
  group.add(chassis);

  const cabLower = new THREE.Mesh(new THREE.BoxGeometry(truckWidth * 0.78, 0.82, 1.6), cabMaterial);
  cabLower.position.set(0, wheelRadius + 0.62, cabFrontZ - 0.78);
  cabLower.castShadow = true;
  group.add(cabLower);

  const cabUpper = new THREE.Mesh(new THREE.BoxGeometry(truckWidth * 0.72, 0.66, 1.12), cabMaterial);
  cabUpper.position.set(0, wheelRadius + 1.2, cabFrontZ - 0.86);
  cabUpper.castShadow = true;
  group.add(cabUpper);

  const windshield = new THREE.Mesh(
    new THREE.BoxGeometry(truckWidth * 0.62, 0.42, 0.06),
    new THREE.MeshStandardMaterial({ color: "#d6ecff", roughness: 0.2, metalness: 0.3 }),
  );
  windshield.position.set(0, wheelRadius + 1.1, cabFrontZ - 0.1);
  windshield.castShadow = true;
  group.add(windshield);

  const grille = new THREE.Mesh(
    new THREE.BoxGeometry(truckWidth * 0.48, 0.3, 0.08),
    new THREE.MeshStandardMaterial({ color: "#1f2732", roughness: 0.65, metalness: 0.35 }),
  );
  grille.position.set(0, wheelRadius + 0.64, cabFrontZ + 0.08);
  grille.castShadow = true;
  group.add(grille);

  const wheelGeometry = new THREE.CylinderGeometry(wheelRadius, wheelRadius, wheelThickness, 18);
  const wheelMaterial = new THREE.MeshStandardMaterial({ color: "#0b1118", roughness: 0.82, metalness: 0.2 });
  const wheelX = [truckWidth * 0.43, -truckWidth * 0.43];
  const trailerAxles = [
    trailerCenterZ - trailerLength * 0.5 + 0.52,
    trailerCenterZ - trailerLength * 0.5 + 0.96,
    trailerCenterZ - trailerLength * 0.5 + 1.4,
  ];
  const tractorAxles = [trailerLength * 0.5 + 0.56, trailerLength * 0.5 + 1.78];
  const axleZs = trailerAxles.concat(tractorAxles);

  for (const x of wheelX) {
    for (const z of axleZs) {
      const wheel = new THREE.Mesh(wheelGeometry, wheelMaterial);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(x, wheelRadius, z);
      wheel.castShadow = true;
      group.add(wheel);
    }
  }

  return group;
}

function createHaulContainer(colorName, width, height, length) {
  const color = colorToHex[colorName] || new THREE.Color("#60768b");
  const group = new THREE.Group();
  const shellMat = new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.12 });
  const shadeMat = new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(0.74),
    roughness: 0.66,
    metalness: 0.08,
  });

  const shell = new THREE.Mesh(new THREE.BoxGeometry(width, height, length), shellMat);
  shell.castShadow = true;
  group.add(shell);

  const ribGeom = new THREE.BoxGeometry(0.04, height * 0.88, 0.44);
  const ribCount = 9;
  for (let i = 0; i < ribCount; i += 1) {
    const z = -length * 0.42 + (i / (ribCount - 1)) * length * 0.84;
    for (const side of [-1, 1]) {
      const rib = new THREE.Mesh(ribGeom, shadeMat);
      rib.position.set(side * (width * 0.51), 0, z);
      rib.castShadow = true;
      group.add(rib);
    }
  }

  return group;
}

function getRailX() {
  return {
    left: CONTAINER_MIN_X - 1.3,
    right: LANE_MIN_X + LANE_WIDTH_WORLD + 1.3,
  };
}

function buildCrane(group) {
  const rails = getRailX();
  const centerX = (rails.left + rails.right) / 2;
  const span = rails.right - rails.left;
  const legDepth = STEP.z * 0.72;
  const legHeight = YARD_CONFIG.height * STEP.y + 6.1;
  const beamY = legHeight;

  const craneGroup = new THREE.Group();
  craneGroup.position.set(centerX, 0, stackZToWorld(0));
  group.add(craneGroup);

  const steelMaterial = new THREE.MeshStandardMaterial({ color: "#4e5965", roughness: 0.56, metalness: 0.35 });
  const beamMaterial = new THREE.MeshStandardMaterial({ color: "#596777", roughness: 0.51, metalness: 0.38 });
  const accentMaterial = new THREE.MeshStandardMaterial({ color: "#ffcd3e", roughness: 0.47, metalness: 0.2 });

  const legGeometry = new THREE.BoxGeometry(0.75, legHeight, 0.75);

  for (const side of [-1, 1]) {
    for (const depth of [-1, 1]) {
      const leg = new THREE.Mesh(legGeometry, steelMaterial);
      leg.position.set((span / 2) * side, legHeight / 2, (legDepth / 2) * depth);
      leg.castShadow = true;
      craneGroup.add(leg);

      const wheel = new THREE.Mesh(
        new THREE.CylinderGeometry(0.32, 0.32, 0.24, 14),
        new THREE.MeshStandardMaterial({ color: "#121820", roughness: 0.75, metalness: 0.18 }),
      );
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set((span / 2) * side + 0.32 * side, 0.34, (legDepth / 2) * depth);
      wheel.castShadow = true;
      craneGroup.add(wheel);

      const wheelHub = new THREE.Mesh(
        new THREE.CylinderGeometry(0.12, 0.12, 0.26, 10),
        new THREE.MeshStandardMaterial({ color: "#ffcd3e", roughness: 0.42, metalness: 0.25 }),
      );
      wheelHub.rotation.z = Math.PI / 2;
      wheelHub.position.copy(wheel.position);
      craneGroup.add(wheelHub);
    }
  }

  const topFront = new THREE.Mesh(new THREE.BoxGeometry(span + 1.2, 0.8, 0.8), beamMaterial);
  topFront.position.set(0, beamY, legDepth / 2);
  topFront.castShadow = true;
  craneGroup.add(topFront);

  const topBack = topFront.clone();
  topBack.position.z = -legDepth / 2;
  craneGroup.add(topBack);

  const bridge = new THREE.Mesh(new THREE.BoxGeometry(span + 0.8, 0.52, 1.15), beamMaterial);
  bridge.position.set(0, beamY - 1.35, 0);
  bridge.castShadow = true;
  craneGroup.add(bridge);

  const stairs = new THREE.Mesh(new THREE.BoxGeometry(0.3, legHeight - 2.6, 0.3), accentMaterial);
  stairs.position.set(-span / 2 - 0.48, (legHeight - 2.6) / 2 + 0.8, -legDepth / 2 + 0.55);
  stairs.castShadow = true;
  craneGroup.add(stairs);

  const trolleyY = beamY - 1.2;
  const trolley = new THREE.Group();
  trolley.position.set(0, trolleyY, 0);
  craneGroup.add(trolley);

  const trolleyBody = new THREE.Mesh(
    new THREE.BoxGeometry(2.3, 0.95, legDepth * 0.8),
    new THREE.MeshStandardMaterial({ color: "#343d48", roughness: 0.5, metalness: 0.32 }),
  );
  trolleyBody.castShadow = true;
  trolley.add(trolleyBody);

  const trolleyCap = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.42, legDepth * 0.44), accentMaterial);
  trolleyCap.position.y = 0.66;
  trolleyCap.castShadow = true;
  trolley.add(trolleyCap);

  const spreader = new THREE.Group();
  spreader.position.set(0, -4.8, 0);
  trolley.add(spreader);

  const spreaderBody = new THREE.Mesh(
    new THREE.BoxGeometry(CONTAINER_DIM.x * 1.05, 0.38, CONTAINER_DIM.z * 0.92),
    new THREE.MeshStandardMaterial({ color: "#ffbb1f", roughness: 0.45, metalness: 0.28 }),
  );
  spreaderBody.castShadow = true;
  spreader.add(spreaderBody);

  const ropeOffsets = [
    new THREE.Vector3(-0.75, 0, -CONTAINER_DIM.z * 0.35),
    new THREE.Vector3(0.75, 0, -CONTAINER_DIM.z * 0.35),
    new THREE.Vector3(-0.75, 0, CONTAINER_DIM.z * 0.35),
    new THREE.Vector3(0.75, 0, CONTAINER_DIM.z * 0.35),
  ];

  const ropes = ropeOffsets.map((offset) => {
    const rope = new THREE.Mesh(
      new THREE.CylinderGeometry(0.028, 0.028, 1, 6),
      new THREE.MeshStandardMaterial({ color: "#bcc9d9", roughness: 0.35, metalness: 0.4 }),
    );
    rope.position.copy(offset);
    rope.castShadow = true;
    trolley.add(rope);
    return rope;
  });

  return {
    group: craneGroup,
    trolley,
    spreader,
    ropes,
    centerX,
    trolleyY,
    travelHookY: beamY - 2.65,
  };
}

function createContainerMesh(color) {
  const group = new THREE.Group();
  const height = CONTAINER_VISUAL_HEIGHT;

  const shellMaterial = new THREE.MeshStandardMaterial({
    color: colorToHex[color],
    roughness: 0.56,
    metalness: 0.16,
  });

  const shadeMaterial = new THREE.MeshStandardMaterial({
    color: colorToHex[color].clone().multiplyScalar(0.72),
    roughness: 0.62,
    metalness: 0.1,
  });

  const trimMaterial = new THREE.MeshStandardMaterial({ color: "#bdc4ce", roughness: 0.38, metalness: 0.45 });

  const shell = new THREE.Mesh(new THREE.BoxGeometry(CONTAINER_DIM.x * 0.94, height, CONTAINER_DIM.z * 0.96), shellMaterial);
  shell.castShadow = true;
  shell.receiveShadow = true;
  group.add(shell);

  const ribGeometry = new THREE.BoxGeometry(0.05, height * 0.88, 0.56);
  const ribCount = 9;
  for (let i = 0; i < ribCount; i += 1) {
    const z = -CONTAINER_DIM.z * 0.42 + (i / (ribCount - 1)) * CONTAINER_DIM.z * 0.84;
    for (const side of [-1, 1]) {
      const rib = new THREE.Mesh(ribGeometry, shadeMaterial);
      rib.position.set((CONTAINER_DIM.x * 0.47 + 0.02) * side, 0, z);
      rib.castShadow = true;
      group.add(rib);
    }
  }

  const roofRibGeometry = new THREE.BoxGeometry(0.16, 0.05, CONTAINER_DIM.z * 0.84);
  for (const offset of [-0.3, 0, 0.3]) {
    const roofRib = new THREE.Mesh(roofRibGeometry, shadeMaterial);
    roofRib.position.set(offset, height * 0.5 - 0.025, 0);
    roofRib.castShadow = true;
    group.add(roofRib);
  }

  const doorPanel = new THREE.Mesh(
    new THREE.BoxGeometry(CONTAINER_DIM.x * 0.9, height * 0.92, 0.05),
    shadeMaterial,
  );
  const frontFaceZ = CONTAINER_DIM.z * 0.48;
  doorPanel.position.z = frontFaceZ;
  doorPanel.castShadow = true;
  group.add(doorPanel);

  const barGeometry = new THREE.BoxGeometry(0.06, height * 0.88, 0.05);
  const latchGeometry = new THREE.BoxGeometry(0.22, 0.05, 0.06);

  for (const xOffset of [-0.56, -0.18, 0.18, 0.56]) {
    const bar = new THREE.Mesh(barGeometry, trimMaterial);
    bar.position.set(xOffset, 0, frontFaceZ + 0.002);
    bar.castShadow = true;
    group.add(bar);

    const latchA = new THREE.Mesh(latchGeometry, trimMaterial);
    latchA.position.set(xOffset + 0.08, -height * 0.12, frontFaceZ + 0.02);
    latchA.castShadow = true;
    group.add(latchA);

    const latchB = latchA.clone();
    latchB.position.y = -height * 0.33;
    group.add(latchB);
  }

  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(CONTAINER_DIM.x * 0.95, height * 1.01, CONTAINER_DIM.z * 0.97)),
    new THREE.LineBasicMaterial({ color: "#00abff", transparent: true, opacity: 1 }),
  );
  edge.visible = false;
  edge.renderOrder = 3;
  group.add(edge);

  const materialSet = new Set();
  group.traverse((node) => {
    if (!node.isMesh) {
      return;
    }
    if (Array.isArray(node.material)) {
      for (const material of node.material) {
        materialSet.add(material);
      }
      return;
    }
    materialSet.add(node.material);
  });
  group.userData.edge = edge;
  group.userData.materials = Array.from(materialSet);

  return group;
}

function stackXToWorld(x) {
  return CONTAINER_MIN_X + (x + 0.5) * STEP.x;
}

function stackZToWorld(z) {
  return YARD_MIN_Z + (z + 0.5) * STEP.z;
}

function stackToWorld(x, z, y) {
  return new THREE.Vector3(
    stackXToWorld(x),
    CONTAINER_VISUAL_HEIGHT / 2 + y * STEP.y + STACK_BASE_OFFSET_Y,
    stackZToWorld(z),
  );
}

function clearContainers() {
  for (const visual of world.containerVisuals.values()) {
    world.containerRoot.remove(visual.mesh);
  }
  world.containerVisuals.clear();
}

function rebuildContainerMeshes() {
  clearContainers();

  for (let x = 0; x < YARD_CONFIG.width; x += 1) {
    for (let z = 0; z < YARD_CONFIG.length; z += 1) {
      const stack = state.stacks[x][z];
      for (let y = 0; y < stack.length; y += 1) {
        const container = stack[y];
        const mesh = createContainerMesh(container.color);
        const pos = stackToWorld(x, z, y);
        mesh.position.copy(pos);
        world.containerRoot.add(mesh);
        world.containerVisuals.set(container.id, {
          mesh,
          color: container.color,
          edge: mesh.userData.edge,
          materials: mesh.userData.materials,
        });
      }
    }
  }

  applyContainerSelectionStyles();
}

function clearProjectionSelection() {
  state.selectedContainerIds = new Set();
  state.selectedProjectionCell = null;
  applyContainerSelectionStyles();
  updateProjections();
}

function applyContainerSelectionStyles() {
  const hasSelection = state.selectedContainerIds.size > 0;

  for (const [containerId, visual] of world.containerVisuals.entries()) {
    const selected = state.selectedContainerIds.has(containerId);
    const faded = hasSelection && state.passthrough && !selected;
    const targetOpacity = faded ? 0.16 : 1;

    for (const material of visual.materials || []) {
      material.transparent = targetOpacity < 1;
      material.opacity = targetOpacity;
      material.depthWrite = targetOpacity >= 1;
      if (material.emissive) {
        material.emissive.set(selected ? "#1e67d3" : "#000000");
        material.emissiveIntensity = selected ? 0.22 : 0;
      }
    }

    if (visual.edge) {
      visual.edge.visible = selected;
    }
  }
}

function applyCranePose() {
  const crane = world.crane;
  crane.group.position.z = state.cranePose.z;
  crane.trolley.position.x = state.cranePose.x - crane.centerX;
  crane.spreader.position.y = state.cranePose.hookY - crane.trolleyY;

  const ropeLength = Math.max(0.55, -crane.spreader.position.y - 0.2);
  for (const rope of crane.ropes) {
    rope.scale.y = ropeLength;
    rope.position.y = -ropeLength / 2;
  }

  if (state.carryingId) {
    const carryingVisual = world.containerVisuals.get(state.carryingId);
    if (carryingVisual) {
      carryingVisual.mesh.position.set(
        state.cranePose.x,
        state.cranePose.hookY - (CONTAINER_VISUAL_HEIGHT * 0.5 + 0.48),
        state.cranePose.z,
      );
    }
  }
}

function animateTrucks(deltaSeconds) {
  if (state.paused) {
    return;
  }

  const speedFactor = Math.max(0.05, state.speed);

  for (const truck of world.trucks) {
    truck.userData.progress = (truck.userData.progress + truck.userData.speed * speedFactor * deltaSeconds) % 1;
    if (truck.userData.progress < 0) {
      truck.userData.progress += 1;
    }
    truck.position.z = truck.userData.routeStart + truck.userData.routeLength * truck.userData.progress;
  }
}

function startRenderLoop() {
  const render = () => {
    const delta = world.clock.getDelta();
    world.controls.update();
    animateTrucks(delta);
    applyCranePose();
    world.renderer.render(world.scene, world.camera);
    requestAnimationFrame(render);
  };

  render();
}

function updateStats() {
  if (!state.stacks) {
    refs.statTotal.textContent = "0";
    refs.statScore.textContent = "0%";
    refs.statProgress.textContent = "-";
    refs.statCost.textContent = "0";
    return;
  }

  const summary = summarizeStacks(state.stacks);
  refs.statTotal.textContent = `${summary.total}`;
  refs.statScore.textContent = `${Math.round(summary.placementScore * 100)}%`;
  refs.statProgress.textContent =
    state.moveTotal > 0 ? `${state.moveCursor} / ${state.moveTotal}` : state.solving ? "0 / ?" : "-";
  refs.statCost.textContent = `${state.weightedCost}`;
}

function setAlgorithmFormValues(settings) {
  refs.algoLam.value = String(settings.lam);
  refs.algoTabuIters.value = String(settings.tabuIters);
  refs.algoTabuLen.value = String(settings.tabuLen);
  refs.algoXRadius.value = String(settings.xRadius);
  refs.algoTopGroups.value = String(settings.topGroups);
  refs.algoNightBudget.value = String(settings.nightBudget);
}

function getAlgorithmFormValues() {
  return {
    lam: Number(refs.algoLam.value),
    tabuIters: Number(refs.algoTabuIters.value),
    tabuLen: Number(refs.algoTabuLen.value),
    xRadius: Number(refs.algoXRadius.value),
    topGroups: Number(refs.algoTopGroups.value),
    nightBudget: Number(refs.algoNightBudget.value),
  };
}

async function loadAlgorithmSettings() {
  try {
    const settings = await getAlgorithmSettings();
    state.algorithmSettings = settings;
    setAlgorithmFormValues(settings);
  } catch (error) {
    refs.statusText.textContent = `Settings load failed: ${error.message}`;
  }
}

async function applyAlgorithmSettings() {
  refs.algoApplyBtn.disabled = true;
  try {
    const settings = await updateAlgorithmSettings(getAlgorithmFormValues());
    state.algorithmSettings = settings;
    setAlgorithmFormValues(settings);
    refs.statusText.textContent = "Algorithm settings updated on backend.";
  } catch (error) {
    refs.statusText.textContent = `Settings update failed: ${error.message}`;
  } finally {
    refs.algoApplyBtn.disabled = false;
  }
}

function drawProjection(view, canvas, cols, rows, cellResolver, options = {}) {
  const flipX = Boolean(options.flipX);
  const flipY = options.flipY === undefined ? true : Boolean(options.flipY);
  const ctx = canvas.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = 240;
  const height = 160;

  if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.fillStyle = "#e8eff7";
  ctx.fillRect(0, 0, width, height);

  const padding = 12;
  const gridWidth = width - padding * 2;
  const gridHeight = height - padding * 2;
  const cellW = gridWidth / cols;
  const cellH = gridHeight / rows;
  const hitMap = new Map();

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const queryCol = flipX ? cols - 1 - col : col;
      const queryRow = flipY ? rows - 1 - row : row;
      const cell = cellResolver(queryCol, queryRow);
      const color = cell?.color ?? null;
      const ids = cell?.ids ?? [];
      hitMap.set(`${col},${row}`, ids);
      ctx.fillStyle = color ? COLOR_PALETTE[color] : "#c8d6e4";
      ctx.fillRect(
        padding + col * cellW + 1,
        padding + row * cellH + 1,
        Math.max(1, cellW - 2),
        Math.max(1, cellH - 2),
      );
    }
  }

  const selectedCell = state.selectedProjectionCell;
  if (selectedCell && selectedCell.view === view) {
    ctx.strokeStyle = "#009cff";
    ctx.lineWidth = 2.5;
    ctx.strokeRect(
      padding + selectedCell.col * cellW + 1,
      padding + selectedCell.row * cellH + 1,
      Math.max(1, cellW - 2),
      Math.max(1, cellH - 2),
    );
  }

  ctx.strokeStyle = "#8ca4bc";
  ctx.lineWidth = 1;

  for (let col = 0; col <= cols; col += 1) {
    const x = padding + col * cellW;
    ctx.beginPath();
    ctx.moveTo(x, padding);
    ctx.lineTo(x, padding + gridHeight);
    ctx.stroke();
  }

  for (let row = 0; row <= rows; row += 1) {
    const y = padding + row * cellH;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(padding + gridWidth, y);
    ctx.stroke();
  }

  state.projectionHitMaps[view] = {
    width,
    height,
    padding,
    cols,
    rows,
    cellW,
    cellH,
    hitMap,
  };
}

function updateProjections() {
  if (!state.stacks) {
    return;
  }

  const stacks = state.stacks;

  drawProjection(
    "top",
    refs.projections.top,
    YARD_CONFIG.width,
    YARD_CONFIG.length,
    (x, z) => {
      const stack = stacks[x][z];
      return {
        color: stack.length ? stack[stack.length - 1].color : null,
        ids: stack.map((container) => container.id),
      };
    },
    { flipX: true, flipY: true },
  );

  drawProjection("bottom", refs.projections.bottom, YARD_CONFIG.width, YARD_CONFIG.length, (x, z) => {
    const stack = stacks[x][z];
    return {
      color: stack.length ? stack[0].color : null,
      ids: stack.map((container) => container.id),
    };
  });

  drawProjection(
    "front",
    refs.projections.front,
    YARD_CONFIG.width,
    YARD_CONFIG.height,
    (x, y) => {
      const ids = [];
      let color = null;
      for (let z = 0; z < YARD_CONFIG.length; z += 1) {
        const stack = stacks[x][z];
        if (stack[y]) {
          ids.push(stack[y].id);
          if (!color) {
            color = stack[y].color;
          }
        }
      }
      return { color, ids };
    },
    { flipY: true },
  );

  drawProjection("back", refs.projections.back, YARD_CONFIG.width, YARD_CONFIG.height, (x, y) => {
    const ids = [];
    let color = null;
    for (let z = YARD_CONFIG.length - 1; z >= 0; z -= 1) {
      const stack = stacks[x][z];
      if (stack[y]) {
        ids.push(stack[y].id);
        if (!color) {
          color = stack[y].color;
        }
      }
    }
    return { color, ids };
  });

  drawProjection("left", refs.projections.left, YARD_CONFIG.length, YARD_CONFIG.height, (z, y) => {
    const ids = [];
    let color = null;
    for (let x = 0; x < YARD_CONFIG.width; x += 1) {
      const stack = stacks[x][z];
      if (stack[y]) {
        ids.push(stack[y].id);
        if (!color) {
          color = stack[y].color;
        }
      }
    }
    return { color, ids };
  });

  drawProjection(
    "right",
    refs.projections.right,
    YARD_CONFIG.length,
    YARD_CONFIG.height,
    (z, y) => {
      const ids = [];
      let color = null;
      for (let x = YARD_CONFIG.width - 1; x >= 0; x -= 1) {
        const stack = stacks[x][z];
        if (stack[y]) {
          ids.push(stack[y].id);
          if (!color) {
            color = stack[y].color;
          }
        }
      }
      return { color, ids };
    },
    { flipX: true, flipY: true },
  );
}

function onProjectionCanvasClick(view, event) {
  const hitInfo = state.projectionHitMaps[view];
  if (!hitInfo) {
    return;
  }

  const rect = event.currentTarget.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * hitInfo.width;
  const y = ((event.clientY - rect.top) / rect.height) * hitInfo.height;

  if (
    x < hitInfo.padding
    || x > hitInfo.padding + hitInfo.cols * hitInfo.cellW
    || y < hitInfo.padding
    || y > hitInfo.padding + hitInfo.rows * hitInfo.cellH
  ) {
    return;
  }

  const col = Math.floor((x - hitInfo.padding) / hitInfo.cellW);
  const row = Math.floor((y - hitInfo.padding) / hitInfo.cellH);
  const ids = hitInfo.hitMap.get(`${col},${row}`) || [];

  if (!ids.length) {
    clearProjectionSelection();
    refs.statusText.textContent = "Selection cleared.";
    return;
  }

  state.selectedContainerIds = new Set(ids);
  state.selectedProjectionCell = { view, col, row };
  applyContainerSelectionStyles();
  updateProjections();
  refs.statusText.textContent = `Selected ${ids.length} container${ids.length === 1 ? "" : "s"} from ${view} view.`;
}

function getViewFitDistance(halfWidth, halfHeight, paddingFactor = 1.14) {
  const fovY = THREE.MathUtils.degToRad(world.camera.fov);
  const fovX = 2 * Math.atan(Math.tan(fovY / 2) * world.camera.aspect);
  const distanceForHeight = halfHeight / Math.tan(fovY / 2);
  const distanceForWidth = halfWidth / Math.tan(fovX / 2);
  return Math.max(distanceForHeight, distanceForWidth) * paddingFactor;
}

function snapCameraToView(view) {
  const heightSpan = YARD_CONFIG.height * STEP.y + 8.6;
  const widthSpan = TOTAL_WIDTH_WORLD + 4.2;
  const lengthSpan = YARD_LENGTH_WORLD + 8.6;
  const center = new THREE.Vector3(CONTAINER_MIN_X + TOTAL_WIDTH_WORLD / 2, heightSpan * 0.42, 0);
  const direction = new THREE.Vector3();
  let distance = 24;

  switch (view) {
    case "front":
      distance = getViewFitDistance(widthSpan / 2, heightSpan / 2) + lengthSpan / 2;
      direction.set(0, 0, -1);
      world.camera.up.set(0, 1, 0);
      break;
    case "back":
      distance = getViewFitDistance(widthSpan / 2, heightSpan / 2) + lengthSpan / 2;
      direction.set(0, 0, 1);
      world.camera.up.set(0, 1, 0);
      break;
    case "left":
      distance = getViewFitDistance(lengthSpan / 2, heightSpan / 2);
      direction.set(-1, 0, 0);
      world.camera.up.set(0, 1, 0);
      break;
    case "right":
      distance = getViewFitDistance(lengthSpan / 2, heightSpan / 2);
      direction.set(1, 0, 0);
      world.camera.up.set(0, 1, 0);
      break;
    case "top":
      distance = getViewFitDistance(widthSpan / 2, lengthSpan / 2);
      direction.set(0, 1, 0.0002);
      world.camera.up.set(0, 0, -1);
      break;
    case "bottom":
      distance = getViewFitDistance(widthSpan / 2, lengthSpan / 2);
      direction.set(0, -1, 0.0002);
      world.camera.up.set(0, 0, 1);
      break;
    default:
      return;
  }

  const newPosition = center.clone().add(direction.normalize().multiplyScalar(distance));
  world.controls.target.copy(center);
  world.camera.position.copy(newPosition);
  world.camera.lookAt(center);
  world.camera.updateProjectionMatrix();
  world.controls.update();
  refs.statusText.textContent = `Camera aligned to ${view} view.`;
}

function setBusyUi(busy) {
  refs.generateBtn.disabled = busy;
  refs.solveBtn.disabled = busy || !state.stacks;
  refs.algoApplyBtn.disabled = busy;
}

async function generateScenario() {
  const token = ++state.runToken;
  state.solving = false;
  state.paused = false;
  refs.pauseBtn.disabled = true;
  refs.pauseBtn.textContent = "Pause";
  refs.statusText.textContent = "Requesting random container layout from backend...";
  state.moveCursor = 0;
  state.moveTotal = 0;
  state.weightedCost = 0;
  state.carryingId = null;
  state.selectedContainerIds = new Set();
  state.selectedProjectionCell = null;
  state.projectionHitMaps = {};

  setBusyUi(true);

  let response;
  try {
    response = await requestRandomConfiguration();
  } catch (error) {
    refs.statusText.textContent = `Random request failed: ${error.message}`;
    setBusyUi(false);
    return;
  }

  if (token !== state.runToken) {
    return;
  }

  state.stacks = cloneStacks(response.stacks);

  state.cranePose = {
    x: stackXToWorld(2),
    z: stackZToWorld(0),
    hookY: world.crane.travelHookY,
  };

  rebuildContainerMeshes();
  updateProjections();
  updateStats();

  refs.statusText.textContent = `Random yard generated (${response.summary.total} containers).`;
  setBusyUi(false);
}

function cancelRun() {
  state.runToken += 1;
  state.solving = false;
  state.paused = false;
  refs.pauseBtn.disabled = true;
  refs.pauseBtn.textContent = "Pause";
}

function tween(durationMs, onFrame, token) {
  return new Promise((resolve) => {
    let lastTime = null;
    let progress = 0;

    const step = (timestamp) => {
      if (token !== state.runToken) {
        resolve(false);
        return;
      }

      if (lastTime === null) {
        lastTime = timestamp;
      }

      const delta = timestamp - lastTime;
      lastTime = timestamp;

      if (!state.paused) {
        progress += (delta * state.speed) / durationMs;
        const t = Math.min(1, progress);
        onFrame(t);
      }

      if (progress >= 1) {
        resolve(true);
        return;
      }

      requestAnimationFrame(step);
    };

    requestAnimationFrame(step);
  });
}

async function moveCraneHorizontal(targetX, targetZ, token) {
  const startX = state.cranePose.x;
  const startZ = state.cranePose.z;

  const cost = Math.abs(targetX - startX) / STEP.x + YARD_CONFIG.lengthCostWeight * (Math.abs(targetZ - startZ) / STEP.z);
  const duration = 220 + cost * 120;

  await tween(
    duration,
    (t) => {
      state.cranePose.x = THREE.MathUtils.lerp(startX, targetX, t);
      state.cranePose.z = THREE.MathUtils.lerp(startZ, targetZ, t);
    },
    token,
  );
}

async function moveHook(targetY, token) {
  const startY = state.cranePose.hookY;
  const duration = 180 + (Math.abs(targetY - startY) / STEP.y) * 130;

  await tween(
    duration,
    (t) => {
      state.cranePose.hookY = THREE.MathUtils.lerp(startY, targetY, t);
    },
    token,
  );
}

function syncStackMesh(containerId, x, z, y) {
  const visual = world.containerVisuals.get(containerId);
  if (!visual) {
    return;
  }
  visual.mesh.position.copy(stackToWorld(x, z, y));
}

async function executeMove(move, token) {
  const sourceStack = state.stacks[move.from.x][move.from.z];
  if (!sourceStack.length) {
    return;
  }

  const container = sourceStack[sourceStack.length - 1];
  const sourceX = stackXToWorld(move.from.x);
  const sourceZ = stackZToWorld(move.from.z);

  await moveCraneHorizontal(sourceX, sourceZ, token);
  if (token !== state.runToken) {
    return;
  }

  const pickLevel = sourceStack.length - 1;
  const pickY = stackToWorld(move.from.x, move.from.z, pickLevel).y + CONTAINER_VISUAL_HEIGHT * 0.5 + 0.58;
  await moveHook(pickY, token);
  if (token !== state.runToken) {
    return;
  }

  sourceStack.pop();
  state.carryingId = container.id;
  updateProjections();
  updateStats();

  await moveHook(world.crane.travelHookY, token);
  if (token !== state.runToken) {
    return;
  }

  const destinationX = stackXToWorld(move.to.x);
  const destinationZ = stackZToWorld(move.to.z);
  await moveCraneHorizontal(destinationX, destinationZ, token);
  if (token !== state.runToken) {
    return;
  }

  const destinationStack = state.stacks[move.to.x][move.to.z];
  const placeLevel = destinationStack.length;
  const placeY = stackToWorld(move.to.x, move.to.z, placeLevel).y + CONTAINER_VISUAL_HEIGHT * 0.5 + 0.58;

  await moveHook(placeY, token);
  if (token !== state.runToken) {
    return;
  }

  destinationStack.push(container);
  state.carryingId = null;
  syncStackMesh(container.id, move.to.x, move.to.z, placeLevel);

  updateProjections();
  updateStats();

  await moveHook(world.crane.travelHookY, token);
}

async function solveScenario() {
  if (!state.stacks || state.solving) {
    return;
  }

  const token = ++state.runToken;
  state.solving = true;
  state.paused = false;
  state.moveCursor = 0;
  state.moveTotal = 0;
  state.weightedCost = 0;

  refs.pauseBtn.disabled = false;
  refs.pauseBtn.textContent = "Pause";
  refs.generateBtn.disabled = true;
  refs.solveBtn.disabled = true;
  refs.statusText.textContent = "Requesting solve plan from backend...";
  updateStats();

  let plan;
  try {
    plan = await requestSolvePlan(cloneStacks(state.stacks), getAlgorithmFormValues());
  } catch (error) {
    state.solving = false;
    refs.pauseBtn.disabled = true;
    refs.pauseBtn.textContent = "Pause";
    refs.generateBtn.disabled = false;
    refs.solveBtn.disabled = false;
    refs.statusText.textContent = `Solve request failed: ${error.message}`;
    return;
  }

  if (token !== state.runToken) {
    return;
  }

  state.moveTotal = plan.moves.length;
  refs.statusText.textContent = `Executing ${plan.moves.length} backend moves...`;
  updateStats();

  for (const move of plan.moves) {
    if (token !== state.runToken) {
      return;
    }

    await executeMove(move, token);
    if (token !== state.runToken) {
      return;
    }

    state.moveCursor += 1;
    state.weightedCost += move.weightedCost;
    updateStats();
  }

  state.solving = false;
  state.paused = false;
  refs.pauseBtn.disabled = true;
  refs.pauseBtn.textContent = "Pause";
  refs.generateBtn.disabled = false;
  refs.solveBtn.disabled = false;

  refs.statusText.textContent = plan.solved
    ? `Solve complete. Weighted crane cost: ${plan.totalWeightedCost}.`
    : `Solve stopped early. Reached ${Math.round(plan.finalSummary.placementScore * 100)}% placement quality.`;

  updateProjections();
  updateStats();
}

window.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "r") {
    cancelRun();
    generateScenario();
  }

  if (event.code === "Space") {
    event.preventDefault();
    if (state.solving) {
      refs.pauseBtn.click();
    }
  }
});
