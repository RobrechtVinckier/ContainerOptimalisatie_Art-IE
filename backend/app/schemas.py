from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ContainerColor = str


class StackContainer(BaseModel):
    id: str
    color: ContainerColor


class StackPosition(BaseModel):
    x: int
    z: int
    y: int


class SimulationMove(BaseModel):
    id: str
    color: ContainerColor
    from_: StackPosition = Field(alias="from")
    to: StackPosition
    weightedCost: float
    tStart: float = 0.0
    tEnd: float = 0.0
    durationSeconds: float = 0.0

    model_config = ConfigDict(populate_by_name=True)


class SimulationSummary(BaseModel):
    colorCount: Dict[str, int]
    total: int
    inTargetSlot: int
    placementScore: float


class AlgorithmSettings(BaseModel):
    seed: int = 1
    lam: float = 1.0
    stackTopMismatchWeight: float = 1.1
    stackRehandleWeight: float = 1.0
    stackImpurityWeight: float = 1.4
    buriedForeignWeight: float = 2.0
    groupFragmentationWeight: float = 0.9
    qualityTieEps: float = 1e-9
    operationalWeight: float = 1.0
    nightBudget: float = 28800.0
    energyWeight: float = 1.0
    energyXCost: float = 10.0
    energyYCost: float = 1.0
    energyZCost: float = 1.0
    topGroups: int = 5
    srcLimit: int = 40
    dstLimit: int = 30
    xRadius: int = 2
    yRadius: int = 1
    yAware: bool = True
    diversifyPeriod: int = 0
    diversifyRandomDsts: int = 0
    tabuIters: int = 1500
    tabuLen: int = 200
    tabuMode: Literal["cid_edge", "edge", "edge_reverse", "combined"] = "combined"
    selectionMode: Literal["best", "topk_best_nontabu", "topk_deterministic"] = "topk_best_nontabu"
    topK: int = 30
    nonImprovingPenalty: float = 1.0
    plateauIters: int = 120
    shakeEnabled: bool = True
    reactiveTabuEnabled: bool = False
    tabuLenMin: int = 200
    tabuLenMax: int = 200
    tabuReactiveWindow: int = 80
    tabuReverseRateThreshold: float = 0.12
    tabuRepeatRateThreshold: float = 0.35
    tabuStagnationRateThreshold: float = 0.04
    tabuLenAdjustStep: int = 10
    frequencyEdgeWeight: float = 0.0
    frequencyStackWeight: float = 0.0
    frequencyContainerWeight: float = 0.0
    elitePoolSize: int = 4
    eliteRestartEnabled: bool = False
    pathRelinkEnabled: bool = False
    pathRelinkSteps: int = 6
    metricsSampleEvery: int = 50


class AlgorithmSettingsPatch(BaseModel):
    seed: Optional[int] = None
    lam: Optional[float] = None
    stackTopMismatchWeight: Optional[float] = None
    stackRehandleWeight: Optional[float] = None
    stackImpurityWeight: Optional[float] = None
    buriedForeignWeight: Optional[float] = None
    groupFragmentationWeight: Optional[float] = None
    qualityTieEps: Optional[float] = None
    operationalWeight: Optional[float] = None
    nightBudget: Optional[float] = None
    energyWeight: Optional[float] = None
    energyXCost: Optional[float] = None
    energyYCost: Optional[float] = None
    energyZCost: Optional[float] = None
    topGroups: Optional[int] = None
    srcLimit: Optional[int] = None
    dstLimit: Optional[int] = None
    xRadius: Optional[int] = None
    yRadius: Optional[int] = None
    yAware: Optional[bool] = None
    diversifyPeriod: Optional[int] = None
    diversifyRandomDsts: Optional[int] = None
    tabuIters: Optional[int] = None
    tabuLen: Optional[int] = None
    tabuMode: Optional[Literal["cid_edge", "edge", "edge_reverse", "combined"]] = None
    selectionMode: Optional[Literal["best", "topk_best_nontabu", "topk_deterministic"]] = None
    topK: Optional[int] = None
    nonImprovingPenalty: Optional[float] = None
    plateauIters: Optional[int] = None
    shakeEnabled: Optional[bool] = None
    reactiveTabuEnabled: Optional[bool] = None
    tabuLenMin: Optional[int] = None
    tabuLenMax: Optional[int] = None
    tabuReactiveWindow: Optional[int] = None
    tabuReverseRateThreshold: Optional[float] = None
    tabuRepeatRateThreshold: Optional[float] = None
    tabuStagnationRateThreshold: Optional[float] = None
    tabuLenAdjustStep: Optional[int] = None
    frequencyEdgeWeight: Optional[float] = None
    frequencyStackWeight: Optional[float] = None
    frequencyContainerWeight: Optional[float] = None
    elitePoolSize: Optional[int] = None
    eliteRestartEnabled: Optional[bool] = None
    pathRelinkEnabled: Optional[bool] = None
    pathRelinkSteps: Optional[int] = None
    metricsSampleEvery: Optional[int] = None


class RandomSimulationRequest(BaseModel):
    seed: Optional[int] = None
    containerCount: int = 130
    groups: Optional[int] = Field(default=None, ge=1)
    containersPerGroup: Optional[int] = Field(default=None, ge=1)
    minContainersPerGroup: Optional[int] = Field(default=None, ge=1)
    maxContainersPerGroup: Optional[int] = Field(default=None, ge=1)


class RandomSimulationResponse(BaseModel):
    seed: int
    stacks: List[List[List[StackContainer]]]
    summary: SimulationSummary


class SolveSimulationRequest(BaseModel):
    stacks: List[List[List[StackContainer]]]
    settings: Optional[AlgorithmSettingsPatch] = None


class SolveSimulationResponse(BaseModel):
    moves: List[SimulationMove]
    solved: bool
    totalWeightedCost: float
    finalSummary: SimulationSummary
    finalStacks: List[List[List[StackContainer]]]
    nightStats: "NightCycleStats"
    dayCycle: "DayCyclePlan"


class YardConfigResponse(BaseModel):
    width: int
    length: int
    height: int
    truckLaneWidth: int
    containerCount: int
    lengthCostWeight: int
    containerMeters: Dict[str, float]


class NightCycleStats(BaseModel):
    greedyMoveCount: int
    tabuMoveCount: int
    tabuSearchMoveCount: int = 0
    tabuUniqueContainersMoved: int = 0
    tabuImmediateReversals: int = 0
    tabuRepeatedEdges: int = 0
    tabuStopReason: str = ""
    tabuRestarts: int = 0
    tabuRelinkSteps: int = 0
    dayPrepMoveCount: int = 0
    totalMoves: int
    timeUsedSeconds: float
    budgetSeconds: float
    startPlacementScore: float
    endPlacementScore: float
    lengthCostWeight: int


class DayTruckJob(BaseModel):
    jobIndex: int
    truckId: str
    company: str
    companyColor: str
    containerId: str
    containerColor: ContainerColor
    source: StackPosition
    slotIndex: int
    slotZ: int
    arrivalTime: float
    loadStartTime: float
    loadEndTime: float
    departTime: float
    craneWeightedCost: float
    laneWaitSeconds: float
    craneTaskSeconds: float


class DayCycleStats(BaseModel):
    totalJobs: int
    trucksUsed: int
    companyTrips: Dict[str, int]
    totalCraneWeightedCost: float
    totalLaneWaitSeconds: float
    makespanSeconds: float
    score: float
    lengthCostWeight: int
    dayStartSeconds: int
    dayEndSeconds: int
    dayDurationSeconds: int
    remainingContainers: int
    completedWithinWindow: bool


class DayCyclePlan(BaseModel):
    slots: int
    jobs: List[DayTruckJob]
    stats: DayCycleStats
