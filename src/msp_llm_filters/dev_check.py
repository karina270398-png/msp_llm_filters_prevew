import asyncio
from typing import Any, Dict

from .server import ping, search_cases


async def main() -> None:
    print("-- ping --")
    res_ping: Dict[str, Any] = await ping()
    print(res_ping)

    print("\n-- search_cases (mock, empty filters) --")
    res_search: Dict[str, Any] = await search_cases({"filters": {}, "page": 1, "page_size": 3})
    # ограничим вывод
    items = res_search.get("items", [])
    print({
        "page": res_search.get("page"),
        "page_size": res_search.get("page_size"),
        "total": res_search.get("total"),
        "items_preview": [i.get("id") for i in items[:3]],
    })


if __name__ == "__main__":
    asyncio.run(main())
