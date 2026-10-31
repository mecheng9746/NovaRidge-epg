import unittest
from scripts.collect_telus_livechannels import extract
class CatalogTests(unittest.TestCase):
    def test_channel_names(self):
        sample={"resultObj":{"containers":[{"metadata":{"channelId":225,"channelName":"TSN1","callLetter":"TSN","externalId":"X"}},{"metadata":{"channelId":225,"channelName":"TSN1"}}]}}
        result=extract(sample,25)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["channel_name"],"TSN1")
        self.assertEqual(result[0]["region_id"],25)
if __name__=="__main__":
    unittest.main()
