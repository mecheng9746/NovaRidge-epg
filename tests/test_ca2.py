import gzip
import tempfile
import unittest
from pathlib import Path
from lxml import etree
from scripts.collect_ca2 import audit_xmltv
from scripts.normalize_sources import normalize

XML = b'''<?xml version="1.0"?><tv><channel id="A.ca"><display-name>A Channel</display-name></channel><programme channel="A.ca" start="20261031120000 +0000" stop="20261031130000 +0000"><title>Sample Show</title><sub-title>Episode 1</sub-title></programme></tv>'''

class CA2Tests(unittest.TestCase):
    def test_audit_and_normalize(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive = base / "sample.xml.gz"
            with gzip.open(archive, "wb") as f:
                f.write(XML)
            audit = audit_xmltv(archive)
            self.assertEqual(audit["channel_count"], 1)
            self.assertEqual(audit["programme_count"], 1)
            output = base / "normalized.jsonl"
            result = normalize(archive, "ca2", output)
            self.assertEqual(result["normalized_programmes"], 1)
            import json
            row = json.loads(output.read_text().strip())
            self.assertEqual(row["channel_key"], "ca2:A.ca")
            self.assertEqual(row["source_channel_name"], "A Channel")
            self.assertEqual(row["episode_title"], "Episode 1")

if __name__ == "__main__":
    unittest.main()
