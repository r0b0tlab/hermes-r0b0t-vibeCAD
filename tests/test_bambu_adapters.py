from vibecad_public_plugin.adapters import load_adapters


def test_adapter_literals_match_studio_and_x2d_contract():
    adapters = load_adapters()
    assert set(adapters) == {"bambu-x2d", "bambu-p2s"}
    p2s = adapters["bambu-p2s"]
    assert p2s.machine_name == "Bambu Lab P2S 0.4 nozzle"
    assert p2s.plate_center_mm == (128.0, 128.0, 0.0)
    assert p2s.build_volume_mm == (256.0, 256.0, 256.0)
    assert p2s.tool_model == "single"
    assert (p2s.default_slot_capacity, p2s.max_slot_capacity) == (4, 20)
    x2d = adapters["bambu-x2d"]
    assert x2d.plate_center_mm == (138.25, 128.0, 0.0)
    assert x2d.build_volume_mm == (235.5, 256.0, 256.0)
    assert x2d.tool_model == "dual_shared_xy"
    assert x2d.default_slot_capacity is None
    assert x2d.extras["auxiliary_limits"]["max_print_speed_mm_s"] == 200
