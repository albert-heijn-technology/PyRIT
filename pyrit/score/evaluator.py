# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import enum
from pathlib import Path
from typing import Optional, Literal, List

import yaml
from langsmith import expect

from pyrit.common.path import DATASETS_PATH
from pyrit.models import PromptRequestPiece, SeedPrompt
from pyrit.models.score import Score, UnvalidatedScore, ScoreType
from pyrit.prompt_target import PromptChatTarget
from pyrit.score.scorer import Scorer
from pyrit.score.scorer_prompt_validator import ScorerPromptValidator

SCORERS_PATH = Path(DATASETS_PATH, "score", "LLM").resolve()

class EvaluatorQuestionPaths(enum.Enum):
    EVALUATOR = Path(SCORERS_PATH, "evaluator_system_prompt.yaml").resolve()

class EvaluatorQuestion:
    """
    A class that represents an evaluator question.

    This is sent to an LLM and can be used as an alternative to a yaml file.
    """

    def __init__(
            self, *, evaluation_criteria: str = "", category: str = "", metadata: Optional[str] = ""
    ):
        self.evaluation_criteria = evaluation_criteria
        self.category = category
        self.metadata = metadata

        self._keys = ["category", "evaluation_criteria"]

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __iter__(self):
        # Define which keys should be included when iterating
        return iter(self._keys)


class Evaluator(Scorer):
    """A class that represents a generic LLM based evaluator for scoring."""

    _default_validator: ScorerPromptValidator = ScorerPromptValidator(
        supported_data_types=["text"],
        is_objective_required=False,
    )

    def __init__(
            self,
            *,
            chat_target: PromptChatTarget,
            evaluator_yaml_path: Optional[Path] = None,
            evaluator_question: Optional[EvaluatorQuestion] = None,
            evaluator_system_prompt_path: Optional[Path] = None,
            additional_evaluator_variables: Optional[dict] = None,
            scorer_type: Literal["true_false", "float_scale"] = "float_scale",
            scorer_role: Optional[str] = None,
            validator: Optional[ScorerPromptValidator] = None,
    ) -> None:
        super().__init__(validator=validator or self._default_validator)

        self._prompt_target = chat_target
        self.scorer_type: ScoreType = scorer_type  # type: ignore[assignment]
        self.scorer_role = scorer_role
        self._additional_evaluator_variables = additional_evaluator_variables or {}

        if not evaluator_yaml_path and not evaluator_question:
            raise ValueError("Either true_false_question_path or true_false_question must be provided.")
        if evaluator_yaml_path and evaluator_question:
            raise ValueError("Only one of true_false_question_path or true_false_question should be provided.")
        if evaluator_yaml_path:
            evaluator_question = yaml.safe_load(evaluator_yaml_path.read_text(encoding="utf-8"))

        for key in ["category", "evaluation_criteria"]:
            if key not in evaluator_question:
                raise ValueError(f"{key} must be provided in true_false_question.")

        self._score_category = evaluator_question["category"]
        evaluation_criteria = evaluator_question["evaluation_criteria"]

        metadata = evaluator_question["metadata"] if "metadata" in evaluator_question else ""

        evaluator_system_prompt_path = (
            evaluator_system_prompt_path
            if evaluator_system_prompt_path
            else SCORERS_PATH / "evaluator_system_prompt.yaml"
        )

        scoring_instructions_template = SeedPrompt.from_yaml_file(evaluator_system_prompt_path)

        self._system_prompt = scoring_instructions_template.render_template_value(
            evaluation_criteria=evaluation_criteria, metadata=metadata
        )

    def validate(self, request_response: PromptRequestPiece, *, task: Optional[str] = None):
        pass

    async def _score_piece_async(
        self, request_piece: PromptRequestPiece, *, objective: Optional[str] = None
    ) -> List[Score]:
        """
        Score a single response piece using the evaluator template.
        """
        self.validate(request_piece, task=objective)

        unvalidated_score: UnvalidatedScore = await self._score_value_with_llm(
            prompt_target=self._prompt_target,
            system_prompt=self._system_prompt,
            prompt_request_value=request_piece.converted_value,
            prompt_request_data_type=request_piece.converted_value_data_type,
            scored_prompt_id=request_piece.id,
            category=self._score_category,
            objective=objective,
            attack_identifier=request_piece.attack_identifier,
            expected_output=request_piece.expected_output,
            request_prompt=request_piece.original_value,
            additional_evaluator_variables=self._additional_evaluator_variables,
        )

        score_value: str
        if self.scorer_type == "true_false":
            raw = str(unvalidated_score.raw_score_value).strip().lower()
            if raw not in {"true", "false"}:
                raise ValueError(f"True/False evaluator must return 'true' or 'false', got '{raw}'")
            score_value = raw
        else:
            try:
                numeric_value = float(unvalidated_score.raw_score_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Float scale evaluator must return a numeric score in [0, 1], got '{unvalidated_score.raw_score_value}'"
                ) from exc
            if not 0.0 <= numeric_value <= 1.0:
                raise ValueError(
                    f"Float scale evaluator must return value between 0 and 1, got {numeric_value}"
                )
            score_value = str(numeric_value)

        expected_output = (
            unvalidated_score.expected_output
            if unvalidated_score.expected_output is not None
            else request_piece.expected_output
        )

        score = Score(
            id=unvalidated_score.id,
            score_value=score_value,
            score_value_description=unvalidated_score.score_value_description,
            score_type=self.scorer_type,
            score_category=unvalidated_score.score_category,
            score_rationale=unvalidated_score.score_rationale,
            score_metadata=unvalidated_score.score_metadata,
            scorer_class_identifier=unvalidated_score.scorer_class_identifier,
            prompt_request_response_id=unvalidated_score.prompt_request_response_id,
            expected_output=expected_output,
            scorer_role=self.scorer_role,
            timestamp=unvalidated_score.timestamp,
            objective=unvalidated_score.objective,
        )

        return [score]

    def validate_return_scores(self, scores: List[Score]):
        """
        Ensure all scores produced by the evaluator match the configured scorer_type.
        """
        for score in scores:
            if score.score_type != self.scorer_type:
                raise ValueError(
                    f"Evaluator configured for '{self.scorer_type}' returned score of type '{score.score_type}'"
                )
            # Trigger built-in validation for the score value
            score.get_value()
