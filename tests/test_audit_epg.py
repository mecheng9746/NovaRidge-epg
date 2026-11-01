import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_epg as audit


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.reports = {name: [["x"] * width] for name, width in audit.WRITE_WIDTHS.items()}
        self.metadata = {"sheets": [{"properties": {
            "sheetId": i, "title": name,
            "gridProperties": {"rowCount": 2000, "columnCount": len(audit.HEADERS[name])}
        }} for i, name in enumerate(audit.WRITE_WIDTHS)]}

    def call(self, old=None):
        session = Mock()
        with patch.object(audit, "sheets_request", side_effect=[self.metadata, {"values": old or []}, {}]) as request:
            audit.publish(session, self.reports)
        return request

    def test_one_atomic_write_and_only_automated_columns(self):
        request = self.call()
        writes = [c for c in request.call_args_list if c.args[1] == "POST"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0].args[2], ":batchUpdate")
        updates = writes[0].kwargs["json"]["requests"]
        self.assertEqual([u["updateCells"]["range"]["endColumnIndex"] for u in updates], [13, 12, 8])
        for u in updates:
            self.assertEqual(u["updateCells"]["range"]["startRowIndex"], 1)
            self.assertEqual(u["updateCells"]["fields"], "userEnteredValue")
            self.assertEqual(u["updateCells"]["range"]["endRowIndex"], 2000)

    def test_grows_beyond_old_2000_row_limit(self):
        self.reports["MAPPING CANDIDATES"] *= 2463
        requests = self.call().call_args.kwargs["json"]["requests"]
        self.assertEqual(requests[1]["appendDimension"]["length"], 464)
        self.assertEqual(requests[2]["updateCells"]["range"]["endRowIndex"], 2464)

    def test_empty_candidates_clear_stale_values(self):
        self.reports["MAPPING CANDIDATES"] = []
        updates = self.call().call_args.kwargs["json"]["requests"]
        self.assertEqual(updates[1]["updateCells"]["rows"], [])

    def test_manual_review_stays_with_same_identity(self):
        self.call([self.reports["MAPPING CANDIDATES"][0] + ["approved", "link"]])

    def test_manual_review_identity_change_blocks_all_writes(self):
        old = ["old"] * 12 + ["approved", ""]
        with patch.object(audit, "sheets_request", side_effect=[self.metadata, {"values": [old]}]) as request:
            with self.assertRaisesRegex(audit.SheetsError, "change identity"):
                audit.publish(Mock(), self.reports)
            self.assertEqual(request.call_count, 2)

    def test_production_tab_and_bad_width_rejected_before_network(self):
        for reports in ({"CANADIAN MASTER": []}, {**self.reports, "SOURCE HEALTH": [["bad"]]}):
            with patch.object(audit, "sheets_request") as request:
                with self.assertRaises(audit.SheetsError):
                    audit.publish(Mock(), reports)
                request.assert_not_called()

    def test_403_diagnostics_do_not_echo_response_secrets(self):
        session = Mock()
        session.request.return_value = Mock(ok=False, status_code=403)
        session.request.return_value.json.return_value = {"error": {"message": "SECRET_TOKEN",
            "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}}
        with self.assertRaises(audit.SheetsError) as error:
            audit.sheets_request(session, "POST", ":batchUpdate")
        self.assertIn("write scope", str(error.exception))
        self.assertNotIn("SECRET_TOKEN", str(error.exception))

    def test_permission_and_api_disabled_diagnostics(self):
        for reason, expected in [("SERVICE_DISABLED", "Enable sheets.googleapis.com"),
                                 ("forbidden", "as Editor")]:
            session = Mock()
            session.request.return_value = Mock(ok=False, status_code=403)
            session.request.return_value.json.return_value = {"error": {"details": [{"reason": reason}]}}
            with self.assertRaisesRegex(audit.SheetsError, expected):
                audit.sheets_request(session, "POST", ":batchUpdate")

    def test_failed_publish_keeps_all_csvs(self):
        with tempfile.TemporaryDirectory() as output:
            args = argparse.Namespace(published="feed", ca2=None, epg6=None, telus=None,
                                      output=output, publish=True)
            with patch.object(audit, "sheets_session"), patch.object(audit, "sheets_rows", return_value=[{}]), \
                 patch.object(audit, "programs", return_value=({}, {})), \
                 patch.object(audit, "publish", side_effect=audit.SheetsError("denied")):
                with self.assertRaises(audit.SheetsError):
                    audit.run(args)
            self.assertEqual(len(list(Path(output).glob("*.csv"))), 3)

    def test_missing_credentials_fail_explicitly(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(audit.SheetsError, "missing"):
                audit.sheets_session()


if __name__ == "__main__":
    unittest.main()
