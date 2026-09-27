"""Graph-based knowledge service using NetworkX."""

import networkx as nx  # type: ignore[import-untyped]
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import pickle


class NetworkXGraphService:
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        """Initialize the graph service.

        Args:
            storage_path: Path to store the serialized graph
        """
        if storage_path is None:
            storage_path = Path.home() / ".basil" / "graph.pkl"

        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize or load existing graph
        self.graph = self._load_graph()

    def _load_graph(self) -> nx.DiGraph:
        """Load graph from disk or create new one."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"Error loading graph: {e}, creating new one")

        return nx.DiGraph()

    def _save_graph(self) -> None:
        """Save graph to disk."""
        with open(self.storage_path, "wb") as f:
            pickle.dump(self.graph, f)

    async def store_activity(
        self,
        activity_id: str,
        timestamp: datetime,
        app_name: str,
        window_title: Optional[str] = None,
        extracted_text: Optional[str] = None,
        ai_analysis: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Store activity node in graph.
        
        Args:
            activity_id: Unique identifier for the activity
            timestamp: When the activity occurred
            app_name: Name of the application
            window_title: Title of the window
            extracted_text: Extracted text content
            ai_analysis: AI-generated analysis
            metadata: Additional metadata key-value pairs
        """
        print(f"Storing activity {activity_id} with metadata: {metadata}")
        
        # Ensure timestamp is a datetime object
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp)
                print(f"Converted timestamp from string to datetime: {timestamp}")
            except Exception as e:
                print(f"Error converting timestamp: {e}")
                print(f"Original timestamp: {timestamp} ({type(timestamp)})")
        
        # Create base node with properties
        node_data = {
            "timestamp": timestamp,  # Store as datetime object
            "app_name": app_name,
            "window_title": window_title,
            "extracted_text": extracted_text,
            "ai_analysis": json.dumps(ai_analysis) if ai_analysis else None,
        }
        
        # Add metadata if provided
        if metadata:
            print(f"Processing metadata for {activity_id}")
            # Store metadata as properties prefixed with 'meta_' to avoid collisions
            for key, value in metadata.items():
                if isinstance(value, dict) and 'value' in value:
                    # Handle confidence-weighted metadata
                    node_data[f"meta_{key}"] = value['value']
                    node_data[f"meta_{key}_confidence"] = value.get('confidence', 1.0)
                else:
                    node_data[f"meta_{key}"] = value
                print(f"Added metadata {key}: {value}")

        # Add node to graph
        self.graph.add_node(activity_id, **node_data)
        print(f"Added node {activity_id} with data: {node_data}")

        # Link metadata relationships first
        if metadata:
            print(f"Linking metadata relationships for {activity_id}")
            await self._link_metadata_relationships(activity_id)

        # Find and link to similar activities
        if extracted_text:
            print(f"Linking similar activities for {activity_id}")
            await self._link_similar_activities(activity_id)

        # Find and link temporal sequences last
        print(f"Updating activity sequences for {activity_id}")
        await self._update_activity_sequences(activity_id)

        # Save changes
        self._save_graph()
        print(f"Saved graph after storing {activity_id}")

        return activity_id

    async def _link_similar_activities(self, activity_id: str) -> None:
        """Find and link similar activities."""
        current = self.graph.nodes[activity_id]
        current_text = current.get("extracted_text", "")

        if not current_text:
            return

        # Find similar activities using text similarity
        for node_id, data in self.graph.nodes(data=True):
            if node_id == activity_id:
                continue

            other_text = data.get("extracted_text", "")
            if not other_text:
                continue

            # Simple word overlap similarity
            current_words = set(current_text.lower().split())
            other_words = set(other_text.lower().split())
            
            # Calculate Jaccard similarity
            intersection = len(current_words & other_words)
            union = len(current_words | other_words)
            
            # Boost similarity for activities with more shared words
            similarity = intersection / union
            if intersection >= 2:  # If at least 2 words match
                similarity = min(1.0, similarity * 1.5)  # Boost similarity but cap at 1.0

            if similarity > 0.2:  # Lower threshold for better matching
                self.graph.add_edge(activity_id, node_id, type="SIMILAR_TO", weight=similarity)

    async def _update_activity_sequences(self, activity_id: str) -> None:
        """Update temporal activity sequences."""
        print(f"\nUpdating sequences for activity {activity_id}")
        current = self.graph.nodes[activity_id]
        current_time = current["timestamp"]
        
        # Find activities in the last 5 minutes
        for node_id, data in self.graph.nodes(data=True):
            if node_id == activity_id:
                continue

            # Skip if there's already a metadata relationship
            has_metadata = False
            # Check edges in both directions
            if self.graph.has_edge(activity_id, node_id):
                edge_data = self.graph.edges[activity_id, node_id]
                if edge_data.get("type") == "SHARES_METADATA":
                    has_metadata = True
            if self.graph.has_edge(node_id, activity_id):
                edge_data = self.graph.edges[node_id, activity_id]
                if edge_data.get("type") == "SHARES_METADATA":
                    has_metadata = True

            if has_metadata:
                print(f"Skipping temporal edge for {node_id} due to metadata relationship")
                continue

            other_time = data["timestamp"]
            
            try:
                # Check if timestamps need to be parsed
                if isinstance(other_time, str):
                    other_time = datetime.fromisoformat(other_time)
                
                if isinstance(current_time, str):
                    current_time = datetime.fromisoformat(current_time)
                
                time_diff = (current_time - other_time).total_seconds()

                if 0 < time_diff <= 300:  # 5 minutes
                    print(f"Adding FOLLOWED_BY edge from {node_id} to {activity_id}")
                    self.graph.add_edge(node_id, activity_id, type="FOLLOWED_BY", time_gap=time_diff)
            except Exception as e:
                print(f"Error calculating time difference: {e}")
                print(f"current_time: {current_time} ({type(current_time)})")
                print(f"other_time: {other_time} ({type(other_time)})")

    async def find_similar_activities(
        self,
        content: str,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Find similar activities using graph relationships.
        
        Args:
            content: The text content to match against
            app_name: Optional app name to filter by
            window_title: Optional window title to filter by
            metadata_filters: Optional metadata key-value pairs to filter by
            limit: Maximum number of results to return
        """
        similar_activities = []

        # Convert nodes to activity records
        for node_id, data in self.graph.nodes(data=True):
            # Apply metadata filters if provided
            if metadata_filters:
                matches_metadata = True
                for key, value in metadata_filters.items():
                    meta_key = f"meta_{key}"
                    if data.get(meta_key) != value:
                        matches_metadata = False
                        break
                if not matches_metadata:
                    continue

            other_text = data.get("extracted_text", "")
            if not other_text and not metadata_filters:
                continue

            # Apply other filters if provided
            if app_name and data.get("app_name") != app_name:
                continue
            if window_title and data.get("window_title") != window_title:
                continue

            # Calculate text similarity if content provided
            text_similarity = 0.0
            if content and other_text:
                current_words = set(content.lower().split())
                other_words = set(other_text.lower().split())
                if current_words and other_words:
                    # Calculate Jaccard similarity
                    intersection = len(current_words & other_words)
                    union = len(current_words | other_words)
                    
                    # Boost similarity for activities with more shared words
                    text_similarity = intersection / union
                    if intersection >= 2:  # If at least 2 words match
                        text_similarity = min(1.0, text_similarity * 1.5)  # Boost similarity but cap at 1.0

            # Check for existing SIMILAR_TO edges
            similar_edges = [
                (e, d) for _, e, d in self.graph.edges(node_id, data=True)
                if d.get("type") == "SIMILAR_TO"
            ]
            if similar_edges:
                # Use the highest similarity from connected nodes
                edge_similarity = max(d.get("weight", 0) for _, d in similar_edges)
                text_similarity = max(text_similarity, edge_similarity)

            # Calculate metadata similarity if available
            metadata_similarity = 0.0
            metadata_edges = [
                (e, d) for _, e, d in self.graph.edges(node_id, data=True)
                if d.get("type") == "SHARES_METADATA"
            ]
            if metadata_edges:
                # Use the highest metadata similarity from connected nodes
                metadata_similarity = max(
                    d.get("match_count", 0) / max(len(d.get("shared_keys", [])), 1)
                    for _, d in metadata_edges
                )

            # Combined similarity score (70% text, 30% metadata if available)
            similarity = text_similarity * 0.7 + metadata_similarity * 0.3

            # If using metadata filters, include all matches
            if metadata_filters and matches_metadata:
                similarity = max(similarity, 0.3)

            if similarity > 0.2:  # Lower threshold to match _link_similar_activities
                # Extract metadata from node
                metadata = {
                    k.replace('meta_', ''): v
                    for k, v in data.items()
                    if k.startswith('meta_') and not k.endswith('_confidence')
                }
                
                activity = {
                    "id": node_id,
                    "timestamp": data["timestamp"],
                    "app_name": data["app_name"],
                    "window_title": data.get("window_title"),
                    "extracted_text": other_text,
                    "ai_analysis": (
                        json.loads(data["ai_analysis"]) if data.get("ai_analysis") else None
                    ),
                    "metadata": metadata,
                    "similarity_score": similarity,
                }
                similar_activities.append(activity)

        # Sort by similarity and limit results
        similar_activities.sort(key=lambda x: x["similarity_score"], reverse=True)
        return similar_activities[:limit]

    async def find_common_sequences(
        self, min_sequence_length: int = 2, min_occurrences: int = 2
    ) -> List[List[Dict[str, Any]]]:
        """Find common sequences of activities."""
        sequences = []

        # Use NetworkX to find simple paths
        for source in self.graph.nodes():
            for target in self.graph.nodes():
                if source == target:
                    continue

                # Find paths between nodes
                paths = list(
                    nx.all_simple_paths(self.graph, source, target, cutoff=min_sequence_length)
                )

                for path in paths:
                    if len(path) >= min_sequence_length:
                        sequence = []
                        for node_id in path:
                            data = self.graph.nodes[node_id]
                            sequence.append(
                                {
                                    "app_name": data["app_name"],
                                    "window_title": data.get("window_title"),
                                    "timestamp": data["timestamp"],
                                }
                            )
                        sequences.append(sequence)

        return sequences

    async def predict_next_activity(self, current_activity_id: str) -> Optional[Dict[str, Any]]:
        """Predict next likely activity based on patterns."""
        if current_activity_id not in self.graph:
            return None

        # Find all "FOLLOWED_BY" edges from this activity
        successors = []
        for _, next_id, data in self.graph.edges(current_activity_id, data=True):
            if data.get("type") == "FOLLOWED_BY":
                next_data = self.graph.nodes[next_id]
                successors.append(
                    {
                        "id": next_id,
                        "app_name": next_data["app_name"],
                        "window_title": next_data.get("window_title"),
                        "frequency": data.get("frequency", 1),
                    }
                )

        if not successors:
            return None

        # Return most frequent successor
        most_frequent = max(successors, key=lambda x: x["frequency"])
        return {
            "app_name": most_frequent["app_name"],
            "window_title": most_frequent["window_title"],
            "confidence": most_frequent["frequency"] / sum(s["frequency"] for s in successors),
        }

    async def _link_metadata_relationships(self, activity_id: str) -> None:
        """Link activities that share metadata."""
        print(f"\nLinking metadata for activity {activity_id}")
        current = self.graph.nodes[activity_id]
        current_metadata = {k: v for k, v in current.items() if k.startswith("meta_")}
        print(f"Current metadata: {current_metadata}")

        if not current_metadata:
            print("No metadata found, skipping")
            return

        # Remove any existing temporal edges for this node
        edges_to_remove = []
        for _, other_id, edge_data in self.graph.edges(activity_id, data=True):
            if edge_data.get("type") == "FOLLOWED_BY":
                edges_to_remove.append((activity_id, other_id))
                print(f"Will remove outgoing temporal edge to {other_id}")
        for other_id, _, edge_data in self.graph.in_edges(activity_id, data=True):
            if edge_data.get("type") == "FOLLOWED_BY":
                edges_to_remove.append((other_id, activity_id))
                print(f"Will remove incoming temporal edge from {other_id}")
        
        for edge in edges_to_remove:
            if self.graph.has_edge(*edge):
                print(f"Removing temporal edge {edge}")
                self.graph.remove_edge(*edge)

        for node_id, data in self.graph.nodes(data=True):
            if node_id == activity_id:
                continue

            other_metadata = {k: v for k, v in data.items() if k.startswith("meta_")}
            if not other_metadata:
                continue

            print(f"\nComparing with node {node_id}")
            print(f"Other metadata: {other_metadata}")

            # Find shared metadata keys
            shared_keys = set(current_metadata.keys()) & set(other_metadata.keys())
            matching_values = sum(
                1 for k in shared_keys
                if current_metadata[k] == other_metadata[k]
            )

            print(f"Shared keys: {shared_keys}")
            print(f"Matching values: {matching_values}")

            if matching_values > 0:
                print(f"Found matching metadata with {node_id}")
                # Remove any existing temporal edges between these nodes
                if self.graph.has_edge(activity_id, node_id):
                    print(f"Removing existing edge from {activity_id} to {node_id}")
                    self.graph.remove_edge(activity_id, node_id)
                if self.graph.has_edge(node_id, activity_id):
                    print(f"Removing existing edge from {node_id} to {activity_id}")
                    self.graph.remove_edge(node_id, activity_id)

                # Add metadata edge
                print(f"Adding SHARES_METADATA edge between {activity_id} and {node_id}")
                self.graph.add_edge(
                    activity_id,
                    node_id,
                    type="SHARES_METADATA",
                    shared_keys=list(shared_keys),
                    match_count=matching_values
                )

    async def update_activity_context(
        self,
        activity_id: str,
        context: Dict[str, Any]
    ) -> None:
        """Update an activity's context information in the graph.
        
        Args:
            activity_id: The ID of the activity to update
            context: New context information to store
        """
        try:
            # Update node attributes if it exists
            if self.graph.has_node(activity_id):
                self.graph.nodes[activity_id]['context'] = context
                self._save_graph()
                
                # Update relationships based on new context
                await self._link_metadata_relationships(activity_id)
                await self._link_similar_activities(activity_id)
                await self._update_activity_sequences(activity_id)
            
        except Exception as e:
            print(f"Error updating activity context in graph: {e}")
            raise
