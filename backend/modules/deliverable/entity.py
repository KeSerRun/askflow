"""modules.deliverable.entity —— 交付物 ORM 领域模型。"""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class Deliverable(Base):
    """一份已生成的交付物（对象存储里的 PDF）。

    - ``id``：uuid hex（对象键 ``deliverables/{user_id}/{session_id}/{id}.pdf``）；
    - ``template``/``title``：生成时使用的模板与标题；
    - ``object_key``/``size``：对象存储定位与字节数。
    """

    __tablename__ = "deliverables"

    id = mapped_column(String(32), primary_key=True)
    user_id = mapped_column(Integer, nullable=False)
    session_id = mapped_column(String(64), nullable=False)
    template = mapped_column(String(64), nullable=False)
    title = mapped_column(String(200), nullable=False)
    object_key = mapped_column(String(512), nullable=False)
    size = mapped_column(Integer, default=0, nullable=False)
    created_at = mapped_column(String(40), nullable=False)
