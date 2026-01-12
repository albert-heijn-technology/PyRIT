import json
from typing import Any, ClassVar, Dict, List, Optional

from pyrit.models import PromptRequestPiece, Score
from pyrit.score import Scorer, ScorerPromptValidator


class SimpleTextLengthScorer(Scorer):
    """Assigns a float score based on whether the response stays within a maximum length."""

    scorer_type = "float_scale"
    _summary_printed: ClassVar[bool] = False

    _default_validator: ScorerPromptValidator = ScorerPromptValidator(
        supported_data_types=["text"],
        is_objective_required=False,
    )

    def __init__(self, max_length: int = 500, *, validator: Optional[ScorerPromptValidator] = None):
        super().__init__(validator=validator or self._default_validator)
        self.max_length = max_length
        self.__class__._summary_printed = False

    def validate(self, request_response: PromptRequestPiece, *, task: Optional[str] = None):
        if not isinstance(request_response.original_value, str):
            raise ValueError("SimpleTextLengthScorer requires original_value to be a string.")

    async def _score_piece_async(
        self,
        request_piece: PromptRequestPiece,
        *,
        objective: Optional[str] = None,
    ) -> List[Score]:
        self.validate(request_piece, task=objective)

        text = request_piece.converted_value or ""
        length = len(text)
        normalized_score = 1.0 if length <= self.max_length else 0.0

        metadata = {"length": length, "max_length": self.max_length}

        score = Score(
            score_value=str(normalized_score),
            score_category=["text_length"],
            score_rationale=f"Text length is {length} characters, normalized to {normalized_score:.2f}",
            score_type=self.scorer_type,
            message_response_id=request_piece.id,
            score_metadata=metadata,
            score_value_description="Normalized text length",
            scorer_role=self.scorer_role,
            scorer_class_identifier=self.get_identifier(),
            objective=objective,
            expected_output=request_piece.expected_output,
        )

        return [score]

    def validate_return_scores(self, scores: List[Score]) -> None:
        for score in scores:
            if score.score_type != self.scorer_type:
                raise ValueError("SimpleTextLengthScorer returned a score with an unexpected type.")
            value = float(score.score_value)
            if not 0.0 <= value <= 1.0:
                raise ValueError("SimpleTextLengthScorer score must be between 0 and 1.")

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
                                "message_response_id": score.get("message_response_id"),
                                "conversation_id": conversation_id,
                                "length": recorded_length,
                                "max_length": max_length,
                                "normalized_score": normalized_score,
                                "task": score.get("task"),
                            }
                        )

        return results
