"""NotebookEdit 工具。

对应 TS: tools/NotebookEditTool/
编辑 Jupyter notebook (.ipynb) 文件的单个单元格。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class NotebookEditTool:
    """编辑 Jupyter notebook 单元格。"""

    @property
    def name(self) -> str:
        return "notebook_edit"

    @property
    def description(self) -> str:
        return (
            "Completely replaces the contents of a specific cell in a Jupyter notebook (.ipynb file). "
            "Use this to add, modify, or delete cells."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "notebook_path": {
                    "type": "string",
                    "description": "The absolute path to the Jupyter notebook file.",
                },
                "new_source": {
                    "type": "string",
                    "description": "The new source content for the cell.",
                },
                "cell_id": {
                    "type": "string",
                    "description": "The ID of the cell to edit. Use 'insert' mode to add a new cell.",
                },
                "cell_type": {
                    "type": "string",
                    "description": "Type of cell: 'code' or 'markdown'.",
                    "enum": ["code", "markdown"],
                },
                "edit_mode": {
                    "type": "string",
                    "description": "Type of edit: 'replace' (default), 'insert', or 'delete'.",
                    "enum": ["replace", "insert", "delete"],
                },
            },
            "required": ["notebook_path", "new_source"],
        }

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    async def call(self, **kwargs: Any) -> str:
        notebook_path = kwargs.get("notebook_path", "")
        new_source = kwargs.get("new_source", "")
        cell_id = kwargs.get("cell_id", "")
        cell_type = kwargs.get("cell_type", "code")
        edit_mode = kwargs.get("edit_mode", "replace")

        if not notebook_path:
            return "Error: notebook_path is required."

        path = Path(notebook_path)
        if not path.exists():
            return f"Error: Notebook not found: {notebook_path}"

        if path.suffix != ".ipynb":
            return f"Error: Not a notebook file: {notebook_path}"

        try:
            notebook = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return f"Error reading notebook: {e}"

        cells = notebook.get("cells", [])

        if edit_mode == "delete":
            # 删除指定单元格
            new_cells = [c for c in cells if c.get("id") != cell_id]
            if len(new_cells) == len(cells):
                return f"Error: Cell '{cell_id}' not found."
            notebook["cells"] = new_cells

        elif edit_mode == "insert":
            # 插入新单元格
            new_cell = {
                "cell_type": cell_type,
                "id": cell_id or f"cell_{len(cells)}",
                "metadata": {},
                "source": new_source,
            }
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None

            if cell_id:
                # 插入在指定 cell 之后
                insert_idx = len(cells)
                for i, c in enumerate(cells):
                    if c.get("id") == cell_id:
                        insert_idx = i + 1
                        break
                cells.insert(insert_idx, new_cell)
            else:
                cells.append(new_cell)

        else:  # replace
            # 替换单元格内容
            found = False
            for cell in cells:
                if cell.get("id") == cell_id:
                    cell["source"] = new_source
                    cell["cell_type"] = cell_type
                    if cell_type == "code" and "outputs" not in cell:
                        cell["outputs"] = []
                    found = True
                    break
            if not found and cell_id:
                return f"Error: Cell '{cell_id}' not found."

        try:
            path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
            return f"Notebook updated: {notebook_path} ({edit_mode} mode)"
        except OSError as e:
            return f"Error writing notebook: {e}"
