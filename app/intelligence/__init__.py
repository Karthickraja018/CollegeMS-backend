"""
Agent Intelligence Layer — Package Init
Provides semantic context to all AI agents in CollegeMS.
"""
from app.intelligence.embedding_service import EmbeddingService, get_embedding_service
from app.intelligence.context_retrieval import ContextRetrievalService
from app.intelligence.context_assembler import ContextAssembler
from app.intelligence.agent_context_bus import AgentContextBus, get_context_bus

__all__ = [
    "EmbeddingService",
    "get_embedding_service",
    "ContextRetrievalService",
    "ContextAssembler",
    "AgentContextBus",
    "get_context_bus",
]
