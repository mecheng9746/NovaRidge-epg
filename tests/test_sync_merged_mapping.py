"""Offline safety tests for post-merge mapping changes."""
import importlib.util,sys,unittest
from pathlib import Path
scripts=Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location("sync",scripts/"sync_merged_mapping.py")
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)

class SyncTests(unittest.TestCase):
    def test_one_ca2_mapping(self):
        old=[{"playlist_position":"5","provider_epg_id":"AdultSwim.ca","provider":"CA2","source_epg_id":"Old.ca2"}]
        new=[{"playlist_position":"5","provider_epg_id":"AdultSwim.ca","provider":"CA2","source_epg_id":"Adult.Swim.ca2"}]
        self.assertEqual(sync.delta(old,new,"CA2")["source_epg_id"],"Adult.Swim.ca2")
    def test_multiple_changes_refused(self):
        with self.assertRaises(ValueError):
            sync.delta([], [{"provider_epg_id":"A","source_epg_id":"a"},{"provider_epg_id":"B","source_epg_id":"b"}],"EPG6")
    def test_deleted_mapping_refused(self):
        with self.assertRaises(ValueError):
            sync.delta([{"provider_epg_id":"A","source_epg_id":"a"}],[],"EPG6")
    def test_ca2_wrong_provider_refused(self):
        with self.assertRaises(ValueError):
            sync.delta([],[{"provider_epg_id":"A","source_epg_id":"a","provider":"TELUS"}],"CA2")

if __name__=="__main__":unittest.main()
