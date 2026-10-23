import pytest
from datetime import datetime, timedelta
from pathlib import Path
import networkx as nx
from typing import Dict, Any

from api.core.knowledge.graph.graph_knowledge_service import NetworkXGraphService

@pytest.fixture
def graph_service(tmp_path: Path):
    """Create a temporary graph service for testing."""
    service = NetworkXGraphService(storage_path=tmp_path / "test_graph.pkl")
    return service

@pytest.mark.asyncio
async def test_basic_activity_storage(graph_service: NetworkXGraphService):
    """Test basic activity storage and retrieval."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    activity_id = await graph_service.store_activity(
        activity_id="test1",
        timestamp=timestamp,
        app_name="TestApp",
        window_title="Test Window",
        extracted_text="Test content",
        metadata={"category": "test"}
    )

    # Verify node exists
    assert activity_id in graph_service.graph
    node = graph_service.graph.nodes[activity_id]
    assert node["timestamp"] == timestamp
    assert node["app_name"] == "TestApp"
    assert node["window_title"] == "Test Window"
    assert node["meta_category"] == "test"

@pytest.mark.asyncio
async def test_similar_activities_linking(graph_service: NetworkXGraphService):
    """Test that similar activities are properly linked."""
    # Store two similar activities
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    activity1_id = await graph_service.store_activity(
        activity_id="test1",
        timestamp=timestamp,
        app_name="TextEditor",
        extracted_text="Python programming guide"
    )

    activity2_id = await graph_service.store_activity(
        activity_id="test2",
        timestamp=timestamp + timedelta(minutes=5),
        app_name="TextEditor",
        extracted_text="Python tutorial and guide"
    )

    # Check for SIMILAR_TO edge
    similar = await graph_service.find_similar_activities(
        content="Python programming",
        limit=2
    )
    assert len(similar) == 2
    assert all(a["similarity_score"] > 0.3 for a in similar)

@pytest.mark.asyncio
async def test_temporal_sequence_tracking(graph_service: NetworkXGraphService):
    """Test temporal sequence tracking between activities."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    # Create a sequence of activities
    activities = []
    for i in range(3):
        activity_id = await graph_service.store_activity(
            activity_id=f"seq{i}",
            timestamp=base_time + timedelta(minutes=i*2),
            app_name=f"App{i}",
            window_title=f"Window {i}"
        )
        activities.append(activity_id)

    # Check for FOLLOWED_BY edges
    for i in range(len(activities)-1):
        assert graph_service.graph.has_edge(activities[i], activities[i+1])
        edge = graph_service.graph.edges[activities[i], activities[i+1]]
        assert edge["type"] == "FOLLOWED_BY"
        assert edge["time_gap"] <= 120  # 2 minutes in seconds

@pytest.mark.asyncio
async def test_metadata_relationships(graph_service: NetworkXGraphService):
    """Test metadata-based relationships between activities."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    
    # Store activities with shared metadata
    activity1_id = await graph_service.store_activity(
        activity_id="meta1",
        timestamp=timestamp,
        app_name="TestApp",
        metadata={"project": "ProjectA", "priority": "high"}
    )

    activity2_id = await graph_service.store_activity(
        activity_id="meta2",
        timestamp=timestamp + timedelta(minutes=5),
        app_name="TestApp",
        metadata={"project": "ProjectA", "status": "active"}
    )

    # Check for SHARES_METADATA edge from newer to older activity
    assert graph_service.graph.has_edge(activity2_id, activity1_id)
    edge = graph_service.graph.edges[activity2_id, activity1_id]
    assert edge["type"] == "SHARES_METADATA"
    assert "meta_project" in edge["shared_keys"]
    assert edge["match_count"] == 1

@pytest.mark.asyncio
async def test_common_sequences(graph_service: NetworkXGraphService):
    """Test finding common activity sequences."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    # Create two similar sequences
    sequence = ["Browser", "TextEditor", "Terminal"]
    for i in range(2):  # Create sequence twice
        for j, app in enumerate(sequence):
            await graph_service.store_activity(
                activity_id=f"seq{i}{j}",
                timestamp=base_time + timedelta(hours=i, minutes=j*5),
                app_name=app,
                window_title=f"{app} Window"
            )

    # Find common sequences
    sequences = await graph_service.find_common_sequences(
        min_sequence_length=2,
        min_occurrences=2
    )
    
    assert len(sequences) > 0
    # Verify we can find at least one sequence with Browser->TextEditor
    found_sequence = False
    for seq in sequences:
        if len(seq) >= 2:
            apps = [activity["app_name"] for activity in seq]
            if apps[0] == "Browser" and apps[1] == "TextEditor":
                found_sequence = True
                break
    assert found_sequence

@pytest.mark.asyncio
async def test_next_activity_prediction(graph_service: NetworkXGraphService):
    """Test prediction of next likely activity."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    # Create a repeated pattern: Browser -> TextEditor -> Terminal
    pattern = ["Browser", "TextEditor", "Terminal"]
    for i in range(3):  # Repeat pattern 3 times
        for j, app in enumerate(pattern):
            await graph_service.store_activity(
                activity_id=f"pred{i}{j}",
                timestamp=base_time + timedelta(hours=i, minutes=j*5),
                app_name=app,
                window_title=f"{app} Window"
            )

    # Predict next activity after Browser
    prediction = await graph_service.predict_next_activity("pred01")  # First TextEditor
    assert prediction is not None
    assert prediction["app_name"] == "Terminal"
    assert prediction["confidence"] > 0

@pytest.mark.asyncio
async def test_graph_persistence(tmp_path: Path):
    """Test that graph state is properly persisted."""
    # Create service and add some data
    service1 = NetworkXGraphService(storage_path=tmp_path / "persist_test.pkl")
    await service1.store_activity(
        activity_id="persist1",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        app_name="TestApp"
    )
    
    # Create new service instance with same storage path
    service2 = NetworkXGraphService(storage_path=tmp_path / "persist_test.pkl")
    
    # Verify data persisted
    assert "persist1" in service2.graph
    assert service2.graph.nodes["persist1"]["app_name"] == "TestApp"

@pytest.mark.asyncio
async def test_activity_context_update(graph_service: NetworkXGraphService):
    """Test updating activity context information."""
    # Store initial activity
    activity_id = await graph_service.store_activity(
        activity_id="context1",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        app_name="TestApp"
    )
    
    # Update context
    new_context = {
        "project": "ProjectX",
        "status": "active",
        "priority": "high"
    }
    await graph_service.update_activity_context(activity_id, new_context)
    
    # Verify context was updated
    node = graph_service.graph.nodes[activity_id]
    assert node["context"] == new_context
    
    # Store another activity with matching context
    await graph_service.store_activity(
        activity_id="context2",
        timestamp=datetime(2024, 1, 1, 12, 5, 0),
        app_name="TestApp",
        metadata={"project": "ProjectX"}
    )
    
    # Verify metadata relationship was created
    similar = await graph_service.find_similar_activities(
        content="",
        metadata_filters={"project": "ProjectX"}
    )
    assert len(similar) > 0 