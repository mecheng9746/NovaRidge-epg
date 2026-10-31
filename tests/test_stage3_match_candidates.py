import unittest
from scripts.stage3_match_candidates import tokens, rank_channel, candidates_for
class Stage3Tests(unittest.TestCase):
 def test_prefix_and_hd(self):
  self.assertEqual(tokens("CA| A&E HD"),tokens("A&E Canada"))
 def test_no_silent_wrong_channel(self):
  channel={"position":3,"name":"CA| ABC EAST HD","tvg_id":"ca.ABC (WCVB) Boston, MA HD","group":"CA| ENGLISH"}
  entries=candidates_for(channel,{"ca2":{"BBC.Earth.ca2":["BBC Earth"]},"telus":{},"epg6":{}})
  self.assertEqual(entries,[])
 def test_sports_not_approved(self):
  p={"position":8,"name":"CA| TSN 1 HD","tvg_id":"","group":"sports"}
  rows=candidates_for(p,{"telus":{"225":["TSN 1"]},"ca2":{},"epg6":{}})
  self.assertEqual(rows[0]["review_status"],"PENDING — verify programme schedule")
  self.assertIn("sports_feed",rows[0]["risk_flags"])
if __name__=="__main__": unittest.main()
