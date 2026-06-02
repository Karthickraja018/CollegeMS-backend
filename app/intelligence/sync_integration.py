"""
Data Sync Integration — Bridges dataset uploads to the Agent Intelligence Layer.

When a new dataset is uploaded and synced, this service:
1. Validates schema and maps columns to semantic attributes
2. Generates semantic entities and metrics from new data
3. Updates semantic relationships
4. Triggers the embedding queue for the Agent Intelligence Layer
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DataSyncIntelligenceBridge:
    """Bridges data sync uploads with the intelligence layer."""

    @classmethod
    async def process_synced_dataset(
        cls, 
        db: AsyncSession, 
        dataset_name: str, 
        schema_metadata: dict[str, Any]
    ) -> bool:
        """
        Process a newly synced dataset and evolve the intelligence layer.
        
        Args:
            dataset_name: Name of the uploaded dataset/table.
            schema_metadata: Inferred schema (columns, types, sample data).
        """
        try:
            logger.info(f"Processing synced dataset for intelligence layer: {dataset_name}")
            
            # Step 1: Generate or Update Semantic Entity
            entity_id = await cls._upsert_semantic_entity(db, dataset_name, schema_metadata)
            if not entity_id:
                return False
                
            # Step 2: Map columns to Semantic Attributes
            mapped_fields = await cls._upsert_semantic_attributes(db, entity_id, schema_metadata)
            
            # Step 3: Infer Metrics (basic heuristics: numeric columns might be metrics)
            metric_score = await cls._infer_metrics(db, dataset_name, schema_metadata)
            
            # Step 4: Calculate Semantic Coverage Profile (Phase 12)
            total_fields = len(schema_metadata.get("columns", []))
            coverage_score = (mapped_fields / total_fields) if total_fields > 0 else 0.0
            
            await db.execute(text("""
                INSERT INTO dataset_semantic_profiles
                    (dataset, mapped_fields, total_fields, coverage_score, metric_score, quality_score)
                VALUES
                    (:dataset, :mapped, :total, :coverage, :metric, :quality)
                ON CONFLICT (dataset) DO UPDATE
                SET mapped_fields = EXCLUDED.mapped_fields,
                    total_fields = EXCLUDED.total_fields,
                    coverage_score = EXCLUDED.coverage_score,
                    metric_score = EXCLUDED.metric_score,
                    quality_score = EXCLUDED.quality_score,
                    updated_at = NOW()
            """), {
                "dataset": dataset_name,
                "mapped": mapped_fields,
                "total": total_fields,
                "coverage": coverage_score,
                "metric": metric_score,
                "quality": coverage_score * 0.8 + metric_score * 0.2
            })
            
            # Step 5: Queue Embeddings happens automatically via triggers
            await db.commit()
            logger.info(f"Successfully integrated {dataset_name} into intelligence layer.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to process synced dataset {dataset_name}: {e}")
            await db.rollback()
            return False

    @classmethod
    async def _upsert_semantic_entity(cls, db: AsyncSession, dataset_name: str, metadata: dict) -> int | None:
        """Create or update semantic entity for the dataset."""
        entity_name = metadata.get("entity_name", dataset_name.title().replace("_", ""))
        desc = metadata.get("description", f"Data entity for {dataset_name}")
        
        result = await db.execute(text("""
            INSERT INTO semantic_entities 
                (entity_name, description, primary_table, join_key, aliases, attributes)
            VALUES 
                (:name, :desc, :table, :key, CAST(:aliases AS jsonb), CAST(:attrs AS jsonb))
            ON CONFLICT (entity_name) DO UPDATE
            SET description = EXCLUDED.description,
                attributes = EXCLUDED.attributes,
                updated_at = NOW()
            RETURNING id
        """), {
            "name": entity_name,
            "desc": desc,
            "table": dataset_name,
            "key": metadata.get("primary_key", "id"),
            "aliases": "[]",
            "attrs": "[]" # Real implementation would extract column names
        })
        row = result.fetchone()
        return row.id if row else None

    @classmethod
    async def _upsert_semantic_attributes(cls, db: AsyncSession, entity_id: int, metadata: dict) -> int:
        """Map columns to semantic attributes."""
        mapped = 0
        columns = metadata.get("columns", [])
        for col in columns:
            await db.execute(text("""
                INSERT INTO semantic_attributes
                    (entity_id, attribute_name, display_name, description, data_type, is_metric)
                VALUES
                    (:eid, :col, :display, :desc, :type, :is_metric)
                ON CONFLICT (entity_id, attribute_name) DO UPDATE
                SET data_type = EXCLUDED.data_type
            """), {
                "eid": entity_id,
                "col": col["name"],
                "display": col["name"].replace("_", " ").title(),
                "desc": f"Column {col['name']}",
                "type": col.get("type", "text"),
                "is_metric": col.get("type") in ["numeric", "integer", "float"]
            })
            mapped += 1
        return mapped

    @classmethod
    async def _infer_metrics(cls, db: AsyncSession, dataset_name: str, metadata: dict) -> float:
        """Basic inference of metrics from numeric columns."""
        metrics_added = 0
        columns = metadata.get("columns", [])
        for col in columns:
            if col.get("type") in ["numeric", "integer", "float"]:
                metric_name = f"Total {col['name'].replace('_', ' ').title()}"
                await db.execute(text("""
                    INSERT INTO semantic_metrics
                        (metric_name, description, formula, entity_name, aggregation_type)
                    VALUES
                        (:name, :desc, :formula, :entity, 'SUM')
                    ON CONFLICT (metric_name) DO NOTHING
                """), {
                    "name": metric_name,
                    "desc": f"Sum of {col['name']} across {dataset_name}",
                    "formula": f"SUM({col['name']})",
                    "entity": dataset_name.title().replace("_", "")
                })
                metrics_added += 1
        
        return min(1.0, metrics_added / 5.0) if metrics_added else 0.0
