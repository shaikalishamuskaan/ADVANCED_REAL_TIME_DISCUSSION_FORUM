from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cursor import decode_cursor, encode_cursor
from app.models.report import Report


async def list_reports(
    db: AsyncSession,
    *,
    report_status: str = "open",
    cursor: str | None = None,
    limit: int = 20,
) -> dict:
    if not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50.")

    if report_status not in ("open", "resolved", "dismissed"):
        raise ValueError("Invalid report status.")

    statement = (
        select(Report)
        .where(Report.status == report_status)
        .order_by(Report.created_at.desc(), Report.id.desc())
    )

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)

        statement = statement.where(
            or_(
                Report.created_at < cursor_created_at,
                (
                    (Report.created_at == cursor_created_at)
                    & (Report.id < cursor_id)
                ),
            )
        )

    result = await db.execute(statement.limit(limit + 1))
    reports = result.scalars().all()

    has_more = len(reports) > limit
    reports = reports[:limit]

    next_cursor = None

    if has_more and reports:
        last_report = reports[-1]
        next_cursor = encode_cursor(
            last_report.created_at,
            last_report.id,
        )

    return {
        "items": reports,
        "next_cursor": next_cursor,
    }