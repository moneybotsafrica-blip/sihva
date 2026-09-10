from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import structlog

from app.db.models import RoutingRule, RoutingDestination, RoutingMetric, RoutingFeedback
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = structlog.get_logger(__name__)


class RoutingRuleService:
    """Service for managing dynamic routing rules."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_rule(
        self,
        name: str,
        conditions: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
        description: Optional[str] = None,
        priority: int = 100,
        weight: float = 1.0,
        is_active: bool = True,
        created_by: Optional[str] = None,
        is_experiment: bool = False,
        parent_rule_id: Optional[str] = None,
    ) -> RoutingRule:
        """Create a new routing rule."""
        rule = RoutingRule(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            conditions=conditions,
            actions=actions,
            priority=priority,
            weight=weight,
            is_active=is_active,
            created_by=created_by,
            is_experiment=is_experiment,
            parent_rule_id=parent_rule_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        
        self.session.add(rule)
        await self.session.flush()
        
        logger.info("Routing rule created", rule_id=rule.id, name=name)
        return rule

    async def get_rule(self, rule_id: str) -> Optional[RoutingRule]:
        """Get a routing rule by ID."""
        result = await self.session.execute(
            select(RoutingRule).where(RoutingRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    async def list_rules(
        self,
        is_active: Optional[bool] = None,
        is_experiment: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RoutingRule]:
        """List routing rules with optional filters."""
        query = select(RoutingRule)
        
        if is_active is not None:
            query = query.where(RoutingRule.is_active == is_active)
        if is_experiment is not None:
            query = query.where(RoutingRule.is_experiment == is_experiment)
        
        query = query.order_by(RoutingRule.priority.asc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_rule(
        self,
        rule_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        conditions: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        priority: Optional[int] = None,
        weight: Optional[float] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[RoutingRule]:
        """Update a routing rule."""
        rule = await self.get_rule(rule_id)
        if not rule:
            return None
        
        update_data = {
            "updated_at": datetime.now(timezone.utc),
        }
        
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if conditions is not None:
            update_data["conditions"] = conditions
        if actions is not None:
            update_data["actions"] = actions
        if priority is not None:
            update_data["priority"] = priority
        if weight is not None:
            update_data["weight"] = weight
        if is_active is not None:
            update_data["is_active"] = is_active
        
        await self.session.execute(
            update(RoutingRule)
            .where(RoutingRule.id == rule_id)
            .values(**update_data)
        )
        
        await self.session.refresh(rule)
        logger.info("Routing rule updated", rule_id=rule_id)
        return rule

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a routing rule."""
        result = await self.session.execute(
            delete(RoutingRule).where(RoutingRule.id == rule_id)
        )
        success = result.rowcount > 0
        
        if success:
            logger.info("Routing rule deleted", rule_id=rule_id)
        
        return success

    async def activate_rule(self, rule_id: str) -> Optional[RoutingRule]:
        """Activate a routing rule."""
        return await self.update_rule(rule_id, is_active=True)

    async def deactivate_rule(self, rule_id: str) -> Optional[RoutingRule]:
        """Deactivate a routing rule."""
        return await self.update_rule(rule_id, is_active=False)

    async def get_rule_stats(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a routing rule."""
        rule = await self.get_rule(rule_id)
        if not rule:
            return None
        
        success_rate = 0.0
        if rule.total_matches > 0:
            success_rate = rule.successful_matches / rule.total_matches
        
        return {
            "rule_id": rule.id,
            "name": rule.name,
            "total_matches": rule.total_matches,
            "successful_matches": rule.successful_matches,
            "success_rate": success_rate,
            "last_matched_at": rule.last_matched_at,
            "is_active": rule.is_active,
        }


class RoutingDestinationService:
    """Service for managing routing destinations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_destination(
        self,
        name: str,
        display_name: str,
        destination_type: str,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        priority: int = 100,
    ) -> RoutingDestination:
        """Create a new routing destination."""
        destination = RoutingDestination(
            id=str(uuid.uuid4()),
            name=name,
            display_name=display_name,
            description=description,
            destination_type=destination_type,
            config=config,
            is_active=is_active,
            priority=priority,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        
        self.session.add(destination)
        await self.session.flush()
        
        logger.info("Routing destination created", destination_id=destination.id, name=name)
        return destination

    async def get_destination(self, destination_id: str) -> Optional[RoutingDestination]:
        """Get a routing destination by ID."""
        result = await self.session.execute(
            select(RoutingDestination).where(RoutingDestination.id == destination_id)
        )
        return result.scalar_one_or_none()

    async def get_destination_by_name(self, name: str) -> Optional[RoutingDestination]:
        """Get a routing destination by name."""
        result = await self.session.execute(
            select(RoutingDestination).where(RoutingDestination.name == name)
        )
        return result.scalar_one_or_none()

    async def list_destinations(
        self,
        is_active: Optional[bool] = None,
        destination_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RoutingDestination]:
        """List routing destinations with optional filters."""
        query = select(RoutingDestination)
        
        if is_active is not None:
            query = query.where(RoutingDestination.is_active == is_active)
        if destination_type is not None:
            query = query.where(RoutingDestination.destination_type == destination_type)
        
        query = query.order_by(RoutingDestination.priority.asc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_destination(
        self,
        destination_id: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None,
        priority: Optional[int] = None,
    ) -> Optional[RoutingDestination]:
        """Update a routing destination."""
        destination = await self.get_destination(destination_id)
        if not destination:
            return None
        
        update_data = {
            "updated_at": datetime.now(timezone.utc),
        }
        
        if display_name is not None:
            update_data["display_name"] = display_name
        if description is not None:
            update_data["description"] = description
        if config is not None:
            update_data["config"] = config
        if is_active is not None:
            update_data["is_active"] = is_active
        if priority is not None:
            update_data["priority"] = priority
        
        await self.session.execute(
            update(RoutingDestination)
            .where(RoutingDestination.id == destination_id)
            .values(**update_data)
        )
        
        await self.session.refresh(destination)
        logger.info("Routing destination updated", destination_id=destination_id)
        return destination

    async def delete_destination(self, destination_id: str) -> bool:
        """Delete a routing destination."""
        result = await self.session.execute(
            delete(RoutingDestination).where(RoutingDestination.id == destination_id)
        )
        success = result.rowcount > 0
        
        if success:
            logger.info("Routing destination deleted", destination_id=destination_id)
        
        return success


class RoutingMetricsService:
    """Service for managing routing metrics and feedback."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_metric(
        self,
        destination: str,
        message: str,
        rule_id: Optional[str] = None,
        ticket_id: Optional[str] = None,
        chat_session_id: Optional[str] = None,
        confidence_score: Optional[float] = None,
        customer_id: Optional[str] = None,
        customer_data: Optional[Dict[str, Any]] = None,
    ) -> RoutingMetric:
        """Create a routing metric."""
        metric = RoutingMetric(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            chat_session_id=chat_session_id,
            rule_id=rule_id,
            destination=destination,
            confidence_score=confidence_score,
            message=message,
            customer_id=customer_id,
            customer_data=customer_data,
            was_escalated=False,
            escalation_count=0,
            created_at=datetime.now(timezone.utc),
        )
        
        self.session.add(metric)
        await self.session.flush()
        
        return metric

    async def update_metric_outcome(
        self,
        metric_id: str,
        resolution_time_seconds: Optional[int] = None,
        first_response_time_seconds: Optional[int] = None,
        customer_satisfaction: Optional[int] = None,
        was_escalated: Optional[bool] = None,
        escalation_count: Optional[int] = None,
    ) -> Optional[RoutingMetric]:
        """Update routing metric with outcome data."""
        metric = await self.get_metric(metric_id)
        if not metric:
            return None
        
        update_data = {}
        
        if resolution_time_seconds is not None:
            update_data["resolution_time_seconds"] = resolution_time_seconds
        if first_response_time_seconds is not None:
            update_data["first_response_time_seconds"] = first_response_time_seconds
        if customer_satisfaction is not None:
            update_data["customer_satisfaction"] = customer_satisfaction
        if was_escalated is not None:
            update_data["was_escalated"] = was_escalated
        if escalation_count is not None:
            update_data["escalation_count"] = escalation_count
        if resolution_time_seconds is not None:
            update_data["resolved_at"] = datetime.now(timezone.utc)
        
        await self.session.execute(
            update(RoutingMetric)
            .where(RoutingMetric.id == metric_id)
            .values(**update_data)
        )
        
        await self.session.refresh(metric)
        return metric

    async def get_metric(self, metric_id: str) -> Optional[RoutingMetric]:
        """Get a routing metric by ID."""
        result = await self.session.execute(
            select(RoutingMetric).where(RoutingMetric.id == metric_id)
        )
        return result.scalar_one_or_none()

    async def add_feedback(
        self,
        metric_id: str,
        feedback_source: str,
        feedback_type: str,
        correct_destination: Optional[str] = None,
        comment: Optional[str] = None,
        rating: Optional[int] = None,
    ) -> RoutingFeedback:
        """Add feedback to a routing metric."""
        feedback = RoutingFeedback(
            id=str(uuid.uuid4()),
            metric_id=metric_id,
            feedback_source=feedback_source,
            feedback_type=feedback_type,
            correct_destination=correct_destination,
            comment=comment,
            rating=rating,
            created_at=datetime.now(timezone.utc),
        )
        
        self.session.add(feedback)
        await self.session.flush()
        
        logger.info("Routing feedback added", metric_id=metric_id, feedback_type=feedback_type)
        return feedback

    async def get_routing_performance(
        self,
        destination: Optional[str] = None,
        rule_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Get routing performance statistics."""
        from datetime import timedelta
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = select(RoutingMetric).where(RoutingMetric.created_at >= cutoff_date)
        
        if destination:
            query = query.where(RoutingMetric.destination == destination)
        if rule_id:
            query = query.where(RoutingMetric.rule_id == rule_id)
        
        result = await self.session.execute(query)
        metrics = list(result.scalars().all())
        
        if not metrics:
            return {
                "total_routings": 0,
                "avg_confidence": 0.0,
                "avg_resolution_time": 0.0,
                "escalation_rate": 0.0,
                "avg_customer_satisfaction": 0.0,
            }
        
        total_routings = len(metrics)
        avg_confidence = sum(m.confidence_score or 0 for m in metrics) / total_routings
        resolved_metrics = [m for m in metrics if m.resolution_time_seconds]
        avg_resolution_time = sum(m.resolution_time_seconds for m in resolved_metrics) / len(resolved_metrics) if resolved_metrics else 0
        escalation_rate = sum(1 for m in metrics if m.was_escalated) / total_routings
        satisfaction_metrics = [m for m in metrics if m.customer_satisfaction]
        avg_satisfaction = sum(m.customer_satisfaction for m in satisfaction_metrics) / len(satisfaction_metrics) if satisfaction_metrics else 0
        
        return {
            "total_routings": total_routings,
            "avg_confidence": avg_confidence,
            "avg_resolution_time": avg_resolution_time,
            "escalation_rate": escalation_rate,
            "avg_customer_satisfaction": avg_satisfaction,
        }

    async def get_routing_feedback_analytics(
        self,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Get routing feedback analytics for quality improvement."""
        from datetime import timedelta
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get all routing metrics with feedback in the period
        query = (
            select(RoutingMetric)
            .options(selectinload(RoutingMetric.feedback))
            .where(RoutingMetric.created_at >= cutoff_date)
        )
        
        result = await self.session.execute(query)
        metrics = list(result.scalars().all())
        
        if not metrics:
            return {
                "total_routings": 0,
                "total_with_feedback": 0,
                "feedback_breakdown": {},
                "incorrect_routing_rate": 0.0,
                "destination_incorrect_rates": {},
                "rule_incorrect_rates": {},
            }
        
        total_routings = len(metrics)
        metrics_with_feedback = [m for m in metrics if m.feedback]
        total_with_feedback = len(metrics_with_feedback)
        
        # Feedback breakdown
        feedback_counts = {}
        for metric in metrics_with_feedback:
            feedback_type = metric.feedback.feedback_type
            feedback_counts[feedback_type] = feedback_counts.get(feedback_type, 0) + 1
        
        incorrect_count = feedback_counts.get("incorrect", 0)
        incorrect_rate = incorrect_count / total_with_feedback if total_with_feedback > 0 else 0.0
        
        # Incorrect routing rate by destination
        destination_counts = {}
        destination_incorrect = {}
        for metric in metrics_with_feedback:
            dest = metric.destination
            destination_counts[dest] = destination_counts.get(dest, 0) + 1
            if metric.feedback.feedback_type == "incorrect":
                destination_incorrect[dest] = destination_incorrect.get(dest, 0) + 1
        
        destination_incorrect_rates = {}
        for dest, count in destination_counts.items():
            incorrect = destination_incorrect.get(dest, 0)
            destination_incorrect_rates[dest] = incorrect / count if count > 0 else 0.0
        
        # Incorrect routing rate by rule
        rule_counts = {}
        rule_incorrect = {}
        for metric in metrics_with_feedback:
            if metric.rule_id:
                rule_counts[metric.rule_id] = rule_counts.get(metric.rule_id, 0) + 1
                if metric.feedback.feedback_type == "incorrect":
                    rule_incorrect[metric.rule_id] = rule_incorrect.get(metric.rule_id, 0) + 1
        
        rule_incorrect_rates = {}
        for rule_id, count in rule_counts.items():
            incorrect = rule_incorrect.get(rule_id, 0)
            rule_incorrect_rates[rule_id] = incorrect / count if count > 0 else 0.0
        
        return {
            "total_routings": total_routings,
            "total_with_feedback": total_with_feedback,
            "feedback_breakdown": feedback_counts,
            "incorrect_routing_rate": incorrect_rate,
            "destination_incorrect_rates": destination_incorrect_rates,
            "rule_incorrect_rates": rule_incorrect_rates,
        }
