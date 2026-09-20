from abc import ABC, abstractmethod
import json
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class RawQuestionSegment(BaseModel):
    raw_text: str
    source_pages: List[int]
    question_hint: Optional[str] = None
    extraction_confidence: float = 0.90


class StructuredQuestionOutput(BaseModel):
    question_number: Optional[str] = None
    question_text: str
    question_type: str # 'mcq' | 'true_false' | 'short_answer' | 'unknown'
    options: Optional[List[Dict[str, str]]] = None # [{"label": "A", "text": "..."}]
    llm_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    validation_error: Optional[str] = None


class AIProvider(ABC):
    @abstractmethod
    def structure_segment(self, segment: RawQuestionSegment) -> StructuredQuestionOutput:
        """Structure raw question segment into structured question object."""
        pass


class MockAIProvider(AIProvider):
    """
    Deterministic rule-based NLP arbiter for offline testing, CI/CD, and zero-API-key execution.
    Acts as the LLM arbiter per PRD §4 Stage 4, extracting options and question boundaries.
    """
    def structure_segment(self, segment: RawQuestionSegment) -> StructuredQuestionOutput:
        text = segment.raw_text.strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        if not lines:
            return StructuredQuestionOutput(
                question_number=None,
                question_text="",
                question_type="unknown",
                llm_confidence=0.10,
                validation_error="Empty text segment"
            )

        # Trigger simulated LLM retry failure for testing resilience per PRD §4
        if "[MALFORMED_LLM_OUTPUT]" in text:
            return StructuredQuestionOutput(
                question_number=segment.question_hint,
                question_text=text,
                question_type="unknown",
                llm_confidence=0.20,
                validation_error="LLM JSON schema validation failed after retry"
            )

        # Detect question number and main prompt
        first_line = lines[0]
        q_num = segment.question_hint
        prompt_lines = []

        q_num_match = re.match(r"^(?:Question\s*|Q\s*)?\(?(\d+[a-zA-Z]?)\)?[\.:\)\s]\s*(.*)$", first_line, re.IGNORECASE)
        if q_num_match:
            q_num = q_num_match.group(1)
            remaining_prompt = q_num_match.group(2).strip()
            if remaining_prompt:
                prompt_lines.append(remaining_prompt)
        else:
            prompt_lines.append(first_line)

        # Collect options and remaining prompt
        options: List[Dict[str, str]] = []
        option_pattern = re.compile(r"^[(\[]?([A-Da-d1-4])[)\].:\s]\s*(.*)$")

        for line in lines[1:]:
            opt_match = option_pattern.match(line)
            if opt_match:
                lbl = opt_match.group(1).upper()
                # Normalize digit options 1-4 to A-D if applicable
                lbl_map = {"1": "A", "2": "B", "3": "C", "4": "D"}
                lbl = lbl_map.get(lbl, lbl)
                opt_text = opt_match.group(2).strip()
                options.append({"label": lbl, "text": opt_text})
            elif not options:
                # Still part of the question prompt (e.g. multi-line or multi-page continuation)
                prompt_lines.append(line)
            else:
                # Append to last option if continuation
                if options:
                    options[-1]["text"] += " " + line

        full_prompt = " ".join(prompt_lines).strip()

        # Classify question type
        q_type = "unknown"
        if options:
            if len(options) == 2 and any("true" in o["text"].lower() for o in options):
                q_type = "true_false"
            else:
                q_type = "mcq"
        elif re.search(r"\btrue\s*or\s*false\b", full_prompt, re.IGNORECASE):
            q_type = "true_false"
        elif full_prompt:
            q_type = "short_answer"

        # Dynamically compute self-reported confidence based on structural & linguistic quality
        words = full_prompt.split()
        word_count = len(words)

        if options and len(options) >= 4:
            base_conf = 0.94
        elif options and len(options) == 2 and q_type == "true_false":
            base_conf = 0.91
        elif options and len(options) == 3:
            base_conf = 0.76
        elif options and len(options) == 1:
            base_conf = 0.45
        elif q_type == "short_answer":
            base_conf = 0.72 if (word_count >= 6 and full_prompt.endswith("?")) else 0.52
        else:
            base_conf = 0.30

        # Penalize for detected OCR noise, spelling garbles, concatenated tokens
        penalties = 0.0
        garbled_tokens = re.findall(r"\b[a-zA-Z]+\d+[a-zA-Z]*\b|[a-z]{3,}[A-Z][a-z]{3,}", text)
        penalties += len(garbled_tokens) * 0.06

        if word_count < 4:
            penalties += 0.15

        if not q_num:
            penalties += 0.05

        llm_conf = max(0.15, min(0.98, round(base_conf - penalties, 2)))

        return StructuredQuestionOutput(
            question_number=q_num,
            question_text=full_prompt or text,
            question_type=q_type,
            options=options if options else None,
            llm_confidence=llm_conf
        )


class OpenAIProvider(AIProvider):
    """Production OpenAI LLM provider with structured JSON-schema prompts and retry loop."""
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.LLM_MODEL or "gpt-4o-mini"

    def structure_segment(self, segment: RawQuestionSegment) -> StructuredQuestionOutput:
        system_prompt = (
            "You are an expert exam question extraction engine. Parse the given raw OCR/document text segment "
            "into a clean, structured JSON object with the following fields:\n"
            "- question_number: string or null (e.g. '1', '12', 'Q3')\n"
            "- question_text: string (the complete question prompt, without option text)\n"
            "- question_type: 'mcq' | 'true_false' | 'short_answer' | 'unknown'\n"
            "- options: array of objects [{\"label\": \"A\", \"text\": \"...\"}] or null\n"
            "- llm_confidence: float between 0.0 and 1.0 representing your confidence in this extraction\n"
            "Respond ONLY with valid JSON."
        )

        for attempt in range(2): # Retry loop per PRD §4 Stage 4
            try:
                user_content = f"Source pages: {segment.source_pages}\nHint: {segment.question_hint}\nText:\n{segment.raw_text}"
                if attempt > 0:
                    user_content += "\n\nCRITICAL: Your previous response was invalid. Return ONLY strict, parsable JSON."

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                raw_json = response.choices[0].message.content
                data = json.loads(raw_json)
                return StructuredQuestionOutput(**data)
            except Exception as e:
                logger.warning("OpenAI structuring attempt %d failed: %s", attempt + 1, e)

        # Retries exhausted - graceful degradation
        return StructuredQuestionOutput(
            question_number=segment.question_hint,
            question_text=segment.raw_text,
            question_type="unknown",
            llm_confidence=0.20,
            validation_error="Schema validation failed after retry"
        )


class GeminiProvider(AIProvider):
    """Production Google Gemini LLM provider with structured JSON output and retry loop."""
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model_name = settings.LLM_MODEL if settings.LLM_MODEL and "gemini" in settings.LLM_MODEL.lower() else "gemini-1.5-flash"
        self.model = genai.GenerativeModel(
            model_name,
            generation_config={"response_mime_type": "application/json"}
        )

    def structure_segment(self, segment: RawQuestionSegment) -> StructuredQuestionOutput:
        system_instructions = (
            "You are an expert exam question extraction engine. Parse the given raw OCR/document text segment "
            "into a clean, structured JSON object with the following fields:\n"
            "- question_number: string or null (e.g. '1', '12', 'Q3')\n"
            "- question_text: string (the complete question prompt, without option text)\n"
            "- question_type: 'mcq' | 'true_false' | 'short_answer' | 'unknown'\n"
            "- options: array of objects [{\"label\": \"A\", \"text\": \"...\"}] or null\n"
            "- llm_confidence: float between 0.0 and 1.0 representing your confidence in this extraction\n"
            "Respond ONLY with valid JSON."
        )

        for attempt in range(2):
            try:
                user_content = (
                    f"{system_instructions}\n\n"
                    f"Source pages: {segment.source_pages}\nHint: {segment.question_hint}\nText:\n{segment.raw_text}"
                )
                if attempt > 0:
                    user_content += "\n\nCRITICAL: Your previous response was invalid. Return ONLY strict, parsable JSON."

                response = self.model.generate_content(user_content)
                raw_json = response.text.strip()
                if raw_json.startswith("```json"):
                    raw_json = raw_json[7:]
                if raw_json.startswith("```"):
                    raw_json = raw_json[3:]
                if raw_json.endswith("```"):
                    raw_json = raw_json[:-3]
                raw_json = raw_json.strip()

                data = json.loads(raw_json)
                return StructuredQuestionOutput(**data)
            except Exception as e:
                logger.warning("Gemini structuring attempt %d failed: %s", attempt + 1, e)

        return StructuredQuestionOutput(
            question_number=segment.question_hint,
            question_text=segment.raw_text,
            question_type="unknown",
            llm_confidence=0.20,
            validation_error="Gemini schema validation failed after retry"
        )


def get_ai_provider() -> AIProvider:
    """Factory returning configured AI structuring provider."""
    provider_name = (settings.AI_PROVIDER or "mock").lower()
    if provider_name == "openai" and settings.OPENAI_API_KEY:
        try:
            return OpenAIProvider()
        except Exception as e:
            logger.warning("Failed to initialize OpenAIProvider (%s). Falling back to MockAIProvider.", e)
            return MockAIProvider()
    elif provider_name == "gemini" and settings.GEMINI_API_KEY:
        try:
            return GeminiProvider()
        except Exception as e:
            logger.warning("Failed to initialize GeminiProvider (%s). Falling back to MockAIProvider.", e)
            return MockAIProvider()
    return MockAIProvider()
