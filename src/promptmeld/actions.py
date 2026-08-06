from __future__ import annotations

from datetime import UTC, datetime

from .models import WritingAction
from .suggestions import (
    ActionSuggestion,
    SuggestionContext,
    contextual_action_score,
)
from .usage import UsageTracker


class ActionRegistry:
    def __init__(
        self,
        actions: list[WritingAction],
        usage: UsageTracker,
        now_provider=lambda: datetime.now(UTC),
    ):
        self._actions = [action for action in actions if action.enabled]
        self._by_id = {action.id: action for action in self._actions}
        self._usage = usage
        self._now_provider = now_provider

    def all(self) -> list[WritingAction]:
        return self.search("")

    def configured(self) -> list[WritingAction]:
        """Return enabled actions in their explicit configuration order."""
        return list(self._actions)

    def most_used(
        self,
        limit: int,
        exclude_ids: set[str] | None = None,
    ) -> list[WritingAction]:
        if limit <= 0:
            return []
        excluded = exclude_ids or set()
        return [
            action
            for action in self.search("")
            if action.id not in excluded and self._usage.get(action.id).count > 0
        ][:limit]

    def get(self, action_id: str) -> WritingAction | None:
        return self._by_id.get(action_id)

    def suggest(
        self,
        context: SuggestionContext,
        limit: int = 4,
        exclude_ids: set[str] | None = None,
    ) -> list[ActionSuggestion]:
        if limit <= 0:
            return []
        excluded = exclude_ids or set()
        now = self._now_provider()
        ranked: list[tuple[float, int, ActionSuggestion]] = []
        for order_index, action in enumerate(self._actions):
            if action.id in excluded:
                continue
            contextual_score, contextual_reasons = contextual_action_score(
                action,
                context,
            )
            usage = self._usage.get(action.id)
            usage_score = min(usage.count, 20) * 1.5
            reasons = list(contextual_reasons)
            if usage.count:
                reasons.append(
                    f"used {usage.count} time{'s' if usage.count != 1 else ''}"
                )
            recency_score = 0.0
            if usage.last_used:
                used = usage.last_used
                if used.tzinfo is None:
                    used = used.replace(tzinfo=UTC)
                age_days = max(0.0, (now - used).total_seconds() / 86_400)
                recency_score = max(0.0, 20.0 - age_days)
                if recency_score:
                    reasons.append("used recently")
            score = contextual_score + usage_score + recency_score
            if score <= 0:
                continue
            suggestion = ActionSuggestion(action, score, tuple(reasons))
            ranked.append((score, order_index, suggestion))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [suggestion for _, _, suggestion in ranked[:limit]]

    def search(
        self,
        query: str,
        context: SuggestionContext | None = None,
    ) -> list[WritingAction]:
        terms = tuple(term.casefold() for term in query.split() if term.strip())
        ranked: list[tuple[tuple[float, ...], int, WritingAction]] = []
        now = self._now_provider()

        for order_index, action in enumerate(self._actions):
            searchable_name = action.name.casefold()
            searchable_keywords = " ".join(action.keywords).casefold()
            searchable_instruction = action.instruction.casefold()
            searchable_folder = action.folder.casefold()
            text_score = 0.0
            if terms:
                for term in terms:
                    if term == searchable_name:
                        text_score += 100
                    elif searchable_name.startswith(term):
                        text_score += 60
                    elif term in searchable_name:
                        text_score += 40
                    elif term in searchable_keywords:
                        text_score += 25
                    elif term in searchable_folder:
                        text_score += 15
                    elif term in searchable_instruction:
                        text_score += 5
                    else:
                        break
                else:
                    pass
                if any(
                    term
                    not in (
                        f"{searchable_name} {searchable_keywords} "
                        f"{searchable_folder} {searchable_instruction}"
                    )
                    for term in terms
                ):
                    continue

            usage = self._usage.get(action.id)
            recency = 0.0
            if usage.last_used:
                used = usage.last_used
                if used.tzinfo is None:
                    used = used.replace(tzinfo=UTC)
                age_days = max(0.0, (now - used).total_seconds() / 86_400)
                recency = max(0.0, 30.0 - age_days)
            usage_score = min(usage.count, 100)
            context_score = (
                contextual_action_score(action, context)[0]
                if context is not None
                else 0.0
            )
            ranked.append(
                (
                    (text_score, context_score, usage_score, recency),
                    order_index,
                    action,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item[0][0],
                -item[0][1],
                -item[0][2],
                -item[0][3],
                item[1],
            )
        )
        return [action for _, _, action in ranked]
