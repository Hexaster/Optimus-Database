from typing import Any, Literal

from pydantic import BaseModel


class NormalizedData(BaseModel):
    """入库前的交接格式：一行一条记录。"""

    table: Literal[
        "patent",
        "binder",
        "car",
        "manufacturing",
        "evidence",
        "abc_combination_db1",
    ]
    data: dict[str, Any]
