"""Offline regression tests for Canadian EPG audit calculations."""
import importlib.util
import unittest
from pathlib import Path
from datetime import datetime, timezone

spec=importlib.util.spec_from_file_location("audit_epg",Path(__file__).resolve().parents[1]/"scripts"/"audit_epg.py")
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class AuditTests(unittest.TestCase):
    def test_timezone_conversion(self):
        self.assertEqual(audit.parse_time("20261101070000 -0700"),audit.parse_time("20261101140000 +0000"))
        self.assertEqual(audit.parse_time("20261101070000 -0600"),audit.parse_time("20261101130000 +0000"))
    def test_coverage_merges_overlaps(self):
        self.assertEqual(audit.coverage([(0,3600,"A"),(1800,7200,"B")],0,7200),100.0)
        self.assertEqual(audit.coverage([(0,3600,"A")],0,7200),50.0)
    def test_name_only_not_schedule_proof(self):
        now=0
        a=[(i*1800,(i+1)*1800,"A") for i in range(48)]
        b=[(i*1800,(i+1)*1800,"B") for i in range(48)]
        score,matched,compared,offset=audit.match_score(a,b,now)
        self.assertEqual(matched,0)
        self.assertEqual(compared,48)
        self.assertLess(score,90)
    def test_header_widths(self):
        self.assertEqual(len(audit.HEADERS["MAPPING CANDIDATES"]),14)
        self.assertEqual(audit.WRITE_WIDTHS["MAPPING CANDIDATES"],12)

if __name__=="__main__":
    unittest.main()
