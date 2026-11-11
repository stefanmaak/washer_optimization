import ast

from interface_service.models import TestRequest
from interface_service.process_generation import ProcessParameters, generate_process_source

PARAMS = ProcessParameters(
    protocol_name="washopt_1",
    start_position=1,
    squid="Squid4",
    empty_check_protocol="empty_check",
    coverage_check_protocol="coverage_check",
    squid_project="washing_optimization",
)


def test_generated_source():
    request = TestRequest(protocol="rackhome", n_washes=3, coverage_checks=[1])
    source = generate_process_source("abc123", request, PARAMS)
    ast.parse(source)

    assert "class WashOpt_abc123(BasicProcess)" in source
    assert "set_start_position(self.hotel2, 1)" in source
    assert "n_washes = 3" in source
    # 0 is done unconditionally before the loop, the last wash is always checked
    assert "coverage_checks = [1, 3]" in source
    assert "protocol='washopt_1'" in source
    assert "squid_pool" not in source
    assert source.count("self.robot_arm.move(cont, self.squid4") == 2
    assert source.count("self.squid4.run_protocol(") == 3
