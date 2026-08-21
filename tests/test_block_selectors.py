from worker.block_selectors import (
    block_contains_keyword,
    blocks_matching_keyword,
    first_block_matching_keyword,
    surface_index_for_custom_data_tag,
)


def test_block_keyword_matching_uses_name_and_custom_data():
    blocks = [
        {"entity_id": 1, "name": "Status LCD", "custom_data": ""},
        {"entity_id": 2, "name": "LCD Panel", "custom_data": "@0 IIM-inventory\nOre 1000000"},
        {"entity_id": 3, "name": "Cargo", "custom_data": "[IIM]\nmode=locked"},
    ]

    assert block_contains_keyword(blocks[0], "Status")
    assert block_contains_keyword(blocks[1], "IIM-inventory")
    assert block_contains_keyword(blocks[2], "[IIM]")
    assert [block["entity_id"] for block in blocks_matching_keyword(blocks, "IIM")] == [2, 3]
    assert first_block_matching_keyword(blocks, "IIM-inventory")["entity_id"] == 2


def test_surface_index_for_custom_data_tag_reads_isy_style_surface_marker():
    block = {"custom_data": "@1 IIM-inventory\nIngot\n@0 IIM-main"}

    assert surface_index_for_custom_data_tag(block, "IIM-inventory") == 1
    assert surface_index_for_custom_data_tag(block, "IIM-main") == 0
    assert surface_index_for_custom_data_tag(block, "missing") == 0
