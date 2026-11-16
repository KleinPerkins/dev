import json
import subprocess
import unittest

from doc_warden.roadmap import (
    BEGIN,
    END,
    new_roadmap_item,
    render_roadmap,
    roadmap_prioritize,
    roadmap_sequence,
)
from fixture_factory import FixtureFactory


def preview_items(preview):
    text = preview.actions[0].content.decode("utf-8")
    return json.loads(text.split(BEGIN, 1)[1].split(END, 1)[0])["items"]


class RoadmapTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()
        first = new_roadmap_item(
            repository_key=self.fixture.repository_key,
            item_id="ROAD-1",
            outcome="First",
            priority="P2",
            sequence=1,
        )
        second = new_roadmap_item(
            repository_key=self.fixture.repository_key,
            item_id="ROAD-2",
            outcome="Second",
            priority="P1",
            sequence=2,
        )
        path = self.fixture.repo / ".planning/ROADMAP.md"
        path.write_bytes(render_roadmap([first, second]))
        subprocess.run(["git", "-C", str(self.fixture.repo), "add", ".planning/ROADMAP.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "add roadmap"], check=True
        )

    def tearDown(self):
        self.fixture.cleanup()

    def test_priority_change_does_not_change_sequence(self):
        preview = roadmap_prioritize(
            self.fixture.repo, self.fixture.repository_key, "ROAD-1", "P0"
        )
        self.assertEqual(preview.transition, "roadmap_update")
        items = preview_items(preview)
        self.assertEqual(items[0]["priority"], "P0")
        self.assertEqual([item["sequence"] for item in items], [1, 2])

    def test_sequence_change_rejects_cycle_without_changing_priority(self):
        with self.assertRaisesRegex(ValueError, "sequence cycle"):
            roadmap_sequence(
                self.fixture.repo,
                self.fixture.repository_key,
                "ROAD-1",
                before="ROAD-1",
            )
        preview = roadmap_sequence(
            self.fixture.repo,
            self.fixture.repository_key,
            "ROAD-2",
            before="ROAD-1",
        )
        items = preview_items(preview)
        self.assertEqual([item["id"] for item in items], ["ROAD-2", "ROAD-1"])
        self.assertEqual(
            {item["id"]: item["priority"] for item in items},
            {"ROAD-1": "P2", "ROAD-2": "P1"},
        )

    def test_fleet_projection_cannot_be_used_as_update_target(self):
        with self.assertRaisesRegex(ValueError, "fleet_projection_read_only"):
            roadmap_prioritize(
                self.fixture.repo,
                self.fixture.repository_key,
                "ROAD-1",
                "P0",
                projection=True,
            )


if __name__ == "__main__":
    unittest.main()
