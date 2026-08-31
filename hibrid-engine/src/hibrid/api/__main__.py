from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("hibrid.api.app:app", reload=True)


if __name__ == "__main__":
    main()
