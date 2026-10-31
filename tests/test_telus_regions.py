import unittest
from scripts.discover_telus_regions import scan
from scripts.collect_telus import THREE_HOURS_MS

class DiscoveryTests(unittest.TestCase):
    def test_inclusive_range_and_errors(self):
        calls = []
        def fetch(start, end, rid):
            calls.append(rid)
            if rid == 2:
                raise RuntimeError("not available")
            return {"resultCode": "OK", "resultObj": {"containers": [{
                "layout": "CHANNEL_ITEM", "metadata": {"channelId": 14},
                "containers": [{"metadata": {"contentType": "PROGRAM", "title": "News",
                    "airingStartTime": start, "airingEndTime": end}}]
            }]}}
        result = scan(1, 3, 1800000000000, 0, fetch)
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual([r["status"] for r in result], ["has_programming", "error", "has_programming"])
        self.assertEqual(result[0]["channels"], 1)

if __name__ == "__main__":
    unittest.main()
