"""Hybrid MCP + FastAPI server exposing a resume parsing tool."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    genai = None


# ----------------------------
# MCP Setup
# ----------------------------
mcp = FastMCP(
    name="resume_parser",
    host="127.0.0.1",
    port=9000,
)

logger = logging.getLogger("resume_parser")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            cleaned = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), cleaned)
        logger.info("Loaded environment variables from %s", env_path)
    except Exception as exc:
        logger.warning("Failed to load .env file %s: %s", env_path, exc)


_load_env_file()


def _safe_json_loads(data: str) -> Any:
    try:
        return json.loads(data)
    except Exception:
        return None


def _find_text_payload(obj: Dict[str, Any]) -> Optional[str]:
    """Search for a likely free-form resume text payload within a dict."""
    text_keys = ("raw_text", "text", "resume", "content")
    for key in text_keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = _find_text_payload(value)
            if nested:
                return nested
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = _find_text_payload(item)
                    if nested:
                        return nested
                elif isinstance(item, str) and item.strip():
                    return item
    return None


def _ensure_shape(obj: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {
        "name": obj.get("name") or "",
        "email": obj.get("email") or "",
        "skills": obj.get("skills") or [],
        "experience": obj.get("experience") or [],
        "education": obj.get("education") or [],
        "projects": obj.get("projects") or [],
    }
    if not isinstance(output["skills"], list):
        output["skills"] = []
    else:
        output["skills"] = [str(skill) for skill in output["skills"]]

    normalized_exp: List[Dict[str, str]] = []
    for exp in output["experience"]:
        if isinstance(exp, dict):
            normalized_exp.append({
                "company": str(exp.get("company", "")),
                "role": str(exp.get("role", "")),
                "years": str(exp.get("years", "")),
            })
    output["experience"] = normalized_exp

    normalized_edu: List[Dict[str, str]] = []
    for edu in output["education"]:
        if isinstance(edu, dict):
            normalized_edu.append({
                "degree": str(edu.get("degree", "")),
                "institution": str(edu.get("institution", "")),
                "years": str(edu.get("years", "")),
            })
    output["education"] = normalized_edu

    normalized_projects: List[Dict[str, Any]] = []
    for proj in output["projects"]:
        if isinstance(proj, dict):
            tech = proj.get("tech") or []
            if not isinstance(tech, list):
                tech = []
            normalized_projects.append({
                "name": str(proj.get("name", "")),
                "description": str(proj.get("description", "")),
                "tech": [str(t) for t in tech],
            })
    output["projects"] = normalized_projects

    return output


def _call_gemini(raw_text: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model_id = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
    if not api_key or genai is None:
        return {"raw_text": raw_text}

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)

        schema_hint = {
            "name": "John Doe",
            "email": "john@example.com",
            "skills": ["Python", "AWS"],
            "experience": [{"company": "Acme", "role": "Engineer", "years": "2020-2023"}],
            "education": [{"degree": "BSc CS", "institution": "XYZ University", "years": "2016-2020"}],
            "projects": [{"name": "Cool App", "description": "Built X", "tech": ["React", "FastAPI"]}],
        }

        prompt = (
            "You are a resume extraction engine. "
            "Given resume content (as raw text or a JSON dump), "
            "produce STRICT JSON only matching this shape:\n"
            + json.dumps(schema_hint)
        )
        request = f"INPUT:\n{raw_text}\n\nOUTPUT JSON:"

        response = model.generate_content([prompt, request])
        text = getattr(response, "text", "")
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end+1]
            data = _safe_json_loads(candidate)
            if isinstance(data, dict):
                return _ensure_shape(data)
    except Exception as exc:
        logger.exception("Gemini call failed: %s", exc)

    return {"raw_text": raw_text}


# ----------------------------
# MCP Tool
# ----------------------------
@mcp.tool()
def parse_resume(raw_text: str) -> Dict[str, Any]:
    if raw_text is None:
        return {"skills": [], "experience": [], "education": [], "projects": []}

    parsed = _safe_json_loads(raw_text)
    if isinstance(parsed, dict):
        text_payload = _find_text_payload(parsed)
        if text_payload:
            return _call_gemini(text_payload)
        if {"skills", "experience", "education", "projects"}.intersection(parsed):
            return _ensure_shape(parsed)
        return _call_gemini(raw_text)

    return _call_gemini(raw_text)


# ----------------------------
# FastAPI Wrapper
# ----------------------------
app = FastAPI()

class ResumeInput(BaseModel):
    raw_text: str

@app.post("/parse_resume")
async def parse_resume_api(data: ResumeInput):
    """REST wrapper around the MCP tool"""
    return parse_resume(data.raw_text)


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    mode = os.getenv("MODE", "rest")  # switch mode easily
    if mode == "mcp":
        mcp.run("streamable-http")   # MCP mode (for Coral/Claude)
    else:
        uvicorn.run(app, host="127.0.0.1", port=9000)  # REST mode (for curl/frontend)
