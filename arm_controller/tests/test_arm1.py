"""Upper-arm (frets 7-11) grid parsing and safety filters."""
import arm1
import pytest

POSE = {str(s): 1500 for s in [5, 4, 6, 1, 2, 3]}


def entries(*names):
    return [{"name": n, "time": "t", "positions": dict(POSE)} for n in names]


def test_upper_cells_parse_with_name_variants():
    m = arm1.load_map(entries=entries("rest", "pose-r7_1", "pose-r_8_5", "pose-8_2"))
    assert set(m["cells"]) == {(1, 7), (5, 8), (2, 8)}
    assert m["warns"] == []


def test_grip_is_filtered_from_motion_poses():
    m = arm1.load_map(entries=entries("rest", "pose-r9_3"))
    assert set(m["rest"]) == set(arm1.BODY_IDS)
    assert arm1.GRIP_ID not in m["cells"][(3, 9)]


def test_out_of_range_and_incomplete_are_skipped():
    bad = entries("rest", "pose-r5_1", "pose-r12_1")
    bad.append({"name": "pose-r9_1", "time": "t", "positions": {"5": 1500}})
    m = arm1.load_map(entries=bad)
    assert m["cells"] == {} and len(m["warns"]) == 3


def test_rest_required():
    with pytest.raises(ValueError, match="rest"):
        arm1.load_map(entries=entries("pose-r7_1"))


def test_voltage_gate_refuses_bad_supply():
    import app

    class Bus:
        def __init__(self, decivolts):
            self.decivolts = decivolts

        def _txrx(self, sid, instr, params, resp_extra=0):
            return bytes([self.decivolts])

    app.check_supply_voltage(Bus(122), [1, 2])  # 12.2V: fine
    with pytest.raises(RuntimeError, match="UNSAFE"):
        app.check_supply_voltage(Bus(140), [1, 2])  # 14.0V: refused
    with pytest.raises(RuntimeError, match="UNSAFE"):
        app.check_supply_voltage(Bus(80), [1])  # 8.0V brownout: refused
