"""Initial generic food catalog schema."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("group_name", sa.String(length=180), nullable=True),
        sa.Column("subgroup_name", sa.String(length=180), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_food_active", "food", ["active"])
    op.create_index("ix_food_group_name", "food", ["group_name"])
    op.create_index("ix_food_normalized_name", "food", ["normalized_name"])
    op.create_index("ix_food_subgroup_name", "food", ["subgroup_name"])

    op.create_table(
        "source_import",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_version", sa.String(length=80), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_version", "file_sha256", name="uq_source_import_version_hash"),
    )
    op.create_index("ix_source_import_source", "source_import", ["source"])
    op.create_index("ix_source_import_source_version", "source_import", ["source_version"])

    op.create_table(
        "food_alias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("normalized_value", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["food_id"], ["food.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("food_id", "normalized_value", name="uq_food_alias_food_value"),
    )
    op.create_index("ix_food_alias_food_id", "food_alias", ["food_id"])
    op.create_index("ix_food_alias_normalized_value", "food_alias", ["normalized_value"])

    op.create_table(
        "food_tag",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["food_id"], ["food.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("food_id", "value", name="uq_food_tag_food_value"),
    )
    op.create_index("ix_food_tag_food_id", "food_tag", ["food_id"])
    op.create_index("ix_food_tag_value", "food_tag", ["value"])

    op.create_table(
        "nutrition_reference",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("external_code", sa.String(length=80), nullable=False),
        sa.Column("source_version", sa.String(length=80), nullable=False),
        sa.Column("carbs_per_100g", sa.Float(), nullable=True),
        sa.Column("raw_value", sa.String(length=80), nullable=False),
        sa.Column("qualifier", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license_name", sa.String(length=120), nullable=True),
        sa.Column("preferred", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["food_id"], ["food.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "external_code",
            "source_version",
            name="uq_nutrition_reference_source_code_version",
        ),
    )
    op.create_index("ix_nutrition_reference_external_code", "nutrition_reference", ["external_code"])
    op.create_index("ix_nutrition_reference_food_id", "nutrition_reference", ["food_id"])
    op.create_index("ix_nutrition_reference_preferred", "nutrition_reference", ["preferred"])
    op.create_index("ix_nutrition_reference_source", "nutrition_reference", ["source"])
    op.create_index("ix_nutrition_reference_source_version", "nutrition_reference", ["source_version"])


def downgrade() -> None:
    op.drop_table("nutrition_reference")
    op.drop_table("food_tag")
    op.drop_table("food_alias")
    op.drop_table("source_import")
    op.drop_table("food")
