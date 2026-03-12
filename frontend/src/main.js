import "./style.css";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { getAlgorithmSettings, requestRandomConfiguration, requestSolvePlan, updateAlgorithmSettings } from "./api/backendClient.js";
import { YARD_CONFIG, cloneStacks, placementScoreWeightsFromAlgorithmSettings, resolveColorHex, summarizeStacks } from "./config/yardModel.js";
import { buildCrane, buildGround } from "./scene/layout.js";
import { createLighting, updateLighting } from "./scene/lighting.js";
import { buildTrucks, clearTruckCargo, createTruckModel, formatTruckDisplayId, setTruckCargo } from "./scene/trucks.js";
import { DAY_TRUCK_PHASES, advanceDayRuntime, createDayRuntime, dayRuntimeHasActiveActors } from "./simulation/dayRuntime.js";
import { renderDayTimeline } from "./ui/dayTimeline.js";

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
const DAY_SLOT_COUNT = 10;
const NIGHT_CLOCK_BASE_SECONDS = 22 * 3600;
const NIGHT_DURATION_SECONDS = 8 * 3600;
const DAY_CLOCK_BASE_SECONDS = 6 * 3600;
const DAY_DURATION_SECONDS = 16 * 3600;
const MAX_RANDOM_CONTAINER_COUNT = YARD_CONFIG.width * YARD_CONFIG.length * YARD_CONFIG.height;
const MAX_RANDOM_MOVABLE_CONTAINER_COUNT = Math.max(1, MAX_RANDOM_CONTAINER_COUNT - 1);
const MAX_PLAYBACK_SPEED = 1000;
const DEFAULT_RANDOM_GROUPS = 3;
const FAST_FORWARD_SPEED_THRESHOLD = 70;
const FAST_FORWARD_PROJECTION_THROTTLE_MS = 90;
const RANDOM_REGENERATE_DEBOUNCE_MS = 380;
const ALGO_SETTINGS_SYNC_DEBOUNCE_MS = 450;
const MAX_SIM_SECONDS_PER_FRAME = 120;
const DAY_RUNTIME_STEP_SECONDS = 0.2;
const DAY_RUNTIME_MAX_STEPS_PER_FRAME = Math.ceil(MAX_SIM_SECONDS_PER_FRAME / DAY_RUNTIME_STEP_SECONDS);

const CONTAINER_MIN_X = -TOTAL_WIDTH_WORLD / 2;
const LANE_MIN_X = CONTAINER_MIN_X + YARD_WIDTH_WORLD;
const YARD_MIN_Z = -YARD_LENGTH_WORLD / 2;
const SCENE_METRICS = Object.freeze({
  totalWidthWorld: TOTAL_WIDTH_WORLD,
  yardLengthWorld: YARD_LENGTH_WORLD,
  yardWidthWorld: YARD_WIDTH_WORLD,
  laneWidthWorld: LANE_WIDTH_WORLD,
  laneMinX: LANE_MIN_X,
  yardMinZ: YARD_MIN_Z,
  daySlotCount: DAY_SLOT_COUNT,
  yardConfig: YARD_CONFIG,
  step: STEP,
  containerMinX: CONTAINER_MIN_X,
  containerDim: CONTAINER_DIM,
  containerVisualHeight: CONTAINER_VISUAL_HEIGHT,
});

const app = document.querySelector("#app");

function fieldLabel(text, tooltip) {
  const safeTip = String(tooltip).replace(/"/g, "&quot;");
  return `<span class="field-label"><span>${text}</span><span class="field-tip" title="${safeTip}">?</span></span>`;
}

app.innerHTML = `
  <div class="layout-shell">
    <header class="topbar reveal-a">
      <div>
        <h1>Container Yard Optimizer</h1>
        <p>5 x 10 x 4 yard, two truck lanes, night rehandling (22:00 to 06:00) then day offloading (06:00 to 22:00), length movement cost = 10x.</p>
      </div>
    </header>

    <section class="toolbar reveal-b">
      <button id="solve-btn" class="btn">Solve With Backend Plan</button>
      <button id="pause-btn" class="btn" disabled>Pause</button>
      <div class="speed-box">
        <div class="speed-box-header">
          <span>Playback Speed</span>
          <output id="speed-value">1x</output>
        </div>
        <input id="speed-slider" type="range" min="1" max="${MAX_PLAYBACK_SPEED}" step="1" value="1" />
        <div class="speed-boosts">
          <label class="boost-toggle" for="boost-10-toggle"><input id="boost-10-toggle" type="checkbox" /> <span>10x boost</span></label>
          <label class="boost-toggle" for="boost-100-toggle"><input id="boost-100-toggle" type="checkbox" /> <span>100x boost</span></label>
          <strong id="effective-speed">Effective 1x</strong>
        </div>
      </div>
      <label class="pass-box" for="passthrough-toggle">
        <input id="passthrough-toggle" type="checkbox" />
        <span>Passthrough</span>
      </label>
      <div class="cycle-box" id="cycle-box">
        <span class="moon" aria-hidden="true">🌙</span>
        <span class="chain" aria-hidden="true">⛓</span>
        <span class="sun" aria-hidden="true">☀</span>
        <strong id="cycle-label">Night Setup</strong>
      </div>
      <div class="clock-box">
        <span aria-hidden="true">🕒</span>
        <strong id="clock-value">20:00:00</strong>
      </div>
      <div class="status-text" id="status-text">Ready.</div>
    </section>

    <main class="content-grid">
      <section class="scene-panel reveal-c">
        <div id="scene-host"></div>
        <div class="scene-legend">
          <div id="legend-colors" class="legend-colors"></div>
          <span class="lane-note">Two-lane road: parking + passing</span>
        </div>
        <section class="runtime-panel">
          <h3>Algorithm Runtime</h3>
          <div class="runtime-grid">
            <div><label>Night Moves</label><strong id="runtime-night-moves">-</strong></div>
            <div><label>Night Time Used</label><strong id="runtime-night-time">-</strong></div>
            <div><label>Day Jobs</label><strong id="runtime-day-jobs">-</strong></div>
            <div><label>Day Score</label><strong id="runtime-day-score">-</strong></div>
            <div><label>Lane Wait</label><strong id="runtime-lane-wait">-</strong></div>
            <div><label>Makespan</label><strong id="runtime-makespan">-</strong></div>
            <div><label>Remaining @ 22:00</label><strong id="runtime-remaining">-</strong></div>
          </div>
        </section>
        <section class="timeline-panel">
          <div class="timeline-panel-header">
            <h3>Day Timeline</h3>
            <span>Truck schedule from 06:00 to 22:00</span>
          </div>
          <div id="day-timeline"></div>
        </section>
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
          <h3>Random Setup</h3>
          <div class="algo-grid">
            <label>${fieldLabel("Groups", "How many logical container groups to generate. Each group gets its own color.")}<input id="random-groups" type="number" value="${DEFAULT_RANDOM_GROUPS}" /></label>
            <label>${fieldLabel("Total Containers", "How many containers are placed into the 5 x 10 x 4 yard for the random scenario.")}<input id="random-container-count" type="number" max="${MAX_RANDOM_MOVABLE_CONTAINER_COUNT}" value="${YARD_CONFIG.containerCount}" /></label>
            <label>${fieldLabel("Min / Group", "Minimum number of containers each group should receive in the generated setup.")}<input id="random-min-per-group" type="number" value="20" /></label>
            <label>${fieldLabel("Max / Group", "Maximum number of containers each group can receive in the generated setup.")}<input id="random-max-per-group" type="number" value="60" /></label>
          </div>
        </section>

        <section class="algo-settings" id="algo-settings-panel">
          <div class="algo-settings-header">
            <div>
              <h3>Algorithm Settings</h3>
              <p>Basic mode is tuned for presentation. Advanced mode exposes the search internals.</p>
            </div>
            <div class="algo-mode-switch" role="tablist" aria-label="Algorithm settings detail level">
              <button id="algo-mode-basic" class="algo-mode-btn is-active" type="button" data-settings-mode="basic">Basic Only</button>
              <button id="algo-mode-advanced" class="algo-mode-btn" type="button" data-settings-mode="advanced" aria-expanded="false">Show Advanced</button>
            </div>
          </div>
          <div id="algo-panel-basic" class="algo-grid">
            <label>${fieldLabel("Optimization Budget (s)", "Maximum amount of night-shift time the optimizer may spend on planned moves.")}<input id="algo-night-budget" type="number" min="1" step="100" value="28800" /></label>
            <label>${fieldLabel("Cluster Weight", "How strongly the optimizer groups containers of the same company together. Higher values improve clustering but can increase travel.")}<input id="algo-lam" type="number" min="0" step="0.1" value="1" /></label>
            <label>${fieldLabel("Energy Weight", "How much the optimizer penalizes energy-heavy moves. Higher values make long and vertical crane moves less attractive.")}<input id="algo-energy-weight" type="number" min="0" step="0.1" value="1" /></label>
            <label>${fieldLabel("Rehandle Penalty", "Penalty for mixed stacks that are likely to require extra reshuffles later in the day.")}<input id="algo-stack-rehandle-weight" type="number" min="0" step="0.1" value="1.0" /></label>
            <label>${fieldLabel("Day Prep Priority", "Penalty for containers buried under other groups. Higher values keep soon-to-load containers more accessible for the day shift.")}<input id="algo-buried-foreign-weight" type="number" min="0" step="0.1" value="2.0" /></label>
          </div>
          <div id="algo-panel-advanced-wrap" class="algo-advanced-shell" hidden>
            <div class="algo-advanced-title">Advanced Search Controls</div>
            <div id="algo-panel-advanced" class="algo-grid algo-grid-advanced">
              <label>${fieldLabel("Tabu Iterations", "Number of search iterations in the tabu phase. More iterations can improve solutions but take longer.")}<input id="algo-tabu-iters" type="number" min="1" step="1" value="1500" /></label>
              <label>${fieldLabel("Tabu Length", "How long recent moves stay temporarily forbidden to avoid immediate cycling.")}<input id="algo-tabu-len" type="number" min="1" step="1" value="200" /></label>
              <label>${fieldLabel("Search Radius", "How far the candidate destination search may look from a group center on the width axis.")}<input id="algo-x-radius" type="number" min="0" step="1" value="2" /></label>
              <label>${fieldLabel("Focus Groups", "How many of the most spread-out groups are prioritized when generating candidate moves.")}<input id="algo-top-groups" type="number" min="1" step="1" value="5" /></label>
              <label>${fieldLabel("Top Mismatch Weight", "Penalty for stacks whose top container does not match the dominant group below it.")}<input id="algo-stack-top-mismatch-weight" type="number" min="0" step="0.1" value="1.1" /></label>
              <label>${fieldLabel("Impurity Weight", "Penalty for stacks that mix multiple groups instead of staying compositionally clean.")}<input id="algo-stack-impurity-weight" type="number" min="0" step="0.1" value="1.4" /></label>
              <label>${fieldLabel("Fragmentation Weight", "Penalty for spreading the same group across too many stacks instead of keeping it compact.")}<input id="algo-group-fragmentation-weight" type="number" min="0" step="0.1" value="0.9" /></label>
              <label>${fieldLabel("Quality Tie Epsilon", "If two moves are almost equal in quality, the optimizer uses this threshold before preferring the cheaper operational move.")}<input id="algo-quality-tie-eps" type="number" min="0" step="0.000001" value="0.000000001" /></label>
            </div>
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
  solveBtn: document.getElementById("solve-btn"),
  pauseBtn: document.getElementById("pause-btn"),
  speedSlider: document.getElementById("speed-slider"),
  speedValue: document.getElementById("speed-value"),
  boost10Toggle: document.getElementById("boost-10-toggle"),
  boost100Toggle: document.getElementById("boost-100-toggle"),
  effectiveSpeed: document.getElementById("effective-speed"),
  passthroughToggle: document.getElementById("passthrough-toggle"),
  cycleBox: document.getElementById("cycle-box"),
  cycleLabel: document.getElementById("cycle-label"),
  clockValue: document.getElementById("clock-value"),
  randomGroups: document.getElementById("random-groups"),
  randomContainerCount: document.getElementById("random-container-count"),
  randomMinPerGroup: document.getElementById("random-min-per-group"),
  randomMaxPerGroup: document.getElementById("random-max-per-group"),
  algoSettingsPanel: document.getElementById("algo-settings-panel"),
  algoModeBasic: document.getElementById("algo-mode-basic"),
  algoModeAdvanced: document.getElementById("algo-mode-advanced"),
  algoPanelBasic: document.getElementById("algo-panel-basic"),
  algoPanelAdvancedWrap: document.getElementById("algo-panel-advanced-wrap"),
  algoPanelAdvanced: document.getElementById("algo-panel-advanced"),
  algoLam: document.getElementById("algo-lam"),
  algoEnergyWeight: document.getElementById("algo-energy-weight"),
  algoTabuIters: document.getElementById("algo-tabu-iters"),
  algoTabuLen: document.getElementById("algo-tabu-len"),
  algoXRadius: document.getElementById("algo-x-radius"),
  algoTopGroups: document.getElementById("algo-top-groups"),
  algoNightBudget: document.getElementById("algo-night-budget"),
  algoStackTopMismatchWeight: document.getElementById("algo-stack-top-mismatch-weight"),
  algoStackRehandleWeight: document.getElementById("algo-stack-rehandle-weight"),
  algoStackImpurityWeight: document.getElementById("algo-stack-impurity-weight"),
  algoBuriedForeignWeight: document.getElementById("algo-buried-foreign-weight"),
  algoGroupFragmentationWeight: document.getElementById("algo-group-fragmentation-weight"),
  algoQualityTieEps: document.getElementById("algo-quality-tie-eps"),
  legendColors: document.getElementById("legend-colors"),
  statusText: document.getElementById("status-text"),
  statTotal: document.getElementById("stat-total"),
  statScore: document.getElementById("stat-score"),
  statProgress: document.getElementById("stat-progress"),
  statCost: document.getElementById("stat-cost"),
  runtimeNightMoves: document.getElementById("runtime-night-moves"),
  runtimeNightTime: document.getElementById("runtime-night-time"),
  runtimeDayJobs: document.getElementById("runtime-day-jobs"),
  runtimeDayScore: document.getElementById("runtime-day-score"),
  runtimeLaneWait: document.getElementById("runtime-lane-wait"),
  runtimeMakespan: document.getElementById("runtime-makespan"),
  runtimeRemaining: document.getElementById("runtime-remaining"),
  dayTimeline: document.getElementById("day-timeline"),
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
  uiBusy: false,
  speed: 1,
  speedBoost: 1,
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
  cyclePhase: "nightSetup",
  phaseClockBase: 20 * 3600,
  phaseClockSeconds: 0,
  nightStats: null,
  dayCyclePlan: null,
  dayStats: null,
  activeDayJobIndex: -1,
  dayRuntime: null,
  clockRunning: false,
  clockBoost: 1,
  lastProjectionDrawAt: 0,
  randomRegenerateTimer: null,
  pendingRandomSetup: null,
  lastRandomSetupSignature: null,
  algoSyncTimer: null,
  algoSyncInFlight: false,
  algoSyncQueued: false,
  algoSettingsMode: "basic",
  legendSignature: "",
  cameraTransition: null,
};

const threeColorCache = new Map();

function colorToThree(colorName) {
  const resolved = resolveColorHex(colorName);
  let color = threeColorCache.get(resolved);
  if (!color) {
    color = new THREE.Color(resolved);
    threeColorCache.set(resolved, color);
  }
  return color;
}

const world = initWorld(refs.sceneHost);
state.cranePose = {
  x: stackXToWorld(2),
  z: stackZToWorld(0),
  hookY: world.crane.travelHookY,
};

function formatClock(secondsSinceMidnight) {
  const normalized = ((Math.floor(secondsSinceMidnight) % 86400) + 86400) % 86400;
  const hours = String(Math.floor(normalized / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((normalized % 3600) / 60)).padStart(2, "0");
  const seconds = String(normalized % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function formatDuration(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  if (safe >= 3600) {
    return `${(safe / 3600).toFixed(2)}h`;
  }
  if (safe >= 60) {
    return `${(safe / 60).toFixed(1)}m`;
  }
  return `${safe.toFixed(0)}s`;
}

function effectivePlaybackSpeed() {
  return Math.max(1, state.speed) * Math.max(1, state.speedBoost || 1);
}

function updatePlaybackSpeedUi() {
  refs.speedSlider.value = String(state.speed);
  refs.speedValue.textContent = `${state.speed}x`;
  refs.boost10Toggle.checked = state.speedBoost === 10;
  refs.boost100Toggle.checked = state.speedBoost === 100;
  refs.effectiveSpeed.textContent = `Effective ${effectivePlaybackSpeed()}x`;
}

function setPlaybackSpeed(baseSpeed, boost = 1) {
  state.speed = Math.min(MAX_PLAYBACK_SPEED, Math.max(1, Math.round(Number(baseSpeed) || 1)));
  state.speedBoost = Math.max(1, Math.round(Number(boost) || 1));
  updatePlaybackSpeedUi();
}

function setCyclePhase(phase, detail = "") {
  state.cyclePhase = phase;
  refs.cycleBox.dataset.phase = phase;
  const labels = {
    nightSetup: "Night Setup",
    nightRunning: "Night Cycle Running",
    phaseShift: "Night -> Day Transition",
    dayRunning: "Day Cycle Running",
    completed: "Cycle Complete",
  };
  refs.cycleLabel.textContent = detail || labels[phase] || "Cycle";
}

function setAlgorithmSettingsMode(mode) {
  const nextMode = mode === "advanced" ? "advanced" : "basic";
  state.algoSettingsMode = nextMode;
  refs.algoSettingsPanel.dataset.mode = nextMode;
  refs.algoPanelBasic.hidden = false;
  refs.algoPanelAdvancedWrap.hidden = nextMode !== "advanced";
  refs.algoModeBasic.classList.toggle("is-active", nextMode === "basic");
  refs.algoModeAdvanced.classList.toggle("is-active", nextMode === "advanced");
  refs.algoModeAdvanced.textContent = nextMode === "advanced" ? "Hide Advanced" : "Show Advanced";
  refs.algoModeAdvanced.setAttribute("aria-expanded", String(nextMode === "advanced"));
}

function setPhaseClock(elapsedSeconds) {
  state.phaseClockSeconds = Math.max(0, Number(elapsedSeconds) || 0);
  refs.clockValue.textContent = formatClock(state.phaseClockBase + state.phaseClockSeconds);
}

function setClockPhaseBase(baseSeconds) {
  state.phaseClockBase = baseSeconds;
  setPhaseClock(state.phaseClockSeconds);
}

function clearRuntimeStats() {
  refs.runtimeNightMoves.textContent = "-";
  refs.runtimeNightTime.textContent = "-";
  refs.runtimeDayJobs.textContent = "-";
  refs.runtimeDayScore.textContent = "-";
  refs.runtimeLaneWait.textContent = "-";
  refs.runtimeMakespan.textContent = "-";
  refs.runtimeRemaining.textContent = "-";
}

function updateDayTimeline() {
  renderDayTimeline(refs.dayTimeline, state.dayCyclePlan, {
    activeJobIndex: state.activeDayJobIndex,
    currentTimeSeconds: state.cyclePhase === "dayRunning" || state.cyclePhase === "completed"
      ? state.phaseClockSeconds
      : null,
    formatTruckLabel: formatTruckDisplayId,
  });
}

function updateRuntimeStats() {
  const night = state.nightStats;
  const day = state.dayStats;
  refs.runtimeNightMoves.textContent = night ? `${night.totalMoves}` : "-";
  refs.runtimeNightTime.textContent = night ? `${formatDuration(night.timeUsedSeconds)} / ${formatDuration(night.budgetSeconds)}` : "-";
  refs.runtimeDayJobs.textContent = day ? `${day.totalJobs}` : "-";
  refs.runtimeDayScore.textContent = day ? `${day.score.toFixed(2)}` : "-";
  refs.runtimeLaneWait.textContent = day ? formatDuration(day.totalLaneWaitSeconds) : "-";
  refs.runtimeMakespan.textContent = day ? formatDuration(day.makespanSeconds) : "-";
  refs.runtimeRemaining.textContent = day ? `${day.remainingContainers}` : "-";
  updateDayTimeline();
}

function toNullableInteger(rawValue) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.floor(parsed);
}

function getRandomGenerationFormValues() {
  const parsedContainerCount = toNullableInteger(refs.randomContainerCount.value);
  if (parsedContainerCount === null) {
    return null;
  }

  const containerCount = Math.min(parsedContainerCount, MAX_RANDOM_MOVABLE_CONTAINER_COUNT);
  const groups = toNullableInteger(refs.randomGroups.value);
  const minContainersPerGroup = toNullableInteger(refs.randomMinPerGroup.value);
  const maxContainersPerGroup = toNullableInteger(refs.randomMaxPerGroup.value);

  refs.randomContainerCount.value = String(containerCount);

  const payload = {
    containerCount,
  };

  if (groups !== null) {
    payload.groups = groups;
  }
  if (minContainersPerGroup !== null) {
    payload.minContainersPerGroup = minContainersPerGroup;
  }
  if (maxContainersPerGroup !== null) {
    payload.maxContainersPerGroup = maxContainersPerGroup;
  }

  return payload;
}

function randomSetupSignature(setup) {
  return [
    setup.containerCount,
    setup.groups ?? "",
    setup.minContainersPerGroup ?? "",
    setup.maxContainersPerGroup ?? "",
  ].join(":");
}

function scheduleRandomRegeneration() {
  const randomSetup = getRandomGenerationFormValues();
  if (!randomSetup) {
    return;
  }
  const signature = randomSetupSignature(randomSetup);
  if (signature === state.lastRandomSetupSignature) {
    return;
  }

  if (state.randomRegenerateTimer !== null) {
    window.clearTimeout(state.randomRegenerateTimer);
  }

  state.randomRegenerateTimer = window.setTimeout(() => {
    state.randomRegenerateTimer = null;
    if (state.uiBusy) {
      state.pendingRandomSetup = randomSetup;
      return;
    }
    if (state.solving) {
      cancelRun();
    }
    void generateScenario(randomSetup);
  }, RANDOM_REGENERATE_DEBOUNCE_MS);
}

setCyclePhase("nightSetup");
setClockPhaseBase(NIGHT_CLOCK_BASE_SECONDS);
setPhaseClock(0);
clearRuntimeStats();
updatePlaybackSpeedUi();

refs.solveBtn.addEventListener("click", () => {
  solveScenario();
});

refs.pauseBtn.addEventListener("click", () => {
  if (!state.solving) {
    return;
  }

  state.paused = !state.paused;
  refs.pauseBtn.textContent = state.paused ? "Resume" : "Pause";
  refs.statusText.textContent = state.paused ? "Paused." : "Simulation running.";
});

refs.speedSlider.addEventListener("input", (event) => {
  setPlaybackSpeed(event.target.value, state.speedBoost);
});

refs.boost10Toggle.addEventListener("change", (event) => {
  setPlaybackSpeed(state.speed, event.target.checked ? 10 : 1);
});

refs.boost100Toggle.addEventListener("change", (event) => {
  setPlaybackSpeed(state.speed, event.target.checked ? 100 : 1);
});

for (const field of [
  refs.randomGroups,
  refs.randomContainerCount,
  refs.randomMinPerGroup,
  refs.randomMaxPerGroup,
]) {
  field.addEventListener("input", () => {
    scheduleRandomRegeneration();
  });
}

refs.passthroughToggle.addEventListener("change", (event) => {
  state.passthrough = event.target.checked;
  applyContainerSelectionStyles();
});

for (const field of [
  refs.algoLam,
  refs.algoEnergyWeight,
  refs.algoTabuIters,
  refs.algoTabuLen,
  refs.algoXRadius,
  refs.algoTopGroups,
  refs.algoNightBudget,
  refs.algoStackTopMismatchWeight,
  refs.algoStackRehandleWeight,
  refs.algoStackImpurityWeight,
  refs.algoBuriedForeignWeight,
  refs.algoGroupFragmentationWeight,
  refs.algoQualityTieEps,
]) {
  field.addEventListener("input", () => {
    scheduleAlgorithmSettingsSync();
  });
}

refs.algoModeBasic.addEventListener("click", () => {
  setAlgorithmSettingsMode("basic");
});

refs.algoModeAdvanced.addEventListener("click", () => {
  setAlgorithmSettingsMode(state.algoSettingsMode === "advanced" ? "basic" : "advanced");
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
setAlgorithmSettingsMode("basic");
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

  const lighting = createLighting(scene);

  const environmentGroup = new THREE.Group();
  const containerRoot = new THREE.Group();
  scene.add(environmentGroup);
  scene.add(containerRoot);

  buildGround(environmentGroup, SCENE_METRICS);
  const trucks = buildTrucks(environmentGroup, SCENE_METRICS);

  const crane = buildCrane(environmentGroup, SCENE_METRICS);

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
    lighting,
    trucks,
    clock,
    onResize,
  };
}

function getOrCreateTruck(truckId, companyColor) {
  const existing = world.trucks.map.get(truckId);
  if (existing) {
    return existing;
  }

  const truck = createTruckModel({
    cabColor: companyColor || "#596b7a",
    containerColor: null,
    metrics: SCENE_METRICS,
    colorToThree,
    truckId,
  });
  truck.visible = false;
  world.trucks.map.set(truckId, truck);
  world.trucks.layer.add(truck);
  return truck;
}

function resetTruckFleet() {
  for (const truck of world.trucks.map.values()) {
    clearTruckCargo(truck);
    truck.visible = false;
  }
}

function createPoseSegment(start, end, fromPose, toPose) {
  return {
    start,
    end,
    fromPose: { ...fromPose },
    toPose: { ...toPose },
  };
}

function buildDayCranePlan(actor, startTime, cranePose) {
  const job = actor.job;
  const sourceStack = state.stacks?.[job.source.x]?.[job.source.z];
  if (!sourceStack?.length) {
    return null;
  }

  const sourceX = stackXToWorld(job.source.x);
  const sourceZ = stackZToWorld(job.source.z);
  const truckDropX = world.trucks.parkingLaneX - LANE_WIDTH_WORLD * 0.13;
  const truckDropZ = actor.slotZ;
  const pickLevel = sourceStack.length - 1;
  const pickY = stackToWorld(job.source.x, job.source.z, pickLevel).y + CONTAINER_VISUAL_HEIGHT * 0.5 + 0.58;
  const truckHookY = CONTAINER_VISUAL_HEIGHT + 1.9;
  const moveDuration = Math.max(0.05, Number(job.craneTaskSeconds) || 0.05);

  const startPose = {
    x: cranePose.x,
    z: cranePose.z,
    hookY: cranePose.hookY,
  };
  const sourceTravelPose = {
    x: sourceX,
    z: sourceZ,
    hookY: startPose.hookY,
  };
  const sourcePickupPose = {
    x: sourceX,
    z: sourceZ,
    hookY: pickY,
  };
  const sourceLiftPose = {
    x: sourceX,
    z: sourceZ,
    hookY: world.crane.travelHookY,
  };
  const truckTravelPose = {
    x: truckDropX,
    z: truckDropZ,
    hookY: world.crane.travelHookY,
  };
  const truckDropPose = {
    x: truckDropX,
    z: truckDropZ,
    hookY: truckHookY,
  };
  const endPose = {
    x: truckDropX,
    z: truckDropZ,
    hookY: world.crane.travelHookY,
  };

  const weightToSource = Math.abs(sourceX - startPose.x) / STEP.x
    + YARD_CONFIG.lengthCostWeight * (Math.abs(sourceZ - startPose.z) / STEP.z);
  const weightToTruckDrop = Math.abs(truckDropX - sourceX) / STEP.x
    + YARD_CONFIG.lengthCostWeight * (Math.abs(truckDropZ - sourceZ) / STEP.z);
  const hookDownWeight = 0.34;
  const hookUpWeight = 0.24;
  const totalWeight = Math.max(
    0.0001,
    weightToSource + hookDownWeight + hookUpWeight + weightToTruckDrop + hookDownWeight + hookUpWeight,
  );

  let clockCursor = startTime;
  const takeClockRange = (weight, forceEnd = false) => {
    const rangeStart = clockCursor;
    if (forceEnd) {
      clockCursor = startTime + moveDuration;
    } else {
      clockCursor += moveDuration * (weight / totalWeight);
    }
    return { start: rangeStart, end: clockCursor };
  };

  const sourceRange = takeClockRange(weightToSource);
  const pickupRange = takeClockRange(hookDownWeight);
  const liftRange = takeClockRange(hookUpWeight);
  const truckRange = takeClockRange(weightToTruckDrop);
  const dropRange = takeClockRange(hookDownWeight);
  const clearRange = takeClockRange(hookUpWeight, true);

  return {
    startTime,
    pickupTime: pickupRange.end,
    dropTime: dropRange.end,
    endTime: clearRange.end,
    finalPose: endPose,
    segments: [
      createPoseSegment(sourceRange.start, sourceRange.end, startPose, sourceTravelPose),
      createPoseSegment(pickupRange.start, pickupRange.end, sourceTravelPose, sourcePickupPose),
      createPoseSegment(liftRange.start, liftRange.end, sourcePickupPose, sourceLiftPose),
      createPoseSegment(truckRange.start, truckRange.end, sourceLiftPose, truckTravelPose),
      createPoseSegment(dropRange.start, dropRange.end, truckTravelPose, truckDropPose),
      createPoseSegment(clearRange.start, clearRange.end, truckDropPose, endPose),
    ],
  };
}

function syncDayRuntimeVisuals(runtime) {
  if (!runtime) {
    return;
  }

  const nextActiveJobIndex = runtime.schedule?.activeJobIndex ?? -1;
  if (state.activeDayJobIndex !== nextActiveJobIndex) {
    state.activeDayJobIndex = nextActiveJobIndex;
    updateDayTimeline();
  }

  state.cranePose.x = runtime.crane.pose.x;
  state.cranePose.z = runtime.crane.pose.z;
  state.cranePose.hookY = runtime.crane.pose.hookY;

  for (const actor of runtime.truckActors) {
    const truck = actor.visual;
    if (!truck) {
      continue;
    }
    truck.visible = actor.visible;
    if (!actor.visible) {
      continue;
    }
    truck.position.set(actor.x, 0.02, actor.z);
    truck.rotation.y = actor.heading;
  }
}

function countRemainingContainers(stacks) {
  if (!Array.isArray(stacks)) {
    return 0;
  }
  let total = 0;
  for (const column of stacks) {
    for (const stack of column) {
      total += stack.length;
    }
  }
  return total;
}

function stepDaySimulation() {
  const runtime = state.dayRuntime;
  if (!runtime || state.cyclePhase !== "dayRunning") {
    return;
  }

  advanceDayRuntime(runtime, state.phaseClockSeconds, runtime.hooks);
  syncDayRuntimeVisuals(runtime);
}

function createContainerMesh(color) {
  const group = new THREE.Group();
  const height = CONTAINER_VISUAL_HEIGHT;

  const shellMaterial = new THREE.MeshStandardMaterial({
    color: colorToThree(color),
    roughness: 0.56,
    metalness: 0.16,
  });

  const shadeMaterial = new THREE.MeshStandardMaterial({
    color: colorToThree(color).clone().multiplyScalar(0.72),
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
    const activeCarry = state.carryingId === containerId;
    const faded = hasSelection && state.passthrough && !selected;
    const targetOpacity = faded ? 0.16 : 1;

    for (const material of visual.materials || []) {
      material.transparent = targetOpacity < 1;
      material.opacity = targetOpacity;
      material.depthWrite = targetOpacity >= 1;
      if (material.emissive) {
        material.emissive.set(activeCarry ? "#ffb01f" : selected ? "#1e67d3" : "#000000");
        material.emissiveIntensity = activeCarry ? 0.34 : selected ? 0.22 : 0;
      }
    }

    if (visual.edge) {
      visual.edge.visible = selected || activeCarry;
      visual.edge.material.color.set(activeCarry ? "#ffb01f" : "#00abff");
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

function updateSimulationClock(deltaSeconds) {
  if (!state.clockRunning || state.paused) {
    return;
  }
  const delta = Math.max(0, Number(deltaSeconds) || 0);
  if (delta <= 0) {
    return;
  }
  const multiplier = effectivePlaybackSpeed() * Math.max(1, state.clockBoost || 1);
  const requestedAdvance = delta * multiplier;
  const safeAdvance = Math.min(requestedAdvance, MAX_SIM_SECONDS_PER_FRAME);
  setPhaseClock(state.phaseClockSeconds + safeAdvance);
}

function updateCameraTransition(deltaSeconds) {
  const transition = state.cameraTransition;
  if (!transition) {
    return;
  }

  transition.elapsed = Math.min(transition.duration, transition.elapsed + Math.max(0, Number(deltaSeconds) || 0));
  const rawT = transition.duration <= 0 ? 1 : transition.elapsed / transition.duration;
  const eased = rawT < 0.5
    ? 4 * rawT * rawT * rawT
    : 1 - ((-2 * rawT + 2) ** 3) / 2;

  world.camera.position.lerpVectors(transition.startPosition, transition.endPosition, eased);
  world.controls.target.lerpVectors(transition.startTarget, transition.endTarget, eased);
  world.camera.up.lerpVectors(transition.startUp, transition.endUp, eased).normalize();
  world.camera.lookAt(world.controls.target);

  if (rawT >= 1) {
    world.camera.position.copy(transition.endPosition);
    world.controls.target.copy(transition.endTarget);
    world.camera.up.copy(transition.endUp);
    world.camera.lookAt(world.controls.target);
    world.camera.updateProjectionMatrix();
    state.cameraTransition = null;
  }
}

function startRenderLoop() {
  const render = () => {
    const delta = world.clock.getDelta();
    updateSimulationClock(delta);
    updateLighting(world.lighting, {
      phaseClockBase: state.phaseClockBase,
      phaseClockSeconds: state.phaseClockSeconds,
    });
    updateCameraTransition(delta);
    stepDaySimulation();
    world.controls.update();
    applyCranePose();
    world.renderer.render(world.scene, world.camera);
    requestAnimationFrame(render);
  };

  render();
}

function renderColorLegend(colorCount) {
  const entries = Object.entries(colorCount || {})
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => a[0].localeCompare(b[0]));
  const signature = entries.map(([color, count]) => `${color}:${count}`).join("|");
  if (signature === state.legendSignature) {
    return;
  }
  state.legendSignature = signature;

  refs.legendColors.textContent = "";
  for (const [colorName] of entries) {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.className = "swatch";
    swatch.style.background = resolveColorHex(colorName);

    const label = document.createElement("span");
    label.textContent = colorName;

    item.appendChild(swatch);
    item.appendChild(label);
    refs.legendColors.appendChild(item);
  }
}

function currentPlacementScoreWeights() {
  return placementScoreWeightsFromAlgorithmSettings(state.algorithmSettings);
}

function updateStats() {
  if (!state.stacks) {
    refs.statTotal.textContent = "0";
    refs.statScore.textContent = "0%";
    refs.statProgress.textContent = "-";
    refs.statCost.textContent = "0";
    renderColorLegend({});
    return;
  }

  const summary = summarizeStacks(state.stacks, currentPlacementScoreWeights());
  refs.statTotal.textContent = `${summary.total}`;
  refs.statScore.textContent = `${Math.round(summary.placementScore * 100)}%`;
  refs.statProgress.textContent =
    state.moveTotal > 0 ? `${state.moveCursor} / ${state.moveTotal}` : state.solving ? "0 / ?" : "-";
  refs.statCost.textContent = `${state.weightedCost}`;
  renderColorLegend(summary.colorCount);
}

function setAlgorithmFormValues(settings) {
  refs.algoLam.value = String(settings.lam);
  refs.algoEnergyWeight.value = String(settings.energyWeight);
  refs.algoTabuIters.value = String(settings.tabuIters);
  refs.algoTabuLen.value = String(settings.tabuLen);
  refs.algoXRadius.value = String(settings.xRadius);
  refs.algoTopGroups.value = String(settings.topGroups);
  refs.algoNightBudget.value = String(settings.nightBudget);
  refs.algoStackTopMismatchWeight.value = String(settings.stackTopMismatchWeight);
  refs.algoStackRehandleWeight.value = String(settings.stackRehandleWeight);
  refs.algoStackImpurityWeight.value = String(settings.stackImpurityWeight);
  refs.algoBuriedForeignWeight.value = String(settings.buriedForeignWeight);
  refs.algoGroupFragmentationWeight.value = String(settings.groupFragmentationWeight);
  refs.algoQualityTieEps.value = String(settings.qualityTieEps);
}

function getAlgorithmFormValues() {
  const lam = Number(refs.algoLam.value);
  const energyWeight = Number(refs.algoEnergyWeight.value);
  const tabuIters = Number(refs.algoTabuIters.value);
  const tabuLen = Number(refs.algoTabuLen.value);
  const xRadius = Number(refs.algoXRadius.value);
  const topGroups = Number(refs.algoTopGroups.value);
  const nightBudget = Number(refs.algoNightBudget.value);
  const stackTopMismatchWeight = Number(refs.algoStackTopMismatchWeight.value);
  const stackRehandleWeight = Number(refs.algoStackRehandleWeight.value);
  const stackImpurityWeight = Number(refs.algoStackImpurityWeight.value);
  const buriedForeignWeight = Number(refs.algoBuriedForeignWeight.value);
  const groupFragmentationWeight = Number(refs.algoGroupFragmentationWeight.value);
  const qualityTieEps = Number(refs.algoQualityTieEps.value);

  if (
    !Number.isFinite(lam)
    || lam < 0
    || !Number.isFinite(energyWeight)
    || energyWeight < 0
    || !Number.isFinite(tabuIters)
    || tabuIters < 1
    || !Number.isFinite(tabuLen)
    || tabuLen < 1
    || !Number.isFinite(xRadius)
    || xRadius < 0
    || !Number.isFinite(topGroups)
    || topGroups < 1
    || !Number.isFinite(nightBudget)
    || nightBudget < 1
    || !Number.isFinite(stackTopMismatchWeight)
    || stackTopMismatchWeight < 0
    || !Number.isFinite(stackRehandleWeight)
    || stackRehandleWeight < 0
    || !Number.isFinite(stackImpurityWeight)
    || stackImpurityWeight < 0
    || !Number.isFinite(buriedForeignWeight)
    || buriedForeignWeight < 0
    || !Number.isFinite(groupFragmentationWeight)
    || groupFragmentationWeight < 0
    || !Number.isFinite(qualityTieEps)
    || qualityTieEps < 0
  ) {
    return null;
  }

  return {
    lam,
    energyWeight,
    tabuIters: Math.floor(tabuIters),
    tabuLen: Math.floor(tabuLen),
    xRadius: Math.floor(xRadius),
    topGroups: Math.floor(topGroups),
    nightBudget,
    stackTopMismatchWeight,
    stackRehandleWeight,
    stackImpurityWeight,
    buriedForeignWeight,
    groupFragmentationWeight,
    qualityTieEps,
  };
}

async function loadAlgorithmSettings() {
  try {
    const settings = await getAlgorithmSettings();
    state.algorithmSettings = settings;
    setAlgorithmFormValues(settings);
    updateStats();
  } catch (error) {
    refs.statusText.textContent = `Settings load failed: ${error.message}`;
  }
}

async function applyAlgorithmSettings() {
  const payload = getAlgorithmFormValues();
  if (!payload) {
    refs.statusText.textContent = "Algorithm settings not synced yet: complete all fields with valid values.";
    return;
  }

  if (state.algoSyncInFlight) {
    state.algoSyncQueued = true;
    return;
  }

  state.algoSyncInFlight = true;
  try {
    const settings = await updateAlgorithmSettings(payload);
    state.algorithmSettings = settings;
    setAlgorithmFormValues(settings);
    updateStats();
    refs.statusText.textContent = "Algorithm settings updated on backend.";
  } catch (error) {
    refs.statusText.textContent = `Settings update failed: ${error.message}`;
  } finally {
    state.algoSyncInFlight = false;
    if (state.algoSyncQueued) {
      state.algoSyncQueued = false;
      void applyAlgorithmSettings();
    }
  }
}

function scheduleAlgorithmSettingsSync() {
  if (state.algoSyncTimer !== null) {
    window.clearTimeout(state.algoSyncTimer);
  }

  state.algoSyncTimer = window.setTimeout(() => {
    state.algoSyncTimer = null;
    if (state.uiBusy) {
      state.algoSyncQueued = true;
      return;
    }
    void applyAlgorithmSettings();
  }, ALGO_SETTINGS_SYNC_DEBOUNCE_MS);
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
      ctx.fillStyle = color ? resolveColorHex(color) : "#c8d6e4";
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

function updateProjections(force = false) {
  if (!state.stacks) {
    return;
  }

  const now = performance.now();
  if (
    !force
    && state.solving
    && effectivePlaybackSpeed() >= FAST_FORWARD_SPEED_THRESHOLD
    && now - state.lastProjectionDrawAt < FAST_FORWARD_PROJECTION_THROTTLE_MS
  ) {
    return;
  }
  state.lastProjectionDrawAt = now;

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
  const startUp = world.camera.up.clone();
  const targetUp = startUp.clone();
  let distance = 24;

  switch (view) {
    case "front":
      distance = getViewFitDistance(widthSpan / 2, heightSpan / 2) + lengthSpan / 2;
      direction.set(0, 0, -1);
      targetUp.set(0, 1, 0);
      break;
    case "back":
      distance = getViewFitDistance(widthSpan / 2, heightSpan / 2) + lengthSpan / 2;
      direction.set(0, 0, 1);
      targetUp.set(0, 1, 0);
      break;
    case "left":
      distance = getViewFitDistance(lengthSpan / 2, heightSpan / 2);
      direction.set(-1, 0, 0);
      targetUp.set(0, 1, 0);
      break;
    case "right":
      distance = getViewFitDistance(lengthSpan / 2, heightSpan / 2);
      direction.set(1, 0, 0);
      targetUp.set(0, 1, 0);
      break;
    case "top":
      distance = getViewFitDistance(widthSpan / 2, lengthSpan / 2);
      direction.set(0, 1, 0.0002);
      targetUp.set(0, 0, -1);
      break;
    case "bottom":
      distance = getViewFitDistance(widthSpan / 2, lengthSpan / 2);
      direction.set(0, -1, 0.0002);
      targetUp.set(0, 0, 1);
      break;
    default:
      return;
  }

  const newPosition = center.clone().add(direction.normalize().multiplyScalar(distance));
  state.cameraTransition = {
    startPosition: world.camera.position.clone(),
    endPosition: newPosition,
    startTarget: world.controls.target.clone(),
    endTarget: center.clone(),
    startUp,
    endUp: targetUp.normalize(),
    elapsed: 0,
    duration: 0.72,
  };
  refs.statusText.textContent = `Camera aligned to ${view} view.`;
}

function setBusyUi(busy) {
  state.uiBusy = busy;
  refs.solveBtn.disabled = busy || !state.stacks;
  refs.randomGroups.disabled = busy;
  refs.randomContainerCount.disabled = busy;
  refs.randomMinPerGroup.disabled = busy;
  refs.randomMaxPerGroup.disabled = busy;

  if (!busy) {
    if (state.pendingRandomSetup !== null && !state.solving) {
      const queuedSetup = state.pendingRandomSetup;
      state.pendingRandomSetup = null;
      void generateScenario(queuedSetup);
      return;
    }
    if (state.algoSyncQueued && !state.algoSyncInFlight) {
      state.algoSyncQueued = false;
      void applyAlgorithmSettings();
    }
  }
}

async function generateScenario(preparedRandomSetup = null) {
  const randomSetup = preparedRandomSetup || getRandomGenerationFormValues();
  if (!randomSetup) {
    refs.statusText.textContent = "Random setup waiting: enter a valid Total Containers value.";
    return;
  }
  const randomSignature = randomSetupSignature(randomSetup);
  if (state.randomRegenerateTimer !== null) {
    window.clearTimeout(state.randomRegenerateTimer);
    state.randomRegenerateTimer = null;
  }

  const token = ++state.runToken;
  state.solving = false;
  state.paused = false;
  state.clockRunning = false;
  state.clockBoost = 1;
  state.nightStats = null;
  state.dayCyclePlan = null;
  state.dayStats = null;
  state.dayRuntime = null;
  state.activeDayJobIndex = -1;
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
  setCyclePhase("nightSetup");
  setClockPhaseBase(NIGHT_CLOCK_BASE_SECONDS);
  setPhaseClock(0);
  clearRuntimeStats();
  updateDayTimeline();
  resetTruckFleet();

  setBusyUi(true);

  let response;
  try {
    response = await requestRandomConfiguration(randomSetup);
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

  state.lastRandomSetupSignature = randomSignature;
  refs.statusText.textContent = `Random yard generated (${response.summary.total} containers).`;
  setBusyUi(false);
}

function cancelRun() {
  state.runToken += 1;
  state.solving = false;
  state.paused = false;
  state.dayRuntime = null;
  state.activeDayJobIndex = -1;
  state.clockRunning = false;
  state.clockBoost = 1;
  refs.pauseBtn.disabled = true;
  refs.pauseBtn.textContent = "Pause";
  updateDayTimeline();
  resetTruckFleet();
}

function waitForSimulationStep(token, isComplete) {
  return new Promise((resolve) => {
    const step = () => {
      if (token !== state.runToken) {
        resolve(false);
        return;
      }
      if (isComplete()) {
        resolve(true);
        return;
      }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

function idleBoostForGap(gapSeconds, explicitBoost = null) {
  if (explicitBoost !== null && explicitBoost !== undefined) {
    return Math.max(1, Number(explicitBoost) || 1);
  }
  const gap = Math.max(0, Number(gapSeconds) || 0);
  if (gap >= 4 * 3600) {
    return 72;
  }
  if (gap >= 3600) {
    return 36;
  }
  if (gap >= 300) {
    return 12;
  }
  if (gap >= 60) {
    return 6;
  }
  return 1;
}

async function advancePhaseClockTo(targetSeconds, token, options = {}) {
  const start = state.phaseClockSeconds;
  const target = Math.max(start, Number(targetSeconds) || start);
  if (target <= start) {
    setPhaseClock(target);
    return true;
  }
  const previousBoost = state.clockBoost;
  state.clockRunning = true;
  state.clockBoost = idleBoostForGap(target - start, options.boost);
  try {
    const completed = await waitForSimulationStep(token, () => state.phaseClockSeconds >= target);
    if (completed && token === state.runToken) {
      setPhaseClock(target);
    }
    return completed;
  } finally {
    state.clockBoost = previousBoost;
  }
}

async function animateBySimulationTime(startSeconds, endSeconds, token, onFrame) {
  const start = Number.isFinite(startSeconds) ? Number(startSeconds) : state.phaseClockSeconds;
  const end = Number.isFinite(endSeconds) ? Math.max(start, Number(endSeconds)) : start;
  const duration = Math.max(0.0001, end - start);
  if (state.phaseClockSeconds < start) {
    const reached = await advancePhaseClockTo(start, token);
    if (!reached) {
      return false;
    }
  }
  onFrame(Math.min(1, Math.max(0, (state.phaseClockSeconds - start) / duration)));
  const completed = await waitForSimulationStep(token, () => {
    const t = Math.min(1, Math.max(0, (state.phaseClockSeconds - start) / duration));
    onFrame(t);
    return state.phaseClockSeconds >= end;
  });
  if (completed && token === state.runToken) {
    onFrame(1);
    setPhaseClock(end);
  }
  return completed;
}

async function moveCraneHorizontal(targetX, targetZ, token, clockRange = null) {
  const startX = state.cranePose.x;
  const startZ = state.cranePose.z;
  const fallbackStart = state.phaseClockSeconds;
  const fallbackDuration = Math.max(
    0.25,
    Math.abs(targetX - startX) / STEP.x + YARD_CONFIG.lengthCostWeight * (Math.abs(targetZ - startZ) / STEP.z),
  );
  const start = clockRange ? clockRange.start : fallbackStart;
  const end = clockRange ? clockRange.end : fallbackStart + fallbackDuration;
  await animateBySimulationTime(start, end, token, (t) => {
    state.cranePose.x = THREE.MathUtils.lerp(startX, targetX, t);
    state.cranePose.z = THREE.MathUtils.lerp(startZ, targetZ, t);
  });
}

async function moveHook(targetY, token, clockRange = null) {
  const startY = state.cranePose.hookY;
  const fallbackStart = state.phaseClockSeconds;
  const fallbackDuration = Math.max(0.15, Math.abs(targetY - startY) / STEP.y);
  const start = clockRange ? clockRange.start : fallbackStart;
  const end = clockRange ? clockRange.end : fallbackStart + fallbackDuration;
  await animateBySimulationTime(start, end, token, (t) => {
    state.cranePose.hookY = THREE.MathUtils.lerp(startY, targetY, t);
  });
}

function syncStackMesh(containerId, x, z, y) {
  const visual = world.containerVisuals.get(containerId);
  if (!visual) {
    return;
  }
  visual.mesh.position.copy(stackToWorld(x, z, y));
}

async function executeMove(move, token) {
  const rawMoveStart = Number.isFinite(move.tStart) ? move.tStart : state.phaseClockSeconds;
  const rawMoveEnd = Number.isFinite(move.tEnd) ? move.tEnd : rawMoveStart + Math.max(1, move.durationSeconds || move.weightedCost || 1);
  const moveStart = Math.min(NIGHT_DURATION_SECONDS, Math.max(0, rawMoveStart));
  const moveEnd = Math.min(NIGHT_DURATION_SECONDS, Math.max(moveStart, rawMoveEnd));
  await advancePhaseClockTo(moveStart, token);
  if (token !== state.runToken) {
    return;
  }

  const sourceStack = state.stacks[move.from.x][move.from.z];
  if (!sourceStack.length) {
    return;
  }

  const container = sourceStack[sourceStack.length - 1];
  const sourceX = stackXToWorld(move.from.x);
  const sourceZ = stackZToWorld(move.from.z);
  const destinationX = stackXToWorld(move.to.x);
  const destinationZ = stackZToWorld(move.to.z);

  const moveDuration = Math.max(0.05, moveEnd - moveStart);
  const weightToSource = Math.abs(sourceX - state.cranePose.x) / STEP.x
    + YARD_CONFIG.lengthCostWeight * (Math.abs(sourceZ - state.cranePose.z) / STEP.z);
  const weightToDestination = Math.abs(destinationX - sourceX) / STEP.x
    + YARD_CONFIG.lengthCostWeight * (Math.abs(destinationZ - sourceZ) / STEP.z);
  const hookDownWeight = 0.34;
  const hookUpWeight = 0.24;
  const totalWeight = Math.max(
    0.0001,
    weightToSource + hookDownWeight + hookUpWeight + weightToDestination + hookDownWeight + hookUpWeight,
  );
  let clockCursor = moveStart;
  const takeClockRange = (weight, forceEnd = false) => {
    const start = clockCursor;
    if (forceEnd) {
      clockCursor = moveEnd;
    } else {
      clockCursor += moveDuration * (weight / totalWeight);
    }
    return { start, end: clockCursor };
  };

  await moveCraneHorizontal(sourceX, sourceZ, token, takeClockRange(weightToSource));
  if (token !== state.runToken) {
    return;
  }

  const pickLevel = sourceStack.length - 1;
  const pickY = stackToWorld(move.from.x, move.from.z, pickLevel).y + CONTAINER_VISUAL_HEIGHT * 0.5 + 0.58;
  await moveHook(pickY, token, takeClockRange(hookDownWeight));
  if (token !== state.runToken) {
    return;
  }

  sourceStack.pop();
  state.carryingId = container.id;
  updateProjections();
  updateStats();

  await moveHook(world.crane.travelHookY, token, takeClockRange(hookUpWeight));
  if (token !== state.runToken) {
    return;
  }

  await moveCraneHorizontal(destinationX, destinationZ, token, takeClockRange(weightToDestination));
  if (token !== state.runToken) {
    return;
  }

  const destinationStack = state.stacks[move.to.x][move.to.z];
  const placeLevel = destinationStack.length;
  const placeY = stackToWorld(move.to.x, move.to.z, placeLevel).y + CONTAINER_VISUAL_HEIGHT * 0.5 + 0.58;

  await moveHook(placeY, token, takeClockRange(hookDownWeight));
  if (token !== state.runToken) {
    return;
  }

  destinationStack.push(container);
  state.carryingId = null;
  syncStackMesh(container.id, move.to.x, move.to.z, placeLevel);

  updateProjections();
  updateStats();

  await moveHook(world.crane.travelHookY, token, takeClockRange(hookUpWeight, true));
  if (token !== state.runToken) {
    return;
  }
  await advancePhaseClockTo(moveEnd, token);
}

function removeContainerVisual(containerId) {
  const visual = world.containerVisuals.get(containerId);
  if (!visual) {
    return;
  }
  world.containerRoot.remove(visual.mesh);
  world.containerVisuals.delete(containerId);
  state.selectedContainerIds.delete(containerId);
}

function createDayRuntimeHooks(runtime) {
  return {
    buildCranePlan(actor, startTime, cranePose) {
      return buildDayCranePlan(actor, startTime, cranePose);
    },
    onTruckPhaseChange(actor, previousPhase, nextPhase) {
      void previousPhase;
      const truckLabel = formatTruckDisplayId(actor.truckId);
      if (nextPhase === DAY_TRUCK_PHASES.enteringRoad) {
        refs.statusText.textContent = `${truckLabel} entering the road for ${actor.company}.`;
      } else if (nextPhase === DAY_TRUCK_PHASES.waiting) {
        refs.statusText.textContent = `${truckLabel} parked at bay ${actor.job.slotIndex + 1} and waiting for the crane.`;
      } else if (nextPhase === DAY_TRUCK_PHASES.loading) {
        refs.statusText.textContent = `Day cycle: loading ${actor.job.containerId} onto ${actor.job.truckId} (${actor.company}).`;
      } else if (nextPhase === DAY_TRUCK_PHASES.loaded) {
        refs.statusText.textContent = `${truckLabel} loaded and waiting for a merge window.`;
      } else if (nextPhase === DAY_TRUCK_PHASES.departing) {
        refs.statusText.textContent = `${truckLabel} leaving ${actor.company}.`;
      }
    },
    onCranePickup(actor) {
      const sourceStack = state.stacks?.[actor.job.source.x]?.[actor.job.source.z];
      if (!sourceStack?.length) {
        return;
      }
      const container = sourceStack.pop();
      actor.pickedContainer = container;
      actor.pickedContainerId = container.id;
      state.carryingId = container.id;
      updateProjections();
      updateStats();
    },
    onCraneDrop(actor) {
      const container = actor.pickedContainer;
      if (!container) {
        return;
      }
      state.carryingId = null;
      removeContainerVisual(container.id);
      if (actor.visual) {
        setTruckCargo(actor.visual, container.color, { metrics: SCENE_METRICS, colorToThree });
      }
      actor.cargoVisible = true;
      updateProjections();
      updateStats();
    },
    onCraneJobComplete(actor) {
      state.moveCursor += 1;
      state.weightedCost += actor.job.craneWeightedCost;
      updateStats();
    },
    onTruckFinished(actor) {
      if (actor.visual) {
        clearTruckCargo(actor.visual);
      }
      if (runtime.completed) {
        refs.statusText.textContent = "All day-cycle truck jobs cleared the road.";
      }
    },
  };
}

async function runDayCycle(dayCycle, token) {
  const jobs = dayCycle?.jobs || [];
  const dayDurationSeconds = dayCycle?.stats?.dayDurationSeconds ?? DAY_DURATION_SECONDS;
  state.dayCyclePlan = dayCycle;
  state.dayStats = dayCycle?.stats || null;
  state.activeDayJobIndex = -1;
  updateRuntimeStats();
  setPlaybackSpeed(1, 1);
  setCyclePhase("dayRunning");
  setClockPhaseBase(DAY_CLOCK_BASE_SECONDS);
  setPhaseClock(0);
  state.moveCursor = 0;
  state.moveTotal = jobs.length;
  updateStats();

  if (!jobs.length) {
    refs.statusText.textContent = "No day-cycle jobs scheduled for this day window.";
    await advancePhaseClockTo(dayDurationSeconds, token, { boost: 48 });
    return;
  }

  const visuals = jobs.map((job) => {
    const truck = getOrCreateTruck(job.truckId, job.companyColor);
    clearTruckCargo(truck);
    truck.visible = false;
    truck.position.set(world.trucks.passingLaneX, 0.02, world.trucks.entryZ);
    truck.rotation.y = 0;
    return truck;
  });
  const maxRoadLength = visuals.reduce((maxLength, truck) => {
    const roadLength = Number(truck.userData?.roadLength);
    if (!Number.isFinite(roadLength)) {
      return maxLength;
    }
    return Math.max(maxLength, roadLength);
  }, STEP.z * 0.84);

  const runtime = createDayRuntime(dayCycle, {
    entryZ: world.trucks.entryZ,
    exitZ: world.trucks.exitZ,
    passingLaneX: world.trucks.passingLaneX,
    parkingLaneX: world.trucks.parkingLaneX,
    slotZ: world.trucks.slotZ,
    initialCranePose: state.cranePose,
    fixedStepSeconds: DAY_RUNTIME_STEP_SECONDS,
    maxFixedStepsPerFrame: DAY_RUNTIME_MAX_STEPS_PER_FRAME,
    maxSimAdvanceSeconds: MAX_SIM_SECONDS_PER_FRAME,
    entryProgressDistance: 2.6,
    approachBuffer: STEP.z * 0.34,
    nominalRoadSpeed: STEP.z * 0.64,
    roadAcceleration: STEP.z * 0.64,
    roadBraking: STEP.z * 1.24,
    stopDistance: Math.max(STEP.z * 0.48, maxRoadLength * 0.44),
    brakingDistance: Math.max(STEP.z * 0.98, maxRoadLength * 0.9),
    truckLength: Math.max(STEP.z * 0.72, maxRoadLength * 0.78),
    bayClearance: STEP.z * 0.88,
    entrySpacing: Math.max(STEP.z * 0.62, maxRoadLength * 0.56),
    preferredVisibleTrucks: 2,
    maxVisibleTrucks: 3,
    dispatchLookaheadSeconds: 140,
    mergeClearanceAhead: Math.max(STEP.z * 0.72, maxRoadLength * 0.62),
    mergeClearanceBehind: Math.max(STEP.z * 0.92, maxRoadLength * 0.74),
    mergePriorityStopDistance: Math.max(STEP.z * 0.34, maxRoadLength * 0.32),
    parkingPriorityStopDistance: Math.max(STEP.z * 0.32, maxRoadLength * 0.28),
    stuckTimeoutSeconds: 14,
    parkingDuration: 2.4,
    mergeDuration: 2.1,
    mergeAdvanceDistance: STEP.z * 0.32,
  });

  runtime.truckActors.forEach((actor, index) => {
    actor.visual = visuals[index];
    actor.visual.visible = false;
  });
  runtime.hooks = createDayRuntimeHooks(runtime);

  state.dayRuntime = runtime;
  refs.statusText.textContent = `Running day schedule with independent road traffic (${jobs.length} truck jobs)...`;
  syncDayRuntimeVisuals(runtime);

  await waitForSimulationStep(token, () => {
    return runtime.completed || state.phaseClockSeconds >= dayDurationSeconds;
  });
  if (token !== state.runToken) {
    return;
  }

  state.activeDayJobIndex = -1;
  updateDayTimeline();

  if (runtime.completed && !dayRuntimeHasActiveActors(runtime)) {
    state.dayRuntime = null;
  }

  if (state.phaseClockSeconds < dayDurationSeconds) {
    await advancePhaseClockTo(dayDurationSeconds, token, { boost: 48 });
    if (token !== state.runToken) {
      return;
    }
  }

  state.dayRuntime = null;
  if (state.dayStats) {
    const remainingContainers = countRemainingContainers(state.stacks);
    state.dayStats = {
      ...state.dayStats,
      remainingContainers,
      completedWithinWindow: remainingContainers === 0,
      makespanSeconds: Math.max(state.dayStats.makespanSeconds, state.phaseClockSeconds),
    };
    updateRuntimeStats();
  }
}

async function solveScenario() {
  if (!state.stacks || state.solving) {
    return;
  }
  const algorithmFormValues = getAlgorithmFormValues();
  if (!algorithmFormValues) {
    refs.statusText.textContent = "Cannot solve: complete all algorithm settings with valid values first.";
    return;
  }

  const token = ++state.runToken;
  state.solving = true;
  state.paused = false;
  state.clockRunning = true;
  state.clockBoost = 1;
  state.moveCursor = 0;
  state.moveTotal = 0;
  state.weightedCost = 0;
  state.dayRuntime = null;
  state.phaseClockSeconds = 0;
  setClockPhaseBase(NIGHT_CLOCK_BASE_SECONDS);
  setPhaseClock(0);
  setCyclePhase("nightRunning");

  refs.pauseBtn.disabled = false;
  refs.pauseBtn.textContent = "Pause";
  refs.solveBtn.disabled = true;
  refs.statusText.textContent = "Requesting solve plan from backend...";
  updateStats();

  let plan;
  try {
    plan = await requestSolvePlan(cloneStacks(state.stacks), algorithmFormValues);
  } catch (error) {
    state.solving = false;
    state.clockRunning = false;
    state.clockBoost = 1;
    refs.pauseBtn.disabled = true;
    refs.pauseBtn.textContent = "Pause";
    refs.solveBtn.disabled = false;
    setCyclePhase("nightSetup");
    refs.statusText.textContent = `Solve request failed: ${error.message}`;
    return;
  }

  if (token !== state.runToken) {
    return;
  }

  state.nightStats = plan.nightStats || null;
  state.dayCyclePlan = plan.dayCycle || null;
  state.dayStats = plan.dayCycle?.stats || null;
  state.activeDayJobIndex = -1;
  updateRuntimeStats();

  state.moveTotal = plan.moves.length;
  refs.statusText.textContent = `Night cycle: executing ${plan.moves.length} backend moves...`;
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

  if (token !== state.runToken) {
    return;
  }

  await advancePhaseClockTo(NIGHT_DURATION_SECONDS, token, { boost: 72 });
  if (token !== state.runToken) {
    return;
  }

  setCyclePhase("phaseShift");
  refs.statusText.textContent = "Night cycle complete. Switching to day-cycle truck schedule...";

  await runDayCycle(plan.dayCycle, token);
  if (token !== state.runToken) {
    return;
  }

  state.solving = false;
  state.paused = false;
  state.clockRunning = false;
  state.clockBoost = 1;
  refs.pauseBtn.disabled = true;
  refs.pauseBtn.textContent = "Pause";
  refs.solveBtn.disabled = true;
  setCyclePhase("completed");

  const remaining = state.dayStats?.remainingContainers ?? 0;
  refs.statusText.textContent =
    remaining === 0
      ? "Day finished at 22:00. All scheduled offloads completed. Adjust the random setup for the next cycle."
      : `Day finished at 22:00 with ${remaining} container${remaining === 1 ? "" : "s"} still in yard. Adjust the random setup to continue.`;

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
