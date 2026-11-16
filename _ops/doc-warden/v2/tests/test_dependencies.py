import unittest

from doc_warden.dependencies import build_graph
from doc_warden.roadmap import new_roadmap_item, render_roadmap
from fixture_factory import FixtureFactory


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()

    def test_cycle_is_reported_with_exact_path(self):
        first = new_roadmap_item(
            repository_key=self.fixture.repository_key,
            item_id="ROAD-1",
            outcome="First",
        )
        second = new_roadmap_item(
            repository_key=self.fixture.repository_key,
            item_id="ROAD-2",
            outcome="Second",
            sequence=2,
        )
        first["dependencies"]["planned"] = ["ROAD-2"]
        second["dependencies"]["planned"] = ["ROAD-1"]
        path = self.fixture.repo / ".planning/ROADMAP.md"
        path.write_bytes(render_roadmap([first, second]))
        graph = build_graph(self.fixture.repo)
        self.assertEqual(graph.cycles, (("ROAD-1", "ROAD-2", "ROAD-1"),))


if __name__ == "__main__":
    unittest.main()
