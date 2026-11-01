"""Pure offline tests for mapping proposal CSV generation."""
import importlib.util
import sys
import unittest
from pathlib import Path

scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location("stage3", scripts / "propose_approved_mappings.py")
stage3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage3)

class ProposalTests(unittest.TestCase):
    def test_ca2_mapping_upsert(self):
        source = "playlist_position,provider_epg_id,provider,source_epg_id\n587,DisneyChannel.ca,CA2,Old.ca2\n"
        row = dict(position="587", pid="DisneyChannel.ca", provider="CA2", source="New.ca2")
        result = stage3.prepare_change(row, source)
        self.assertIn("587,DisneyChannel.ca,CA2,New.ca2", result)
        self.assertNotIn("Old.ca2", result)
        self.assertEqual(result.count("DisneyChannel.ca"), 1)

    def test_epg6_mapping_upsert(self):
        source = "provider_epg_id,source_epg_id\nAMC.ca,old.ca\n"
        row = dict(position="7", pid="AMC.ca", provider="EPG6", source="new.ca")
        result = stage3.prepare_change(row, source)
        self.assertIn("AMC.ca,new.ca", result)
        self.assertNotIn("old.ca", result)

    def test_disallow_non_manual_run(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"GITHUB_EVENT_NAME": "schedule"}):
            with self.assertRaises(ValueError):
                stage3.main()

if __name__ == "__main__":
    unittest.main()
