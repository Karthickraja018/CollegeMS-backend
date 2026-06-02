"""
Context Assembler — Builds the final structured context dict for AI agents.

Takes a RetrievalResult and assembles a rich, agent-ready context object that:
  - Lists relevant entities with their tables, attributes, and business rules
  - Maps terminology to DB values (CIA → cia1/cia2/cia3)
  - Provides validated join paths between entities
  - Includes top matching SQL patterns from query memory
  - Packages everything as a single JSON-serializable dict
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.intelligence.context_retrieval import RetrievalResult, RetrievedEntity, EntityRelationship

logger = logging.getLogger(__name__)


class ContextAssembler:
    """
    Converts a RetrievalResult into a structured context dict
    that AI agents can consume directly in their prompts.
    """

    def assemble(
        self,
        retrieval: RetrievalResult,
        agent_type: str = "query",
    ) -> dict[str, Any]:
        """
        Build the final context dictionary.

        Returns:
        {
            "entities": [{ name, table, key_column, attributes, rules }],
            "join_paths": ["JOIN departments d ON d.id = s.department_id"],
            "terminology": { "CIA": { full_form, definition, db_mapping }, ... },
            "query_examples": [{ question, sql, tables, entities }],
            "business_rules": ["Minimum attendance is 75%", ...],
            "schema_summary": "text summary for LLM context",
            "meta": { retrieval_ms, embedding_ms, entities_found, ... }
        }
        """
        context: dict[str, Any] = {
            "entities": [],
            "join_paths": [],
            "terminology": {},
            "query_examples": [],
            "business_rules": [],
            "schema_summary": "",
            "meta": {
                "retrieval_ms": retrieval.retrieval_ms,
                "embedding_ms": retrieval.embedding_ms,
                "entities_found": len(retrieval.entities),
                "terms_found": len(retrieval.terminology),
                "queries_found": len(retrieval.query_examples),
                "agent_type": agent_type,
                "question": retrieval.question,
            }
        }

        # ── Entities ──────────────────────────────────────────────────────
        for entity in retrieval.entities:
            context["entities"].append(self._format_entity(entity))

        # ── Terminology ───────────────────────────────────────────────────
        for term in retrieval.terminology:
            context["terminology"][term.term] = {
                "full_form": term.full_form,
                "definition": term.definition,
                "category": term.category,
                "db_mapping": term.db_mapping,
                "db_table": term.db_table,
                "aliases": term.aliases,
                "similarity": round(term.similarity, 3),
            }

        # ── Join paths (deduplicated) ─────────────────────────────────────
        seen_joins: set[str] = set()
        for rel in sorted(retrieval.relationships, key=lambda r: -r.confidence):
            join_normalized = rel.join_sql.strip()
            if join_normalized not in seen_joins:
                context["join_paths"].append({
                    "from": rel.from_entity,
                    "type": rel.relationship,
                    "to": rel.to_entity,
                    "sql": join_normalized,
                    "description": rel.description,
                    "confidence": rel.confidence,
                })
                seen_joins.add(join_normalized)

        # ── Query examples ─────────────────────────────────────────────────
        for qe in retrieval.query_examples:
            context["query_examples"].append({
                "question": qe.question,
                "sql": qe.generated_sql,
                "entities_used": qe.entities_used,
                "tables_used": qe.tables_used,
                "query_type": qe.query_type,
                "similarity": round(qe.similarity, 3),
            })

        # ── Business Rules (deduplicated from all entities) ────────────────
        seen_rules: set[str] = set()
        for entity in retrieval.entities:
            for rule in entity.business_rules:
                if rule not in seen_rules:
                    context["business_rules"].append(rule)
                    seen_rules.add(rule)

        # ── Schema Summary (text for LLM prompt injection) ────────────────
        context["schema_summary"] = self._build_schema_summary(context, agent_type)

        return context

    def _format_entity(self, entity: RetrievedEntity) -> dict[str, Any]:
        """Format a single entity for the context dict."""
        return {
            "name": entity.entity_name,
            "description": entity.description,
            "primary_table": entity.primary_table,
            "key_column": entity.join_key or "id",
            "attributes": entity.attributes,
            "aliases": entity.aliases,
            "business_rules": entity.business_rules,
            "similarity": round(entity.similarity, 3),
        }

    def _build_schema_summary(
        self, context: dict[str, Any], agent_type: str
    ) -> str:
        """
        Build a concise text summary of the context for injection into LLM prompts.
        This replaces raw schema dumps.
        """
        parts: list[str] = []

        # Entities section
        if context["entities"]:
            parts.append("=== RELEVANT ENTITIES ===")
            for e in context["entities"]:
                attrs_preview = ", ".join(e["attributes"][:10])
                if len(e["attributes"]) > 10:
                    attrs_preview += f" ... (+{len(e['attributes'])-10} more)"
                parts.append(
                    f"• {e['name']} (table: {e['primary_table']})\n"
                    f"  Description: {e['description']}\n"
                    f"  Key columns: {attrs_preview}"
                )

        # Terminology section
        if context["terminology"]:
            parts.append("\n=== ACADEMIC TERMINOLOGY ===")
            for term, info in context["terminology"].items():
                full_form = f" ({info['full_form']})" if info.get("full_form") else ""
                db_map = f" → DB value: {info['db_mapping']}" if info.get("db_mapping") else ""
                parts.append(f"• {term}{full_form}: {info['definition']}{db_map}")

        # Business rules
        if context["business_rules"]:
            parts.append("\n=== BUSINESS RULES ===")
            for rule in context["business_rules"][:8]:  # Top 8 rules
                parts.append(f"• {rule}")

        # Join paths
        if context["join_paths"]:
            parts.append("\n=== JOIN PATHS ===")
            for jp in context["join_paths"][:8]:
                parts.append(f"• {jp['from']} → {jp['to']}: {jp['sql']}")

        # Query examples
        if context["query_examples"]:
            parts.append("\n=== RELEVANT PAST QUERIES (use as SQL patterns) ===")
            for i, qe in enumerate(context["query_examples"][:3]):
                parts.append(
                    f"\nExample {i+1}: \"{qe['question']}\"\n"
                    f"Tables used: {', '.join(qe['tables_used'])}\n"
                    f"SQL:\n{qe['sql']}"
                )

        if not parts:
            return "No semantic context retrieved. Use general academic database knowledge."

        return "\n".join(parts)

    def assemble_for_prompt(
        self,
        retrieval: RetrievalResult,
        agent_type: str = "query",
    ) -> str:
        """
        Convenience method — returns just the schema_summary string
        for direct injection into LLM prompts.
        """
        ctx = self.assemble(retrieval, agent_type)
        return ctx["schema_summary"]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_assembler: Optional[ContextAssembler] = None


def get_context_assembler() -> ContextAssembler:
    """Return the singleton ContextAssembler instance."""
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler()
    return _assembler
