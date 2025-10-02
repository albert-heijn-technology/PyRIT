import json
from typing import Any, ClassVar, Dict, List, Optional

from pyrit.models import PromptRequestPiece, Score
from pyrit.score import Scorer


class SimpleTextLengthScorer(Scorer):
    scorer_type = "float_scale"  # since output is a float between 0 and 1

    _summary_printed: ClassVar[bool] = False

    def __init__(self, max_length: int = 500):
        self.max_length = max_length
        self.__class__._summary_printed = False

    def validate(self, request_response: PromptRequestPiece, *, task: Optional[str] = None):
        # Ensure original_value is a string
        if not isinstance(request_response.original_value, str):
            raise ValueError("SimpleTextLengthScorer requires original_value to be a string.")

    async def _score_async(
        self, request_response: PromptRequestPiece, *, task: Optional[str] = None
    ) -> List[Score]:
        self.validate(request_response, task=task)

        text = request_response.converted_value or ""
        length = len(text)
        normalized_score = 1.0 if length <= self.max_length else 0.0

        score = Score(
            score_value=normalized_score,
            score_category="text_length",
            score_rationale=f"Text length is {length} characters, normalized to {normalized_score:.2f}",
            score_type=self.scorer_type,
            prompt_request_response_id=request_response.id,
            task=task,
            score_metadata=json.dumps({"length": length, "max_length": self.max_length}),
            score_value_description=None,
            scorer_role=self.scorer_role,
        )

        return [score]

    @classmethod
    def on_run_complete(
        cls,
        report_payload: Optional[Dict[str, Any]] = None,
        report_path: Optional[str] = None,
    ) -> None:
        if cls._summary_printed:
            return

        cls._summary_printed = True

        extracted = cls._extract_results_from_report(report_payload or {})
        if not extracted:
            print("SimpleTextLengthScorer summary: no responses were scored.")
            return

        successes = sum(1 for result in extracted if result["normalized_score"] >= 1.0)
        failures = len(extracted) - successes
        max_lengths = sorted({result["max_length"] for result in extracted if result["max_length"] is not None})

        summary = {
            "total": len(extracted),
            "within_limit": successes,
            "exceeded_limit": failures,
            "max_lengths": max_lengths,
        }

        payload: Dict[str, Any] = {"summary": summary, "results": extracted}
        if report_path:
            payload["report_path"] = report_path

        print("SimpleTextLengthScorer summary:")
        print(json.dumps(payload, indent=2))

    @staticmethod
    def _extract_results_from_report(report_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        chat_reports = report_payload.get("chat_reports") or []
        results: List[Dict[str, Any]] = []

        for conversation in chat_reports:
            conversation_id = conversation.get("conversation_id")
            for turn in conversation.get("transcript", []):
                for piece in turn.get("pieces", []):
                    if piece.get("role") != "assistant":
                        continue

                    text = piece.get("converted_value") or ""
                    for score in piece.get("scores", []):
                        identifier = score.get("scorer_identifier") or {}
                        if identifier.get("__type__") != SimpleTextLengthScorer.__name__:
                            continue

                        metadata = score.get("score_metadata")
                        metadata_obj: Dict[str, Any]
                        if isinstance(metadata, str):
                            try:
                                metadata_obj = json.loads(metadata)
                            except json.JSONDecodeError:
                                metadata_obj = {}
                        elif isinstance(metadata, dict):
                            metadata_obj = metadata
                        else:
                            metadata_obj = {}

                        recorded_length = metadata_obj.get("length")
                        max_length = metadata_obj.get("max_length")

                        if recorded_length is None:
                            recorded_length = len(text)
                        if max_length is None:
                            max_length = metadata_obj.get("limit") or len(text)

                        raw_score = score.get("score")
                        if raw_score is None:
                            raw_score = score.get("score_value")

                        try:
                            normalized_score = float(raw_score)
                        except (TypeError, ValueError):
                            normalized_score = 0.0

                        results.append(
                            {
                                "prompt_request_response_id": score.get("prompt_request_response_id"),
                                "conversation_id": conversation_id,
                                "length": recorded_length,
                                "max_length": max_length,
                                "normalized_score": normalized_score,
                                "task": score.get("task"),
                            }
                        )

        return results
