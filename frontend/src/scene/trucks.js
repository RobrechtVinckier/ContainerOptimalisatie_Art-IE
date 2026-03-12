import * as THREE from "three";

export function formatTruckDisplayId(truckId) {
  const digits = String(truckId || "").match(/\d+/);
  if (digits) {
    return `Truck #${Number(digits[0])}`;
  }
  return String(truckId || "Truck");
}

export function buildTrucks(group, metrics) {
  const { laneMinX, laneWidthWorld, yardMinZ, containerDim, yardLengthWorld, daySlotCount } = metrics;
  const layer = new THREE.Group();
  group.add(layer);

  return {
    layer,
    map: new Map(),
    parkingLaneX: laneMinX + laneWidthWorld * 0.3,
    passingLaneX: laneMinX + laneWidthWorld * 0.74,
    entryZ: yardMinZ - containerDim.z - 10,
    exitZ: yardMinZ + yardLengthWorld + containerDim.z + 12,
    slotZ: Array.from({ length: daySlotCount }, (_, slot) => yardMinZ + ((slot + 0.5) * yardLengthWorld) / daySlotCount),
  };
}

function createTruckIdBadge(truckId) {
  const canvas = document.createElement("canvas");
  canvas.width = 768;
  canvas.height = 256;
  const ctx = canvas.getContext("2d");
  const label = formatTruckDisplayId(truckId).toUpperCase();

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "rgba(255, 248, 232, 0.92)";
  ctx.fillRect(12, 28, canvas.width - 24, canvas.height - 56);
  ctx.strokeStyle = "rgba(30, 42, 56, 0.28)";
  ctx.lineWidth = 8;
  ctx.strokeRect(12, 28, canvas.width - 24, canvas.height - 56);
  ctx.fillStyle = "#111111";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = 'bold 96px Impact, "Arial Black", sans-serif';
  ctx.fillText(label, canvas.width / 2, canvas.height / 2 + 8);

  const texture = new THREE.CanvasTexture(canvas);
  texture.anisotropy = 8;
  const material = new THREE.MeshStandardMaterial({
    map: texture,
    transparent: true,
    roughness: 0.52,
    metalness: 0.05,
  });
  return new THREE.Mesh(new THREE.PlaneGeometry(2.7, 0.9), material);
}

function createHaulContainer(colorName, metrics, colorToThree) {
  const { laneWidthWorld, containerDim, containerVisualHeight } = metrics;
  const truckWidth = Math.min(laneWidthWorld * 0.82, containerDim.x * 0.92);
  const width = truckWidth * 0.97;
  const height = containerVisualHeight * 0.78;
  const length = containerDim.z * 0.93;
  const color = colorToThree(colorName).clone();
  const group = new THREE.Group();
  const shellMat = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.6,
    metalness: 0.12,
    emissive: color.clone().multiplyScalar(0.14),
    emissiveIntensity: 0.28,
  });
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

export function clearTruckCargo(truck) {
  const existing = truck.userData.cargo;
  if (existing) {
    truck.userData.cargoAnchor.remove(existing);
    truck.userData.cargo = null;
  }
}

export function setTruckCargo(truck, colorName, { metrics, colorToThree }) {
  clearTruckCargo(truck);
  if (!colorName) {
    return;
  }
  const cargo = createHaulContainer(colorName, metrics, colorToThree);
  cargo.castShadow = true;
  truck.userData.cargoAnchor.add(cargo);
  truck.userData.cargo = cargo;
}

export function createTruckModel({ cabColor, containerColor = null, metrics, colorToThree, truckId = "" }) {
  const { laneWidthWorld, containerDim, containerVisualHeight } = metrics;
  const group = new THREE.Group();
  const truckWidth = Math.min(laneWidthWorld * 0.82, containerDim.x * 0.92);
  const containerLength = containerDim.z * 0.93;
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

  const containerHeight = containerVisualHeight * 0.78;
  const cargoAnchor = new THREE.Group();
  cargoAnchor.position.set(0, trailerDeckTopY + containerHeight * 0.5 + 0.08, trailerCenterZ - 0.08);
  group.add(cargoAnchor);

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
  windshield.position.set(0, wheelRadius + 1.07, cabFrontZ - 0.44);
  windshield.rotation.x = -0.34;
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

  const badgeOffsetX = truckWidth * 0.51;
  const badgeY = trailerDeckTopY + 0.58;
  const badgeZ = -0.1;
  const leftBadge = createTruckIdBadge(truckId);
  leftBadge.position.set(-badgeOffsetX, badgeY, badgeZ);
  leftBadge.rotation.y = Math.PI / 2;
  group.add(leftBadge);

  const rightBadge = createTruckIdBadge(truckId);
  rightBadge.position.set(badgeOffsetX, badgeY, badgeZ);
  rightBadge.rotation.y = -Math.PI / 2;
  group.add(rightBadge);

  group.userData.cargoAnchor = cargoAnchor;
  group.userData.cargoSize = {
    width: truckWidth * 0.97,
    height: containerHeight,
    length: containerLength,
  };
  group.userData.cargo = null;
  group.userData.displayId = formatTruckDisplayId(truckId);

  if (containerColor) {
    setTruckCargo(group, containerColor, { metrics, colorToThree });
  }

  return group;
}
