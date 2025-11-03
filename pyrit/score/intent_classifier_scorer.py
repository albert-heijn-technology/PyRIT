import ast
import json
from typing import Any, ClassVar, Dict, List, Optional

from pyrit.models import MessagePiece, Score
from pyrit.score import Scorer, ScorerPromptValidator


class IntentClassifierScorer(Scorer):
    """Scores assistant responses by comparing emitted intent text with the expected intent string."""

    scorer_type = "float_scale"
    _default_validator: ScorerPromptValidator = ScorerPromptValidator(
        supported_data_types=["text", "reasoning", "function_call", "function_call_output", "tool_call"],
        is_objective_required=False,
    )

    _summary_printed: ClassVar[bool] = False
    _summary_data: ClassVar[Dict[str, int]] = {}
    _confusion_matrix: ClassVar[Dict[str, Dict[str, int]]] = {}

    MISSING_INTENT_LABEL = "<missing_intent>"

    def __init__(self, case_sensitive: bool = False, *, validator: Optional[ScorerPromptValidator] = None):
        super().__init__(validator=validator or self._default_validator)
        self.case_sensitive = case_sensitive

        cls = self.__class__
        cls._summary_printed = False
        cls._summary_data = {
            "total": 0,
            "matched": 0,
            "mismatched": 0,
            "missing_expected": 0,
            "missing_intent": 0,
        }
        cls._confusion_matrix = {}

    def _validate_piece(self, request_piece: MessagePiece) -> None:
        if not isinstance(request_piece.original_value, str):
            raise ValueError("IntentClassifierScorer requires original_value to be a string.")

    async def _score_piece_async(
        self,
        message_piece: MessagePiece,
        *,
        objective: Optional[str] = None,
    ) -> List[Score]:
        self._validate_piece(message_piece)

        expected_intent = self._coerce_to_string(getattr(message_piece, "expected_output", None))
        if not expected_intent:
            self.__class__._summary_data["missing_expected"] += 1
            raise ValueError("IntentClassifierScorer requires expected_output to contain the intent string.")

        actual_intent = self._extract_actual_intent(getattr(message_piece, "converted_value", None))

        self.__class__._summary_data["total"] += 1

        matched = False
        rationale: str
        self._record_confusion(expected_intent, actual_intent)

        if not actual_intent:
            self.__class__._summary_data["missing_intent"] += 1
            rationale = f"Assistant response did not expose an intent; expected '{expected_intent}'."
        else:
            matched = self._normalise(actual_intent) == self._normalise(expected_intent)
            if matched:
                self.__class__._summary_data["matched"] += 1
                rationale = f"Intent '{actual_intent}' matched expected intent '{expected_intent}'."
            else:
                self.__class__._summary_data["mismatched"] += 1
                rationale = f"Expected intent '{expected_intent}', but assistant returned '{actual_intent}'."

        if message_piece.id is None:
            raise ValueError("MessagePiece must have a non-null id to create a Score.")
        
        score = Score(
            score_value=str(1.0 if matched else 0.0),
            score_category=["intent_classification"],
            score_rationale=rationale,
            score_type=self.scorer_type,
            message_piece_id=message_piece.id,
            score_metadata={
                "expected_intent": expected_intent,
                "actual_intent": actual_intent or self.MISSING_INTENT_LABEL,
                "case_sensitive": "true" if self.case_sensitive else "false",
                "matched": "true" if matched else "false",
            },
            score_value_description="1.0 indicates the emitted intent matches the expected intent; 0.0 otherwise.",
            scorer_role=self.scorer_role,
            scorer_class_identifier=self.get_identifier(),
            objective=objective,
            expected_output=message_piece.expected_output,
        )

        return [score]

    def _record_confusion(self, expected: Optional[str], actual: Optional[str]) -> None:
        if not expected:
            return

        cls = self.__class__
        actual_label = actual if actual else self.MISSING_INTENT_LABEL
        row = cls._confusion_matrix.setdefault(expected, {})
        row[actual_label] = row.get(actual_label, 0) + 1

    def _extract_actual_intent(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, dict):
            return self._coerce_to_string(value.get("intent") or value.get("Intent"))
        if not isinstance(value, str):
            return self._extract_actual_intent(str(value))

        raw = value.strip()
        if not raw:
            return None

        if raw.startswith("{"):
            payload: Dict[str, Any] = {}
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                try:
                    payload = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    payload = {}
            if isinstance(payload, dict):
                return self._extract_actual_intent(payload)

        return self._coerce_to_string(raw)

    def _coerce_to_string(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        cleaned = str(value).strip()
        return cleaned or None

    def _normalise(self, value: str) -> str:
        return value.strip() if self.case_sensitive else value.strip().lower()

    def validate_return_scores(self, scores: List[Score]) -> None:
        for score in scores:
            if score.score_type != self.scorer_type:
                raise ValueError("IntentClassifierScorer returned a score with an unexpected type.")
            value = float(score.score_value)
            if value not in (0.0, 1.0):
                raise ValueError("IntentClassifierScorer score_value must be 0.0 or 1.0.")

    @classmethod
    def on_run_complete(
        cls,
        report_payload: Optional[Dict[str, Any]] = None,
        report_path: Optional[str] = None,
    ) -> None:
        if cls._summary_printed:
            return

        cls._summary_printed = True

        matrix = {
            expected: dict(sorted(actual_counts.items()))
            for expected, actual_counts in sorted(cls._confusion_matrix.items())
        }

        payload: Dict[str, Any] = {
            "summary": cls._summary_data,
            "confusion_matrix": matrix,
        }
        # if report_payload:
        #     payload["report_payload"] = report_payload
        if report_path:
            payload["report_path"] = report_path

        print("IntentClassifierScorer summary:")
        print(json.dumps(payload, indent=2))
