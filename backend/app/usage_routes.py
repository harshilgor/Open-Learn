"""Usage summary endpoint. Aggregates the current owner's Forma usage only."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from .material_routes import material_owner
from .usage_service import analytics, fetch_completed_rows, fetch_session_titles, summarize
from .usage_estimates import build_usage_estimate_router


class UsageTotals(BaseModel):
    totalTokens: int
    promptTokens: int
    completionTokens: int
    generations: int
    exactGenerations: int
    estimatedGenerations: int
    providerCost: float
    costIsExact: bool


class UsageDay(BaseModel):
    date: str
    totalTokens: int
    generations: int


class UsageModelEntry(BaseModel):
    model: str
    totalTokens: int
    generations: int


class UsageProviderEntry(BaseModel):
    provider: str
    totalTokens: int
    generations: int


class UsageSummary(BaseModel):
    range: str
    totals: UsageTotals
    byDay: list[UsageDay] = Field(default_factory=list)
    byModel: list[UsageModelEntry] = Field(default_factory=list)
    byProvider: list[UsageProviderEntry] = Field(default_factory=list)


class AnalyticsSeries(BaseModel):
    key: str
    totalTokens: int
    generations: int
    sharePct: float
    points: list[int] = Field(default_factory=list)
    genPoints: list[int] = Field(default_factory=list)


class AnalyticsDay(BaseModel):
    date: str
    totalTokens: int
    generations: int
    promptTokens: int
    completionTokens: int
    cost: float


class AnalyticsSessionModel(BaseModel):
    model: str
    totalTokens: int
    generations: int


class AnalyticsSession(BaseModel):
    sessionId: str
    title: str
    totalTokens: int
    generations: int
    providerCost: float
    costIsExact: bool
    lastActive: str | None = None
    byModel: list[AnalyticsSessionModel] = Field(default_factory=list)


class UsageAnalytics(BaseModel):
    range: str
    dimension: str
    totals: UsageTotals
    days: list[AnalyticsDay] = Field(default_factory=list)
    series: list[AnalyticsSeries] = Field(default_factory=list)
    topSessions: list[AnalyticsSession] = Field(default_factory=list)


class SingleOperationEstimate(BaseModel):
    component: Literal['model','stt','tts','voice','browser']
    inputTokens: int = Field(default=0,ge=0,le=48000)
    outputTokens: int = Field(default=2000,ge=0,le=2000)
    milliseconds: int = Field(default=0,ge=0,le=1800000)
    characters: int = Field(default=0,ge=0,le=2400)


def build_usage_router(store_provider) -> APIRouter:
    router = APIRouter(prefix="/v1")

    # Task-level estimates are additive. Keep /usage/estimate below unchanged
    # for clients that still send a single bounded model request.
    router.include_router(build_usage_estimate_router(store_provider))

    @router.get('/usage/allowance')
    def allowance(response: Response, owner: str = Depends(material_owner)):
        from .usage.ledger import Ledger
        response.headers['Cache-Control']='private, no-store'
        return Ledger(store_provider()).allowance(owner)

    @router.get('/usage/activity')
    def activity(response: Response, cursor: str | None = Query(default=None,max_length=512), limit: int = Query(default=30,ge=1,le=100), includeComponents: bool = True, owner: str = Depends(material_owner)):
        from .usage.ledger import Ledger
        response.headers['Cache-Control']='private, no-store'
        return Ledger(store_provider()).activity(owner,cursor,limit,includeComponents)

    @router.post('/usage/estimate')
    def estimate(body: SingleOperationEstimate, response: Response, owner: str = Depends(material_owner)):
        from .usage.ledger import Ledger
        from .usage.pricing import price
        response.headers['Cache-Control']='private, no-store'
        ledger=Ledger(store_provider())
        snapshot=ledger.allowance(owner)
        if body.component!='model':
            return {'supported':False,'reasonCode':'provider_rate_and_bounded_route_required',
                    'rateVersion':snapshot['rateVersion'],'availability':snapshot['availability']}
        amount=price(body.component,{'input_tokens':body.inputTokens,'output_tokens':body.outputTokens,'milliseconds':body.milliseconds,'characters':body.characters})
        return {'maximumCreditsMicro':amount,'percentage':amount*100/snapshot['grantedMicrocredits'],'rateVersion':snapshot['rateVersion'],'expiresAt':snapshot['serverTime']+60,'supported':True,'availability':snapshot['availability']}

    @router.get("/usage/summary", response_model=UsageSummary)
    def summary(
        range: Literal["7d", "30d", "all"] = Query(default="all"),
        sessionId: str | None = Query(default=None, max_length=160),
        owner: str = Depends(material_owner),
    ) -> dict:
        rows = fetch_completed_rows(store_provider(), owner, session_id=sessionId)
        return summarize(rows, range_key=range)

    @router.get("/usage/analytics", response_model=UsageAnalytics)
    def analytics_view(
        range: Literal["7d", "30d"] = Query(default="7d"),
        dimension: Literal["mode", "model", "provider", "course"] = Query(default="mode"),
        limit: int = Query(default=5, ge=1, le=20),
        owner: str = Depends(material_owner),
    ) -> dict:
        store = store_provider()
        rows = fetch_completed_rows(store, owner)
        titles = fetch_session_titles(store, owner)
        return analytics(rows, range_key=range, dimension=dimension, session_titles=titles, session_limit=limit)

    return router
