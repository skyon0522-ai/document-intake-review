"""Seed an installed user's fresh workspace without making review decisions."""

from pathlib import Path

from intake_review import IntakeError, Store

SAMPLE = """# Service handbook

The operations team reviews changes before the handbook enters the knowledge system.

## Response targets

| Priority | Owner | Hours |
| --- | --- | --- |
| High | Operations | 4 |
| Normal | Service desk | 24 |

- Record the source document.
- Review this version before approval.

The sample contains no customer data.
"""


def seed(workspace: Path) -> dict:
    if workspace.exists() or workspace.is_symlink():
        raise IntakeError("Demo requires a new workspace; existing files are retained.")
    store = Store(workspace)
    try:
        with (store.sources / "handbook.md").open(
            "x", encoding="utf-8", newline="\n"
        ) as output:
            output.write(SAMPLE)
        result = store.intake("handbook.md")
        return {"workspace": str(store.workspace), **result}
    finally:
        store.close()
