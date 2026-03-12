import * as THREE from "three";

export function getRailX({ containerMinX, laneMinX, laneWidthWorld }) {
  return {
    left: containerMinX - 1.3,
    right: laneMinX + laneWidthWorld + 1.3,
  };
}

function stackZToWorld(z, { yardMinZ, step }) {
  return yardMinZ + (z + 0.5) * step.z;
}

export function buildGround(group, metrics) {
  const {
    totalWidthWorld,
    yardLengthWorld,
    yardWidthWorld,
    laneWidthWorld,
    laneMinX,
    yardMinZ,
    daySlotCount,
    yardConfig,
    step,
    containerMinX,
  } = metrics;
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(totalWidthWorld + 22, yardLengthWorld + 30),
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
    new THREE.PlaneGeometry(yardWidthWorld, yardLengthWorld),
    new THREE.MeshStandardMaterial({
      color: "#8da8be",
      roughness: 0.8,
      metalness: 0.04,
    }),
  );
  yardPad.rotation.x = -Math.PI / 2;
  yardPad.position.set(containerMinX + yardWidthWorld / 2, 0.01, 0);
  yardPad.receiveShadow = true;
  group.add(yardPad);

  const lanePad = new THREE.Mesh(
    new THREE.PlaneGeometry(laneWidthWorld, yardLengthWorld),
    new THREE.MeshStandardMaterial({
      color: "#a3afbb",
      roughness: 0.87,
      metalness: 0.08,
    }),
  );
  lanePad.rotation.x = -Math.PI / 2;
  lanePad.position.set(laneMinX + laneWidthWorld / 2, 0.015, 0);
  lanePad.receiveShadow = true;
  group.add(lanePad);

  const stripeMat = new THREE.MeshStandardMaterial({ color: "#ffd248", roughness: 0.55 });
  const passingLaneX = laneMinX + laneWidthWorld * 0.74;
  const parkingLaneX = laneMinX + laneWidthWorld * 0.3;
  const laneDividerX = (passingLaneX + parkingLaneX) / 2;

  const divider = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.03, yardLengthWorld), stripeMat);
  divider.position.set(laneDividerX, 0.032, 0);
  group.add(divider);

  const arrowCount = Math.floor(yardLengthWorld / 8);
  for (let i = 0; i < arrowCount; i += 1) {
    const z = yardMinZ + 3 + i * 8;
    const shaft = new THREE.Mesh(new THREE.BoxGeometry(laneWidthWorld * 0.08, 0.05, 2.3), stripeMat);
    shaft.position.set(passingLaneX, 0.035, z);
    group.add(shaft);

    for (const direction of [-1, 1]) {
      const chevron = new THREE.Mesh(new THREE.BoxGeometry(laneWidthWorld * 0.05, 0.03, 0.9), stripeMat);
      chevron.rotation.y = direction * 0.72;
      chevron.position.set(passingLaneX + direction * laneWidthWorld * 0.045, 0.034, z + 1.28);
      group.add(chevron);
    }
  }

  const slotMarkMat = new THREE.MeshStandardMaterial({ color: "#fff2c4", roughness: 0.65 });
  const slotLength = yardLengthWorld / daySlotCount;
  for (let i = 0; i <= daySlotCount; i += 1) {
    const z = yardMinZ + i * slotLength;
    const line = new THREE.Mesh(new THREE.BoxGeometry(laneWidthWorld * 0.46, 0.03, 0.06), slotMarkMat);
    line.position.set(parkingLaneX, 0.033, z);
    group.add(line);
  }

  const gridMaterial = new THREE.LineBasicMaterial({ color: "#6e8ca8" });
  const gridPoints = [];

  for (let ix = 0; ix <= yardConfig.width; ix += 1) {
    const x = containerMinX + ix * step.x;
    gridPoints.push(new THREE.Vector3(x, 0.06, yardMinZ));
    gridPoints.push(new THREE.Vector3(x, 0.06, yardMinZ + yardLengthWorld));
  }

  for (let iz = 0; iz <= yardConfig.length; iz += 1) {
    const z = yardMinZ + iz * step.z;
    gridPoints.push(new THREE.Vector3(containerMinX, 0.06, z));
    gridPoints.push(new THREE.Vector3(containerMinX + yardWidthWorld, 0.06, z));
  }

  const gridGeometry = new THREE.BufferGeometry().setFromPoints(gridPoints);
  const gridLines = new THREE.LineSegments(gridGeometry, gridMaterial);
  group.add(gridLines);

  const railMaterial = new THREE.MeshStandardMaterial({ color: "#5b6771", metalness: 0.35, roughness: 0.52 });
  const rails = getRailX(metrics);
  for (const x of [rails.left, rails.right]) {
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.33, 0.2, yardLengthWorld + 8), railMaterial);
    rail.position.set(x, 0.1, 0);
    rail.receiveShadow = true;
    group.add(rail);
  }
}

export function buildCrane(group, metrics) {
  const { yardConfig, step, containerDim } = metrics;
  const rails = getRailX(metrics);
  const centerX = (rails.left + rails.right) / 2;
  const span = rails.right - rails.left;
  const legDepth = step.z * 0.72;
  const legHeight = yardConfig.height * step.y + 6.1;
  const beamY = legHeight;

  const craneGroup = new THREE.Group();
  craneGroup.position.set(centerX, 0, stackZToWorld(0, metrics));
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
    new THREE.BoxGeometry(containerDim.x * 1.05, 0.38, containerDim.z * 0.92),
    new THREE.MeshStandardMaterial({ color: "#ffbb1f", roughness: 0.45, metalness: 0.28 }),
  );
  spreaderBody.castShadow = true;
  spreader.add(spreaderBody);

  const ropeOffsets = [
    new THREE.Vector3(-0.75, 0, -containerDim.z * 0.35),
    new THREE.Vector3(0.75, 0, -containerDim.z * 0.35),
    new THREE.Vector3(-0.75, 0, containerDim.z * 0.35),
    new THREE.Vector3(0.75, 0, containerDim.z * 0.35),
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
