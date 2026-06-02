import os
import yaml
from typing import Dict, List, Optional
from pydantic import BaseModel

class ColumnDef(BaseModel):
    type: str
    pk: bool = False
    fk: Optional[str] = None
    nullable: bool = True
    enum_values: Optional[List[str]] = None
    lookup: bool = False
    lookup_limit: int = 20

class TableDef(BaseModel):
    description: Optional[str] = None
    columns: Dict[str, ColumnDef]

class SchemaDef(BaseModel):
    tables: Dict[str, TableDef]

class AppConfig:
    _schema: Optional[SchemaDef] = None

    @classmethod
    def load_schema(cls, schema_path: Optional[str] = None) -> SchemaDef:
        if cls._schema is not None and schema_path is None:
            return cls._schema
            
        if schema_path is None:
            # Default schema.yaml location next to this file
            schema_path = os.path.join(os.path.dirname(__file__), "schema.yaml")

        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    cls._schema = SchemaDef(**data)
                else:
                    cls._schema = SchemaDef(tables={})
        else:
            cls._schema = SchemaDef(tables={})
            
        return cls._schema

    @classmethod
    def get_schema(cls) -> SchemaDef:
        if cls._schema is None:
            cls.load_schema()
        return cls._schema
