from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ContainerColor = Literal["red", "green", "blue"]


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

    class Config:
        populate_by_name = True


class SimulationSummary(BaseModel):
    colorCount: Dict[ContainerColor, int]
    total: int
    inTargetSlot: int
    placementScore: float


class AlgorithmSettings(BaseModel):
    seed: int = 1
    lam: float = 1.0
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
    tabuIters: int = 1500
    tabuLen: int = 200
    tabuMode: Literal["cid_edge", "edge", "edge_reverse", "combined"] = "combined"
    selectionMode: Literal["best", "topk_best_nontabu", "topk_deterministic"] = "topk_best_nontabu"
    topK: int = 30
    nonImprovingPenalty: float = 1.0
    plateauIters: int = 120
    shakeEnabled: bool = True


class AlgorithmSettingsPatch(BaseModel):
    seed: Optional[int] = None
    lam: Optional[float] = None
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
    tabuIters: Optional[int] = None
    tabuLen: Optional[int] = None
    tabuMode: Optional[Literal["cid_edge", "edge", "edge_reverse", "combined"]] = None
    selectionMode: Optional[Literal["best", "topk_best_nontabu", "topk_deterministic"]] = None
    topK: Optional[int] = None
    nonImprovingPenalty: Optional[float] = None
    plateauIters: Optional[int] = None
    shakeEnabled: Optional[bool] = None


class RandomSimulationRequest(BaseModel):
    seed: Optional[int] = None
    containerCount: int = 130


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


class YardConfigResponse(BaseModel):
    width: int
    length: int
    height: int
    truckLaneWidth: int
    containerCount: int
    lengthCostWeight: int
    containerMeters: Dict[str, float]
