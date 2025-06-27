# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, TypeVar, List

from pyrit.models.prompt_request_piece import PromptRequestPiece
from pyrit.models.score import Score
from pyrit.memory import CentralMemory

ResultT = TypeVar("ResultT", bound="AttackResult")


class AttackOutcome(Enum):
    """
    Enum representing the possible outcomes of an attack.
    """

    # The attack was successful in achieving its objective
    SUCCESS = "success"

    # The attack failed to achieve its objective
    FAILURE = "failure"

    # The outcome of the attack is unknown or could not be determined
    UNDETERMINED = "undetermined"

@dataclass
class AttackResult:
    """Base class for all attack results"""

    # Identity
    # Unique identifier of the conversation that produced this result
    conversation_id: str

    # Natural-language description of the attacker’s objective
    objective: str

    # Identifier of the attack (e.g., name, module)
    attack_identifier: dict[str, str]

    # Evidence
    # Model response generated in the final turn of the attack
    last_response: Optional[PromptRequestPiece] = None

    # Score assigned to the final response by a scorer component
    last_score: Optional[Score] = None

    # Metrics
    # Total number of turns that were executed
    executed_turns: int = 0

    # Total execution time of the attack in milliseconds
    execution_time_ms: int = 0

    # Outcome
    # The outcome of the attack, indicating success, failure, or undetermined
    outcome: AttackOutcome = AttackOutcome.UNDETERMINED

    # Optional reason for the outcome, providing additional context
    outcome_reason: Optional[str] = None

    # Additional information
    # Metadata can be included as key-value pairs to provide extra context
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Builds a dictionary representation of the interaction based on attack result.
    async def get_conversation_report_async(self) -> dict:
        """
        Returns a structured conversation report for HTML reporting or metrics.

        Groups user and assistant messages into turns:
          - Each turn contains up to two messages: one user message, one assistant message.
          - Each piece stores both original_value and converted_value.
          - Assistant pieces may have scores and expected_output if found in memory.
        """
        memory = CentralMemory.get_memory_instance()
        target_messages = memory.get_conversation(conversation_id=self.conversation_id)
        if not target_messages:
            return {"error": "No conversation with the target"}

        report: Dict[str, Any] = {}
        transcript: List[Dict] = []
        scores_by_turn: List[Dict] = []

        report["objective"] = self.objective
        report["achieved_objective"] = (self.outcome == AttackOutcome.SUCCESS)
        report["attack_identifier"] = self.attack_identifier
        report["executed_turns"] = self.executed_turns
        report["outcome"] = self.outcome.value
        report["outcome_reason"] = self.outcome_reason
        report["metadata"] = self.metadata
        report["conversation_id"] = self.conversation_id

        turn_index = 1
        i = 0
        n = len(target_messages)

        while i < n:
            turn_data = {"turn_index": turn_index, "pieces": []}

            # User message
            if i < n:
                turn_data["pieces"].extend(
                    self._build_piece_data(
                        target_messages[i],
                        turn_index=turn_index,
                        scores_by_turn=scores_by_turn,
                        is_assistant=False
                    )
                )
                i += 1

            # Assistant message
            if i < n:
                turn_data["pieces"].extend(
                    self._build_piece_data(
                        target_messages[i],
                        turn_index=turn_index,
                        scores_by_turn=scores_by_turn,
                        is_assistant=True
                    )
                )
                i += 1

            transcript.append(turn_data)
            turn_index += 1

        # Locate final_score from last assistant piece
        final_score = None
        for turn in reversed(transcript):
            for piece in reversed(turn["pieces"]):
                if piece.get("role", "").lower() == "assistant" and piece.get("scores"):
                    final_score = piece["scores"][0].get("score")
                    break
            if final_score is not None:
                break

        report["transcript"] = transcript
        report["aggregated_metrics"] = {
            "total_turns": len(transcript),
            "final_score": final_score,
            "scores_by_turn": scores_by_turn
        }

        return report

    def _build_piece_data(
            self,
            message,
            turn_index: int,
            scores_by_turn: List[Dict],
            is_assistant: bool
    ) -> List[Dict]:
        """
        Convert each message piece into dict with:
          - role
          - original_value
          - converted_value
          - scores (assistant only, including expected_output if present)
        """
        memory = CentralMemory.get_memory_instance()
        pieces_data: List[Dict] = []
        for piece in message.request_pieces:
            piece_data = {
                "role": piece.role,
                "original_value": piece.original_value or "",
                "converted_value": piece.converted_value or "",
                "scores": []
            }

            if is_assistant and piece.role.lower() == "assistant":
                raw_scores = memory.get_scores_by_prompt_ids(
                    prompt_request_response_ids=[str(piece.id)]
                )
                if raw_scores:
                    piece_scores: List[Dict] = []
                    for s in raw_scores:
                        score_entry = {
                            "score": getattr(s, "score_value", None),
                            "rationale": getattr(s, "score_rationale", None)
                        }
                        if hasattr(s, "expected_output") and s.expected_output:
                            score_entry["expected_output"] = s.expected_output
                        piece_scores.append(score_entry)

                    piece_data["scores"] = piece_scores

                    if piece_scores:
                        scores_by_turn.append({
                            "turn_index": turn_index,
                            "score_details": piece_scores
                        })

            pieces_data.append(piece_data)
        return pieces_data
