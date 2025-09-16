"""FastMCP server exposing a resume parsing tool."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    genai = None


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
        logger.debug("No .env file found at %s", env_path)
        return

    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            cleaned = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, cleaned)
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
    # Ensure required keys exist with correct types
    output: Dict[str, Any] = {
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
        if not isinstance(exp, dict):
            continue
        normalized_exp.append(
            {
                "company": str(exp.get("company", "")),
                "role": str(exp.get("role", "")),
                "years": str(exp.get("years", "")),
            }
        )
    output["experience"] = normalized_exp

    normalized_edu: List[Dict[str, str]] = []
    for edu in output["education"]:
        if not isinstance(edu, dict):
            continue
        normalized_edu.append(
            {
                "degree": str(edu.get("degree", "")),
                "institution": str(edu.get("institution", "")),
                "years": str(edu.get("years", "")),
            }
        )
    output["education"] = normalized_edu

    normalized_projects: List[Dict[str, Any]] = []
    for proj in output["projects"]:
        if not isinstance(proj, dict):
            continue
        tech = proj.get("tech") or []
        if not isinstance(tech, list):
            tech = []
        normalized_projects.append(
            {
                "name": str(proj.get("name", "")),
                "description": str(proj.get("description", "")),
                "tech": [str(t) for t in tech],
            }
        )
    output["projects"] = normalized_projects

    return output


def _call_gemini(raw_text: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model_id = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")  # Gemini 2.x model
    if not api_key:
        logger.info("Gemini unavailable: missing GEMINI_API_KEY/GOOGLE_API_KEY")
        return {"missing": "gemini"}
    if genai is None:
        logger.info("Gemini unavailable: google-generativeai package not installed")
        return {"missing": "gemini"}

    try:
        logger.info("Gemini available: using model %s", model_id)
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)

        schema_hint = {
            "skills": ["Python", "AWS", "Docker"],
            "experience": [
                {
                    "company": "Acme Inc",
                    "role": "Software Engineer",
                    "years": "2020-2023",
                }
            ],
            "education": [
                {
                    "degree": "BSc Computer Science",
                    "institution": "XYZ University",
                    "years": "2016-2020",
                }
            ],
            "projects": [
                {
                    "name": "Cool App",
                    "description": "Built X",
                    "tech": ["React", "FastAPI"],
                }
            ],
        }

        prompt = (
            "You are a resume extraction engine. Given resume content (as raw text or a JSON dump), "
            "produce STRICT JSON only (no prose) matching this Python-like example shape: \n"
            + json.dumps(schema_hint)
            + "\nRules: return a minimal, accurate summary; omit fields if unknown by leaving empty strings; keep skills concise."
        )

        request = f"INPUT:\n{raw_text}\n\nOUTPUT JSON:"
        response = model.generate_content([prompt, request])
        text = response.text if hasattr(response, "text") else ""

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            data = _safe_json_loads(candidate)
            if isinstance(data, dict):
                logger.info("Gemini parse succeeded")
                return _ensure_shape(data)

        logger.info("Gemini response missing JSON payload; falling back")
    except Exception as exc:  # pragma: no cover - network/LLM issues
        logger.exception("Gemini call failed: %s", exc)

    return {"missing": "gemini"}


@mcp.tool()
def parse_resume(raw_text: str) -> Dict[str, Any]:
    """Parse resume JSON/text into structured skills, experience, education, and projects."""
    if raw_text is None:
        return {"skills": [], "experience": [], "education": [], "projects": []}

    parsed = _safe_json_loads(raw_text)
    if isinstance(parsed, dict):
        text_payload = _find_text_payload(parsed)
        if text_payload:
            return _call_gemini(text_payload)
        structured_keys = {"skills", "experience", "education", "projects"}
        if structured_keys.intersection(parsed):
            return _ensure_shape(parsed)
        return _call_gemini(raw_text)

    return _call_gemini(raw_text)


if __name__ == "__main__":
    mcp.run("streamable-http")
