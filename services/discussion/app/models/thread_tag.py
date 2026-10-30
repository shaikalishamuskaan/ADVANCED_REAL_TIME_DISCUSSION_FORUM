from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column
import uuid
from app.core.database import Base


class ThreadTag(Base):
    __tablename__ = "thread_tag"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("thread.id", ondelete="CASCADE"),
        primary_key=True,
    )

    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tag.id", ondelete="CASCADE"),
        primary_key=True,
    )