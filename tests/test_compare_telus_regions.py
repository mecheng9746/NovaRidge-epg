import unittest
from scripts.compare_telus_regions import compare
class CompareTests(unittest.TestCase):
 def test_same_airings(self):
  a=[{"channel_id":"225","start_ms":100,"end_ms":200,"title":"TSN Live"}]
  r=compare(a,a,{"225":"TSN 1"},{"225":"TSN 1"},1,25)
  self.assertEqual(len(r),1)
  self.assertEqual(r[0]["identical"],"YES")
 def test_mismatched_title(self):
  a=[{"channel_id":"225","start_ms":100,"end_ms":200,"title":"Game A"}]
  b=[{"channel_id":"225","start_ms":100,"end_ms":200,"title":"Game B"}]
  self.assertEqual(compare(a,b,{}, {},1,25)[0]["jaccard_pct"],0)
if __name__=="__main__": unittest.main()
