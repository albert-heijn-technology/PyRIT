from typing import Optional, List
from pyrit.models import PromptRequestPiece, Score
from pyrit.score import Scorer


class SimpleTextLengthScorer(Scorer):
    scorer_type = "float_scale"  # since output is a float between 0 and 1

    def __init__(self, max_length: int = 500):
        self.max_length = max_length

    def validate(self, request_response: PromptRequestPiece, *, task: Optional[str] = None):
        # Ensure original_value is a string
        if not isinstance(request_response.original_value, str):
            raise ValueError("SimpleTextLengthScorer requires original_value to be a string.")

    async def _score_async(self, request_response: PromptRequestPiece, *, task: Optional[str] = None) -> List[Score]:
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
            score_metadata={"length": length, "max_length": self.max_length},
            score_value_description=None,
            scorer_role=self.scorer_role
        )

        return [score]
