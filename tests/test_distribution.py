"""D1 — the Distribution channel-model contract (pure contract, no behavior yet)."""

from __future__ import annotations

from metalworks.contract import Channel, ChannelSurfaceType, ProductType


def test_channel_minimal_construction_and_defaults() -> None:
    """A Channel needs only its placement axes + a grounded routing signal."""
    ch = Channel(
        surface_type=ChannelSurfaceType.COMMUNITY,
        name="r/sideproject",
        motion="pull",
        cadence="compounding",
        discovery="algorithmic",
        role="lead_gen",
        funnel_stage="awareness",
        routing_signal="audience names r/sideproject repeatedly in the corpus",
    )
    # The optional, downstream-filled fields default to empty / off.
    assert ch.requires_spark is False
    assert ch.spark_channel is None
    assert ch.test == ""
    assert ch.success_threshold == ""
    # Round-trips through pydantic JSON (the stable wire shape D2+ rely on).
    assert Channel.model_validate_json(ch.model_dump_json()) == ch


def test_surface_type_spans_the_structured_space() -> None:
    """The surface type covers the whole space, not just launch platforms."""
    values = {s.value for s in ChannelSurfaceType}
    assert {
        "launch_platform",
        "marketplace",
        "community",
        "answer_engine_geo",
        "embedded_loop",
        "wedge_integration",
        "borrowed_audience",
        "data_asset",
    } <= values
    assert len(values) == 14


def test_product_type_archetypes() -> None:
    assert {p.value for p in ProductType} == {
        "b2b_sales_led",
        "b2b_plg",
        "dev_tool",
        "consumer",
        "ai_product",
        "marketplace",
        "prosumer",
    }
