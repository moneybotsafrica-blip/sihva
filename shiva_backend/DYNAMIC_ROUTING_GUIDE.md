# Dynamic Routing System Guide

## Overview

The Shiva Support Platform now features a fully dynamic routing system that replaces static pattern matching with database-driven, configurable routing rules. This enables runtime rule updates, A/B testing, and continuous improvement without code deployments.

## Architecture

### Core Components

1. **Database Models** (`app/db/models.py`)
   - `RoutingDestination`: Available routing targets (support_ai, code_ai, staff, etc.)
   - `RoutingRule`: Configurable routing rules with conditions and actions
   - `RoutingMetric`: Performance tracking for routing decisions
   - `RoutingFeedback`: Feedback collection for continuous improvement

2. **Dynamic Router** (`app/ai_router/dynamic_router.py`)
   - Rule evaluation engine with multiple condition types
   - Priority-based rule matching
   - Confidence scoring
   - Caching for performance

3. **Routing Services** (`app/ai_router/routing_service.py`)
   - `RoutingRuleService`: CRUD operations for routing rules
   - `RoutingDestinationService`: Manage routing destinations
   - `RoutingMetricsService`: Track performance and collect feedback

4. **Updated Classifier** (`app/ai_router/classifier.py`)
   - Backward compatible with static routing
   - Optional dynamic routing via `use_dynamic_routing=True`
   - Automatic fallback to static patterns

5. **API Endpoints** (`app/main.py`)
   - Full REST API for managing rules, destinations, metrics, and feedback
   - Swagger documentation at `/docs`

## Condition Types

The dynamic router supports 14 condition types:

1. **Text Matching**
   - `contains`: Field contains value (case-insensitive by default)
   - `regex`: Regular expression match
   - `exact_match`: Exact string match

2. **Length Analysis**
   - `length_greater_than`: Field length > value
   - `length_less_than`: Field length < value

3. **Attachment Analysis**
   - `has_attachment`: Message has any attachment
   - `attachment_type`: Has specific attachment type (.log, .png, etc.)

4. **Customer Context**
   - `customer_plan`: Customer subscription plan matches
   - Time-based: `time_of_day`, `day_of_week`

5. **AI Context**
   - `confidence_threshold`: AI confidence above threshold
   - `kb_similarity`: Knowledge base similarity score
   - `complexity_score`: Message complexity score

## Action Types

Rules can trigger multiple actions:

1. **route_to**: Route to specific destination
2. **set_priority**: Set routing priority
3. **add_tag**: Add metadata tags
4. **escalate**: Force escalation to staff
5. **require_human**: Require human intervention
6. **use_ai_model**: Specify AI model to use
7. **call_webhook**: Trigger external webhook

## API Endpoints

### Rule Management
- `POST /routing/rules` - Create new routing rule
- `GET /routing/rules` - List routing rules (with filters)
- `GET /routing/rules/{rule_id}` - Get specific rule
- `PUT /routing/rules/{rule_id}` - Update rule
- `DELETE /routing/rules/{rule_id}` - Delete rule
- `POST /routing/rules/{rule_id}/activate` - Activate rule
- `POST /routing/rules/{rule_id}/deactivate` - Deactivate rule
- `GET /routing/rules/{rule_id}/stats` - Get rule statistics

### Destination Management
- `POST /routing/destinations` - Create destination
- `GET /routing/destinations` - List destinations
- `PUT /routing/destinations/{destination_id}` - Update destination
- `DELETE /routing/destinations/{destination_id}` - Delete destination

### Metrics & Feedback
- `GET /routing/metrics/performance` - Get performance statistics
- `POST /routing/feedback` - Add routing feedback

### Streaming Endpoints
- `POST /routing/stream` - **NEW**: Stream routing decision analysis in real-time
- `POST /test-groq-analysis` - **UPDATED**: Now supports streaming with `stream: true` parameter

## Setup Instructions

### 1. Run Database Migration

```bash
cd shiva_backend
alembic upgrade head
```

This will create the new routing tables: `routing_destinations`, `routing_rules`, `routing_metrics`, `routing_feedback`.

### 2. Initialize Default Rules

```bash
python init_routing_rules.py
```

This creates default routing rules that mirror the static patterns from the legacy classifier:
- Greeting detection → Support AI
- HTTP error codes → Code AI
- Stack traces → Code AI
- Technical trigger phrases → Code AI
- Log attachments → Code AI
- High KB similarity → Support AI

### 3. Enable Dynamic Routing

Update your `AIRouter` initialization:

```python
from app.ai_router.classifier import AIRouter

# Enable dynamic routing
router = AIRouter(
    qdrant_client=qdrant_client,
    use_dynamic_routing=True,  # Enable dynamic routing
)

# Use in async context
decision = await router.classify(
    message="I need help with my dashboard",
    session=db_session,  # Required for dynamic routing
    customer_id="cust_123",
    customer_data={"plan": "enterprise", "application": "shiva_analytics"},
)
```

## Example Rules

### Rule 1: Greeting Detection

```json
{
  "name": "Greeting Detection",
  "description": "Routes greetings to Support AI",
  "conditions": [
    {
      "type": "contains",
      "field": "message",
      "value": "hello",
      "case_sensitive": false
    }
  ],
  "actions": [
    {
      "type": "route_to",
      "destination": "support_ai"
    }
  ],
  "priority": 1,
  "weight": 1.0,
  "is_active": true
}
```

### Rule 2: Technical Issue with Log Attachment

```json
{
  "name": "Technical Issue with Log",
  "description": "Routes technical issues with log attachments to Code AI",
  "conditions": [
    {
      "type": "contains",
      "field": "message",
      "value": "error"
    },
    {
      "type": "attachment_type",
      "value": ".log"
    }
  ],
  "actions": [
    {
      "type": "route_to",
      "destination": "code_ai"
    },
    {
      "type": "set_priority",
      "priority": 1
    }
  ],
  "priority": 10,
  "weight": 0.9,
  "is_active": true
}
```

### Rule 3: Enterprise Customer Priority

```json
{
  "name": "Enterprise Customer Priority",
  "description": "Prioritizes enterprise customers",
  "conditions": [
    {
      "type": "customer_plan",
      "value": "enterprise"
    }
  ],
  "actions": [
    {
      "type": "set_priority",
      "priority": 1
    }
  ],
  "priority": 5,
  "weight": 0.8,
  "is_active": true
}
```

### Rule 4: Business Hours Routing

```json
{
  "name": "Business Hours Support",
  "description": "Routes to staff during business hours",
  "conditions": [
    {
      "type": "day_of_week",
      "value": "weekday"
    },
    {
      "type": "time_of_day",
      "value": "09:00-17:00"
    }
  ],
  "actions": [
    {
      "type": "route_to",
      "destination": "staff"
    }
  ],
  "priority": 15,
  "weight": 0.7,
  "is_active": true
}
```

## Advanced Features

### A/B Testing

Create experiment rules by setting `is_experiment: true` and referencing a parent rule:

```json
{
  "name": "Greeting Detection - Experiment",
  "description": "A/B test variant of greeting detection",
  "conditions": [...],
  "actions": [...],
  "is_experiment": true,
  "parent_rule_id": "original_rule_id",
  "priority": 1,
  "weight": 0.5
}
```

### Performance Tracking

The system automatically tracks:
- Total matches per rule
- Successful matches (positive outcomes)
- Last matched timestamp
- Resolution times
- Customer satisfaction scores
- Escalation rates

Access via API:
```bash
GET /routing/metrics/performance?rule_id=rule_123&days=30
```

### Feedback Collection

Collect feedback on routing decisions:

```bash
POST /routing/feedback
{
  "metric_id": "metric_123",
  "feedback_source": "staff",
  "feedback_type": "incorrect",
  "correct_destination": "code_ai",
  "comment": "This was actually a code issue",
  "rating": 2
}
```

## Migration from Static Routing

The system is fully backward compatible. You can:

1. **Keep static routing**: Don't set `use_dynamic_routing=True`
2. **Gradual migration**: Enable dynamic routing but keep static fallback
3. **Full migration**: Enable dynamic routing and retire static patterns

The initialization script automatically converts your static patterns into dynamic rules, maintaining the same behavior.

## Monitoring and Optimization

### Monitor Rule Performance

```bash
# Get rule statistics
GET /routing/rules/{rule_id}/stats

# Get overall performance
GET /routing/metrics/performance?days=7
```

### Optimize Rules

1. **Check success rates**: Low success rates indicate poor rule quality
2. **Review feedback**: Look for patterns in incorrect routing
3. **A/B test**: Create experiment variants to test improvements
4. **Adjust weights**: Increase weights for high-performing rules

### Cache Management

The dynamic router caches rules for 5 minutes. To force cache refresh:

```python
router.dynamic_router.invalidate_cache()
```

## Troubleshooting

### Rules Not Matching

1. Check rule is active: `is_active: true`
2. Verify conditions are correct
3. Check priority (lower numbers = higher priority)
4. Review rule evaluation order
5. Check cache (invalidate if needed)

### Database Errors

1. Ensure migration ran: `alembic upgrade head`
2. Check database connection
3. Verify session is passed to `classify()`

### Performance Issues

1. Monitor cache hit rate
2. Consider reducing rule complexity
3. Use indexes on frequently queried fields
4. Review rule count (too many rules can slow evaluation)

## Future Enhancements

Planned features for the dynamic routing system:

1. **ML-Based Routing**: Learn optimal routing from historical data
2. **Auto-Rule Generation**: Suggest rules based on patterns
3. **Real-time Analytics**: Dashboard for routing performance
4. **Rule Templates**: Pre-built rule templates for common scenarios
5. **Integration Testing**: Test rules against historical messages

## Support

For issues or questions about the dynamic routing system:
- Check API documentation at `/docs`
- Review rule statistics in the database
- Enable debug logging for detailed rule evaluation
- Contact the development team
