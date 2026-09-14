"""Quick import check for Private Domain module"""
import sys
sys.path.insert(0, 'H:/AI-Agent-Platform/backend')

print("Testing imports...")

# Test models
try:
    from app.db.models.private_domain import (
        PrivateChannel, NurturePlan, ContentItem, FollowUpTask,
        CustomerSegment, DealPipeline, DealStage, DealItem
    )
    print("✓ Models imported successfully")
except Exception as e:
    print(f"✗ Model import failed: {e}")

# Test schemas
try:
    from app.schemas.private_domain import (
        PrivateChannelCreate, NurturePlanCreate, ContentItemCreate,
        FollowUpTaskCreate, CustomerSegmentCreate, DealPipelineCreate
    )
    print("✓ Schemas imported successfully")
except Exception as e:
    print(f"✗ Schema import failed: {e}")

# Test services
try:
    from app.services.private_domain import (
        get_private_channels, create_private_channel,
        get_nurture_plans, create_nurture_plan
    )
    print("✓ Services imported successfully")
except Exception as e:
    print(f"✗ Service import failed: {e}")

# Test routers
try:
    from app.routers.private_domain import router
    print("✓ Router imported successfully")
except Exception as e:
    print(f"✗ Router import failed: {e}")

# Test main app
try:
    from app.main import app
    print("✓ Main app imported successfully")
    print(f"\nApp title: {app.title}")
    print(f"Routes count: {len(app.routes)}")
except Exception as e:
    print(f"✗ Main app import failed: {e}")

print("\nAll imports completed!")
