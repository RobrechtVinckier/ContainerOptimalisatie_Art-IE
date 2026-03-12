import * as THREE from "three";

const SKY_NIGHT = new THREE.Color("#2757a4");
const SKY_DAWN = new THREE.Color("#f5a652");
const SKY_DAY = new THREE.Color("#f3cb72");
const FOG_NIGHT = new THREE.Color("#5775a6");
const FOG_DAY = new THREE.Color("#efd596");
const AMBIENT_NIGHT = new THREE.Color("#eff4fb");
const AMBIENT_DAY = new THREE.Color("#fff1d2");
const HEMI_SKY_NIGHT = new THREE.Color("#acc7ff");
const HEMI_SKY_DAY = new THREE.Color("#ffe0a1");
const HEMI_GROUND_NIGHT = new THREE.Color("#728094");
const HEMI_GROUND_DAY = new THREE.Color("#aa8d5b");
const FILL_NIGHT = new THREE.Color("#eef4fb");
const FILL_DAY = new THREE.Color("#fff7e9");
const SUN_LIGHT_COLOR = new THREE.Color("#ffe2ad");
const MOON_LIGHT_COLOR = new THREE.Color("#edf4ff");
const CELESTIAL_RADIUS_X = 88;
const CELESTIAL_RADIUS_Y = 74;
const CELESTIAL_HORIZON_Y = 9;
const CELESTIAL_SUN_START_Z = 34;
const CELESTIAL_SUN_END_Z = -26;
const CELESTIAL_MOON_START_Z = 28;
const CELESTIAL_MOON_END_Z = -32;
const SUNRISE_START = 5 * 3600;
const DAY_START = 6 * 3600;
const SUNSET_START = 21 * 3600;
const NIGHT_START = 22 * 3600;

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

function skyPhaseProfile(timeSeconds) {
  if (timeSeconds < SUNRISE_START) {
    return { daylightBlend: 0, twilightBlend: 0, nightBlend: 1 };
  }
  if (timeSeconds < DAY_START) {
    const t = smoothstep(SUNRISE_START, DAY_START, timeSeconds);
    return {
      daylightBlend: t,
      twilightBlend: Math.sin(t * Math.PI),
      nightBlend: 1 - t,
    };
  }
  if (timeSeconds < SUNSET_START) {
    return { daylightBlend: 1, twilightBlend: 0, nightBlend: 0 };
  }
  if (timeSeconds < NIGHT_START) {
    const t = smoothstep(SUNSET_START, NIGHT_START, timeSeconds);
    return {
      daylightBlend: 1 - t,
      twilightBlend: Math.sin(t * Math.PI),
      nightBlend: t,
    };
  }
  return { daylightBlend: 0, twilightBlend: 0, nightBlend: 1 };
}

function createCanvasTexture(size, draw) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  draw(ctx, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function createSunTexture() {
  return createCanvasTexture(256, (ctx, size) => {
    const center = size / 2;
    const rayCount = 12;
    const innerRadius = 74;
    const outerRadius = 108;
    const raySpread = Math.PI / rayCount * 0.45;

    ctx.clearRect(0, 0, size, size);
    ctx.save();
    ctx.translate(center, center);

    ctx.fillStyle = "rgba(255, 140, 22, 0.92)";
    for (let index = 0; index < rayCount; index += 1) {
      const angle = (index / rayCount) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(Math.cos(angle - raySpread) * innerRadius, Math.sin(angle - raySpread) * innerRadius);
      ctx.lineTo(Math.cos(angle) * outerRadius, Math.sin(angle) * outerRadius);
      ctx.lineTo(Math.cos(angle + raySpread) * innerRadius, Math.sin(angle + raySpread) * innerRadius);
      ctx.closePath();
      ctx.fill();
    }

    const glow = ctx.createRadialGradient(0, 0, 16, 0, 0, 118);
    glow.addColorStop(0, "rgba(255, 241, 180, 0.9)");
    glow.addColorStop(0.42, "rgba(255, 188, 76, 0.82)");
    glow.addColorStop(0.78, "rgba(255, 140, 22, 0.22)");
    glow.addColorStop(1, "rgba(255, 140, 22, 0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(0, 0, 118, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#ff9120";
    ctx.beginPath();
    ctx.arc(0, 0, 56, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#ffd56e";
    ctx.beginPath();
    ctx.arc(-6, -6, 30, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  });
}

function createMoonTexture() {
  return createCanvasTexture(256, (ctx, size) => {
    const center = size / 2;
    ctx.clearRect(0, 0, size, size);
    ctx.save();
    ctx.translate(center, center);

    const glow = ctx.createRadialGradient(0, 0, 18, 0, 0, 110);
    glow.addColorStop(0, "rgba(255, 255, 255, 0.95)");
    glow.addColorStop(0.45, "rgba(239, 246, 255, 0.72)");
    glow.addColorStop(0.8, "rgba(209, 226, 255, 0.18)");
    glow.addColorStop(1, "rgba(209, 226, 255, 0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(0, 0, 110, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(0, 0, 44, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "rgba(232, 239, 255, 0.95)";
    ctx.beginPath();
    ctx.arc(-8, -8, 18, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  });
}

function createCelestialSprite(texture, size) {
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
    }),
  );
  sprite.scale.set(size, size, 1);
  return sprite;
}

export function createLighting(scene) {
  const ambient = new THREE.AmbientLight(AMBIENT_NIGHT.clone(), 0.8);
  scene.add(ambient);

  const hemiLight = new THREE.HemisphereLight(HEMI_SKY_NIGHT.clone(), HEMI_GROUND_NIGHT.clone(), 0.56);
  scene.add(hemiLight);

  const sunLight = new THREE.DirectionalLight(SUN_LIGHT_COLOR.clone(), 1.08);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  sunLight.shadow.camera.near = 1;
  sunLight.shadow.camera.far = 220;
  sunLight.shadow.camera.left = -65;
  sunLight.shadow.camera.right = 65;
  sunLight.shadow.camera.top = 65;
  sunLight.shadow.camera.bottom = -65;
  scene.add(sunLight);

  const fillLight = new THREE.DirectionalLight(FILL_NIGHT.clone(), 0.74);
  fillLight.position.set(-30, 26, -22);
  scene.add(fillLight);

  const moonLight = new THREE.DirectionalLight(MOON_LIGHT_COLOR.clone(), 0.24);
  scene.add(moonLight);

  const sun = createCelestialSprite(createSunTexture(), 18);
  scene.add(sun);

  const moon = createCelestialSprite(createMoonTexture(), 14);
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
  const sunElevation = sunT === null ? 0 : Math.sin(sunT * Math.PI);
  const { daylightBlend, twilightBlend, nightBlend } = skyPhaseProfile(sceneTime);

  const sky = SKY_NIGHT.clone().lerp(SKY_DAWN, twilightBlend).lerp(SKY_DAY, daylightBlend);
  lighting.scene.background.copy(sky);
  if (lighting.scene.fog) {
    lighting.scene.fog.color.copy(FOG_NIGHT.clone().lerp(FOG_DAY, daylightBlend * 0.9 + twilightBlend * 0.35));
  }

  lighting.ambient.color.copy(AMBIENT_NIGHT).lerp(AMBIENT_DAY, daylightBlend * 0.86 + twilightBlend * 0.16);
  lighting.hemiLight.color.copy(HEMI_SKY_NIGHT).lerp(HEMI_SKY_DAY, daylightBlend * 0.88 + twilightBlend * 0.12);
  lighting.hemiLight.groundColor.copy(HEMI_GROUND_NIGHT).lerp(HEMI_GROUND_DAY, daylightBlend * 0.72 + twilightBlend * 0.16);
  lighting.fillLight.color.copy(FILL_NIGHT).lerp(FILL_DAY, daylightBlend * 0.72 + twilightBlend * 0.14);
  lighting.sunLight.color.copy(SUN_LIGHT_COLOR);
  lighting.moonLight.color.copy(MOON_LIGHT_COLOR);

  lighting.ambient.intensity = 0.5 + daylightBlend * 0.28 + twilightBlend * 0.06;
  lighting.hemiLight.intensity = 0.4 + daylightBlend * 0.3 + twilightBlend * 0.06;
  lighting.sunLight.intensity = sunT === null ? 0 : 0.08 + sunElevation * 1.12;
  lighting.fillLight.intensity = 0.28 + daylightBlend * 0.24 + twilightBlend * 0.04;
  lighting.moonLight.intensity = 0.14 + nightBlend * 0.22 + twilightBlend * 0.05;

  const sunPosition = celestialArcPosition(sunT ?? 0, CELESTIAL_SUN_START_Z, CELESTIAL_SUN_END_Z);
  lighting.sun.position.copy(sunPosition);
  lighting.sun.visible = sunT !== null;
  lighting.sunLight.position.copy(lighting.sun.position);
  lighting.fillLight.position.set(-lighting.sun.position.x * 0.28, 28 + daylightBlend * 6, 24);

  const moonPosition = celestialArcPosition(moonT ?? 0, CELESTIAL_MOON_START_Z, CELESTIAL_MOON_END_Z);
  lighting.moon.position.copy(moonPosition);
  lighting.moon.visible = moonT !== null;
  lighting.moonLight.position.copy(lighting.moon.position);
}
