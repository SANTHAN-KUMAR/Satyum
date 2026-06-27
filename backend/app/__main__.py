"""Run the Satyum API directly: ``python -m app`` (from ``backend/``).

Equivalent production entry: ``uvicorn app.main:app`` (add ``--reload`` in development).
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
