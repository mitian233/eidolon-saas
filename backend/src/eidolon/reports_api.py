"""Submit a public notice, or review and handle it as an admin."""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from eidolon.admin_api import Admin
from eidolon.assembly import Backend
from eidolon.reports import Report, ReportCategory, ReportPage, ReportRateLimited, ReportStatus

# JSON can represent one Unicode code point with up to 12 ASCII bytes.
MAX_REPORT_REQUEST_BYTES = 80_000


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ReportCategory
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048, pattern=r"^[^\x00]*$")]
    details: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, pattern=r"^[^\x00]*$")]
    contact: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^\x00]*$")] | None = None


class DispositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReportStatus | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000, pattern=r"^[^\x00]*$")] | None = None


def add_report_routes(app: FastAPI, backend: Backend) -> None:
    reports = backend.reports

    @app.post("/api/reports", status_code=201)
    async def submit(body: ReportInput, request: Request) -> dict[str, str]:
        source = request.client.host if request.client else "unknown"
        try:
            report_id = await reports.submit(source, body.category, body.target, body.details, body.contact)
        except ReportRateLimited as refused:
            raise HTTPException(
                429, "此网络提交的举报过多",
                headers={"Retry-After": str(refused.retry_after)},
            ) from None
        return {"id": report_id}

    @app.get("/api/admin/reports")
    async def list_reports(
        _: Admin,
        status: ReportStatus | None = None,
        offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> ReportPage:
        return await reports.list(status, offset, limit)

    @app.patch("/api/admin/reports/{report_id}")
    async def update_report(report_id: str, body: DispositionInput, _: Admin) -> Report:
        replace_note = "note" in body.model_fields_set
        if body.status is None and not replace_note:
            raise HTTPException(422, "请填写处理状态或备注")
        report = await reports.update(report_id, status=body.status, note=body.note, replace_note=replace_note)
        if report is None:
            raise HTTPException(404, "没有这条举报")
        return report
