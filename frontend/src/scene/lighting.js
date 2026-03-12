import * as THREE from "three";

const SKY_NIGHT = new THREE.Color("#0d1c30");
const SKY_DAWN = new THREE.Color("#f0b46b");
const SKY_DAY = new THREE.Color("#dcefff");
const FOG_NIGHT = new THREE.Color("#263a4b");
const FOG_DAY = new THREE.Color("#d8e6f4");
const CELESTIAL_RADIUS_X = 88;
const CELESTIAL_RADIUS_Y = 74;
const CELESTIAL_HORIZON_Y = 9;
const CELESTIAL_SUN_START_Z = 34;
const CELESTIAL_SUN_END_Z = -26;
const CELESTIAL_MOON_START_Z = 28;
const CELESTIAL_MOON_END_Z = -32;

function clamp01(value) {
  return Math.max(0, Math.min(1, value));
}

function smoothstep(edge0, edge1, value) {
  const x = clamp01((value - edge0) / Math.max(1e-9, edge1 - edge0));
  return x * x * (3 - 2 * x);
}

function secondsSinceMidnight(baseSeconds, offsetSeconds) {
  return ((Math.floor(baseSeconds + offsetSeconds) % 86400) + 86400) % 86400;
}

function sunProgress(timeSeconds) {
  const dayStart = 6 * 3600;
  const dayEnd = 22 * 3600;
  if (timeSeconds < dayStart || timeSeconds > dayEnd) {
    return null;
  }
  return (timeSeconds - dayStart) / (dayEnd - dayStart);
}

function moonProgress(timeSeconds) {
  const nightStart = 22 * 3600;
  const nightDuration = 8 * 3600;
  if (timeSeconds >= nightStart) {
    return (timeSeconds - nightStart) / nightDuration;
  }
  if (timeSeconds <= 6 * 3600) {
    return (timeSeconds + 2 * 3600) / nightDuration;
  }
  return null;
}

function celestialArcPosition(progress, startZ, endZ) {
  const t = clamp01(progress);
  const angle = t * Math.PI;
  return new THREE.Vector3(
    Math.cos(angle) * CELESTIAL_RADIUS_X,
    CELESTIAL_HORIZON_Y + Math.sin(angle) * CELESTIAL_RADIUS_Y,
    THREE.MathUtils.lerp(startZ, endZ, t),
  );
}

export function createLighting(scene) {
  const ambient = new THREE.AmbientLight("#d8e0e8", 0.8);
  scene.add(ambient);

  const hemiLight = new THREE.HemisphereLight("#dcecff", "#6d7f91", 0.56);
  scene.add(hemiLight);

  const sunLight = new THREE.DirectionalLight("#fff3d6", 1.08);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  sunLight.shadow.camera.near = 1;
  sunLight.shadow.camera.far = 220;
  sunLight.shadow.camera.left = -65;
  sunLight.shadow.camera.right = 65;
  sunLight.shadow.camera.top = 65;
  sunLight.shadow.camera.bottom = -65;
  scene.add(sunLight);

  const fillLight = new THREE.DirectionalLight("#eef4fb", 0.74);
  fillLight.position.set(-30, 26, -22);
  scene.add(fillLight);

  const moonLight = new THREE.DirectionalLight("#dbe5f2", 0.24);
  scene.add(moonLight);

  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(2.2, 24, 24),
    new THREE.MeshBasicMaterial({ color: "#ffd467" }),
  );
  scene.add(sun);

  const moon = new THREE.Mesh(
    new THREE.SphereGeometry(1.5, 20, 20),
    new THREE.MeshBasicMaterial({ color: "#e9f2ff" }),
  );
  scene.add(moon);

  scene.fog = new THREE.Fog(FOG_DAY.clone(), 90, 210);

  return {
    scene,
    ambient,
    hemiLight,
    sunLight,
    fillLight,
    moonLight,
    sun,
    moon,
  };
}

export function updateLighting(lighting, { phaseClockBase, phaseClockSeconds }) {
  const sceneTime = secondsSinceMidnight(phaseClockBase, phaseClockSeconds);
  const sunT = sunProgress(sceneTime);
  const moonT = moonProgress(sceneTime);
  const daylight = sunT === null ? 0 : Math.sin(sunT * Math.PI);
  const sunriseBlend = smoothstep(5 * 3600, 7.5 * 3600, sceneTime) * (1 - smoothstep(19 * 3600, 22 * 3600, sceneTime));
  const twilight = clamp01(Math.max(sunriseBlend, 1 - smoothstep(20 * 3600, 23 * 3600, sceneTime)) * (1 - daylight * 0.75));

  const sky = SKY_NIGHT.clone().lerp(SKY_DAWN, twilight).lerp(SKY_DAY, daylight);
  lighting.scene.background.copy(sky);
  if (lighting.scene.fog) {
    lighting.scene.fog.color.copy(FOG_NIGHT.clone().lerp(FOG_DAY, 0.34 + daylight * 0.66));
  }

  lighting.ambient.intensity = 0.42 + daylight * 0.44 + twilight * 0.12;
  lighting.hemiLight.intensity = 0.34 + daylight * 0.46 + twilight * 0.14;
  lighting.sunLight.intensity = 0.1 + daylight * 1.18 + twilight * 0.24;
  lighting.fillLight.intensity = 0.22 + daylight * 0.38 + twilight * 0.08;
  lighting.moonLight.intensity = 0.18 + (1 - daylight) * 0.22;

  const sunPosition = celestialArcPosition(sunT ?? 0, CELESTIAL_SUN_START_Z, CELESTIAL_SUN_END_Z);
  lighting.sun.position.copy(sunPosition);
  lighting.sun.visible = sunT !== null;
  lighting.sunLight.position.copy(lighting.sun.position);
  lighting.fillLight.position.set(-lighting.sun.position.x * 0.28, 28 + daylight * 6, 24);

  const moonPosition = celestialArcPosition(moonT ?? 0, CELESTIAL_MOON_START_Z, CELESTIAL_MOON_END_Z);
  lighting.moon.position.copy(moonPosition);
  lighting.moon.visible = moonT !== null;
  lighting.moonLight.position.copy(lighting.moon.position);
}
