import re
import asyncio
import uuid
from typing import Any, Optional, Sequence, List, Dict, Callable

from pyrit.attacks import SingleTurnAttackContext, PromptSendingAttack, AttackConverterConfig, AttackScoringConfig, \
    AttackOutcome
from pyrit.memory import CentralMemory
from pyrit.models import PromptRequestResponse, SeedPromptGroup, PromptRequestPiece
from pyrit.models.filter_criteria import PromptConverterState, PromptFilterCriteria
from pyrit.orchestrator import Orchestrator, OrchestratorResultStatus
from pyrit.prompt_normalizer import PromptConverterConfiguration, PromptNormalizer
from pyrit.prompt_target import PromptTarget
from pyrit.prompt_target.batch_helper import batch_task_async
from pyrit.score import Scorer
from pyrit.orchestrator.models.orchestrator_result import OrchestratorResult


class PromptOrchestrator(Orchestrator):
    def __init__(
            self,
            *,
            objective_target: PromptTarget,
            request_converter_configurations: Optional[List[PromptConverterConfiguration]] = None,
            response_converter_configurations: Optional[List[PromptConverterConfiguration]] = None,
            objective_scorer: Optional[Scorer] = None,
            auxiliary_scorers: Optional[List[Scorer]] = None,
            should_convert_prepended_conversation: bool = True,
            batch_size: int = 10,
            retries_on_objective_failure: int = 0,
            scorer_type: str = "float_scale",
            thread_id_injector: Optional[Callable[[str, str], str]] = None,
            verbose: bool = False,
    ) -> None:
        super().__init__(verbose=verbose)

        if scorer_type not in {"float_scale", "true_false"}:
            raise ValueError(f"Invalid scorer_type '{scorer_type}', must be 'float_scale' or 'true_false'.")

        if not objective_scorer:
            raise ValueError("Objective scorer must be provided.")

        if scorer_type != objective_scorer.scorer_type:
            raise ValueError(
                f"Mismatch between scorer_type '{scorer_type}' and objective_scorer.scorer_type '{objective_scorer.scorer_type}'."
            )

        if thread_id_injector is None:
            raise ValueError("A 'thread_id_injector' callable must be provided to inject thread IDs into HTTP requests.")

        self._prompt_normalizer = PromptNormalizer()
        self._objective_scorer = objective_scorer
        self._auxiliary_scorers = auxiliary_scorers or []
        self._objective_target = objective_target
        self._request_converter_configurations = request_converter_configurations or []
        self._response_converter_configurations = response_converter_configurations or []
        self._should_convert_prepended_conversation = should_convert_prepended_conversation
        self._batch_size = batch_size
        self._retries_on_objective_failure = retries_on_objective_failure
        self._scorer_type = scorer_type
        self._thread_id_injector = thread_id_injector

        # Build the new attack model
        self._attack = PromptSendingAttack(
            objective_target=objective_target,
            attack_converter_config=AttackConverterConfig(
                request_converters=self._request_converter_configurations,
                response_converters=self._response_converter_configurations,
            ),
            attack_scoring_config=AttackScoringConfig(
                objective_scorer=objective_scorer,
                auxiliary_scorers=self._auxiliary_scorers,
            ),
            prompt_normalizer=self._prompt_normalizer,
            max_attempts_on_failure=self._retries_on_objective_failure,
            orchestrator_identifier=self.get_identifier(),
        )

    def set_skip_criteria(
            self, *, skip_criteria: PromptFilterCriteria, skip_value_type: PromptConverterState = "original"
    ):
        self._prompt_normalizer.set_skip_criteria(skip_criteria=skip_criteria, skip_value_type=skip_value_type)

    async def execute_step_async(
            self,
            *,
            objective: str,
            expected_output: Optional[str] = None,
            seed_prompt: SeedPromptGroup = None,
            prepended_conversation: Optional[List[PromptRequestResponse]] = None,
            memory_labels: Optional[Dict[str, str]] = None,
            conversation_id: str = "",
    ) -> tuple[Optional[OrchestratorResult], Optional[PromptRequestPiece]]:

        if conversation_id is None or conversation_id == "":
            conversation_id = str(uuid.uuid4())

        context = SingleTurnAttackContext(
            objective=objective,
            seed_prompt_group=seed_prompt,
            prepended_conversation=prepended_conversation or [],
            memory_labels=memory_labels or {},
            conversation_id=conversation_id,
            expected_output=expected_output,
        )

        result = await self._attack.execute_with_context_async(context=context)

        # Map attack outcome to orchestrator status
        status_mapping: dict[AttackOutcome, OrchestratorResultStatus] = {
            AttackOutcome.SUCCESS: "success",
            AttackOutcome.FAILURE: "failure",
            AttackOutcome.UNDETERMINED: "unknown",
        }

        orchestrator_result = OrchestratorResult(
            conversation_id=result.conversation_id,
            objective=objective,
            status=status_mapping.get(result.outcome, "unknown"),
            objective_score=result.last_score,
        )
        return orchestrator_result, result.last_response


    async def execute_multiple_steps_async(
            self,
            *,
            objectives: List[str],
            conversation_ids: Optional[List[str]] = None,
            expected_outputs: Optional[List[str]] = None,
            seed_prompts: Optional[List[SeedPromptGroup]] = None,
            prepended_conversations: Optional[List[List[PromptRequestResponse]]] = None,
            memory_labels: Optional[Dict[str, str]] = None,
    ) -> List[OrchestratorResult]:
        if not expected_outputs:
            expected_outputs = [None] * len(objectives)
        elif len(expected_outputs) != len(objectives):
            raise ValueError("Number of expected outputs must match number of objectives")

        if not seed_prompts:
            seed_prompts = [None] * len(objectives)
        elif len(seed_prompts) != len(objectives):
            raise ValueError("Number of seed prompts must match number of objectives")

        if not prepended_conversations:
            prepended_conversations = [None] * len(objectives)
        elif len(prepended_conversations) != len(objectives):
            raise ValueError("Number of prepended conversations must match number of objectives")

        if not conversation_ids:
            conversation_ids = [None] * len(objectives)
        elif len(conversation_ids) != len(objectives):
            raise ValueError("Number of conversation IDs must match number of objectives")

        batch_items: List[Sequence[Any]] = [
            objectives, expected_outputs, seed_prompts, prepended_conversations, conversation_ids
        ]
        batch_item_keys = [
            "objective", "expected_output", "seed_prompt", "prepended_conversation", "conversation_id"
        ]

        results = await batch_task_async(
            prompt_target=self._objective_target,
            batch_size=self._batch_size,
            items_to_batch=batch_items,
            task_func=self.execute_step_async,
            task_arguments=batch_item_keys,
            memory_labels=memory_labels,
        )

        return [res[0] for res in results if res is not None and res[0] is not None]

    async def execute(self, qa_pairs: List[Dict[str, Any]]) -> Any:
        single_turn_objectives = []
        single_turn_expected_outputs = []
        start_request_copy = self._objective_target.http_request

        for i, qa in enumerate(qa_pairs):
            print(f"\nExecuting test case: {i + 1}")
            self._objective_target.http_request = start_request_copy

            if "conversation" in qa:
                conversation_id = str(uuid.uuid4())
                is_thread_id_set = False

                for idx, turn in enumerate(qa["conversation"]):
                    prompt_text = turn["question"]
                    expected_output = turn["expected_outcome"]
                    print("Question:", prompt_text)

                    await asyncio.sleep(15)
                    result, prompt_response = await self.execute_step_async(
                        objective=prompt_text,
                        expected_output=expected_output,
                        conversation_id=conversation_id,
                    )

                    if not result:
                        continue

                    # Inject thread ID once if present in first assistant response
                    if idx == 0 and not is_thread_id_set:
                        if prompt_response:
                            thread_id = prompt_response.prompt_metadata.get("thread_id")
                            if thread_id:
                                self._objective_target.http_request = self._thread_id_injector(
                                    self._objective_target.http_request, thread_id
                                )
                                is_thread_id_set = True
                        else:
                            print("Thread ID not found in first turn's response. Aborting this conversation.")
                            break

                    await asyncio.sleep(1)
            else:
                # Single-turn QA
                single_turn_objectives.append(qa["question"])
                single_turn_expected_outputs.append(qa["expected_outcome"])

        # Run batched single-turn prompts
        if single_turn_objectives:
            await self.execute_multiple_steps_async(
                objectives=single_turn_objectives,
                expected_outputs=single_turn_expected_outputs,
            )

    def get_all_chat_results(self) -> List[Dict[str, Any]]:
        messages = self.get_memory()
        conv_dict: Dict[str, List[Dict[str, Any]]] = {}

        for msg in messages:
            conv_id = msg.conversation_id
            if conv_id not in conv_dict:
                conv_dict[conv_id] = []
            entry = {
                "role": msg.role,
                "message": msg.converted_value
            }
            if msg.scores:
                entry["scores"] = [
                    {
                        "score_value": s.score_value,
                        "score_rationale": s.score_rationale,
                        "expected_output": s.expected_output
                    }
                    for s in msg.scores
                ]
            conv_dict[conv_id].append(entry)

        results = []
        for conv_id, conversation in conv_dict.items():
            if len(conversation) == 2 and conversation[0]["role"].lower() == "user" and conversation[1]["role"].lower() == "assistant":
                results.append({
                    "conversation_id": conv_id,
                    "prompt": conversation[0]["message"],
                    "assistant_response": conversation[1]["message"],
                    "scores": conversation[1].get("scores", [])
                })
            else:
                results.append({
                    "conversation_id": conv_id,
                    "conversation": conversation
                })
        return results
