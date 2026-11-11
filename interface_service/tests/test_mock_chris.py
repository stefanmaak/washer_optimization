import random

from interface_service.backend import protocol_lines
from interface_service.models import TestRequest
from interface_service.sim.mock_chris import random_test
from interface_service.sim.settings import WashModelParameters
from interface_service.sim.wash_model import evaluate


def test_random_tests_are_valid_requests_and_spin_the_rotor():
    rng = random.Random(0)
    for _ in range(50):
        test = random_test(rng)
        request = TestRequest(**test)
        assert 5 <= request.n_washes <= 12
        lines = protocol_lines(request.protocol)
        assert any(line.startswith("rotormoveendless") for line in lines)
        assert evaluate(lines, WashModelParameters(), rng).loss >= 2.0
