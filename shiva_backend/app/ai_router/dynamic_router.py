from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import re
import structlog
from dataclasses import dataclass

from app.db.models import (
    RoutingRule, 
    RoutingDestination, 
    RoutingMetric,
    RuleConditionType,
    RuleActionType
)
from app.clients.qdrant_client import QdrantClientInterface

logger = structlog.get_logger(__name__)


@dataclass
class RoutingDecision:
    """Result of routing decision."""
    destination: str
    confidence: float
    matched_rules: List[str]
    actions: List[Dict[str, Any]]
    reasoning: str


@dataclass
class RoutingContext:
    """Context for routing decision."""
    message: str
    customer_id: Optional[str] = None
    customer_data: Optional[Dict[str, Any]] = None
    attachments: Optional[List[str]] = None
    conversation_history: Optional[List] = None
    kb_similarity_score: Optional[float] = None
    complexity_score: Optional[float] = None
    current_time: Optional[datetime] = None


class DynamicRouter:
    """
    Dynamic routing engine using database-driven rules.
    
    This replaces the static pattern matching in AIRouter with a flexible,
    configurable rule system that can be updated at runtime.
    """

    def __init__(
        self,
        qdrant_client: Optional[QdrantClientInterface] = None,
    ):
        self.qdrant_client = qdrant_client
        self._rule_cache: Optional[List[RoutingRule]] = None
        self._destination_cache: Optional[Dict[str, RoutingDestination]] = None
        self._cache_expires_at: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes

    async def route(
        self,
        context: RoutingContext,
        session,
    ) -> RoutingDecision:
        """
        Make a routing decision based on dynamic rules.
        
        Args:
            context: Routing context with message and metadata
            session: Database session for rule access
            
        Returns:
            RoutingDecision with destination and metadata
        """
        # Ensure current time is set
        if context.current_time is None:
            context.current_time = datetime.now(timezone.utc)

        # Get active rules (with cache)
        rules = await self._get_active_rules(session)
        destinations = await self._get_active_destinations(session)

        # Evaluate rules in priority order
        matched_rules = []
        rule_scores = []

        for rule in rules:
            if await self._evaluate_rule(rule, context):
                matched_rules.append(rule)
                rule_scores.append((rule, rule.weight))

        # If no rules matched, use default fallback
        if not matched_rules:
            logger.info("No rules matched, using default fallback")
            return await self._get_fallback_decision(context, destinations)

        # Select best matching rule based on weight and priority
        best_rule = max(rule_scores, key=lambda x: (x[0].priority, x[1]))[0]

        # Extract actions from the rule
        actions = best_rule.actions

        # Determine destination from actions
        destination = self._extract_destination(actions, destinations)

        # Calculate confidence based on rule weight and match quality
        confidence = self._calculate_confidence(best_rule, context)

        # Generate reasoning
        reasoning = self._generate_reasoning(best_rule, context)

        # Update rule statistics
        await self._update_rule_stats(session, best_rule.id)

        logger.info(
            "Routing decision made",
            destination=destination,
            confidence=confidence,
            matched_rule=best_rule.name,
            rule_id=best_rule.id,
        )

        return RoutingDecision(
            destination=destination,
            confidence=confidence,
            matched_rules=[rule.id for rule in matched_rules],
            actions=actions,
            reasoning=reasoning,
        )

    async def _get_active_rules(self, session) -> List[RoutingRule]:
        """Get active routing rules with caching."""
        now = datetime.now(timezone.utc)
        
        # Check cache
        if (self._rule_cache is not None and 
            self._cache_expires_at is not None and 
            now < self._cache_expires_at):
            return self._rule_cache

        # Load from database
        from sqlalchemy import select
        result = await session.execute(
            select(RoutingRule)
            .where(RoutingRule.is_active == True)
            .order_by(RoutingRule.priority.asc())
        )
        rules = list(result.scalars().all())

        # Update cache
        self._rule_cache = rules
        self._cache_expires_at = now + timezone.timedelta(seconds=self._cache_ttl_seconds)

        return rules

    async def _get_active_destinations(self, session) -> Dict[str, RoutingDestination]:
        """Get active routing destinations with caching."""
        now = datetime.now(timezone.utc)
        
        # Check cache
        if (self._destination_cache is not None and 
            self._cache_expires_at is not None and 
            now < self._cache_expires_at):
            return self._destination_cache

        # Load from database
        from sqlalchemy import select
        result = await session.execute(
            select(RoutingDestination)
            .where(RoutingDestination.is_active == True)
            .order_by(RoutingDestination.priority.asc())
        )
        destinations = {dest.name: dest for dest in result.scalars().all()}

        # Update cache
        self._destination_cache = destinations
        self._cache_expires_at = now + timezone.timedelta(seconds=self._cache_ttl_seconds)

        return destinations

    async def _evaluate_rule(self, rule: RoutingRule, context: RoutingContext) -> bool:
        """
        Evaluate if a rule matches the given context.
        
        All conditions in a rule must match (AND logic).
        """
        for condition in rule.conditions:
            if not await self._evaluate_condition(condition, context):
                return False
        return True

    async def _evaluate_condition(self, condition: Dict[str, Any], context: RoutingContext) -> bool:
        """Evaluate a single condition."""
        condition_type = condition.get("type")
        field = condition.get("field")
        value = condition.get("value")
        case_sensitive = condition.get("case_sensitive", False)

        try:
            if condition_type == RuleConditionType.CONTAINS:
                return self._eval_contains(field, value, context, case_sensitive)
            elif condition_type == RuleConditionType.REGEX:
                return self._eval_regex(field, value, context, case_sensitive)
            elif condition_type == RuleConditionType.EXACT_MATCH:
                return self._eval_exact_match(field, value, context, case_sensitive)
            elif condition_type == RuleConditionType.LENGTH_GREATER_THAN:
                return self._eval_length_greater_than(field, value, context)
            elif condition_type == RuleConditionType.LENGTH_LESS_THAN:
                return self._eval_length_less_than(field, value, context)
            elif condition_type == RuleConditionType.HAS_ATTACHMENT:
                return self._eval_has_attachment(context)
            elif condition_type == RuleConditionType.ATTACHMENT_TYPE:
                return self._eval_attachment_type(value, context)
            elif condition_type == RuleConditionType.CUSTOMER_PLAN:
                return self._eval_customer_plan(value, context)
            elif condition_type == RuleConditionType.TIME_OF_DAY:
                return self._eval_time_of_day(value, context)
            elif condition_type == RuleConditionType.DAY_OF_WEEK:
                return self._eval_day_of_week(value, context)
            elif condition_type == RuleConditionType.CONFIDENCE_THRESHOLD:
                return self._eval_confidence_threshold(value, context)
            elif condition_type == RuleConditionType.KB_SIMILARITY:
                return self._eval_kb_similarity(value, context)
            elif condition_type == RuleConditionType.COMPLEXITY_SCORE:
                return self._eval_complexity_score(value, context)
            else:
                logger.warning(f"Unknown condition type: {condition_type}")
                return False
        except Exception as e:
            logger.error(f"Error evaluating condition: {e}", condition=condition)
            return False

    def _eval_contains(self, field: str, value: str, context: RoutingContext, case_sensitive: bool) -> bool:
        """Evaluate contains condition."""
        field_value = self._get_field_value(field, context)
        if field_value is None:
            return False
        
        if not case_sensitive:
            return value.lower() in str(field_value).lower()
        return value in str(field_value)

    def _eval_regex(self, field: str, pattern: str, context: RoutingContext, case_sensitive: bool) -> bool:
        """Evaluate regex condition."""
        field_value = self._get_field_value(field, context)
        if field_value is None:
            return False
        
        flags = 0 if case_sensitive else re.IGNORECASE
        return bool(re.search(pattern, str(field_value), flags))

    def _eval_exact_match(self, field: str, value: str, context: RoutingContext, case_sensitive: bool) -> bool:
        """Evaluate exact match condition."""
        field_value = self._get_field_value(field, context)
        if field_value is None:
            return False
        
        if not case_sensitive:
            return str(value).lower() == str(field_value).lower()
        return str(value) == str(field_value)

    def _eval_length_greater_than(self, field: str, value: int, context: RoutingContext) -> bool:
        """Evaluate length greater than condition."""
        field_value = self._get_field_value(field, context)
        if field_value is None:
            return False
        return len(str(field_value)) > value

    def _eval_length_less_than(self, field: str, value: int, context: RoutingContext) -> bool:
        """Evaluate length less than condition."""
        field_value = self._get_field_value(field, context)
        if field_value is None:
            return False
        return len(str(field_value)) < value

    def _eval_has_attachment(self, context: RoutingContext) -> bool:
        """Evaluate has attachment condition."""
        return bool(context.attachments and len(context.attachments) > 0)

    def _eval_attachment_type(self, value: str, context: RoutingContext) -> bool:
        """Evaluate attachment type condition."""
        if not context.attachments:
            return False
        
        value_lower = value.lower()
        for attachment in context.attachments:
            if attachment.lower().endswith(value_lower):
                return True
        return False

    def _eval_customer_plan(self, value: str, context: RoutingContext) -> bool:
        """Evaluate customer plan condition."""
        if not context.customer_data:
            return False
        return context.customer_data.get("plan", "").lower() == value.lower()

    def _eval_time_of_day(self, value: str, context: RoutingContext) -> bool:
        """Evaluate time of day condition."""
        if not context.current_time:
            return False
        
        # value should be in format "HH:MM-HH:MM" or "HH:MM+"
        current_hour = context.current_time.hour
        
        if "-" in value:
            # Range: "09:00-17:00"
            start, end = value.split("-")
            start_hour = int(start.split(":")[0])
            end_hour = int(end.split(":")[0])
            return start_hour <= current_hour < end_hour
        elif "+" in value:
            # After: "17:00+"
            hour = int(value.split("+")[0].split(":")[0])
            return current_hour >= hour
        else:
            # Exact hour
            hour = int(value.split(":")[0])
            return current_hour == hour

    def _eval_day_of_week(self, value: str, context: RoutingContext) -> bool:
        """Evaluate day of week condition."""
        if not context.current_time:
            return False
        
        # value can be "monday", "mon", "0" (0=Monday), or "weekend", "weekday"
        current_day = context.current_time.weekday()  # 0=Monday, 6=Sunday
        
        if value.lower() in ["weekend"]:
            return current_day >= 5  # Saturday or Sunday
        elif value.lower() in ["weekday"]:
            return current_day < 5  # Monday-Friday
        elif value.lower() in ["monday", "mon", "0"]:
            return current_day == 0
        elif value.lower() in ["tuesday", "tue", "1"]:
            return current_day == 1
        elif value.lower() in ["wednesday", "wed", "2"]:
            return current_day == 2
        elif value.lower() in ["thursday", "thu", "3"]:
            return current_day == 3
        elif value.lower() in ["friday", "fri", "4"]:
            return current_day == 4
        elif value.lower() in ["saturday", "sat", "5"]:
            return current_day == 5
        elif value.lower() in ["sunday", "sun", "6"]:
            return current_day == 6
        
        return False

    def _eval_confidence_threshold(self, value: float, context: RoutingContext) -> bool:
        """Evaluate confidence threshold condition."""
        # This would be set during routing evaluation
        # For now, return True as placeholder
        return True

    def _eval_kb_similarity(self, value: float, context: RoutingContext) -> bool:
        """Evaluate knowledge base similarity condition."""
        if context.kb_similarity_score is None:
            return False
        return context.kb_similarity_score >= value

    def _eval_complexity_score(self, value: float, context: RoutingContext) -> bool:
        """Evaluate complexity score condition."""
        if context.complexity_score is None:
            return False
        return context.complexity_score >= value

    def _get_field_value(self, field: str, context: RoutingContext) -> Any:
        """Get value from context by field name."""
        if field == "message":
            return context.message
        elif field == "customer_id":
            return context.customer_id
        elif field == "customer_plan" and context.customer_data:
            return context.customer_data.get("plan")
        elif field == "customer_application" and context.customer_data:
            return context.customer_data.get("application")
        elif context.customer_data and field in context.customer_data:
            return context.customer_data[field]
        return None

    def _extract_destination(self, actions: List[Dict[str, Any]], destinations: Dict[str, RoutingDestination]) -> str:
        """Extract destination from rule actions."""
        for action in actions:
            if action.get("type") == RuleActionType.ROUTE_TO:
                dest_name = action.get("destination")
                if dest_name in destinations:
                    return dest_name
                else:
                    logger.warning(f"Destination not found: {dest_name}")
        
        # Default fallback
        return "support_ai"

    def _calculate_confidence(self, rule: RoutingRule, context: RoutingContext) -> float:
        """Calculate confidence score for the routing decision."""
        # Base confidence from rule weight
        confidence = min(rule.weight, 1.0)
        
        # Boost confidence if KB similarity is high
        if context.kb_similarity_score and context.kb_similarity_score > 0.8:
            confidence = min(confidence + 0.2, 1.0)
        
        # Reduce confidence if complexity is high
        if context.complexity_score and context.complexity_score > 0.7:
            confidence = max(confidence - 0.2, 0.1)
        
        return confidence

    def _generate_reasoning(self, rule: RoutingRule, context: RoutingContext) -> str:
        """Generate human-readable reasoning for the routing decision."""
        conditions_desc = []
        for condition in rule.conditions:
            cond_type = condition.get("type")
            field = condition.get("field")
            value = condition.get("value")
            conditions_desc.append(f"{cond_type} on {field}={value}")
        
        return f"Matched rule '{rule.name}' based on: {', '.join(conditions_desc)}"

    async def _get_fallback_decision(self, context: RoutingContext, destinations: Dict[str, RoutingDestination]) -> RoutingDecision:
        """Get fallback routing decision when no rules match."""
        # Default to support_ai if available, otherwise staff
        if "support_ai" in destinations:
            destination = "support_ai"
        elif "staff" in destinations:
            destination = "staff"
        else:
            # Use first available destination
            destination = list(destinations.keys())[0] if destinations else "staff"
        
        return RoutingDecision(
            destination=destination,
            confidence=0.3,  # Low confidence for fallback
            matched_rules=[],
            actions=[],
            reasoning="No rules matched, using fallback destination",
        )

    async def _update_rule_stats(self, session, rule_id: str):
        """Update rule match statistics."""
        from sqlalchemy import update
        await session.execute(
            update(RoutingRule)
            .where(RoutingRule.id == rule_id)
            .values(
                total_matches=RoutingRule.total_matches + 1,
                last_matched_at=datetime.now(timezone.utc),
            )
        )

    def invalidate_cache(self):
        """Invalidate the rule and destination cache."""
        self._rule_cache = None
        self._destination_cache = None
        self._cache_expires_at = None
        logger.info("Routing cache invalidated")

    async def record_routing_metric(
        self,
        session,
        decision: RoutingDecision,
        context: RoutingContext,
        ticket_id: Optional[str] = None,
        chat_session_id: Optional[str] = None,
    ) -> RoutingMetric:
        """Record routing metric for analysis."""
        import uuid
        
        metric = RoutingMetric(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            chat_session_id=chat_session_id,
            rule_id=decision.matched_rules[0] if decision.matched_rules else None,
            destination=decision.destination,
            confidence_score=decision.confidence,
            message=context.message,
            customer_id=context.customer_id,
            customer_data=context.customer_data,
            was_escalated=False,  # Will be updated later
            escalation_count=0,
        )
        
        session.add(metric)
        await session.flush()
        
        return metric
