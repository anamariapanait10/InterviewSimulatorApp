from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RAW_PROBLEM_PATH = Path(__file__).resolve().parent / "data" / "problem_catalog_rag" / "raw"


def _function_starter(
    name: str,
    params: str,
    py_params: str,
    java_signature: str,
    csharp_signature: str,
) -> dict[str, str]:
    return {
        "typescript": (
            f"export function {name}({params}): unknown {{\n"
            "  // Explain your thinking as you code.\n"
            "  return null\n"
            "}\n"
        ),
        "javascript": (
            f"export function {name}({params}) {{\n"
            "  // Explain your thinking as you code.\n"
            "  return null\n"
            "}\n"
        ),
        "python": (
            f"def {name}({py_params}):\n"
            "    # Explain your thinking as you code.\n"
            "    return None\n"
        ),
        "java": (
            "class Solution {\n"
            f"    public {java_signature} {{\n"
            "        // Explain your thinking as you code.\n"
            "        return null;\n"
            "    }\n"
            "}\n"
        ),
        "csharp": (
            "public class Solution\n"
            "{\n"
            f"    public {csharp_signature}\n"
            "    {\n"
            "        // Explain your thinking as you code.\n"
            "        return null;\n"
            "    }\n"
            "}\n"
        ),
    }


def _class_starter(spec: dict[str, Any]) -> dict[str, str]:
    return {
        "typescript": spec["typescript"],
        "javascript": spec["javascript"],
        "python": spec["python"],
        "java": spec["java"],
        "csharp": spec["csharp"],
    }


def _build_starter_code(problem: dict[str, Any]) -> dict[str, str]:
    starter_template = problem.pop("starter_template", None)
    if not isinstance(starter_template, dict):
        starter_code = problem.get("starter_code")
        if isinstance(starter_code, dict):
            return {str(key): str(value) for key, value in starter_code.items()}
        raise ValueError(f"Problem {problem.get('id')!r} is missing starter template information.")

    starter_kind = str(starter_template.get("kind") or "").strip().lower()
    if starter_kind == "function":
        return _function_starter(
            str(starter_template["name"]),
            str(starter_template["typescript_params"]),
            str(starter_template["python_params"]),
            str(starter_template["java_signature"]),
            str(starter_template["csharp_signature"]),
        )
    if starter_kind == "class":
        return _class_starter(starter_template)
    raise ValueError(f"Unsupported starter template kind {starter_kind!r} for problem {problem.get('id')!r}.")


def load_coding_problems() -> list[dict[str, Any]]:
    if not RAW_PROBLEM_PATH.exists():
        return []

    problems: list[dict[str, Any]] = []
    for path in sorted(RAW_PROBLEM_PATH.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, list):
            raise ValueError(f"Problem catalog file {path} must contain a JSON array.")

        for raw_problem in payload:
            if not isinstance(raw_problem, dict):
                raise ValueError(f"Invalid problem entry in {path}: expected object.")
            problem = dict(raw_problem)
            problem["starter_code"] = _build_starter_code(problem)
            problems.append(problem)

    return problems


DEFAULT_CODING_PROBLEMS: list[dict[str, Any]] = load_coding_problems()
