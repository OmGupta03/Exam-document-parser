import os
import sys
from unittest.mock import MagicMock, patch
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice

from app.services.ai_provider import OpenAIProvider, RawQuestionSegment

def test_live_or_mocked_openai():
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key and api_key.startswith("sk-"):
        print("=== RUNNING LIVE OPENAI PROVIDER WITH REAL API KEY ===")
        provider = OpenAIProvider()
        segment = RawQuestionSegment(
            raw_text="1. What is the time complexity of binary search?\nA. O(1)\nB. O(log n)\nC. O(n)\nD. O(n log n)",
            source_pages=[1],
            question_hint="1",
            extraction_confidence=0.98
        )
        output = provider.structure_segment(segment)
        print("OpenAI Model Used:     ", provider.model)
        print("Question Text:         ", output.question_text)
        print("Question Type:         ", output.question_type)
        print("Options:               ", output.options)
        print("Model Self-Reported Conf:", output.llm_confidence)
        print("Validation Error:      ", output.validation_error)
        return

    print("=== [OFFLINE UNIT TEST] OPENAI PROVIDER PARSING & DESERIALIZATION ===")
    print("NOTE: No external OPENAI_API_KEY is configured in this environment (.env OPENAI_API_KEY='').")
    print("This is strictly an offline unit test using a mocked ChatCompletion payload to verify JSON schema parsing:")
    
    # Simulate an actual ChatCompletion object from OpenAI with self-reported confidence = 0.88
    mock_completion = ChatCompletion(
        id="chatcmpl-test-12345",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(
                    content='{\n  "question_number": "1",\n  "question_text": "What is the time complexity of binary search?",\n  "question_type": "mcq",\n  "options": [\n    {"label": "A", "text": "O(1)"},\n    {"label": "B", "text": "O(log n)"},\n    {"label": "C", "text": "O(n)"},\n    {"label": "D", "text": "O(n log n)"}\n  ],\n  "llm_confidence": 0.88\n}',
                    role="assistant"
                )
            )
        ],
        created=1726850000,
        model="gpt-4o-mini",
        object="chat.completion"
    )

    with patch("openai.OpenAI") as MockClient:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_completion
        MockClient.return_value = mock_instance

        with patch("app.core.config.settings.OPENAI_API_KEY", "sk-mock-key-for-test"):
            provider = OpenAIProvider()
            segment = RawQuestionSegment(
                raw_text="1. What is the time complexity of binary search?\nA. O(1)\nB. O(log n)\nC. O(n)\nD. O(n log n)",
                source_pages=[1],
                question_hint="1",
                extraction_confidence=0.98
            )
            output = provider.structure_segment(segment)

            print("Provider Initialized:  ", type(provider).__name__)
            print("Model Target:          ", provider.model)
            print("Received JSON Content: ", mock_completion.choices[0].message.content)
            print("\nParsed StructuredQuestionOutput:")
            print("  question_number:     ", output.question_number)
            print("  question_text:       ", output.question_text)
            print("  question_type:       ", output.question_type)
            print("  options count:       ", len(output.options))
            print("  llm_confidence:      ", output.llm_confidence, "(Genuinely deserialized from model JSON payload)")

            assert output.llm_confidence == 0.88, f"Expected 0.88, got {output.llm_confidence}"
            print("\nVerification PASSED: llm_confidence is read dynamically from the model output!")

if __name__ == "__main__":
    test_live_or_mocked_openai()
