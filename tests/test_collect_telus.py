import gzip
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from scripts.collect_telus import THREE_HOURS_MS, collect, parse_response, unique_records, write_xmltv

def fixture(cid=14, start=1_800_000_000_000):
    return {"resultCode": "OK", "resultObj": {"containers": [
        {"layout": "CHANNEL_ITEM", "metadata": {"channelId": cid},
         "containers": [{"metadata": {"contentType": "PROGRAM", "contentId": 123,
                                      "title": "Life Below Zero", "programId": "TMS_ABC",
                                      "airingStartTime": start, "airingEndTime": start + 3600000}}]}
    ]}}

class CollectorTests(unittest.TestCase):
    def test_parse_and_duplicate(self):
        records = parse_response(fixture())
        self.assertEqual(records[0]["channel_id"], "14")
        self.assertEqual(len(unique_records(records * 3)), 1)

    def test_seven_days_56_windows(self):
        calls = []
        def fetch(start, end, region):
            calls.append((start, end, region))
            return fixture(start=start)
        records, windows = collect(1_800_000_000_000, 7, 25, 0, fetch)
        self.assertEqual(windows, 56)
        self.assertEqual(len(calls), 56)
        self.assertEqual(calls[-1][1] - calls[0][0], 7 * 86400000)
        self.assertEqual(len(records), 56)

    def test_xmltv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telus.xml.gz"
            write_xmltv(parse_response(fixture()), path)
            with gzip.open(path, "rb") as stream:
                root = ET.parse(stream).getroot()
            self.assertEqual(root.find("channel").get("id"), "telus.14")
            self.assertEqual(root.find("programme").find("title").text, "Life Below Zero")

if __name__ == "__main__":
    unittest.main()
